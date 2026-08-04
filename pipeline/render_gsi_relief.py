"""国土地理院の色別標高図タイルをそのまま貼り合わせて使う。

自前で標高を色分けするのではなく、地理院地図が公式に提供する色別標高図
(https://maps.gsi.go.jp/ の「標高・土地の凹凸」レイヤ)のタイル画像を
モザイク・切り出しするだけなので、色の基準は完全に国土地理院のものと一致する。
利用規約により表示ページ側に「出典:国土地理院」の表記が必要
(render.pyのsourcesセクションにリンクを追加している)。
"""

import math
import os

import numpy as np
import requests
from PIL import Image

import config
import render
import sigwx_georef


def _abs_pixel(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2.0**zoom
    x = (lon + 180.0) / 360.0 * n * 256
    y = (
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
        * 256
    )
    return x, y


def _fetch_tile_image(zoom, xtile, ytile):
    os.makedirs(config.RELIEF_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(config.RELIEF_CACHE_DIR, f"{zoom}_{xtile}_{ytile}.png")
    if os.path.exists(cache_path):
        return Image.open(cache_path).convert("RGB")

    url = config.RELIEF_TILE_URL.format(z=zoom, x=xtile, y=ytile)
    resp = requests.get(
        url, headers={"User-Agent": config.USER_AGENT}, timeout=config.HTTP_TIMEOUT_SEC
    )
    if resp.status_code == 404:
        # このレイヤは海域や離島遠方などタイル自体が存在しない場合がある
        img = Image.new("RGB", (256, 256), (210, 224, 236))
    else:
        resp.raise_for_status()
        with open(cache_path, "wb") as f:
            f.write(resp.content)
        img = Image.open(cache_path).convert("RGB")
    return img


def _build_relief_crop():
    """地理院地図の色別標高図タイルをモザイク・切り出しし、(画像, mercator情報)を返す。

    mercator情報(zoom, x0, y0, x1, y1)は絶対ピクセル座標での切り出し範囲で、
    HTML版JSの逆変換や、下層悪天オーバーレイの座標変換にそのまま使う。
    """
    zoom = config.RELIEF_ZOOM
    x0, y0 = _abs_pixel(config.LAT_MAX, config.LON_MIN, zoom)
    x1, y1 = _abs_pixel(config.LAT_MIN, config.LON_MAX, zoom)

    xtile_min = int(x0 // 256)
    xtile_max = int((x1 - 1) // 256)
    ytile_min = int(y0 // 256)
    ytile_max = int((y1 - 1) // 256)

    mosaic_w = (xtile_max - xtile_min + 1) * 256
    mosaic_h = (ytile_max - ytile_min + 1) * 256
    mosaic = Image.new("RGB", (mosaic_w, mosaic_h))

    for xt in range(xtile_min, xtile_max + 1):
        for yt in range(ytile_min, ytile_max + 1):
            tile = _fetch_tile_image(zoom, xt, yt)
            mosaic.paste(tile, ((xt - xtile_min) * 256, (yt - ytile_min) * 256))

    crop_box = (
        int(x0 - xtile_min * 256),
        int(y0 - ytile_min * 256),
        int(x1 - xtile_min * 256),
        int(y1 - ytile_min * 256),
    )
    cropped = mosaic.crop(crop_box)
    mercator = {"zoom": zoom, "x0": x0, "y0": y0, "x1": x1, "y1": y1}
    return cropped, mercator


def render_gsi_relief_map(out_path):
    """地理院地図の色別標高図タイルをそのまま切り出して保存する。

    タイルはWebメルカトル図法(経度は線形だが緯度は非線形)なので、他レイヤの
    等距円筒図法(matplotlib)と違いカーソル位置→緯度経度の変換式が異なる。
    HTML版JS側で正しく逆変換できるよう、axes_frac(常に全面)に加えて
    ズームレベルと切り出しに使った絶対ピクセル範囲(mercator)も返す。
    呼び出し側で再利用できるよう、切り出し済み画像そのものも返す。
    """
    cropped, mercator = _build_relief_crop()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cropped.save(out_path)

    axes_frac = {"left": 0.0, "right": 1.0, "top": 0.0, "bottom": 1.0}
    return axes_frac, mercator, cropped


def _mercator_lonlat_grid(mercator, width, height):
    """出力画像(width x height)の各ピクセルに対応する(経度,緯度)グリッドを逆算する。"""
    zoom = mercator["zoom"]
    n = 2.0**zoom * 256
    px = mercator["x0"] + np.arange(width)
    py = mercator["y0"] + np.arange(height)
    lon = px / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * py / n))))
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    return lon_grid, lat_grid


def overlay_sigwx_on_relief(base_image, mercator, sigwx_image_paths, out_path):
    """下層悪天予想図(校正済み地域のみ)を、色別標高図(Webメルカトル)に正確に重ねる。

    地理院タイル側はWebメルカトル、下層悪天側は地域ごとの緯度経度線形近似と
    座標系が異なるため、出力側の各ピクセルから緯度経度を逆算し、その地点が
    どの地域画像のどのピクセルに当たるかを引き当てる「逆写像」で合成する
    (順写像だと高緯度ほどメルカトル側が疎になり穴が空くため)。
    地域6分割は範囲が重複する仕様なので、最も中心が近い地域を優先して
    二重描画・継ぎ目を防ぐ。
    """
    width, height = base_image.size
    lon_grid, lat_grid = _mercator_lonlat_grid(mercator, width, height)

    calibrated = {
        area: path for area, path in sigwx_image_paths.items() if sigwx_georef.is_calibrated(area)
    }
    if not calibrated:
        base_image.save(out_path)
        return

    region_centers = {area: render._region_center(area) for area in calibrated}

    canvas = np.array(base_image.convert("RGB"), dtype=np.float64)
    border_px = 3  # 元図の外枠線を除去(継ぎ目に黒線が残らないように)

    for region, image_path in calibrated.items():
        left, top, right, bottom = sigwx_georef.panel_bbox(region)
        cropped = Image.open(image_path).convert("RGB").crop((left, top, right, bottom))
        arr = np.array(cropped)
        h, w = arr.shape[:2]

        non_white = (arr < 245).any(axis=2)
        non_white[:border_px, :] = False
        non_white[-border_px:, :] = False
        non_white[:, :border_px] = False
        non_white[:, -border_px:] = False

        georef = config.SIGWX_GEOREF[region]
        region_x = (lon_grid - georef["lon_b"]) / georef["lon_a"] - left
        region_y = (lat_grid - georef["lat_b"]) / georef["lat_a"] - top
        valid = (region_x >= 0) & (region_x < w) & (region_y >= 0) & (region_y < h)

        own_lat, own_lon = region_centers[region]
        own_dist2 = (lat_grid - own_lat) ** 2 + (lon_grid - own_lon) ** 2
        owned = np.ones_like(own_dist2, dtype=bool)
        for other, (o_lat, o_lon) in region_centers.items():
            if other == region:
                continue
            other_dist2 = (lat_grid - o_lat) ** 2 + (lon_grid - o_lon) ** 2
            owned &= own_dist2 <= other_dist2

        target_mask = valid & owned
        rows, cols = np.nonzero(target_mask)
        if rows.size == 0:
            continue
        ys = np.clip(region_y[rows, cols].round().astype(int), 0, h - 1)
        xs = np.clip(region_x[rows, cols].round().astype(int), 0, w - 1)
        src_alpha = non_white[ys, xs]
        if not src_alpha.any():
            continue
        rows, cols, ys, xs = rows[src_alpha], cols[src_alpha], ys[src_alpha], xs[src_alpha]
        colors = arr[ys, xs].astype(np.float64)
        blend = 210.0 / 255.0
        canvas[rows, cols] = canvas[rows, cols] * (1.0 - blend) + colors * blend

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    Image.fromarray(canvas.astype(np.uint8)).save(out_path)
