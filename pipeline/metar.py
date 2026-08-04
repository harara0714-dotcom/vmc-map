"""aviationweather.gov の無料METAR APIから日本の空港実況を取得する。

calibrate.py(精度検証)と main.py(直近マップのナウキャスト上書き)の両方から使う
共通ロジック。
"""

import math

import requests

import config


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fetch_metars():
    """登録済み空港ICAOコードの生METAR JSON配列を返す。"""
    resp = requests.get(
        config.METAR_URL,
        params={"ids": ",".join(config.METAR_STATIONS), "format": "json"},
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.HTTP_TIMEOUT_SEC,
    )
    resp.raise_for_status()
    return resp.json()


def actual_ceiling_m(clouds):
    """BKN/OVC/VVの最低雲底高度(AGL, m)。無ければNone(=雲底なし/CLR等)。"""
    bases = [c["base"] for c in clouds if c["cover"] in ("BKN", "OVC", "VV")]
    if not bases:
        return None
    return min(bases) * 0.3048


def actual_visibility_m(visib):
    if isinstance(visib, str):
        val = float(visib.rstrip("+"))
    else:
        val = float(visib)
    return val * 1609.34


def fetch_current_obs():
    """ナウキャスト上書き用に整形した観測点のリストを返す。

    各要素: {icao, lat, lon, base_m_msl, visibility_m}
    base_m_msl は 標高+実測雲底高度(AGL)。雲底が無い(CLR/FEW/SCT)場合は
    METAR_NO_CEILING_BASE_M を使い、「有意な雲底なしを確認済み」として扱う。
    """
    metars = fetch_metars()
    obs = []
    for m in metars:
        ceiling_agl = actual_ceiling_m(m.get("clouds", []))
        elev = m.get("elev")
        if elev is None:
            continue
        base_m_msl = (
            elev + ceiling_agl if ceiling_agl is not None else config.METAR_NO_CEILING_BASE_M
        )
        obs.append(
            {
                "icao": m["icaoId"],
                "lat": m["lat"],
                "lon": m["lon"],
                "base_m_msl": base_m_msl,
                "visibility_m": actual_visibility_m(m.get("visib", "6+")),
            }
        )
    return obs


def nearest_override(lat, lon, obs, max_dist_km=None):
    """最寄りの空港実況が範囲内にあれば(base_m_msl, visibility_m)を返す。無ければ(None, None)。"""
    if not obs:
        return None, None
    if max_dist_km is None:
        max_dist_km = config.METAR_OVERRIDE_RADIUS_KM

    best, best_dist = None, None
    for o in obs:
        dist = _haversine_km(lat, lon, o["lat"], o["lon"])
        if best_dist is None or dist < best_dist:
            best_dist, best = dist, o

    if best is None or best_dist > max_dist_km:
        return None, None
    return best["base_m_msl"], best["visibility_m"]
