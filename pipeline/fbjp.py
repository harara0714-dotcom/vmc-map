"""気象庁の悪天予想図を参考画像としてダウンロードするだけの薄いモジュール。

記号・数値が描かれた画像であり自動解析はしない。目視での突き合わせ用。
- FBJP: 全国, SFC-FL250, 前線・CB・乱気流など特筆事象のみを描く粗い図
- 下層悪天予想図(地域6分割): SFC-FL150, 雲域・雲底/雲頂高度・降水域などVFRの
  高度帯に対応した詳細な図。VMCマップとの目視比較にはこちらの方が有用
"""

import os
import re

import pytesseract
import requests
from PIL import Image

import config

pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

# 凡例欄の"VALID TIME : hhmm UTC dd Mon yyyy"が書かれている位置(全地域共通のテンプレート)
_VALID_TIME_CROP_BOX = (0, 524, 345, 546)
_VALID_TIME_RE = re.compile(r"(\d{3,4})\s*UTC\s*(\d{1,2})\s*([A-Za-z]{3})[a-z]*\s*(\d{4})")


def _download(url, dest_path):
    resp = requests.get(
        url, headers={"User-Agent": config.USER_AGENT}, timeout=config.HTTP_TIMEOUT_SEC
    )
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    return dest_path


def download_fbjp(dest_path):
    return _download(config.FBJP_URL, dest_path)


def extract_valid_time(image_path):
    """下層悪天予想図の凡例欄から"VALID TIME"をOCRで読み取る。読めなければNone。"""
    crop = Image.open(image_path).convert("L").crop(_VALID_TIME_CROP_BOX)
    crop = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
    text = pytesseract.image_to_string(crop, config="--psm 7")
    m = _VALID_TIME_RE.search(text)
    if not m:
        return None
    hhmm, day, mon, year = m.groups()
    return f"{hhmm} UTC {day} {mon} {year}"


def download_low_level_sigwx(dest_dir, ft=None):
    """地域別下層悪天予想図(6枚)をdest_dir配下に保存し、{area: 保存先パス}を返す。

    ft(予想時間コード、例:"03"/"06"/"09")を省略するとconfig.LOW_LEVEL_SIGWX_FTを使う。
    """
    if ft is None:
        ft = config.LOW_LEVEL_SIGWX_FT
    os.makedirs(dest_dir, exist_ok=True)
    paths = {}
    for area in config.LOW_LEVEL_SIGWX_AREAS:
        url = config.LOW_LEVEL_SIGWX_URL_TEMPLATE.format(area=area, ft=ft)
        dest_path = os.path.join(dest_dir, f"{area}.png")
        paths[area] = _download(url, dest_path)
    return paths
