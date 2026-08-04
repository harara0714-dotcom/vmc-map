"""下層悪天予想図(地域版)のピクセル座標<->緯度経度の変換。

各地域画像は同一テンプレート(1000x734、左に基図パネル・右に雲/降水詳細パネル)で
生成されており、パネル内は緯度経度に対してほぼ線形に描画されている。
`config.SIGWX_GEOREF` に地域ごとの校正済み係数(空港の実際の緯度経度を基準点にして
最小二乗フィットしたもの)を持つ。校正済みでない地域は未対応としてNoneを返す。
"""

import config


def panel_bbox(region):
    georef = config.SIGWX_GEOREF.get(region)
    return georef["panel_bbox"] if georef else None


def pixel_to_latlon(region, x, y):
    """詳細パネル内のピクセル(x, y)(元画像スケール)を(lat, lon)に変換する。

    校正データが無い地域はNoneを返す。
    """
    georef = config.SIGWX_GEOREF.get(region)
    if georef is None:
        return None
    lon = georef["lon_a"] * x + georef["lon_b"]
    lat = georef["lat_a"] * y + georef["lat_b"]
    return lat, lon


def is_calibrated(region):
    return region in config.SIGWX_GEOREF
