"""850hPa相当温位(θe)をOpen-Meteo(気象庁MSM)の気温・相対湿度から計算する。

気象庁がPDFで公開しているFXJP854(850hPa相当温位・風予想図)を自動色付けしようと
したが、風羽根の線が数字ラベルに直接重なっており自動抽出の精度が出せなかった
(検証済み)ため、同じ気象庁MSMの気温・相対湿度から自前で計算する方式にした。
"""

import math
import time
from datetime import datetime, timezone

import numpy as np

import config
import weather

PRESSURE_HPA = 850
HOURLY_VARS = ["temperature_850hPa", "relative_humidity_850hPa"]


def generate_grid():
    """VMCグリッドより粗い専用グリッド(config.THETA_E_GRID_STEP_DEG間隔)を返す。"""
    step = config.THETA_E_GRID_STEP_DEG
    lats = np.arange(config.LAT_MIN, config.LAT_MAX + step / 2, step)
    lons = np.arange(config.LON_MIN, config.LON_MAX + step / 2, step)
    return [(float(lat), float(lon)) for lat in lats for lon in lons]


def compute_theta_e(temp_c, rh_pct, pressure_hpa=PRESSURE_HPA):
    """Bolton(1980)近似による相当温位(K)。気温(℃)・相対湿度(%)から計算する。"""
    if temp_c is None or rh_pct is None:
        return None
    t_k = temp_c + 273.15
    es = 6.112 * math.exp(17.67 * temp_c / (temp_c + 243.5))  # 飽和水蒸気圧(hPa, Magnus式)
    e = max(rh_pct, 0.0) / 100.0 * es
    r = 0.622 * e / max(pressure_hpa - e, 1e-6)  # 混合比 (kg/kg)
    theta = t_k * (1000.0 / pressure_hpa) ** 0.286  # 温位(K)
    return theta * math.exp((2.5e6 * r) / (1004.0 * t_k))


def fetch_theta_e_grid(points, target_time=None):
    """points: [(lat, lon), ...] -> [theta_e(K) or None, ...] (順序維持)"""
    now_utc = datetime.now(timezone.utc)
    if target_time is None:
        target_time = now_utc
    days_ahead = (target_time.date() - now_utc.date()).days
    forecast_days = min(max(config.OPEN_METEO_FORECAST_DAYS, days_ahead + 1), 16)

    results = []
    batch_size = config.OPEN_METEO_BATCH_SIZE
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        entries = weather._fetch_variables(
            batch, HOURLY_VARS, config.OPEN_METEO_MODEL, target_time, forecast_days
        )
        for entry in entries:
            if entry is None:
                results.append(None)
                continue
            results.append(
                compute_theta_e(
                    entry.get("temperature_850hPa"), entry.get("relative_humidity_850hPa")
                )
            )
        if i + batch_size < len(points):
            time.sleep(config.OPEN_METEO_REQUEST_DELAY_SEC)
    return results
