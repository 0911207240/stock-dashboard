"""財報與法說會日期警示 — 避免在高不確定性時期進行當沖"""
import yfinance as yf
from datetime import date, timedelta


def get_earnings_date(ticker: str) -> date | None:
    """用 yfinance 取得最近一次財報公布日（台股效果有限，美股較準）"""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None or cal.empty:
            return None
        col = cal.columns[0] if hasattr(cal, "columns") else None
        if col is None:
            return None
        val = cal.loc["Earnings Date", col] if "Earnings Date" in cal.index else None
        if val is None:
            return None
        return val.date() if hasattr(val, "date") else None
    except Exception:
        return None


def build_earnings_alert(holdings: dict, watchlist: dict, days_ahead: int = 5) -> str | None:
    """
    掃描持股中 N 天內有財報公布的標的
    回傳推播訊息；無則回傳 None
    """
    today    = date.today()
    deadline = today + timedelta(days=days_ahead)
    alerts   = []

    for name in holdings:
        ticker = watchlist.get(name)
        if not ticker:
            continue
        ed = get_earnings_date(ticker)
        if ed and today <= ed <= deadline:
            days_left = (ed - today).days
            alerts.append(f"• {name}｜財報 {ed.strftime('%m/%d')}（{days_left}天後）⚠️ 建議避免當沖")

    if not alerts:
        return None
    return "📋 【財報警示】以下持股近期公布財報，請降低操作頻率\n" + "\n".join(alerts)


def has_earnings_risk(name: str, ticker: str, days_ahead: int = 3) -> bool:
    """當沖候選是否在財報前 N 天內（是則降低推播優先度）"""
    today = date.today()
    ed    = get_earnings_date(ticker)
    return ed is not None and today <= ed <= today + timedelta(days=days_ahead)
