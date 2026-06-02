"""
image_notifier.py
將當沖候選資料渲染成 PNG 卡片，上傳 imgbb 後推 LINE 圖片訊息
"""
from __future__ import annotations
import io
import base64
import json
import urllib.request
import urllib.error
import urllib.parse

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID, IMGBB_API_KEY

# ── 色盤 ─────────────────────────────────────────────────────────────
BG         = (13,  17,  23)
CARD_DARK  = (18,  22,  30)
CARD_LIGHT = (22,  27,  36)
DIVIDER    = (45,  52,  60)
TEXT_W     = (228, 235, 242)
TEXT_DIM   = (130, 140, 152)
GREEN      = ( 35, 197,  94)
RED        = (240,  75,  68)
YELLOW     = (210, 155,  35)
BLUE       = ( 90, 168, 255)
HEADER_BG  = ( 18,  38,  62)

# ── 版型常數 ─────────────────────────────────────────────────────────
W           = 760
PAD         = 24
LINE_H      = 28
CARD_PAD_V  = 16
HEADER_H    = 90
FOOTER_H    = 50

_FONTS: dict = {}


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    key = (size, bold)
    if key not in _FONTS:
        candidates = (
            ["C:/Windows/Fonts/msjhbd.ttc", "C:/Windows/Fonts/msyhbd.ttc",
             "C:/Windows/Fonts/msjh.ttc",   "C:/Windows/Fonts/msyh.ttc"]
            if bold else
            ["C:/Windows/Fonts/msjh.ttc",   "C:/Windows/Fonts/msyh.ttc",
             "C:/Windows/Fonts/msjhbd.ttc",  "C:/Windows/Fonts/msyhbd.ttc"]
        )
        loaded = None
        for path in candidates:
            try:
                loaded = ImageFont.truetype(path, size)
                break
            except OSError:
                pass
        _FONTS[key] = loaded or ImageFont.load_default()
    return _FONTS[key]


def _card_h(c: dict) -> int:
    extra = (1 if c.get("suggested_lots") else 0) + (1 if c.get("signals") else 0)
    return CARD_PAD_V * 2 + (5 + extra) * LINE_H


def _fmt(val, fmt: str = ".1f", fallback: str = "-") -> str:
    try:
        return format(float(val), fmt) if val not in (None, "-", "") else fallback
    except (TypeError, ValueError):
        return fallback


