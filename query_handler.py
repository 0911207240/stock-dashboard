"""LINE 互動查詢核心邏輯 — 接受股票代號/名稱，回傳完整分析快照"""
import pandas as pd
from data_fetcher import WATCHLIST, fetch, fetch_institutional, fetch_margin_data
from analyzer import add_indicators
from daytrade_scorer import calc_daytrade_score, calc_entry_exit, is_tw_stock
from fundamental_filter import is_fundamentally_weak
from tdcc_holders import get_holder_signal

# 雙向查找表
_NAME_TO_TICKER = {name: ticker for name, ticker in WATCHLIST.items()}
_CODE_TO_NAME   = {
    ticker.replace(".TW", "").replace(".TWO", ""): name
    for name, ticker in WATCHLIST.items()
    if ticker.endswith(".TW") or ticker.endswith(".TWO")
}


def resolve_query(text: str) -> tuple[str | None, str | None]:
    """輸入文字 → (名稱, ticker)。
    WATCHLIST 找不到時，自動嘗試解析為台股(.TW)或美股代號。
    """
    import re
    text = text.strip()

    # ── 優先查 WATCHLIST ──────────────────────────────
    if text in _NAME_TO_TICKER:
        return text, _NAME_TO_TICKER[text]
    code = text.upper().replace(".TW", "").replace(".TWO", "")
    if code in _CODE_TO_NAME:
        name = _CODE_TO_NAME[code]
        return name, _NAME_TO_TICKER[name]
    for name, ticker in WATCHLIST.items():
        if text in name:
            return name, ticker

    # ── 自動解析：不在 WATCHLIST 的代號 ──────────────
    # 台股：4–5 位數字 → 先試主板 .TW（_build_flex 若空再 fallback .TWO）
    if re.match(r'^\d{4,6}$', text):
        return text, f"{text}.TW"

    # 明確帶 .TW / .TWO / .T 後綴
    if re.match(r'^\d{4,6}\.(TW|TWO|T)$', text.upper()):
        upper = text.upper()
        return upper.split(".")[0], upper

    # 美股：1–5 個英文字母（可含 - 如 BRK-B）
    if re.match(r'^[A-Za-z]{1,5}$', text) or re.match(r'^[A-Za-z]+-[A-Za-z]$', text):
        upper = text.upper()
        return upper, upper

    return None, None


def _pct(v: float, decimals: int = 1) -> str:
    return f"{'+'if v >= 0 else ''}{v:.{decimals}f}%"


def _rsi_label(rsi: float) -> str:
    if rsi > 75:
        return f"RSI {rsi:.0f} 超買⚠️"
    if rsi < 30:
        return f"RSI {rsi:.0f} 超賣"
    if 40 <= rsi <= 65:
        return f"RSI {rsi:.0f} 健康"
    return f"RSI {rsi:.0f}"


def _safe(row, key: str, default=0.0) -> float:
    v = row.get(key)
    return float(v) if v is not None and pd.notna(v) else default


