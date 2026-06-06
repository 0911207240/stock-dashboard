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
    """輸入文字 → (名稱, ticker)，找不到回傳 (None, None)"""
    text = text.strip()
    if text in _NAME_TO_TICKER:
        return text, _NAME_TO_TICKER[text]
    code = text.upper().replace(".TW", "").replace(".TWO", "")
    if code in _CODE_TO_NAME:
        name = _CODE_TO_NAME[code]
        return name, _NAME_TO_TICKER[name]
    for name, ticker in WATCHLIST.items():
        if text in name:
            return name, ticker
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
    """多股比較摘要，每檔一行"""
    from datetime import datetime
    date_str = datetime.now().strftime("%m/%d")
    lines = [f"📊 比較查詢（{date_str}）"]
    for name, ticker in pairs:
        lines.append(build_compact_response(name, ticker))
    lines.append("\n輸入單一代號可看完整分析")
    return "\n".join(lines)


HELP_MSG = """📌 歸毛投資助理

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
