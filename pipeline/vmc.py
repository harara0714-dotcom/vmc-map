"""地形標高と気象データから、その地点でVMCを維持できるかを判定する。

固定の巡航高度を仮定するのではなく、「地形と雲底の間の隙間 (gap) に、
最低安全高度(AGL_MIN_M) と雲からの垂直距離基準(CLOUD_CLEARANCE_MIN_M) を
同時に満たせる高度が存在するか」で判定する。
"""

import config


def classify(
    elevation_m,
    weather_entry,
    sigwx_base_m_msl=None,
    metar_base_m_msl=None,
    metar_visibility_m=None,
):
    """1地点の判定結果を返す。海域・データ欠損はNone。

    優先順位は METAR実況 > 下層悪天予想図OCR(sigwx, USE_SIGWX_OVERRIDE時) > LCL近似。
    metar_base_m_msl / metar_visibility_m: 直近の空港実況による上書き値(海抜/m)。
    sigwx_base_m_msl: 下層悪天予想図OCRから得た雲底高度(海抜/MSL)。
    """
    if elevation_m is None or weather_entry is None:
        return None

    vis = metar_visibility_m if metar_visibility_m is not None else weather_entry.get("visibility")

    if metar_base_m_msl is not None:
        gap = metar_base_m_msl - elevation_m
        source = "metar"
    elif config.USE_SIGWX_OVERRIDE and sigwx_base_m_msl is not None:
        gap = sigwx_base_m_msl - elevation_m
        source = "sigwx"
    else:
        cloud_low = weather_entry.get("cloud_cover_low")
        temp = weather_entry.get("temperature_2m")
        dew = weather_entry.get("dew_point_2m")

        has_significant_low_cloud = (
            cloud_low is not None
            and cloud_low >= config.LOW_CLOUD_COVER_THRESHOLD_PCT
            and temp is not None
            and dew is not None
        )
        if has_significant_low_cloud:
            gap = max(config.LCL_COEFFICIENT * (temp - dew), 0.0)
        else:
            gap = config.NO_CLOUD_BASE_GAP_M
        source = "lcl"

    required_gap = config.AGL_MIN_M + config.CLOUD_CLEARANCE_MIN_M
    margin = gap - required_gap

    vis_ok = vis is not None and vis >= config.VIS_MIN_M
    vis_comfortable = vis is not None and vis >= config.VIS_COMFORT_M

    if not vis_ok or margin < 0:
        status = "red"
    elif margin < config.MARGIN_BUFFER_M or not vis_comfortable:
        status = "yellow"
    else:
        status = "green"

    return {
        "status": status,
        "gap_m": gap,
        "margin_m": margin,
        "visibility_m": vis,
        "source": source,
    }


def classify_all(
    elevations, weather_entries, sigwx_base_list=None, metar_base_list=None, metar_vis_list=None
):
    n = len(elevations)
    sigwx_base_list = sigwx_base_list or [None] * n
    metar_base_list = metar_base_list or [None] * n
    metar_vis_list = metar_vis_list or [None] * n
    return [
        classify(e, w, sx, mb, mv)
        for e, w, sx, mb, mv in zip(
            elevations, weather_entries, sigwx_base_list, metar_base_list, metar_vis_list
        )
    ]
