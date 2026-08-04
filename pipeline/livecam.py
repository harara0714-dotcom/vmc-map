"""グリッド点の緯度経度から、ウェザーニューズのライブカメラ一覧ページへのリンクを作る。

映像・画像そのものは自動取得しない(公開APIが無く、利用規約上のリスクもあるため)。
都道府県境界(Natural Earth)で点がどの都道府県に属するかを判定し、該当都道府県の
一覧ページURLを返すだけの薄いモジュール。
"""

import json
import os

import requests

import config

# 都道府県名(Natural Earthのname_ja) -> (地方スラッグ, 都道府県スラッグ)
# 北海道・沖縄はURL構造が特殊なので別扱い(Noneはスラッグ無し=地方ページそのもの)
PREFECTURE_LIVECAM_MAP = {
    "青森県": ("tohoku", "aomori"),
    "岩手県": ("tohoku", "iwate"),
    "宮城県": ("tohoku", "miyagi"),
    "秋田県": ("tohoku", "akita"),
    "山形県": ("tohoku", "yamagata"),
    "福島県": ("tohoku", "fukushima"),
    "茨城県": ("kanto", "ibaraki"),
    "栃木県": ("kanto", "tochigi"),
    "群馬県": ("kanto", "gunma"),
    "埼玉県": ("kanto", "saitama"),
    "千葉県": ("kanto", "chiba"),
    "東京都": ("kanto", "tokyo"),
    "神奈川県": ("kanto", "kanagawa"),
    "新潟県": ("chubu", "niigata"),
    "富山県": ("chubu", "toyama"),
    "石川県": ("chubu", "ishikawa"),
    "福井県": ("chubu", "fukui"),
    "山梨県": ("chubu", "yamanashi"),
    "長野県": ("chubu", "nagano"),
    "岐阜県": ("chubu", "gifu"),
    "静岡県": ("chubu", "shizuoka"),
    "愛知県": ("chubu", "aichi"),
    "三重県": ("kinki", "mie"),
    "滋賀県": ("kinki", "shiga"),
    "京都府": ("kinki", "kyoto"),
    "大阪府": ("kinki", "osaka"),
    "兵庫県": ("kinki", "hyogo"),
    "奈良県": ("kinki", "nara"),
    "和歌山県": ("kinki", "wakayama"),
    "鳥取県": ("chugoku", "tottori"),
    "島根県": ("chugoku", "shimane"),
    "岡山県": ("chugoku", "okayama"),
    "広島県": ("chugoku", "hiroshima"),
    "山口県": ("chugoku", "yamaguchi"),
    "徳島県": ("shikoku", "tokushima"),
    "香川県": ("shikoku", "kagawa"),
    "愛媛県": ("shikoku", "ehime"),
    "高知県": ("shikoku", "kouchi"),
    "福岡県": ("kyushu", "fukuoka"),
    "佐賀県": ("kyushu", "saga"),
    "長崎県": ("kyushu", "nagasaki"),
    "熊本県": ("kyushu", "kumamoto"),
    "大分県": ("kyushu", "oita"),
    "宮崎県": ("kyushu", "miyazaki"),
    "鹿児島県": ("kyushu", "kagoshima"),
    "沖縄県": ("okinawa", None),
    "北海道": ("hokkaido", None),  # 道北/道南/道央/道東は緯度経度から別途判定
}


def _hokkaido_subregion(lat, lon):
    """北海道内のおおよその位置から地方区分サブページのスラッグを推定する(簡易)。"""
    if lat >= 43.5:
        return "douhoku"  # 道北
    if lon >= 143.0:
        return "doutou"  # 道東
    if lat <= 42.5 and lon <= 142.0:
        return "dounan"  # 道南
    return "douou"  # 道央


def _download_prefectures():
    resp = requests.get(
        config.NE_10M_ADMIN1_URL, headers={"User-Agent": config.USER_AGENT}, timeout=120
    )
    resp.raise_for_status()
    world = resp.json()
    japan_features = [f for f in world["features"] if f["properties"].get("iso_a2") == "JP"]
    if not japan_features:
        raise RuntimeError("Natural Earthデータセット内に日本の都道府県が見つかりません")

    os.makedirs(config.CACHE_DIR, exist_ok=True)
    collection = {"type": "FeatureCollection", "features": japan_features}
    with open(config.JAPAN_PREFECTURES_CACHE, "w", encoding="utf-8") as f:
        json.dump(collection, f, ensure_ascii=False)
    return japan_features


def load_prefectures():
    """[{name_ja, rings: [[(lon,lat), ...], ...]}, ...] を返す(初回のみダウンロード)。"""
    if os.path.exists(config.JAPAN_PREFECTURES_CACHE):
        with open(config.JAPAN_PREFECTURES_CACHE, "r", encoding="utf-8") as f:
            features = json.load(f)["features"]
    else:
        features = _download_prefectures()

    prefectures = []
    for feature in features:
        name_ja = feature["properties"].get("name_ja") or feature["properties"].get("name")
        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            polygons = [geometry["coordinates"]]
        elif geometry["type"] == "MultiPolygon":
            polygons = geometry["coordinates"]
        else:
            continue
        rings = [ring for polygon in polygons for ring in polygon]
        prefectures.append({"name_ja": name_ja, "rings": rings})
    return prefectures


def _point_in_ring(lat, lon, ring):
    """レイキャスト法による点内判定。ringは[(lon,lat), ...]。"""
    inside = False
    n = len(ring)
    x, y = lon, lat
    x1, y1 = ring[0]
    for i in range(1, n + 1):
        x2, y2 = ring[i % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
            inside = not inside
        x1, y1 = x2, y2
    return inside


def find_prefecture(lat, lon, prefectures):
    for pref in prefectures:
        if any(_point_in_ring(lat, lon, ring) for ring in pref["rings"]):
            return pref["name_ja"]
    return None


def livecam_url(lat, lon, prefectures):
    """該当地点のウェザーニューズ・ライブカメラ一覧ページURL(無ければNone)。"""
    name_ja = find_prefecture(lat, lon, prefectures)
    if name_ja is None or name_ja not in PREFECTURE_LIVECAM_MAP:
        return None

    region, pref_slug = PREFECTURE_LIVECAM_MAP[name_ja]
    if name_ja == "北海道":
        pref_slug = _hokkaido_subregion(lat, lon)

    if pref_slug is None:
        return f"{config.WEATHERNEWS_LIVECAM_BASE_URL}{region}/"
    return f"{config.WEATHERNEWS_LIVECAM_BASE_URL}{region}/{pref_slug}/"