def build_daytrade_image(
    candidates: list[dict],
    date_str: str,
    regime: dict | None = None,
    concentration_warning: str = "",
) -> bytes:
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow 未安裝，請執行: pip install Pillow")

    extra_h = LINE_H if concentration_warning else 0
    total_h = HEADER_H + sum(_card_h(c) for c in candidates) + extra_h + FOOTER_H

    img  = Image.new("RGB", (W, total_h), BG)
    draw = ImageDraw.Draw(img)

    # ── header ───────────────────────────────────────────────────────
    draw.rectangle([0, 0, W, HEADER_H], fill=HEADER_BG)
    title = f"{date_str}  明日當沖候選 Top{len(candidates)}"
    draw.text((PAD, 12), title, font=_font(26, bold=True), fill=TEXT_W)

    if regime:
        min_score = 40 + regime.get("min_score_adj", 0)
        sub = f"{regime['state']}  |  門檻 {min_score} 分  |  量能+籌碼+技術+波動度"
        dot_col = GREEN if "多" in regime.get("state", "") else (YELLOW if "震" in regime.get("state", "") else RED)
        draw.ellipse([PAD, 57, PAD + 14, 71], fill=dot_col)
        draw.text((PAD + 20, 53), sub, font=_font(19), fill=TEXT_DIM)
    else:
        draw.text((PAD, 53), "量能+籌碼+技術+波動度評分", font=_font(19), fill=TEXT_DIM)

    # ── stock cards ──────────────────────────────────────────────────
    y = HEADER_H
    for idx, c in enumerate(candidates, 1):
        ch = _card_h(c)
        bg = CARD_DARK if idx % 2 == 1 else CARD_LIGHT
        draw.rectangle([0, y, W, y + ch], fill=bg)
        draw.line([PAD, y, W - PAD, y], fill=DIVIDER)

        cy = y + CARD_PAD_V

        # row 1: index · name · 昨收價 · 分數badge
        arrow = "▲" if c["change_pct"] >= 0 else "▼"
        a_col = GREEN if c["change_pct"] >= 0 else RED

        draw.text((PAD,      cy), f"{idx}.", font=_font(21, bold=True), fill=TEXT_DIM)
        draw.text((PAD + 42, cy), c["name"], font=_font(22, bold=True), fill=TEXT_W)
        draw.text((PAD + 195, cy), f"昨收 ${c['price']:.1f}", font=_font(20), fill=TEXT_DIM)

        sc = c["score"]
        sc_col = GREEN if sc >= 50 else (YELLOW if sc >= 35 else RED)
        # 分數 badge
        badge = f"{sc} 分"
        draw.rectangle([W - PAD - 82, cy - 2, W - PAD, cy + 24], fill=sc_col)
        draw.text((W - PAD - 74, cy + 1), badge, font=_font(19, bold=True), fill=BG)
        # 分數長條（badge 下方，滿分100 → 最長 120px）
        bar_max = 120
        bar_w   = max(4, int(bar_max * min(sc, 100) / 100))
        bar_x   = W - PAD - bar_max
        bar_y   = cy + 28
        draw.rectangle([bar_x, bar_y, W - PAD, bar_y + 5], fill=DIVIDER)
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 5], fill=sc_col)

        cy += LINE_H

        # row 2: change% · vol_ratio · ATR
        draw.text((PAD + 42, cy), f"{arrow}{abs(c['change_pct']):.1f}%", font=_font(20), fill=a_col)
        draw.text((PAD + 145, cy), f"量比 {c.get('vol_ratio', 1):.1f}x", font=_font(20), fill=TEXT_DIM)
        draw.text((PAD + 280, cy), f"ATR {_fmt(c.get('atr_pct'), '.1f')}%", font=_font(20), fill=TEXT_DIM)
        cy += LINE_H

        # row 3: entry range
        draw.rectangle([PAD + 38, cy + 5, PAD + 42, cy + 21], fill=BLUE)
        entry = (f"甜蜜點  ${_fmt(c.get('entry_low'), '.2f')} ～ ${_fmt(c.get('entry_high'), '.2f')}"
                 f"  (參考 ${_fmt(c.get('entry_mid'), '.2f')})")
        draw.text((PAD + 50, cy), entry, font=_font(20), fill=BLUE)
        cy += LINE_H

        # row 4: stop · tp1
        stop_txt = f"停損 ${_fmt(c.get('stop'), '.2f')}  (-{_fmt(c.get('risk_pct'), '.1f')}%)"
        draw.text((PAD + 50, cy), stop_txt, font=_font(20), fill=RED)
        tp1_txt = (f"停利①  ${_fmt(c.get('tp1'), '.2f')}"
                   f"  (+{_fmt(c.get('upside_pct1'), '.1f')}%  RR={_fmt(c.get('rr1'), '.1f')})  出半倉")
        draw.text((PAD + 295, cy), tp1_txt, font=_font(20), fill=GREEN)
        cy += LINE_H

        # row 5: tp2
        tp2_txt = (f"停利②  ${_fmt(c.get('tp2'), '.2f')}"
                   f"  (+{_fmt(c.get('upside_pct2'), '.1f')}%  RR={_fmt(c.get('rr2'), '.1f')})  全出")
        draw.text((PAD + 50, cy), tp2_txt, font=_font(20), fill=GREEN)
        cy += LINE_H

        # row 6 (optional): suggested lots
        if c.get("suggested_lots"):
            risk_amt = round((c["entry_mid"] - c["stop"]) * c["suggested_lots"] * 1000)
            lots_txt = f"建議 {c['suggested_lots']} 張  |  風控 ${risk_amt:,}  約總資產 1%"
            draw.text((PAD + 50, cy), lots_txt, font=_font(20), fill=YELLOW)
            cy += LINE_H

        # row 7 (optional): signals
        if c.get("signals"):
            sigs = c["signals"][:2]
            sig_txt = "→ " + "  /  ".join(str(s) for s in sigs)
            draw.text((PAD + 50, cy), sig_txt, font=_font(18), fill=TEXT_DIM)

        y += ch

    draw.line([PAD, y, W - PAD, y], fill=DIVIDER)

    # ── concentration warning ────────────────────────────────────────
    if concentration_warning:
        draw.text((PAD, y + 10), concentration_warning, font=_font(19), fill=YELLOW)
        y += LINE_H

    # ── footer ───────────────────────────────────────────────────────
    draw.text((PAD, y + 14), "⚠  僅供參考，操作自負風險", font=_font(20), fill=TEXT_DIM)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _save_local(image_bytes: bytes, date_str: str) -> None:
    """存一份 PNG 到 action_logs/images/ 當歷史備份"""
    import os
    folder = os.path.join(os.path.dirname(__file__), "action_logs", "images")
    os.makedirs(folder, exist_ok=True)
    fname = os.path.join(folder, f"daytrade_{date_str.replace('/', '')}.png")
    with open(fname, "wb") as f:
        f.write(image_bytes)
    print(f"[IMAGE] 本地備份：{fname}")


