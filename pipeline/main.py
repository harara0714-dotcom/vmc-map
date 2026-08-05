"""VMCマップ生成のCLIエントリポイント。

実行例:
    python main.py                  直近の予報でマップ生成
    python main.py --hours-ahead 6  6時間後の予報でマップ生成

出力:
    output/<timestamp>[_+Nh]/vmc_map.png          VMC判定マップ
    output/<timestamp>[_+Nh]/fbjp_reference.png   気象庁下層悪天予想図の参考画像
"""

import argparse
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

import numpy as np

import config
import deploy_pages
import fbjp
import metar
import render
import render_elevation
import render_gsi_relief
import render_theta_e
import sigwx_field
import terrain
import theta_e
import vmc
import weather


def cleanup_old_outputs(retention_days=None):
    if retention_days is None:
        retention_days = config.OUTPUT_RETENTION_DAYS
    if retention_days <= 0 or not os.path.isdir(config.OUTPUT_DIR):
        return

    cutoff = time.time() - retention_days * 86400
    for name in os.listdir(config.OUTPUT_DIR):
        path = os.path.join(config.OUTPUT_DIR, name)
        if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
            shutil.rmtree(path)
            print(f"  古い出力を削除: {path}")


def generate_grid():
    lats = np.arange(config.LAT_MIN, config.LAT_MAX + config.GRID_STEP_DEG / 2, config.GRID_STEP_DEG)
    lons = np.arange(config.LON_MIN, config.LON_MAX + config.GRID_STEP_DEG / 2, config.GRID_STEP_DEG)
    return [(float(lat), float(lon)) for lat in lats for lon in lons]


