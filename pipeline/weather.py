"""Open-Meteo APIから気象データをグリッド点ごとにバッチ取得する。"""

import time
from datetime import datetime, timezone

import requests

import config


def _get_with_retry(params):
    """429(レート制限)はRetry-Afterヘッダ(無ければ指数バックオフ)に従って再試行する。

    タイムアウト・接続エラー(スリープ復帰直後にネットワークがまだ繋がっていない、等)も
    同様に再試行する。以前は429だけを対象にしており、スリープ復帰直後のネットワーク
    未接続でタイムアウトした際にリトライされずスクリプト全体がクラッシュしていた。
    """
    last_exc = None
    for attempt in range(config.OPEN_METEO_MAX_RETRIES + 1):
        try:
            resp = requests.get(
                config.OPEN_METEO_URL,
                params=params,
                headers={"User-Agent": config.USER_AGENT},
                timeout=config.HTTP_TIMEOUT_SEC,
            )
        except requests.exceptions.RequestException as e:
            last_exc = e
            wait = 2**attempt * 3
            if attempt < config.OPEN_METEO_MAX_RETRIES:
                time.sleep(wait)
            continue

        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        wait = float(resp.headers.get("Retry-After", 2**attempt * 2))
        last_exc = requests.exceptions.HTTPError(
            f"429 Too Many Requests (attempt {attempt + 1}), waiting {wait}s", response=resp
        )
        if attempt < config.OPEN_METEO_MAX_RETRIES:
            time.sleep(wait)
    raise last_exc


def _nearest_hour_index(time_strings, now_utc):
    best_idx = 0
    best_diff = None
    for i, t in enumerate(time_strings):
        dt = datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        diff = abs((dt - now_utc).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_idx = i
    return best_idx


def _fetch_variables(points, variables, model, target_time, forecast_days):
    lats = ",".join(f"{lat:.4f}" for lat, _ in points)
    lons = ",".join(f"{lon:.4f}" for _, lon in points)
    params = {
        "latitude": lats,
        "longitude": lons,
        "hourly": ",".join(variables),
        "forecast_days": forecast_days,
        "timezone": "UTC",
    }
    if model:
        params["models"] = model
    resp = _get_with_retry(params)
    data = resp.json()
    if isinstance(data, dict):
        data = [data]

    results = []
    for loc in data:
        hourly = loc.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            results.append(None)
            continue
        idx = _nearest_hour_index(times, target_time)
        entry = {"valid_time": times[idx]}
        for var in variables:
            series = hourly.get(var, [])
            entry[var] = series[idx] if idx < len(series) else None
        results.append(entry)
    return results


def _fetch_batch(points, target_time, forecast_days):
    """雲量/気温/露点はJMA MSM、視程は既定モデルから取得してマージする。"""
    msm_results = _fetch_variables(
        points, config.OPEN_METEO_MSM_VARS, config.OPEN_METEO_MODEL, target_time, forecast_days
    )
    time.sleep(config.OPEN_METEO_REQUEST_DELAY_SEC)
    default_results = _fetch_variables(
        points, config.OPEN_METEO_DEFAULT_VARS, None, target_time, forecast_days
    )

    merged = []
    for msm, default in zip(msm_results, default_results):
        if msm is None and default is None:
            merged.append(None)
            continue
        entry = dict(msm) if msm else {}
        if default:
            entry.update(default)
            entry.setdefault("valid_time", default.get("valid_time"))
        merged.append(entry)
    return merged


def fetch_weather(points, target_time=None):
    """points: [(lat, lon), ...] -> [entry_dict or None, ...] (順序を維持)

    target_time: 予報の対象時刻(UTC, tz-aware)。Noneなら現在時刻に最も近い予報を使う。
    未来の日付が指定された場合は、それをカバーできるようforecast_daysを自動で広げる
    (Open-Meteoの上限16日まで)。
    """
    now_utc = datetime.now(timezone.utc)
    if target_time is None:
        target_time = now_utc

    days_ahead = (target_time.date() - now_utc.date()).days
    forecast_days = min(max(config.OPEN_METEO_FORECAST_DAYS, days_ahead + 1), 16)

    all_results = []
    batch_size = config.OPEN_METEO_BATCH_SIZE
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        all_results.extend(_fetch_batch(batch, target_time, forecast_days))
        if i + batch_size < len(points):
            time.sleep(config.OPEN_METEO_REQUEST_DELAY_SEC)
    return all_results
