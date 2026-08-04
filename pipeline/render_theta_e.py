"""850hPa相当温位(θe)の色付きマップをmatplotlibで描画する。"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import PathPatch

import config
import render

VMIN, VMAX = 300.0, 366.0  # カラースケールの範囲(K)。FXJP854で実際に見られる値域を参考に設定


def render_theta_e_map(points, values, valid_time_str, out_path):
    """points: [(lat, lon), ...] (main.generate_grid()と同じ規則的格子)
    values: fetch_theta_e_grid()の結果(同じ順序)
    """
    lats = sorted(set(round(p[0], 4) for p in points))
    lons = sorted(set(round(p[1], 4) for p in points))
    lat_idx = {lat: i for i, lat in enumerate(lats)}
    lon_idx = {lon: i for i, lon in enumerate(lons)}

    grid = np.full((len(lats), len(lons)), np.nan)
    for (lat, lon), v in zip(points, values):
        if v is None:
            continue
        grid[lat_idx[round(lat, 4)], lon_idx[round(lon, 4)]] = v

    coastline = render.load_japan_coastline()
    polygons = render._polygons_from_geometry(coastline["geometry"])

    fig, ax = plt.subplots(figsize=(10, 11), dpi=150)

    mesh = ax.pcolormesh(
        lons, lats, grid, shading="nearest", cmap="RdYlBu_r", vmin=VMIN, vmax=VMAX, zorder=1
    )
    cbar = fig.colorbar(mesh, ax=ax, orientation="vertical", fraction=0.035, pad=0.02)
    cbar.set_label("850hPa 相当温位 θe (K)")

    for rings in polygons:
        path = render._rings_to_path(rings)
        patch = PathPatch(path, facecolor="none", edgecolor="#333333", linewidth=0.6, zorder=2)
        ax.add_patch(patch)

    ax.set_xlim(config.LON_MIN, config.LON_MAX)
    ax.set_ylim(config.LAT_MIN, config.LAT_MAX)
    ax.set_aspect(1.0)
    ax.set_xlabel("経度")
    ax.set_ylabel("緯度")
    ax.set_title(
        f"850hPa相当温位 θe （気象庁MSM実況値から算出・参考情報） 対象時刻: {valid_time_str} UTC\n"
        "※前線・下層暖湿気流入の目安。正式な予報判断には気象庁の資料を使用してください",
        fontsize=9,
    )

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path
