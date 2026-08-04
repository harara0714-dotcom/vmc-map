"""下層悪天予想図から抽出した雲底点群を統合し、最近傍検索を提供する。"""

import math

import config
import sigwx_ocr


def build_field(region_image_paths):
    """{region: image_path} から抽出した雲底点をまとめて返す。

    校正データが無い地域は自動的にスキップされる(sigwx_ocr側の挙動)。
    """
    field = []
    for region, image_path in region_image_paths.items():
        field.extend(sigwx_ocr.extract_cloud_points(image_path, region))
    return field


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_cloud_base(lat, lon, field, max_dist_km=None):
    """最も近いSIGWX抽出点のbase_m(m)を返す。近傍になければNone。"""
    if not field:
        return None
    if max_dist_km is None:
        max_dist_km = config.SIGWX_NEAREST_MAX_DIST_KM

    best_point, best_dist = None, None
    for point in field:
        dist = _haversine_km(lat, lon, point["lat"], point["lon"])
        if best_dist is None or dist < best_dist:
            best_dist, best_point = dist, point

    if best_point is None or best_dist > max_dist_km:
        return None
    return best_point["base_m"]
