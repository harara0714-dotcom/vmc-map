"""VMCマップ生成の設定値。全て調整可能な定数として集約する。"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DEM_CACHE_DIR = os.path.join(CACHE_DIR, "dem")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# 気象データ取得に失敗した回でも、HTML(タブ・参考リンク等、気象に依存しない部分)は
# 常に最新化したいので、直近成功時のVMC判定結果をここにキャッシュして使い回す。
VMC_STATE_CACHE = os.path.join(CACHE_DIR, "last_vmc_state.json")

# --- 対象範囲・グリッド ---
LAT_MIN, LAT_MAX = 24.0, 46.0
LON_MIN, LON_MAX = 122.0, 146.0
GRID_STEP_DEG = 0.3  # 約30km間隔

# 850hPa相当温位は地形に依らない大気の大規模場で、VMCグリッドほど細かい解像度は
# 不要かつAPI呼び出し数を抑えたいため、専用の粗いグリッドを使う
THETA_E_GRID_STEP_DEG = 1.0  # 約100km間隔

# --- 標高タイル (国土地理院、DEM5A/5B/10Bの合成) ---
DEM_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem/{z}/{x}/{y}.txt"
DEM_ZOOM = 8
DEM_NODATA = "e"

# --- 色別標高図タイル (国土地理院地図をそのままモザイク・切り出しして使う) ---
RELIEF_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png"
RELIEF_ZOOM = 7  # 全国表示で解像度とタイル数(初回ダウンロード数)のバランスを取った値
RELIEF_CACHE_DIR = os.path.join(CACHE_DIR, "relief")

# --- Open-Meteo 気象予報 ---
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
# 雲量・気温・露点は気象庁MSM(日本域, 約5km分解能, 3時間更新)を使う方が精度が良いと
# 期待されるため明示的に指定。ただしJMA系モデルには視程(visibility)が無いため、
# 視程だけは既定モデル(best match)から別途取得する
OPEN_METEO_MODEL = "jma_msm"
OPEN_METEO_MSM_VARS = [
    "cloud_cover_low",
    "cloud_cover_mid",
    "temperature_2m",
    "dew_point_2m",
]
OPEN_METEO_DEFAULT_VARS = [
    "visibility",
]
OPEN_METEO_HOURLY_VARS = OPEN_METEO_MSM_VARS + OPEN_METEO_DEFAULT_VARS
OPEN_METEO_BATCH_SIZE = 80
OPEN_METEO_FORECAST_DAYS = 1
OPEN_METEO_REQUEST_DELAY_SEC = 1.5  # リクエスト間隔(429対策)
OPEN_METEO_MAX_RETRIES = 4  # 429時の再試行回数(Retry-Afterに従って待機)

# --- VMC判定基準 (航空法施行規則第5条 「3000m未満・管制圏外」を基本ケースとして採用) ---
# v1の割り切り: 管制空域境界データを持たないため全域一律。
# 判定は「地形と雲底の隙間に、最低安全高度+雲間隔を同時に満たす高度が存在するか」で行う。
AGL_MIN_M = 150.0  # 最低安全高度の仮定 (約500ft)
CLOUD_CLEARANCE_MIN_M = 150.0  # 雲からの上方垂直距離基準
MARGIN_BUFFER_M = 150.0  # この余裕があればgreen、なければyellow

VIS_MIN_M = 1500.0  # 飛行視程の最低基準
VIS_COMFORT_M = 3000.0  # これ以上あれば視程面では余裕ありとみなす

LOW_CLOUD_COVER_THRESHOLD_PCT = 50.0  # これ未満なら「有意な雲底なし」として扱う
NO_CLOUD_BASE_GAP_M = 99999.0  # 有意な雲がない場合の隙間の代用値

# LCL(持ち上げ凝結高度)近似式の係数: 高度(m) = LCL_COEFFICIENT * (気温 - 露点)
# METAR実測(calibrate.py)との比較で125だと雲底高度を系統的に低く見積もる傾向が見られたため補正
LCL_COEFFICIENT = 150.0

# --- 気象庁 悪天予想図 (参考画像。自動解析はせず並べて保存するだけ) ---
FBJP_URL = "https://www.data.jma.go.jp/airinfo/data/pict/fbjp/fbjp.png"

# 下層悪天予想図(地域版, SFC-FL150。VFRの高度帯に対応した詳細な雲底/雲頂・降水域図)
LOW_LEVEL_SIGWX_URL_TEMPLATE = (
    "https://www.data.jma.go.jp/airinfo/data/pict/low-level_sigwx/{area}{ft}.png"
)
LOW_LEVEL_SIGWX_AREAS = {
    "fbsp": "北海道",
    "fbsn": "東北",
    "fbtk": "東日本",
    "fbos": "西日本",
    "fbkg": "奄美",
    "fbok": "沖縄",
}
LOW_LEVEL_SIGWX_FT = "03"  # 発表初期時刻からの予想時間コード (03/06/09/39)
LOW_LEVEL_SIGWX_FTS = ["03", "06", "09"]  # 地理院色別標高図に重ねて表示するFT一覧


def sigwx_region_dirname(ft):
    """FTごとの下層悪天予想図(地域6分割)保存ディレクトリ名。FT03は後方互換のため無印。"""
    return "low_level_sigwx" if ft == LOW_LEVEL_SIGWX_FT else f"low_level_sigwx_ft{ft}"

# --- 下層悪天予想図(地域版)からの雲頂/雲底OCR自動抽出 ---
# このMacにはHomebrewが無くtesseract本体がpipで入らないため、
# `conda create -n vmc_ocr -c conda-forge tesseract` で別環境に入れたバイナリを直接指す。
# 他の環境に持っていく場合は環境変数 VMC_TESSERACT_CMD で上書きすること。
TESSERACT_CMD = os.environ.get(
    "VMC_TESSERACT_CMD", "/opt/anaconda3/envs/vmc_ocr/bin/tesseract"
)

# 安全弁: OCR統合の信頼性に問題が出た場合はFalseにして純LCL方式に戻す
# 2026-07-17時点: OCR抽出の再現率が低く(東日本全域で7点、最近傍でも99km)METAR検証が
# 機能しないほど疎だったため、当面Falseにして純LCL方式を主力にする
USE_SIGWX_OVERRIDE = False

# 各地域画像(1000x734)内の「詳細(右)パネル」のピクセル範囲と、そこから緯度経度への
# 線形変換係数。各地域とも図の目盛線(2度間隔)のピクセル位置を読み取り、空港位置
# (METAR実況の緯度経度)との整合を確認して校正した(2026-07-17、6地域すべて完了)。
# panel_bboxは全地域共通のテンプレートで(503,25,970,493)と確認済み。
# lon = LON_A * x + LON_B ; lat = LAT_A * y + LAT_B  (x,yは元画像1000x734上のピクセル)
SIGWX_GEOREF = {
    "fbtk": {  # 東日本
        "panel_bbox": (503, 25, 970, 493),
        "lon_a": 0.019754,
        "lon_b": 123.9495,
        "lat_a": -0.015020,
        "lat_b": 39.2133,
    },
    "fbsp": {  # 北海道
        "panel_bbox": (503, 25, 970, 493),
        "lon_a": 0.022599,
        "lon_b": 127.0056,
        "lat_a": -0.015686,
        "lat_b": 46.2405,
    },
    "fbsn": {  # 東北
        "panel_bbox": (503, 25, 970, 493),
        "lon_a": 0.020779,
        "lon_b": 124.5854,
        "lat_a": -0.015094,
        "lat_b": 42.1887,
    },
    "fbos": {  # 西日本
        "panel_bbox": (503, 25, 970, 493),
        "lon_a": 0.018518,
        "lon_b": 118.5745,
        "lat_a": -0.014134,
        "lat_b": 36.6042,
    },
    "fbkg": {  # 奄美
        "panel_bbox": (503, 25, 970, 493),
        "lon_a": 0.017021,
        "lon_b": 116.1192,
        "lat_a": -0.014035,
        "lat_b": 32.1754,
    },
    "fbok": {  # 沖縄
        "panel_bbox": (503, 25, 970, 493),
        "lon_a": 0.014652,
        "lon_b": 115.3700,
        "lat_a": -0.013683,
        "lat_b": 30.4430,
    },
}

# OCR抽出時の許容範囲・信頼度しきい値
# 単独のpsmモードだけでは(特に単桁の雲底値で)取りこぼしが多かったため、
# 複数のpsmモードで抽出してマージする
SIGWX_OCR_UPSCALE = 4
SIGWX_OCR_PSM_MODES = (6, 11, 12)
SIGWX_OCR_MIN_CONF = 30
SIGWX_OCR_VALUE_MIN = 0
SIGWX_OCR_VALUE_MAX = 150  # 百ft単位。150=15,000ft=FL150 (この図の対象上限)
SIGWX_OCR_DEDUP_RADIUS_PX = 12  # 複数psmモード間で同一文字とみなす距離
SIGWX_PAIR_X_TOLERANCE_PX = 15
SIGWX_PAIR_Y_GAP_MIN_PX = 12
SIGWX_PAIR_Y_GAP_MAX_PX = 26
SIGWX_NEAREST_MAX_DIST_KM = 40

# --- METAR実況によるナウキャスト上書き ---
# 直近(hours_ahead=0)のマップ生成時のみ、空港周辺のグリッド点を予報値ではなく
# 実際の観測値(雲底・視程)で上書きする。優先度は METAR > SIGWX > LCL近似。
METAR_URL = "https://aviationweather.gov/api/data/metar"
METAR_STATIONS = [
    "ROAH", "RORS", "RJNK", "RJOA", "RJOK", "RJOM", "RJOO", "RJOT",
    "RJSN", "RJSS", "RJAA", "RJAH", "RJBB", "RJCC", "RJCH", "RJEC",
    "RJFF", "RJFM", "RJFO", "RJFT", "RJKA", "RJTT",
]
METAR_OVERRIDE_RADIUS_KM = 25
METAR_NO_CEILING_BASE_M = 999999.0  # CLR/FEW/SCT等、有意な雲底が無いことが確認できた場合の代用値

# --- 日本の海岸線 (Natural Earth 50m, パブリックドメイン) ---
NE_50M_COUNTRIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_50m_admin_0_countries.geojson"
)
JAPAN_COASTLINE_CACHE = os.path.join(CACHE_DIR, "japan_coastline.geojson")

# --- 都道府県境界 (Natural Earth 10m admin-1, パブリックドメイン) ---
# ライブカメラ(ウェザーニューズ)リンクをどの都道府県に紐づけるか判定するために使う
NE_10M_ADMIN1_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_10m_admin_1_states_provinces.geojson"
)
JAPAN_PREFECTURES_CACHE = os.path.join(CACHE_DIR, "japan_prefectures.geojson")

# --- ウェザーニューズ ライブカメラ (映像そのものは自動取得せず、一覧ページへのリンクのみ生成) ---
WEATHERNEWS_LIVECAM_BASE_URL = "https://weathernews.jp/onebox/livecam/"

# --- GitHub Pagesへの自動デプロイ (小規模共有用。実名メールを出さないためcommit authorは
# GitHubのnoreplyアドレスを使う。個人アカウント名などが出るのは想定内として運用する) ---
GH_PAGES_ENABLED = True
GH_PAGES_DIR = os.path.join(BASE_DIR, "gh_pages_site")
GH_PAGES_REMOTE = "origin"
GH_PAGES_BRANCH = "main"
GH_PAGES_URL = "https://harara0714-dotcom.github.io/vmc-map/"

OUTPUT_RETENTION_DAYS = 7  # これより古いoutput/配下のフォルダは実行時に自動削除

HTTP_TIMEOUT_SEC = 30
USER_AGENT = "vmc-map-generator/0.1 (personal VFR planning tool)"

STATUS_COLORS = {
    "green": "#2e7d32",
    "yellow": "#f9a825",
    "red": "#c62828",
}
