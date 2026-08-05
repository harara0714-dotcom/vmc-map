"""matplotlibで日本地図にVMC判定結果を重ねてPNGとして保存する。"""

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["font.family"] = [
    "Hiragino Sans",
    "Hiragino Kaku Gothic Pro",
    "Yu Gothic",
    "Noto Sans CJK JP",
    "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path
import numpy as np
from PIL import Image
import requests

import config
import livecam
import sigwx_georef

STATUS_LABELS = {
    "green": "VMC維持可 (余裕あり)",
    "yellow": "VMC維持は際どい (注意)",
    "red": "VMC維持不可",
}


def _download_japan_coastline():
    resp = requests.get(
        config.NE_50M_COUNTRIES_URL,
        headers={"User-Agent": config.USER_AGENT},
        timeout=60,
    )
    resp.raise_for_status()
    world = resp.json()
    japan_feature = None
    for feature in world["features"]:
        props = feature.get("properties", {})
        if props.get("ADMIN") == "Japan" or props.get("NAME") == "Japan":
            japan_feature = feature
            break
    if japan_feature is None:
        raise RuntimeError("Natural Earthデータセット内にJapanが見つかりません")

    os.makedirs(config.CACHE_DIR, exist_ok=True)
    with open(config.JAPAN_COASTLINE_CACHE, "w", encoding="utf-8") as f:
        json.dump(japan_feature, f)
    return japan_feature


def load_japan_coastline():
    if os.path.exists(config.JAPAN_COASTLINE_CACHE):
        with open(config.JAPAN_COASTLINE_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    return _download_japan_coastline()


def _polygons_from_geometry(geometry):
    gtype = geometry["type"]
    coords = geometry["coordinates"]
    if gtype == "Polygon":
        return [coords]
    if gtype == "MultiPolygon":
        return coords
    raise ValueError(f"未対応のgeometry type: {gtype}")


def _rings_to_path(rings):
    vertices = []
    codes = []
    for ring in rings:
        if len(ring) < 3:
            continue
        vertices.append(ring[0])
        codes.append(Path.MOVETO)
        for pt in ring[1:]:
            vertices.append(pt)
            codes.append(Path.LINETO)
        vertices.append(ring[0])
        codes.append(Path.CLOSEPOLY)
    return Path(vertices, codes)


def _write_html_map(
    points,
    classifications,
    elevations,
    valid_time_str,
    sigwx_valid_time_str,
    layers,
    html_path,
):
    """420箇所ある透明リンクの重ね方式(CSS position:absolute + %位置)がiOS Safariで
    タップに全く反応しない(長押しメニューも出ない)報告があったため、DOM要素を大量に
    重ねる方式をやめ、画像を1枚のクリック対象にしてJSでタップ位置→緯度経度→最寄りの
    ライブカメラURLを判定してwindow.openする方式に変更(ブラウザ非依存で確実)。
    """
    prefectures = livecam.load_prefectures()

    region_points = []
    elevation_points = []
    for (lat, lon), c, elev in zip(points, classifications, elevations):
        if c is None:
            continue
        if elev is not None:
            elevation_points.append([round(lat, 4), round(lon, 4), round(elev * 3.28084)])
        url = livecam.livecam_url(lat, lon, prefectures)
        if url is None:
            continue
        region_points.append([round(lat, 4), round(lon, 4), url])

    points_json = json.dumps(region_points, ensure_ascii=False)
    elevation_points_json = json.dumps(elevation_points, ensure_ascii=False)
    def _layer_entry(layer):
        entry = {
            "label": layer["label"],
            "filename": layer["filename"],
            "axLeft": layer["axes_frac"]["left"],
            "axRight": layer["axes_frac"]["right"],
            "axTop": layer["axes_frac"]["top"],
            "axBottom": layer["axes_frac"]["bottom"],
        }
        if layer.get("mercator"):
            entry["mercator"] = layer["mercator"]
        if layer.get("caption"):
            entry["caption"] = layer["caption"]
        return entry

    layers_json = json.dumps([_layer_entry(layer) for layer in layers], ensure_ascii=False)
    layer_tabs = "".join(
        f'<button type="button" class="layer-tab{" active" if i == 0 else ""}" data-layer="{i}">'
        f'{layer["label"]}</button>'
        for i, layer in enumerate(layers)
    )

    sigwx_chip = (
        f'<span class="chip">下層悪天予想図 有効時刻 <b>{sigwx_valid_time_str}</b></span>'
        if sigwx_valid_time_str
        else ""
    )

    sigwx_area_buttons = "".join(
        f'<button type="button" class="source-link area-btn" data-area="{area}">{name}</button>'
        for area, name in config.LOW_LEVEL_SIGWX_AREAS.items()
    )
    sigwx_areas_json = json.dumps(
        {
            area: {
                "name": name,
                "fts": [
                    {
                        "ft": str(int(ft)),
                        "filename": f"{config.sigwx_region_dirname(ft)}/{area}.png",
                    }
                    for ft in config.LOW_LEVEL_SIGWX_FTS
                ],
            }
            for area, name in config.LOW_LEVEL_SIGWX_AREAS.items()
        },
        ensure_ascii=False,
    )
    sigwx_source_links = sigwx_area_buttons
    sigwx_source_links += (
        '<a class="source-link" href="fbjp_reference.png" target="_blank" rel="noopener">'
        "全国(FBJP)</a>"
        '<a class="source-link" href="https://www.data.jma.go.jp/airinfo/data/'
        'awfo_low-level_sigwx.html" target="_blank" rel="noopener">気象庁 原本サイト</a>'
        '<a class="source-link" href="theta_e_850hpa.png" target="_blank" rel="noopener">'
        "850hPa相当温位図(自前算出)</a>"
        '<a class="source-link" href="https://maps.gsi.go.jp/" target="_blank" rel="noopener">'
        "出典: 国土地理院(色別標高図)</a>"
    )

    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VFR VMC 維持可否マップ (対象時刻: {valid_time_str} UTC)</title>
<style>
  :root {{
    --bg: #eef1f5; --surface: #ffffff; --text: #1b2530; --text-muted: #5b6b7d;
    --border: #d7dee6; --accent: #2b6a8f; --accent-soft: rgba(43,106,143,0.10);
    --shadow: 0 1px 2px rgba(20,30,40,0.06), 0 8px 24px rgba(20,30,40,0.07);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d141c; --surface: #141d27; --text: #e6ecf2; --text-muted: #93a4b8;
      --border: #263242; --accent: #74acce; --accent-soft: rgba(116,172,206,0.14);
      --shadow: 0 1px 2px rgba(0,0,0,0.5), 0 8px 24px rgba(0,0,0,0.4);
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #0d141c; --surface: #141d27; --text: #e6ecf2; --text-muted: #93a4b8;
    --border: #263242; --accent: #74acce; --accent-soft: rgba(116,172,206,0.14);
    --shadow: 0 1px 2px rgba(0,0,0,0.5), 0 8px 24px rgba(0,0,0,0.4);
  }}
  :root[data-theme="light"] {{
    --bg: #eef1f5; --surface: #ffffff; --text: #1b2530; --text-muted: #5b6b7d;
    --border: #d7dee6; --accent: #2b6a8f; --accent-soft: rgba(43,106,143,0.10);
    --shadow: 0 1px 2px rgba(20,30,40,0.06), 0 8px 24px rgba(20,30,40,0.07);
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", "Noto Sans JP", sans-serif;
    line-height: 1.6; padding: 40px 20px 64px;
  }}
  .page {{ max-width: 980px; margin: 0 auto; display: flex; flex-direction: column; gap: 26px; }}
  header.brief {{ display:flex; flex-direction:column; gap:12px; }}
  .eyebrow {{
    font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.72rem;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent);
  }}
  h1 {{ font-size: clamp(1.5rem, 1.1rem + 1.6vw, 2.15rem); margin:0; letter-spacing:-0.01em; text-wrap: balance; font-weight:700; }}
  .subtitle {{ color: var(--text-muted); font-size: 0.95rem; margin:0; max-width: 62ch; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:10px; }}
  .chip {{
    font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.78rem;
    font-variant-numeric: tabular-nums; letter-spacing: 0.01em;
    background: var(--accent-soft); color: var(--accent); border: 1px solid var(--border);
    border-radius: 7px; padding: 7px 11px; display:flex; gap:7px; align-items:baseline;
  }}
  .chip b {{ font-weight:600; color: var(--text); font-family: inherit; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:18px; align-items:center; font-size:0.85rem; color:var(--text-muted); }}
  .refresh-row {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
  .refresh-btn {{
    font: inherit; font-size: 0.85rem; font-weight:600; color: var(--surface);
    background: var(--accent); border: 1px solid var(--accent); border-radius: 8px;
    padding: 9px 16px; cursor: pointer; transition: opacity 0.15s;
  }}
  .refresh-btn:hover {{ opacity: 0.88; }}
  .refresh-btn:disabled {{ opacity: 0.5; cursor: default; }}
  .legend .item {{ display:flex; align-items:center; gap:7px; }}
  .swatch {{ width:14px; height:14px; border-radius:3px; display:inline-block; flex:none; }}
  .layer-tabs {{ display:flex; flex-wrap:wrap; gap:8px; }}
  .layer-tab {{
    font: inherit; font-size: 0.85rem; color: var(--text); background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px;
    cursor: pointer; transition: background 0.15s, color 0.15s, border-color 0.15s;
  }}
  .layer-tab:hover {{ border-color: var(--accent); }}
  .layer-tab.active {{ background: var(--accent); color: var(--surface); border-color: var(--accent); font-weight:600; }}
  .map-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 10px; }}
  .map-container {{ position: relative; display:block; line-height:0; border-radius: 9px; overflow:hidden; }}
  .map-container img {{
    display:block; width:100%; height:auto; cursor: pointer;
    -webkit-tap-highlight-color: var(--accent-soft);
  }}
  .elev-tooltip {{
    position: absolute; pointer-events: none; z-index: 5;
    background: var(--surface); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 11px; font-size: 0.8rem; font-weight:600;
    white-space: nowrap; box-shadow: var(--shadow); opacity: 0;
    transform: translate(14px, -130%); transition: opacity 0.1s;
  }}
  .elev-tooltip.visible {{ opacity: 1; }}
  .hint {{ font-size: 0.85rem; color: var(--text-muted); margin:0; }}
  .sources {{ display:flex; flex-direction:column; gap:10px; }}
  .source-links {{ display:flex; flex-wrap:wrap; gap:8px; }}
  .source-link {{
    font: inherit; font-size: 0.82rem; color: var(--accent); background: var(--accent-soft);
    border: 1px solid var(--border); border-radius: 999px; padding: 6px 14px;
    text-decoration: none; cursor: pointer; -webkit-appearance: none; appearance: none;
    transition: background 0.15s, color 0.15s;
  }}
  .source-link:hover, .source-link:focus-visible {{ background: var(--accent); color: var(--surface); }}
  .area-btn.active {{ background: var(--accent); color: var(--surface); font-weight:600; }}
  .sigwx-area-panel {{ display:flex; flex-direction:column; gap:14px; }}
  .sigwx-area-panel .sigwx-item {{ display:flex; flex-direction:column; gap:6px; }}
  .sigwx-area-panel .sigwx-item-label {{ font-size:0.8rem; color:var(--text-muted); font-weight:600; }}
  .sigwx-area-panel img {{ width:100%; height:auto; border-radius:8px; border:1px solid var(--border); display:block; }}
  footer.notes {{ border-top: 1px solid var(--border); padding-top:18px; font-size:0.8rem; color:var(--text-muted); display:flex; flex-direction:column; gap:7px; }}
  footer.notes strong {{ color: var(--text); }}
