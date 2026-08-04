"""国土地理院の標高タイル(DEM5A/5B/10B合成)からグリッド点の標高を取得する。"""

import math
import os

import requests

import config


def _latlon_to_tile_pixel(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    xtile = int(x)
    ytile = int(y)
    xpixel = min(255, int((x - xtile) * 256))
    ypixel = min(255, int((y - ytile) * 256))
    return xtile, ytile, xpixel, ypixel


def _tile_cache_path(zoom, xtile, ytile):
    return os.path.join(config.DEM_CACHE_DIR, f"{zoom}_{xtile}_{ytile}.txt")


def _fetch_tile_text(zoom, xtile, ytile):
    cache_path = _tile_cache_path(zoom, xtile, ytile)
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()

    url = config.DEM_TILE_URL.format(z=zoom, x=xtile, y=ytile)
    resp = requests.get(
        url, headers={"User-Agent": config.USER_AGENT}, timeout=config.HTTP_TIMEOUT_SEC
    )
    if resp.status_code == 404:
        # タイル範囲外(海域データなし等)。空データとして扱う
        text = ""
    else:
        resp.raise_for_status()
        text = resp.text

    os.makedirs(config.DEM_CACHE_DIR, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def _parse_tile(text):
    """256x256の標高値グリッドを返す。欠測値(海など)はNone。"""
    rows = []
    for line in text.splitlines():
        if not line:
            continue
        values = []
        for cell in line.split(","):
            cell = cell.strip()
            if cell == config.DEM_NODATA or cell == "":
                values.append(None)
            else:
                values.append(float(cell))
        rows.append(values)
    return rows


_tile_cache = {}


def _get_parsed_tile(zoom, xtile, ytile):
    key = (zoom, xtile, ytile)
    if key not in _tile_cache:
        text = _fetch_tile_text(zoom, xtile, ytile)
        _tile_cache[key] = _parse_tile(text) if text else None
    return _tile_cache[key]


def get_elevations(points):
    """points: [(lat, lon), ...] -> [elevation_m or None, ...]

    Noneは海域または欠測。
    """
    results = []
    for lat, lon in points:
        xtile, ytile, xpixel, ypixel = _latlon_to_tile_pixel(lat, lon, config.DEM_ZOOM)
        grid = _get_parsed_tile(config.DEM_ZOOM, xtile, ytile)
        if grid is None or ypixel >= len(grid) or xpixel >= len(grid[ypixel]):
            results.append(None)
            continue
        results.append(grid[ypixel][xpixel])
    return results