def build_query_response(name: str, ticker: str) -> str:
    """完整分析快照，格式化為 LINE 文字訊息"""
    df = fetch(ticker, period="6mo")
    if df is None or df.empty:
        return f"❌ 找不到 {name}（{ticker}）的資料，請確認代號是否正確。"

    df      = add_indicators(df)
    latest  = df.iloc[-1]
    prev    = df.iloc[-2] if len(df) > 1 else latest
    close   = float(latest["Close"])
    chg_pct = (close - float(prev["Close"])) / float(prev["Close"]) * 100
    vol_ratio = _safe(latest, "Vol_ratio", 1.0)
    date_str  = df.index[-1].strftime("%m/%d")
    arrow     = "▲" if chg_pct >= 0 else "▼"

    lines = [f"【{name}  {ticker.replace('.TW','').replace('.TWO','')}】{date_str}"]
    lines.append(f"收盤 ${close:.1f}  {arrow}{abs(chg_pct):.1f}%  量比 {vol_ratio:.1f}x")

    # ── 技術面 ───────────────────────────────────
    rsi      = _safe(latest, "RSI",       50.0)
    rsi6     = _safe(latest, "RSI6",      50.0)
    ma5      = _safe(latest, "MA5",       close)
    ma20     = _safe(latest, "MA20",      close)
    ma60     = _safe(latest, "MA60",      close)
    atr_pct  = _safe(latest, "ATR_pct",  0.0)
    bb_upper = _safe(latest, "BB_upper",  close * 1.04)
    bb_lower = _safe(latest, "BB_lower",  close * 0.96)
    vwap_dev = _safe(latest, "VWAP_MA_dev", 0.0)
    bb_pos   = (close - bb_lower) / (bb_upper - bb_lower) * 100 if bb_upper != bb_lower else 50.0

    if ma5 > ma20 > ma60:
        ma_tag = "多頭排列✅"
    elif ma5 < ma20 < ma60:
        ma_tag = "空頭排列⚠️"
    else:
        ma_tag = "均線糾結"

    lines += [
        "",
        "📈 技術面",
        f"  {_rsi_label(rsi)}（RSI6 {rsi6:.0f}）",
        f"  {ma_tag}（MA5 ${ma5:.1f} / MA20 ${ma20:.1f}）",
        f"  布林位置 {bb_pos:.0f}%  VWAP偏離 {_pct(vwap_dev)}",
        f"  ATR {atr_pct:.1f}%",
    ]

    # ── 籌碼面（台股才有）────────────────────────
    inst_data   = {}
    margin_data = {}
    if is_tw_stock(ticker):
        code        = ticker.replace(".TW", "").replace(".TWO", "")
        inst_data   = fetch_institutional(code)   or {}
        margin_data = fetch_margin_data(code)     or {}

        lines += ["", "💼 籌碼面"]
        if inst_data:
            lines.append(
                f"  外資 {inst_data['foreign_net']:+,}張"
                f"  投信 {inst_data['trust_net']:+,}張"
                f"  自營 {inst_data['dealer_net']:+,}張"
            )
        else:
            lines.append("  法人資料暫無（假日或尚未公布）")

        if margin_data:
            lines.append(
                f"  融資 {margin_data['margin_change']:+,}張"
                f"  融券 {margin_data['short_change']:+,}張"
                f"  券資比 {margin_data['margin_ratio']:.1f}%"
            )
        else:
            lines.append("  融資融券資料暫無")

        holder = get_holder_signal(ticker)
        if holder.get("label"):
            lines.append(f"  {holder['label']}")

    # ── 當沖評分（台股 + 非 ETF）────────────────
    is_etf = ticker.replace(".TW", "").replace(".TWO", "").startswith("00")
    if is_tw_stock(ticker) and not is_etf:
        result = calc_daytrade_score(df, inst_data=inst_data, margin_data=margin_data)
        score  = result["score"]
        lines += ["", f"🎯 當沖評分：{score}分"]
        if score > 0:
            if is_fundamentally_weak(ticker):
                lines[-1] += "（基本面偏弱，謹慎）"
            ee = calc_entry_exit(df, score)
            lines += [
                f"  甜蜜點 ${ee['entry_low']}～${ee['entry_high']}",
                f"  停損 ${ee['stop']}（{_pct(-ee['risk_pct'])}）",
                f"  停利① ${ee['tp1']}（{_pct(ee['upside_pct1'])} RR={ee['rr1']}）",
                f"  停利② ${ee['tp2']}（{_pct(ee['upside_pct2'])} RR={ee['rr2']}）",
            ]
            top_sigs = result["signals"][:2]
            if top_sigs:
                lines.append(f"  → {'／'.join(top_sigs)}")
        else:
            lines.append("  不符合當沖條件（流動性或分數不足）")

    lines += ["", "⚠️ 資料 T+1，僅供參考"]
    return "\n".join(lines)


def build_compact_response(name: str, ticker: str) -> str:
    """單行快速分析，用於多股同時查詢"""
    df = fetch(ticker, period="3mo")
    if df is None or df.empty:
        return f"❌ {name}：資料不足"

    df      = add_indicators(df)
    latest  = df.iloc[-1]
    prev    = df.iloc[-2] if len(df) > 1 else latest
    close   = float(latest["Close"])
    chg_pct = (close - float(prev["Close"])) / float(prev["Close"]) * 100
    rsi     = _safe(latest, "RSI", 50.0)
    vol_r   = _safe(latest, "Vol_ratio", 1.0)
    arrow   = "▲" if chg_pct >= 0 else "▼"

    score_tag = ""
    if is_tw_stock(ticker) and not ticker.replace(".TW", "").replace(".TWO", "").startswith("00"):
        r = calc_daytrade_score(df)
        if r["score"] > 0:
            score_tag = f"  🎯{r['score']}分"

    return (
        f"【{name}】${close:.1f} {arrow}{abs(chg_pct):.1f}%"
        f"  RSI{rsi:.0f}  量{vol_r:.1f}x{score_tag}"
    )


def build_multi_response(pairs: list[tuple[str, str]]) -> str:
    """多股比較摘要，每檔一行（文字 fallback）"""
    from datetime import datetime
    date_str = datetime.now().strftime("%m/%d")
    lines = [f"📊 比較查詢（{date_str}）"]
    for name, ticker in pairs:
        lines.append(build_compact_response(name, ticker))
    lines.append("\n輸入單一代號可看完整分析")
    return "\n".join(lines)