</style>
</head>
<body>
<div class="page">
  <header class="brief">
    <span class="eyebrow">VFR Planning Reference</span>
    <h1>VFR VMC 維持可否マップ</h1>
    <p class="subtitle">日本全国、地形と雲底の隙間からVMC(視認気象状態)を維持できるかを判定した参考マップです。v1簡易判定につき、実運航の判断には正式な気象情報を使用してください。</p>
    <div class="chips">
      <span class="chip">気象予報 対象時刻 <b>{valid_time_str} UTC</b></span>
      {sigwx_chip}
    </div>
    <div class="refresh-row">
      <button type="button" id="refreshBtn" class="refresh-btn">今すぐ最新データを取得</button>
      <span id="refreshStatus" class="hint"></span>
    </div>
  </header>

  <div id="statusLegend" class="legend">
    <span class="item"><span class="swatch" style="background:{config.STATUS_COLORS['green']}"></span>{STATUS_LABELS['green']}</span>
    <span class="item"><span class="swatch" style="background:{config.STATUS_COLORS['yellow']}"></span>{STATUS_LABELS['yellow']}</span>
    <span class="item"><span class="swatch" style="background:{config.STATUS_COLORS['red']}"></span>{STATUS_LABELS['red']}</span>
  </div>

  <div class="layer-tabs">{layer_tabs}</div>
  <p id="layerCaption" class="hint"></p>

  <div class="map-card">
    <div class="map-container" id="mapContainer">
      <img id="vmcImg" src="{layers[0]['filename']}" alt="{layers[0]['label']}">
      <div id="elevTooltip" class="elev-tooltip"></div>
    </div>
  </div>
  <p id="elevInfo" class="hint">地図にカーソルを合わせる(スマホは指でなぞる)と、その地点の標高が表示されます。</p>
  <p class="hint">地図をタップ/クリックすると、一番近い地点の都道府県のウェザーニューズ・ライブカメラ一覧が別タブで開きます。</p>

  <div class="sources">
    <p class="hint">気象庁 下層悪天予想図(原本)を見る(地域を選ぶとFT3/FT6/FT9をまとめて表示):</p>
    <div class="source-links">{sigwx_source_links}</div>
    <div id="sigwxAreaPanel" class="sigwx-area-panel"></div>
  </div>

  <footer class="notes">
    <p><strong>参考情報としてご利用ください。</strong>管制空域境界は未反映、雲底高度はLCL近似値/気象庁MSMベースの推定値です。薄く重ねた図は気象庁下層悪天予想図の実況(座標校正済み地域のみ)。</p>
    <p>データ出典: 標高=国土地理院 / 気象=Open-Meteo(気象庁MSM) / 実況=aviationweather.gov METAR / 悪天図=気象庁 / 地図境界=Natural Earth / ライブカメラリンク先=ウェザーニューズ</p>
  </footer>