def upload_to_imgbb(image_bytes: bytes, api_key: str) -> str:
    """上傳 PNG 到 imgbb，回傳公開 URL"""
    b64  = base64.b64encode(image_bytes).decode()
    data = urllib.parse.urlencode({"image": b64}).encode()
    req  = urllib.request.Request(
        f"https://api.imgbb.com/1/upload?key={api_key}",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("success"):
        raise RuntimeError(f"imgbb 上傳失敗：{result}")
    return result["data"]["url"]


def _build_price_summary(candidates: list[dict]) -> str:
    """產生可複製價位的精簡文字，隨圖片一併推送"""
    lines = ["📋 快速價位參考"]
    for c in candidates:
        entry = f"{_fmt(c.get('entry_low'), '.2f')}-{_fmt(c.get('entry_high'), '.2f')}"
        stop  = _fmt(c.get('stop'), '.2f')
        tp1   = _fmt(c.get('tp1'), '.2f')
        tp2   = _fmt(c.get('tp2'), '.2f')
        lines.append(f"{c['name']}  入 {entry}  停 {stop}  利 {tp1}/{tp2}")
    return "\n".join(lines)


def _send_line_messages(messages: list[dict]) -> bool:
    """透過 LINE Messaging API 一次推送多則訊息（最多5則）"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("[LINE] 未設定 Token 或 User ID")
        return False

    payload = json.dumps({
        "to": LINE_USER_ID,
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status == 200
    except urllib.error.HTTPError as e:
        print(f"[LINE] 推播失敗：{e.code} {e.read().decode()}")
        return False


def send_daytrade_image(
    candidates: list[dict],
    date_str: str,
    regime: dict | None = None,
    concentration_warning: str = "",
) -> bool:
    """完整流程：生成圖 → 上傳 imgbb → 推 LINE 圖片訊息

    若未設定 IMGBB_API_KEY，圖片存至本地後回傳 False（呼叫方可 fallback 至文字）
    """
    try:
        img_bytes = build_daytrade_image(candidates, date_str, regime, concentration_warning)
    except Exception as e:
        print(f"[IMAGE] 圖片生成失敗：{e}")
        return False

    # 無論是否上傳，都存一份本地備份
    _save_local(img_bytes, date_str)

    api_key = IMGBB_API_KEY
    if not api_key:
        print("[IMAGE] IMGBB_API_KEY 未設定，僅存本地")
        return False

    try:
        img_url = upload_to_imgbb(img_bytes, api_key)
        print(f"[IMAGE] 圖片已上傳：{img_url}")
    except Exception as e:
        print(f"[IMAGE] imgbb 上傳失敗：{e}")
        return False

    messages = [
        {"type": "image", "originalContentUrl": img_url, "previewImageUrl": img_url},
        {"type": "text",  "text": _build_price_summary(candidates)},
    ]
    return _send_line_messages(messages)