def _compact_bubble(name: str, ticker: str) -> dict | None:
    """回傳單檔比較用的小 Flex bubble，抓不到資料回 None"""
    df = fetch(ticker, period="3mo")
    if df is None or df.empty:
        return None

    df      = add_indicators(df)
    latest  = df.iloc[-1]
    prev    = df.iloc[-2] if len(df) > 1 else latest
    close   = float(latest["Close"])
    chg_pct = (close - float(prev["Close"])) / float(prev["Close"]) * 100
    rsi     = _safe(latest, "RSI",      50.0)
    vol_r   = _safe(latest, "Vol_ratio", 1.0)
    ma5     = _safe(latest, "MA5",  close)
    ma20    = _safe(latest, "MA20", close)
    ma60    = _safe(latest, "MA60", close)
    code    = ticker.replace(".TW","").replace(".TWO","")

    is_up      = chg_pct >= 0
    arrow      = "▲" if is_up else "▼"
    chg_color  = "#EF5350" if is_up else "#26A69A"
    header_bg  = "#C62828" if is_up else "#00695C"

    if ma5 > ma20 > ma60:
        ma_tag, ma_color = "多頭✅", "#EF5350"
    elif ma5 < ma20 < ma60:
        ma_tag, ma_color = "空頭⚠️", "#26A69A"
    else:
        ma_tag, ma_color = "糾結", "#888888"

    rsi_color = "#EF5350" if rsi > 75 else "#26A69A" if rsi < 30 else "#555555"

    score_row = []
    if is_tw_stock(ticker) and not code.startswith("00"):
        try:
            r = calc_daytrade_score(df)
            if r["score"] > 0:
                sc = r["score"]
                sc_color = "#EF5350" if sc >= 60 else "#FF9800" if sc >= 40 else "#888888"
                score_row = [{
                    "type": "box", "layout": "horizontal", "margin": "sm",
                    "contents": [
                        {"type": "text", "text": "🎯 當沖",
                         "size": "xs", "color": "#888888", "flex": 3},
                        {"type": "text", "text": f"{sc}分",
                         "size": "xs", "color": sc_color,
                         "weight": "bold", "align": "end", "flex": 2},
                    ],
                }]
        except Exception:
            pass

    return {
        "type": "bubble",
        "size": "micro",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": header_bg, "paddingAll": "10px",
            "contents": [
                {"type": "text", "text": name[:6],
                 "color": "#FFFFFF", "weight": "bold", "size": "sm"},
                {"type": "text", "text": f"{code}",
                 "color": "#FFFFFF99", "size": "xs"},
            ],
        },
        "body": {
            "type": "box", "layout": "vertical",
            "paddingAll": "10px", "spacing": "xs",
            "contents": [
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"${close:.1f}",
                         "weight": "bold", "size": "md", "flex": 3},
                        {"type": "text", "text": f"{arrow}{abs(chg_pct):.1f}%",
                         "color": chg_color, "weight": "bold",
                         "size": "sm", "align": "end", "flex": 2},
                    ],
                },
                {"type": "separator", "margin": "sm"},
                {
                    "type": "box", "layout": "horizontal", "margin": "xs",
                    "contents": [
                        {"type": "text", "text": "RSI",
                         "size": "xs", "color": "#888888", "flex": 2},
                        {"type": "text", "text": f"{rsi:.0f}",
                         "size": "xs", "color": rsi_color,
                         "weight": "bold", "align": "end", "flex": 2},
                    ],
                },
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "量比",
                         "size": "xs", "color": "#888888", "flex": 2},
                        {"type": "text", "text": f"{vol_r:.1f}x",
                         "size": "xs", "color": "#555555",
                         "align": "end", "flex": 2},
                    ],
                },
                {
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "均線",
                         "size": "xs", "color": "#888888", "flex": 2},
                        {"type": "text", "text": ma_tag,
                         "size": "xs", "color": ma_color,
                         "align": "end", "flex": 3},
                    ],
                },
                *score_row,
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "paddingAll": "6px",
            "contents": [{
                "type": "button",
                "action": {"type": "message", "label": "完整分析",
                           "text": code},
                "style": "secondary", "height": "sm",
            }],
        },
    }


def build_multi_flex(pairs: list[tuple[str, str]]) -> dict:
    """多股比較 Flex Carousel，每檔一張小卡片"""
    from datetime import datetime
    date_str = datetime.now().strftime("%m/%d")

    bubbles = []
    for name, ticker in pairs:
        b = _compact_bubble(name, ticker)
        if b:
            bubbles.append(b)

    if not bubbles:
        return {"type": "text", "text": "❌ 所有股票資料均無法取得"}

    return {
        "type": "flex",
        "altText": f"比較查詢 {date_str}",
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }


HELP_MSG = """📌 AUNO 股票查詢助理

輸入股票代號或名稱即可查詢：
  2330　→ 台積電完整分析
  鴻海　→ 鴻海完整分析
  00878 → ETF 技術分析

回傳內容：
  收盤價 / 漲跌 / 量比
  技術面（RSI / 均線 / 布林 / VWAP）
  籌碼面（法人 / 融資券 / 集保大戶）
  當沖評分＋進出場區間

⚠️ 資料為前日收盤，非盤中即時"""