</div>
<script>
(function() {{
  var livecamPoints = {points_json};
  var elevationPoints = {elevation_points_json};
  var sigwxAreas = {sigwx_areas_json};
  var layers = {layers_json};
  var currentLayer = 0;
  var lonMin = {config.LON_MIN}, lonMax = {config.LON_MAX};
  var latMin = {config.LAT_MIN}, latMax = {config.LAT_MAX};
  var maxDist = {config.GRID_STEP_DEG} * 0.8;
  var img = document.getElementById('vmcImg');
  var mapContainer = document.getElementById('mapContainer');
  var elevInfo = document.getElementById('elevInfo');
  var elevInfoDefault = elevInfo.textContent;
  var elevTooltip = document.getElementById('elevTooltip');
  var statusLegend = document.getElementById('statusLegend');
  var layerCaption = document.getElementById('layerCaption');

  function pixelToLatLon(clientX, clientY) {{
    var layer = layers[currentLayer];
    var rect = img.getBoundingClientRect();
    var xFracImg = (clientX - rect.left) / rect.width;
    var yFracImg = (clientY - rect.top) / rect.height;
    if (xFracImg < layer.axLeft || xFracImg > layer.axRight ||
        yFracImg < layer.axTop || yFracImg > layer.axBottom) {{
      return null; // タイトル・軸ラベル・凡例部分
    }}
    var xFrac = (xFracImg - layer.axLeft) / (layer.axRight - layer.axLeft);
    var yFrac = (yFracImg - layer.axTop) / (layer.axBottom - layer.axTop);
    if (layer.mercator) {{
      // 地理院地図タイルはWebメルカトル図法(経度は線形だが緯度は非線形)なので、
      // 他レイヤ(matplotlibの等距円筒図法)と同じ線形補間では緯度がずれる。
      var m = layer.mercator;
      var n = Math.pow(2, m.zoom) * 256;
      var px = m.x0 + xFrac * (m.x1 - m.x0);
      var py = m.y0 + yFrac * (m.y1 - m.y0);
      var lon = px / n * 360 - 180;
      var latRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * py / n)));
      return {{ lon: lon, lat: latRad * 180 / Math.PI }};
    }}
    return {{
      lon: lonMin + xFrac * (lonMax - lonMin),
      lat: latMax - yFrac * (latMax - latMin)
    }};
  }}

  function selectLayer(index) {{
    currentLayer = index;
    img.src = layers[index].filename;
    img.alt = layers[index].label;
    statusLegend.style.display = (index === 0) ? '' : 'none';
    layerCaption.textContent = layers[index].caption || '';
    var tabs = document.querySelectorAll('.layer-tab');
    for (var i = 0; i < tabs.length; i++) {{
      tabs[i].classList.toggle('active', i === index);
    }}
    elevInfo.textContent = elevInfoDefault;
    elevTooltip.classList.remove('visible');
  }}

  var tabButtons = document.querySelectorAll('.layer-tab');
  for (var t = 0; t < tabButtons.length; t++) {{
    tabButtons[t].addEventListener('click', function() {{
      selectLayer(parseInt(this.getAttribute('data-layer'), 10));
    }});
  }}

  var sigwxAreaPanel = document.getElementById('sigwxAreaPanel');
  var areaButtons = document.querySelectorAll('.area-btn');
  var activeArea = null;
  for (var a = 0; a < areaButtons.length; a++) {{
    areaButtons[a].addEventListener('click', function() {{
      var area = this.getAttribute('data-area');
      for (var i = 0; i < areaButtons.length; i++) {{
        areaButtons[i].classList.remove('active');
      }}
      if (activeArea === area) {{
        activeArea = null;
        sigwxAreaPanel.innerHTML = '';
        return;
      }}
      activeArea = area;
      this.classList.add('active');
      var info = sigwxAreas[area];
      var html = '';
      for (var j = 0; j < info.fts.length; j++) {{
        var item = info.fts[j];
        html += '<div class="sigwx-item"><div class="sigwx-item-label">' + info.name +
          ' FT' + item.ft + '</div><img src="' + item.filename + '" alt="' + info.name +
          ' FT' + item.ft + '" loading="lazy"></div>';
      }}
      sigwxAreaPanel.innerHTML = html;
    }});
  }}

  function findNearest(pts, lat, lon) {{
    var best = null, bestDist = Infinity;
    for (var i = 0; i < pts.length; i++) {{
      var dLat = pts[i][0] - lat, dLon = pts[i][1] - lon;
      var dist = dLat * dLat + dLon * dLon;
      if (dist < bestDist) {{ bestDist = dist; best = pts[i]; }}
    }}
    return {{ point: best, dist: best ? Math.sqrt(bestDist) : Infinity }};
  }}

  function handleTap(clientX, clientY) {{
    var ll = pixelToLatLon(clientX, clientY);
    if (!ll) return;
    var r = findNearest(livecamPoints, ll.lat, ll.lon);
    if (r.point && r.dist <= maxDist) {{
      window.open(r.point[2], '_blank', 'noopener');
    }}
  }}

  function showElevation(clientX, clientY) {{
    var ll = pixelToLatLon(clientX, clientY);
    if (!ll) {{
      elevInfo.textContent = elevInfoDefault;
      elevTooltip.classList.remove('visible');
      return;
    }}
    var r = findNearest(elevationPoints, ll.lat, ll.lon);
    var text;
    if (r.point && r.dist <= maxDist) {{
      text = "標高 " + r.point[2] + " ft";
      elevInfo.textContent = "標高: " + r.point[2] + " ft  (緯度" + ll.lat.toFixed(2) + " / 経度" + ll.lon.toFixed(2) + ")";
    }} else {{
      text = "標高: 海上/データなし";
      elevInfo.textContent = text;
    }}
    var rect = mapContainer.getBoundingClientRect();
    var left = clientX - rect.left;
    var top = clientY - rect.top;
    // ツールチップが右端・上端からはみ出さないよう反転させる
    var flipX = left > rect.width - 120;
    var flipY = top < 60;
    elevTooltip.style.left = left + 'px';
    elevTooltip.style.top = top + 'px';
    elevTooltip.style.transform = "translate(" + (flipX ? "-100%" : "14px") + ", " + (flipY ? "20px" : "-130%") + ")";
    elevTooltip.textContent = text;
    elevTooltip.classList.add('visible');
  }}

  img.addEventListener('click', function(e) {{
    handleTap(e.clientX, e.clientY);
  }});
  img.addEventListener('mousemove', function(e) {{
    showElevation(e.clientX, e.clientY);
  }});
  img.addEventListener('mouseleave', function() {{
    elevInfo.textContent = elevInfoDefault;
    elevTooltip.classList.remove('visible');
  }});
  img.addEventListener('touchstart', function(e) {{
    var t = e.touches[0];
    showElevation(t.clientX, t.clientY);
  }}, {{ passive: true }});
  img.addEventListener('touchmove', function(e) {{
    var t = e.touches[0];
    showElevation(t.clientX, t.clientY);
  }}, {{ passive: true }});

  var dispatchToken = "{config.GH_DISPATCH_TOKEN}";
  var refreshBtn = document.getElementById('refreshBtn');
  var refreshStatus = document.getElementById('refreshStatus');
  var COOLDOWN_MS = 5 * 60 * 1000;

  function updateCooldownUI() {{
    var last = parseInt(localStorage.getItem('vmcLastDispatch') || '0', 10);
    var remain = COOLDOWN_MS - (Date.now() - last);
    if (remain > 0) {{
      refreshBtn.disabled = true;
      refreshStatus.textContent = 'リクエスト送信済み。しばらくお待ちください(あと約' + Math.ceil(remain / 60000) + '分)';
      setTimeout(updateCooldownUI, 15000);
    }} else {{
      refreshBtn.disabled = false;
      refreshStatus.textContent = '';
    }}
  }}

  if (!dispatchToken) {{
    refreshBtn.style.display = 'none';
  }} else {{
    updateCooldownUI();
    refreshBtn.addEventListener('click', function() {{
      refreshBtn.disabled = true;
      refreshStatus.textContent = 'リクエスト送信中...';
      fetch('https://api.github.com/repos/{config.GH_ACTIONS_REPO}/actions/workflows/{config.GH_ACTIONS_WORKFLOW}/dispatches', {{
        method: 'POST',
        headers: {{
          'Authorization': 'Bearer ' + dispatchToken,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28'
        }},
        body: JSON.stringify({{ref: 'main'}})
      }}).then(function(resp) {{
        if (resp.status === 204) {{
          localStorage.setItem('vmcLastDispatch', String(Date.now()));
          refreshStatus.textContent = '更新をリクエストしました。3〜5分後にページを再読み込みしてください。';
          setTimeout(updateCooldownUI, 5000);
        }} else {{
          refreshBtn.disabled = false;
          refreshStatus.textContent = 'リクエスト失敗 (' + resp.status + ')';
        }}
      }}).catch(function() {{
        refreshBtn.disabled = false;
        refreshStatus.textContent = '通信エラーが発生しました';
      }});
    }});
  }}
}})();
</script>
</body>
</html>
"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def _region_center(region):
    """地域パネルの4隅の平均から、その地域の中心緯度経度を求める。"""
    left, top, right, bottom = sigwx_georef.panel_bbox(region)
    lats, lons = [], []
    for x, y in ((left, top), (right, top), (left, bottom), (right, bottom)):
        lat, lon = sigwx_georef.pixel_to_latlon(region, x, y)
        lats.append(lat)
        lons.append(lon)
    return sum(lats) / 4, sum(lons) / 4