def parse_args():
    parser = argparse.ArgumentParser(description="VFR VMCマップ生成")
    parser.add_argument(
        "--hours-ahead",
        type=int,
        default=0,
        help="現在から何時間後の予報を使うか(デフォルト0=直近の予報)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    target_time = None
    if args.hours_ahead:
        target_time = datetime.now(timezone.utc) + timedelta(hours=args.hours_ahead)

    print(f"古い出力の削除確認中 (保持期間: {config.OUTPUT_RETENTION_DAYS}日)...")
    cleanup_old_outputs()

    print("グリッド生成中...")
    points = generate_grid()
    print(f"  {len(points)}点")

    print("標高取得中 (国土地理院DEMタイル)...")
    elevations = terrain.get_elevations(points)
    land_indices = [i for i, e in enumerate(elevations) if e is not None]
    print(f"  陸地点: {len(land_indices)} / {len(points)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    if args.hours_ahead:
        timestamp += f"_+{args.hours_ahead}h"
    out_dir = os.path.join(config.OUTPUT_DIR, timestamp)
    os.makedirs(out_dir, exist_ok=True)

    # 気象データ(Open-Meteo)が失敗しても、標高図・下層悪天オーバーレイなど気象に
    # 依存しない部分は取得できる限り常に最新化したい。そのためここでは例外を
    # 握りつぶさず記録するだけにし、後段でweather_okに応じて処理を分岐する。
    print("気象データ取得中 (Open-Meteo)..." + (f" [{args.hours_ahead}時間後]" if args.hours_ahead else ""))
    land_points = [points[i] for i in land_indices]
    weather_ok = True
    try:
        land_weather = weather.fetch_weather(land_points, target_time=target_time)
    except Exception as e:
        print(f"  取得失敗 (スキップ、VMCマップ本体の更新は見送り): {e}")
        land_weather = []
        weather_ok = False

    weather_entries = [None] * len(points)
    for idx, w in zip(land_indices, land_weather):
        weather_entries[idx] = w

    valid_time = "N/A"
    for w in land_weather:
        if w is not None:
            valid_time = w["valid_time"]
            break

    print("下層悪天予想図(地域6分割)取得中...")
    sigwx_paths = {}
    try:
        sigwx_paths = fbjp.download_low_level_sigwx(
            os.path.join(out_dir, config.sigwx_region_dirname(config.LOW_LEVEL_SIGWX_FT))
        )
        print(f"  保存: {len(sigwx_paths)}枚 -> {out_dir}/low_level_sigwx")
    except Exception as e:
        print(f"  取得失敗 (スキップ): {e}")

    print("下層悪天予想図から雲底点をOCR抽出中(校正済み地域のみ)...")
    calibrated_paths = {
        area: path for area, path in sigwx_paths.items() if area in config.SIGWX_GEOREF
    }
    field = sigwx_field.build_field(calibrated_paths)
    print(f"  抽出点数: {len(field)} (対象地域: {list(calibrated_paths)})")
    sigwx_base_list = [sigwx_field.nearest_cloud_base(lat, lon, field) for lat, lon in points]

    sigwx_valid_time = None
    if sigwx_paths:
        try:
            sigwx_valid_time = fbjp.extract_valid_time(next(iter(sigwx_paths.values())))
            print(f"  下層悪天予想図の有効時刻: {sigwx_valid_time}")
        except Exception as e:
            print(f"  有効時刻の読み取り失敗 (スキップ): {e}")

    metar_base_list = [None] * len(points)
    metar_vis_list = [None] * len(points)
    if target_time is None:
        print(f"METAR実況取得中 (空港周辺{config.METAR_OVERRIDE_RADIUS_KM}km以内を上書き)...")
        try:
            obs = metar.fetch_current_obs()
            for i, (lat, lon) in enumerate(points):
                base, vis = metar.nearest_override(lat, lon, obs)
                metar_base_list[i] = base
                metar_vis_list[i] = vis
            hit_count = sum(1 for b in metar_base_list if b is not None)
            print(f"  {len(obs)}空港取得、{hit_count}地点を上書き")
        except Exception as e:
            print(f"  取得失敗 (スキップ): {e}")

    classifications = None
    if weather_ok:
        print("VMC判定中...")
        classifications = vmc.classify_all(
            elevations, weather_entries, sigwx_base_list, metar_base_list, metar_vis_list
        )
    else:
        print("VMC判定スキップ (気象データ取得失敗のため、VMCマップ本体は前回分を維持)")

    print("標高マップ描画中 (地図切り替えタブ用)...")
    extra_layers = []
    elevation_map_path = os.path.join(out_dir, "elevation_map.png")
    try:
        elevation_axes_frac = render_elevation.render_elevation_map(
            points, elevations, elevation_map_path
        )
        extra_layers.append(
            {
                "label": "標高マップ",
                "filename": os.path.basename(elevation_map_path),
                "axes_frac": elevation_axes_frac,
            }
        )
        print(f"  保存: {elevation_map_path}")
    except Exception as e:
        print(f"  生成失敗 (スキップ): {e}")

    print("色別標高図取得中 (国土地理院タイルをそのままモザイク・切り出し)...")
    gsi_relief_path = os.path.join(out_dir, "gsi_relief_map.png")
    gsi_relief_base = None
    gsi_relief_mercator = None
    try:
        gsi_relief_axes_frac, gsi_relief_mercator, gsi_relief_base = (
            render_gsi_relief.render_gsi_relief_map(gsi_relief_path)
        )
        extra_layers.append(
            {
                "label": "色別標高図(地理院地図)",
                "filename": os.path.basename(gsi_relief_path),
                "axes_frac": gsi_relief_axes_frac,
                "mercator": gsi_relief_mercator,
            }
        )
        print(f"  保存: {gsi_relief_path}")
    except Exception as e:
        print(f"  取得失敗 (スキップ): {e}")

    # FT03の有効時刻から初期時刻(ベースタイム)を逆算する。各FTの有効時刻は
    # 「初期時刻+FT時間」で一致するはずなので、FT06/09用に別途OCRし直す必要はない。
    sigwx_base_time_dt = None
    if sigwx_valid_time:
        try:
            sigwx_base_time_dt = datetime.strptime(
                sigwx_valid_time, "%H%M UTC %d %b %Y"
            ) - timedelta(hours=int(config.LOW_LEVEL_SIGWX_FT))
        except ValueError as e:
            print(f"  下層悪天予想図の初期時刻の算出に失敗 (スキップ): {e}")

    def _sigwx_ft_caption(ft):
        if sigwx_base_time_dt is None:
            return None
        valid_dt = sigwx_base_time_dt + timedelta(hours=int(ft))
        fmt = "%H%M UTC %d %b %Y"
        return f"初期時刻 {sigwx_base_time_dt.strftime(fmt)} / 有効時刻 {valid_dt.strftime(fmt)}"

    if gsi_relief_base is not None:
        print("下層悪天予想図をFT別に色別標高図へ重ね合わせ中...")
        sigwx_paths_by_ft = {"03": calibrated_paths}
        for ft in config.LOW_LEVEL_SIGWX_FTS:
            if ft == "03":
                continue
            try:
                ft_dir = os.path.join(out_dir, config.sigwx_region_dirname(ft))
                ft_paths = fbjp.download_low_level_sigwx(ft_dir, ft=ft)
                sigwx_paths_by_ft[ft] = {
                    area: path for area, path in ft_paths.items() if area in config.SIGWX_GEOREF
                }
                print(f"  FT{ft}: {len(ft_paths)}枚取得")
            except Exception as e:
                print(f"  FT{ft} 取得失敗 (スキップ): {e}")

        for ft in config.LOW_LEVEL_SIGWX_FTS:
            calibrated_ft_paths = sigwx_paths_by_ft.get(ft)
            if not calibrated_ft_paths:
                continue
            combo_path = os.path.join(out_dir, f"gsi_relief_sigwx_ft{ft}.png")
            try:
                render_gsi_relief.overlay_sigwx_on_relief(
                    gsi_relief_base, gsi_relief_mercator, calibrated_ft_paths, combo_path
                )
                extra_layers.append(
                    {
                        "label": f"下層悪天 FT{ft}(標高図)",
                        "filename": os.path.basename(combo_path),
                        "axes_frac": gsi_relief_axes_frac,
                        "mercator": gsi_relief_mercator,
                        "caption": _sigwx_ft_caption(ft),
                    }
                )
                print(f"  保存: {combo_path}")
            except Exception as e:
                print(f"  FT{ft} 重ね合わせ失敗 (スキップ): {e}")

    map_path = None
    html_path = None
    if weather_ok:
        print("地図描画中 (PNG + ライブカメラリンク付きHTML + 下層悪天予想図オーバーレイ)...")
        map_path = os.path.join(out_dir, "vmc_map.png")
        html_path = os.path.join(out_dir, "vmc_map.html")
        vmc_axes_frac = render.render_map(
            points,
            classifications,
            valid_time,
            map_path,
            html_path=html_path,
            sigwx_image_paths=calibrated_paths,
            sigwx_valid_time_str=sigwx_valid_time,
            elevations=elevations,
            extra_layers=extra_layers,
        )
        print(f"  保存: {map_path}")
        print(f"  保存: {html_path}")

        try:
            with open(config.VMC_STATE_CACHE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "points": points,
                        "classifications": classifications,
                        "elevations": elevations,
                        "valid_time": valid_time,
                        "sigwx_valid_time": sigwx_valid_time,
                        "axes_frac": vmc_axes_frac,
                    },
                    f,
                )
        except Exception as e:
            print(f"  VMC状態キャッシュ保存失敗 (スキップ): {e}")
    else:
        # VMCマップ本体(vmc_map.png)は前回分を維持しつつ、直近成功時の判定結果を
        # キャッシュから読み込んでHTMLだけは再生成する。こうすることで、参考リンクや
        # 標高図・下層悪天オーバーレイなど気象に依存しないタブは気象データ取得失敗時
        # でも常に最新化される。
        print("VMCマップHTML再生成中 (前回成功分の判定結果を再利用)...")
        try:
            with open(config.VMC_STATE_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            html_path = os.path.join(out_dir, "vmc_map.html")
            layers = [
                {
                    "label": "VMCマップ",
                    "filename": "vmc_map.png",
                    "axes_frac": cached["axes_frac"],
                }
            ]
            layers.extend(extra_layers)
            render._write_html_map(
                cached["points"],
                cached["classifications"],
                cached["elevations"],
                cached["valid_time"],
                cached["sigwx_valid_time"],
                layers,
                html_path,
            )
            print(f"  保存: {html_path} (VMCマップ本体は {cached['valid_time']} UTC時点のまま)")
        except FileNotFoundError:
            print("  キャッシュなし (初回失敗のためHTML更新もスキップ)")
        except Exception as e:
            print(f"  HTML再生成失敗 (スキップ): {e}")

    print("FBJP参考画像取得中...")
    fbjp_path = os.path.join(out_dir, "fbjp_reference.png")
    try:
        fbjp.download_fbjp(fbjp_path)
        print(f"  保存: {fbjp_path}")
    except Exception as e:
        print(f"  取得失敗 (スキップ): {e}")

    print("850hPa相当温位図を生成中 (気象庁MSMの気温・湿度から算出)...")
    theta_e_path = os.path.join(out_dir, "theta_e_850hpa.png")
    try:
        theta_e_points = theta_e.generate_grid()
        theta_e_values = theta_e.fetch_theta_e_grid(theta_e_points, target_time=target_time)
        render_theta_e.render_theta_e_map(theta_e_points, theta_e_values, valid_time, theta_e_path)
        print(f"  保存: {theta_e_path}")
    except Exception as e:
        print(f"  生成失敗 (スキップ): {e}")

    print("GitHub Pagesへデプロイ中...")
    try:
        deployed = deploy_pages.deploy(out_dir, map_path, html_path)
        print(f"  {'公開しました: ' + config.GH_PAGES_URL if deployed else '変更なし(スキップ)'}")
    except Exception as e:
        print(f"  デプロイ失敗 (スキップ): {e}")

    print("完了")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # スリープ復帰直後などネットワーク未接続でリトライしても失敗した場合、
        # 生々しいトレースバックではなくログで分かる形で終了する。
        # launchdは次回のStartIntervalで改めて実行するので、ここで握りつぶして
        # 正常終了扱いにする必要はない(実行に失敗したことが分かった方がよい)。
        print(f"致命的エラーで終了: {e}")
        raise
