"""下層悪天予想図(地域版)の詳細パネルから雲頂/雲底数値をOCRで抽出する。

各セルは「雲頂(上) / 雲底(下)」を百フィート単位の数字で縦に並べて表示している。
セル境界(雲の輪郭)の検出はせず、幾何的に近い上下のトークンをペアリングするだけの
簡易版。ペアが見つからないトークンは採用しない(再現率より精度を優先)。
"""

from PIL import Image
import pytesseract

import config
import sigwx_georef

pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


def _tokens_for_psm(upscaled, scale, x0, y0, psm):
    data = pytesseract.image_to_data(
        upscaled,
        config=f"--psm {psm} -c tessedit_char_whitelist=0123456789",
        output_type=pytesseract.Output.DICT,
    )
    tokens = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text or not text.isdigit():
            continue
        conf = float(data["conf"][i])
        if conf < config.SIGWX_OCR_MIN_CONF:
            continue
        value = int(text)
        if not (config.SIGWX_OCR_VALUE_MIN <= value <= config.SIGWX_OCR_VALUE_MAX):
            continue
        left = data["left"][i] / scale + x0
        top = data["top"][i] / scale + y0
        width = data["width"][i] / scale
        height = data["height"][i] / scale
        tokens.append(
            {
                "value": value,
                "cx": left + width / 2,
                "cy": top + height / 2,
                "conf": conf,
            }
        )
    return tokens


def _dedup(tokens):
    """複数psmモードの結果をマージし、近接する重複検出は信頼度が高い方を残す。"""
    radius = config.SIGWX_OCR_DEDUP_RADIUS_PX
    merged = []
    for tok in sorted(tokens, key=lambda t: -t["conf"]):
        if any(
            abs(m["cx"] - tok["cx"]) < radius and abs(m["cy"] - tok["cy"]) < radius
            for m in merged
        ):
            continue
        merged.append(tok)
    return merged


def _extract_tokens(image_path, region):
    bbox = sigwx_georef.panel_bbox(region)
    if bbox is None:
        return []

    im = Image.open(image_path).convert("L")
    x0, y0, x1, y1 = bbox
    crop = im.crop((x0, y0, x1, y1))
    scale = config.SIGWX_OCR_UPSCALE
    upscaled = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)

    all_tokens = []
    for psm in config.SIGWX_OCR_PSM_MODES:
        all_tokens.extend(_tokens_for_psm(upscaled, scale, x0, y0, psm))
    return _dedup(all_tokens)


def _pair_tokens(tokens):
    """雲頂(上)/雲底(下)のペアを、直下にある近いトークンとの幾何制約だけで見つける。"""
    used = set()
    pairs = []
    for i, top_tok in enumerate(tokens):
        if i in used:
            continue
        best_j, best_dist = None, None
        for j, base_tok in enumerate(tokens):
            if j == i or j in used:
                continue
            dx = abs(base_tok["cx"] - top_tok["cx"])
            dy = base_tok["cy"] - top_tok["cy"]
            if dx > config.SIGWX_PAIR_X_TOLERANCE_PX:
                continue
            if not (config.SIGWX_PAIR_Y_GAP_MIN_PX <= dy <= config.SIGWX_PAIR_Y_GAP_MAX_PX):
                continue
            if top_tok["value"] < base_tok["value"]:
                continue  # 雲頂は雲底以上のはず
            dist = dx + dy
            if best_dist is None or dist < best_dist:
                best_dist, best_j = dist, j
        if best_j is not None:
            pairs.append((top_tok, tokens[best_j]))
            used.add(i)
            used.add(best_j)
    return pairs


def extract_cloud_points(image_path, region):
    """[{lat, lon, base_m, top_m}, ...] を返す。校正データが無い地域は空リスト。"""
    if not sigwx_georef.is_calibrated(region):
        return []

    tokens = _extract_tokens(image_path, region)
    pairs = _pair_tokens(tokens)

    points = []
    for top_tok, base_tok in pairs:
        cx = (top_tok["cx"] + base_tok["cx"]) / 2
        cy = (top_tok["cy"] + base_tok["cy"]) / 2
        latlon = sigwx_georef.pixel_to_latlon(region, cx, cy)
        if latlon is None:
            continue
        lat, lon = latlon
        points.append(
            {
                "lat": lat,
                "lon": lon,
                "base_m": base_tok["value"] * 100 * 0.3048,
                "top_m": top_tok["value"] * 100 * 0.3048,
            }
        )
    return points
