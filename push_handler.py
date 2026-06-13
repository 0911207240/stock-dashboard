"""推播入口 — 早盤委派 scanner.py，盤後 / 週報由本模組處理"""
import sys
from datetime import datetime

from tw_calendar import is_trading_day
from data_fetcher import fetch_all, WATCHLIST, SECTORS
from line_notifier import send, build_weekly_message
from sector_rotation import (
    calc_sector_momentum, build_sector_weekly_report,
    calc_holding_correlation, build_correlation_warning,
)


def run_push(push_type: str = "morning") -> str:
    """執行推播，回傳結果摘要字串"""
    if push_type == "aftermarket":
        return _run_aftermarket_push()
    if push_type == "weekly":
        return _run_weekly_push()
    # morning / all → 委派給 scanner（功能完整版）
    from scanner import run_scan
    found = run_scan()
    return f"早盤掃描完成，{len(found) if found else 0} 檔有訊號"


def _run_weekly_push() -> str:
    """週報：本週漲跌排行 + 強勢 / 弱勢股 + 板塊輪動 + 持倉相關性"""
    from analyzer import add_indicators

    date_str = datetime.now().strftime("%m/%d")

    try:
        all_data = fetch_all(period="1mo")
    except Exception as e:
        return f"週報資料抓取失敗：{e}"

    weekly = []
    for name, df in all_data.items():
        if df is None or df.empty or len(df) < 6:
            continue
        try:
            df = add_indicators(df)
            latest   = df.iloc[-1]
            week_ago = df.iloc[-6]
            close    = float(latest["Close"])
            ref      = float(week_ago["Close"])
            chg_w    = (close - ref) / ref * 100

            ma5  = float(latest.get("MA5",  close) or close)
            ma20 = float(latest.get("MA20", close) or close)
            ma60 = float(latest.get("MA60", close) or close)
            rsi  = float(latest.get("RSI",  50)    or 50)
            macd_v   = float(latest.get("MACD",        0) or 0)
            macd_sig = float(latest.get("MACD_signal", 0) or 0)

            trend     = "多" if ma5 > ma20 > ma60 else ("空" if ma5 < ma20 < ma60 else "中")
            macd_bull = macd_v > macd_sig

            weekly.append({
                "name":      name,
                "ticker":    WATCHLIST.get(name, ""),
                "close":     close,
                "chg_w":     chg_w,
                "trend":     trend,
                "macd_bull": macd_bull,
                "rsi":       rsi,
            })
        except Exception:
            continue

    if not weekly:
        return "週報：無資料"

    sector_report = ""
    try:
        sector_list   = calc_sector_momentum(all_data, SECTORS)
        sector_report = build_sector_weekly_report(sector_list)
    except Exception:
        pass

    corr_warning = ""
    try:
        from portfolio_manager import load_holdings
        holdings      = load_holdings()
        holding_names = [v["name"] for v in holdings.values()]
        alerts        = calc_holding_correlation(all_data, holding_names)
        corr_warning  = build_correlation_warning(alerts)
    except Exception:
        pass

    msg = build_weekly_message(weekly, date_str,
                               sector_report=sector_report,
                               corr_warning=corr_warning)
    send(msg)
    return f"週報推播完成，共 {len(weekly)} 檔"


def _run_aftermarket_push() -> str:
    """盤後推播（13:30）：當日強勢 / 弱勢 / 爆量彙整"""
    if not is_trading_day():
        return "非交易日，跳過"

    date_str = datetime.now().strftime("%m/%d")

    try:
        all_data = fetch_all(period="5d")
    except Exception as e:
        return f"盤後資料抓取失敗：{e}"

    gainers, losers, surge = [], [], []

    for name, df in all_data.items():
        if df is None or df.empty or len(df) < 2:
            continue
        try:
            latest    = df.iloc[-1]
            prev      = df.iloc[-2]
            close     = float(latest["Close"])
            prev_c    = float(prev["Close"])
            chg_pct   = (close - prev_c) / prev_c * 100
            vol_today = float(latest.get("Volume", 0))
            vol_prev  = float(prev.get("Volume", 1))
            vol_ratio = vol_today / vol_prev if vol_prev > 0 else 1.0

            item = {"name": name, "close": close,
                    "chg_pct": chg_pct, "vol_ratio": vol_ratio}

            if chg_pct >= 3.0:
                gainers.append(item)
            elif chg_pct <= -3.0:
                losers.append(item)

            if vol_ratio >= 2.5 and abs(chg_pct) >= 1.5:
                surge.append(item)
        except Exception:
            continue

    gainers.sort(key=lambda x: -x["chg_pct"])
    losers.sort(key=lambda x: x["chg_pct"])
    surge.sort(key=lambda x: -x["vol_ratio"])

    if not gainers and not losers and not surge:
        return "盤後無顯著異動"

    lines = [f"📊 盤後異動彙整（{date_str}）", ""]

    if gainers:
        lines.append("🔴 強勢股（+3%↑）")
        for d in gainers[:5]:
            lines.append(f"  {d['name']} +{d['chg_pct']:.1f}%  ${d['close']:.1f}")
        lines.append("")

    if losers:
        lines.append("🟢 弱勢股（-3%↓）")
        for d in losers[:5]:
            lines.append(f"  {d['name']} {d['chg_pct']:.1f}%  ${d['close']:.1f}")
        lines.append("")

    if surge:
        lines.append("🔥 爆量異動（量比≥2.5x）")
        for d in surge[:5]:
            arrow = "▲" if d["chg_pct"] >= 0 else "▼"
            lines.append(
                f"  {d['name']} {arrow}{abs(d['chg_pct']):.1f}%  量比 {d['vol_ratio']:.1f}x"
            )

    lines.append("\n⚠️ 資料 T+1，僅供參考")
    send("\n".join(lines))
    return f"盤後推播：強勢 {len(gainers)} 檔 / 弱勢 {len(losers)} 檔 / 爆量 {len(surge)} 檔"


if __name__ == "__main__":
    push_type = sys.argv[1] if len(sys.argv) > 1 else "morning"
    print(run_push(push_type))