def _sigwx_overlay(image_path, region, region_centers):
    """下層悪天予想図の詳細パネルを、白地を透過させたRGBA画像とlon/lat範囲で返す。

    地域6分割は隣接図とわざと範囲が重なる仕様なので、重複部分は「その地点から
    最も近い中心を持つ地域」だけを描画し、二重描画による継ぎ目を無くす。
    校正データが無い地域はNone。
    """
    bbox = sigwx_georef.panel_bbox(region)
    if bbox is None:
        return None

    left, top, right, bottom = bbox
    cropped = Image.open(image_path).convert("RGB").crop((left, top, right, bottom))
    arr = np.array(cropped)
    h, w = arr.shape[:2]

    non_white = (arr < 245).any(axis=2)
    alpha = np.where(non_white, 210, 0).astype(np.uint8)
    border_px = 3  # 元図の外枠線を除去(継ぎ目に黒線が残らないように)
    alpha[:border_px, :] = 0
    alpha[-border_px:, :] = 0
    alpha[:, :border_px] = 0
    alpha[:, -border_px:] = 0

    georef = config.SIGWX_GEOREF[region]
    xx, yy = np.meshgrid(left + np.arange(w), top + np.arange(h))
    lon_grid = georef["lon_a"] * xx + georef["lon_b"]
    lat_grid = georef["lat_a"] * yy + georef["lat_b"]

    own_lat, own_lon = region_centers[region]
    own_dist2 = (lat_grid - own_lat) ** 2 + (lon_grid - own_lon) ** 2
    owned = np.ones_like(own_dist2, dtype=bool)
    for other, (o_lat, o_lon) in region_centers.items():
        if other == region:
            continue
        other_dist2 = (lat_grid - o_lat) ** 2 + (lon_grid - o_lon) ** 2
        owned &= own_dist2 <= other_dist2

    alpha = np.where(owned, alpha, 0)
    rgba = np.dstack([arr, alpha])

    lat_top, lon_left = sigwx_georef.pixel_to_latlon(region, left, top)
    lat_bottom, lon_right = sigwx_georef.pixel_to_latlon(region, right, bottom)
    extent = [lon_left, lon_right, lat_bottom, lat_top]
    return rgba, extent


