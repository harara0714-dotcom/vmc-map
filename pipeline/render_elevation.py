"""地形標高マップ(ft)をmatplotlibで描画する。

VMCマップ生成時に既に取得済みのDEM標高データ(terrain.get_elevations)をそのまま
使うので、追加のAPI呼び出しは発生しない。
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import PathPatch

import config
import render


def render_elevation_map(points, elevations, out_path):
    """points/elevations: main.generate_grid()とterrain.get_elevations()の結果と対応

    HTML版の地図切り替えタブで使うaxes_frac(図全体に対する実プロット部分の割合)を返す。
    """
    lats = sorted(set(round(p[0], 4) for p in points))
    lons = sorted(set(round(p[1], 4) for p in points))
    lat_idx = {lat: i for i, lat in enumerate(lats)}
    lon_idx = {lon: i for i, lon in enumerate(lons)}

    grid = np.full((len(lats), len(lons)), np.nan)
    for (lat, lon), elev in zip(points, elevations):
        if elev is None:
            continue
        grid[lat_idx[round(lat, 4)], lon_idx[round(lon, 4)]] = elev * 3.28084  # ft

    coastline = render.load_japan_coastline()
    polygons = render._polygons_from_geometry(coastline["geometry"])

    fig, ax = plt.subplots(figsize=(10, 11), dpi=150)

    finite = grid[np.isfinite(grid)]
    vmax = max(float(finite.max()), 3000.0) if finite.size else 12000.0
    mesh = ax.pcolormesh(
        lons, lats, grid, shading="nearest", cmap="terrain", vmin=0, vmax=vmax, zorder=1
    )
    cbar = fig.colorbar(mesh, ax=ax, orientation="vertical", fraction=0.035, pad=0.02)
    cbar.set_label("標高 (ft)")

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
        "地形標高マップ（国土地理院DEM・参考情報）\n※最低安全高度の目安。正式な運航判断には航空図を使用してください",
        fontsize=9,
    )

    fig.tight_layout()
    fig.canvas.draw()
    (x0, y0), (x1, y1) = ax.transData.transform(
        [(config.LON_MIN, config.LAT_MIN), (config.LON_MAX, config.LAT_MAX)]
    )
    fig_w_px, fig_h_px = fig.get_size_inches() * fig.dpi
    axes_frac = {
        "left": min(x0, x1) / fig_w_px,
        "right": max(x0, x1) / fig_w_px,
        "top": 1.0 - max(y0, y1) / fig_h_px,
        "bottom": 1.0 - min(y0, y1) / fig_h_px,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return axes_frac
