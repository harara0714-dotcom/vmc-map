"""METAR実測値(雲底高度・視程)を正解データとして、モデルの予測精度を検証する。

aviationweather.gov の無料METAR API(キー不要)を使い、日本各地の空港の
実況を取得し、terrain.py/weather.py/vmc.py で同じ地点を計算した予測値と比較する。
METARによるナウキャスト上書き(main.pyが本番で使う)は無効化した状態で、
JMA MSMベースのLCL推定そのものの精度を検証する。
"""

import json
import os

import requests

import config
import metar
import sigwx_field
import terrain
import vmc
import weather


def build_sigwx_field():
    """校正済み地域(現時点ではfbtkのみ)の画像を取得し、雲底点群を構築する。"""
    cache_dir = os.path.join(config.CACHE_DIR, "low_level_sigwx")
    os.makedirs(cache_dir, exist_ok=True)
    region_paths = {}
    for area in config.SIGWX_GEOREF:
        dest_path = os.path.join(cache_dir, f"{area}.png")
        url = config.LOW_LEVEL_SIGWX_URL_TEMPLATE.format(area=area, ft=config.LOW_LEVEL_SIGWX_FT)
        resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=30)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        region_paths[area] = dest_path
    return sigwx_field.build_field(region_paths)


def main():
    metars = metar.fetch_metars()
    points = [(m["lat"], m["lon"]) for m in metars]

    elevations = terrain.get_elevations(points)
    weather_entries = weather.fetch_weather(points)

    print("下層悪天予想図から雲底点を抽出中...")
    field = build_sigwx_field()
    print(f"  抽出点数: {len(field)}")
    sigwx_base_list = [
        sigwx_field.nearest_cloud_base(lat, lon, field) for lat, lon in points
    ]

    # METARナウキャスト上書きは使わず、LCL(JMA MSM)とSIGWXそのものの精度を見る
    classifications_lcl = vmc.classify_all(elevations, weather_entries)
    classifications_sigwx = vmc.classify_all(elevations, weather_entries, sigwx_base_list)

    print(
        f"{'ICAO':6}{'実況雲':10}{'実測天井(m)':12}{'LCL gap(m)':12}{'SIGWX gap(m)':14}"
        f"{'実測視程(m)':12}{'低層雲%':8}{'LCL判定':8}{'SIGWX判定':8}"
    )
    for m, w, c_lcl, c_sigwx, sigwx_msl in zip(
        metars, weather_entries, classifications_lcl, classifications_sigwx, sigwx_base_list
    ):
        ac_ceil = metar.actual_ceiling_m(m.get("clouds", []))
        ac_vis = metar.actual_visibility_m(m.get("visib", "6+"))
        cover_summary = m.get("cover", "?")
        low_cloud = w["cloud_cover_low"] if w else None

        def fmt(v):
            return f"{v:10.0f}" if isinstance(v, (int, float)) else f"{'N/A':>10}"

        gap_lcl = c_lcl["gap_m"] if c_lcl else None
        gap_sigwx = c_sigwx["gap_m"] if (c_sigwx and sigwx_msl is not None) else None
        status_lcl = c_lcl["status"] if c_lcl else "N/A"
        status_sigwx = c_sigwx["status"] if (c_sigwx and sigwx_msl is not None) else "N/A"

        print(
            f"{m['icaoId']:6}{cover_summary:10}{fmt(ac_ceil)}  {fmt(gap_lcl)}  {fmt(gap_sigwx)}  "
            f"{fmt(ac_vis)}  {str(low_cloud):>6}  {status_lcl:>7}  {status_sigwx:>8}"
        )

    with open("calibration_raw.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "metars": metars,
                "elevations": elevations,
                "weather": weather_entries,
                "sigwx_base_list": sigwx_base_list,
                "classifications_lcl": classifications_lcl,
                "classifications_sigwx": classifications_sigwx,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    main()