def render_map(
    points,
    classifications,
    valid_time_str,
    out_path,
    html_path=None,
    sigwx_image_paths=None,
    sigwx_valid_time_str=None,
    elevations=None,
    extra_layers=None,
):
    """points: [(lat, lon), ...]、classifications: vmc.classify_all()の結果と対応

    html_path を指定すると、同じ地図にクリック可能なライブカメラリンクを重ねた
    HTML(画像マップ)も併せて生成する。
    sigwx_image_paths を指定すると、校正済み地域については下層悪天予想図の実画像
    (雲域・雲頂雲底の数値)を白地を透過させて薄く重ねる。
    sigwx_valid_time_str を指定すると、その下層悪天予想図がいつの時刻のものかを
    タイトルに明記する(気象予報の対象時刻とは別物であることが分かるように)。
    elevations を指定すると、HTML版でカーソル(タップ)位置の標高をft表示する。
    extra_layers を指定すると、HTML版に地図切り替えタブを追加する。
    [{"label": "標高マップ", "filename": "elevation_map.png", "axes_frac": {...}}, ...] の形式。
    """
    coastline = load_japan_coastline()
    polygons = _polygons_from_geometry(coastline["geometry"])

    fig, ax = plt.subplots(figsize=(10, 11), dpi=150)

    for rings in polygons:
        path = _rings_to_path(rings)
        patch = PathPatch(
            path, facecolor="#e8e8e0", edgecolor="#888888", linewidth=0.5, zorder=1
        )
        ax.add_patch(patch)

    if sigwx_image_paths:
        region_centers = {region: _region_center(region) for region in sigwx_image_paths}
        for region, image_path in sigwx_image_paths.items():
            overlay = _sigwx_overlay(image_path, region, region_centers)
            if overlay is None:
                continue
            rgba, extent = overlay
            ax.imshow(rgba, extent=extent, zorder=1.5, interpolation="nearest", aspect="auto")

    plot_lons, plot_lats, colors = [], [], []
    for (lat, lon), c in zip(points, classifications):
        if c is None:
            continue
        plot_lons.append(lon)
        plot_lats.append(lat)
        colors.append(config.STATUS_COLORS[c["status"]])

    ax.scatter(
        plot_lons,
        plot_lats,
        c=colors,
        s=55,
        marker="s",
        zorder=2,
        edgecolors="none",
        alpha=0.65 if sigwx_image_paths else 0.85,
    )

    ax.set_xlim(config.LON_MIN, config.LON_MAX)
    ax.set_ylim(config.LAT_MIN, config.LAT_MAX)
    ax.set_aspect(1.0)
    ax.set_xlabel("経度")
    ax.set_ylabel("緯度")

    legend_elements = [
        Patch(facecolor=config.STATUS_COLORS[s], label=STATUS_LABELS[s])
        for s in ("green", "yellow", "red")
    ]
    legend_elements.append(Line2D([0], [0], marker="", linestyle=""))
    ax.legend(handles=legend_elements, loc="lower left", fontsize=8, framealpha=0.9)

    if sigwx_image_paths:
        sigwx_time_note = f"(有効時刻: {sigwx_valid_time_str})" if sigwx_valid_time_str else "(有効時刻不明)"
        overlay_note = (
            f"\n薄く重ねた図は下層悪天予想図の実況{sigwx_time_note}(校正済み地域のみ、雲頂/雲底はhundred-ft単位)"
        )
    else:
        overlay_note = ""
    ax.set_title(
        f"VFR VMC維持可否マップ（v1簡易判定・参考情報） 対象時刻: {valid_time_str} UTC\n"
        f"※管制空域境界は未反映、雲底高度はLCL近似値。実運航の判断には正式な気象情報を使用してください{overlay_note}",
        fontsize=9,
    )

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    fig.canvas.draw()
    (x0, y0), (x1, y1) = ax.transData.transform(
        [(config.LON_MIN, config.LAT_MIN), (config.LON_MAX, config.LAT_MAX)]
    )
    fig_w_px, fig_h_px = fig.get_size_inches() * fig.dpi
    # 図全体(タイトル・軸ラベル・凡例込み)に対する、実際の地図プロット部分の割合。
    # 画像上のクリック位置→緯度経度の変換に使う(タイトルや余白をクリックしても
    # 反応しないよう、またプロット内は正しい緯度経度になるよう補正するため)。
    axes_frac = {
        "left": min(x0, x1) / fig_w_px,
        "right": max(x0, x1) / fig_w_px,
        "top": 1.0 - max(y0, y1) / fig_h_px,
        "bottom": 1.0 - min(y0, y1) / fig_h_px,
    }

    fig.savefig(out_path)

    if html_path is not None:
        layers = [
            {"label": "VMCマップ", "filename": os.path.basename(out_path), "axes_frac": axes_frac}
        ]
        layers.extend(extra_layers or [])
        _write_html_map(
            points,
            classifications,
            elevations or [None] * len(points),
            valid_time_str,
            sigwx_valid_time_str,
            layers,
            html_path,
        )

    return axes_frac

    plt.close(fig)
    return out_path
