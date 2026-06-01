import yfinance as yf
from datetime import date, timedelta

# 個人持股設定（股數 + 成交均價 + 停損停利）
HOLDINGS = {
    "台泥":             {"shares": 5250,  "cost": None,    "stop_loss": None, "take_profit": None},
    "華南金":           {"shares": 40,    "cost": None,    "stop_loss": None, "take_profit": None},
    "南茂":             {"shares": 2000,  "cost": 39.82,   "stop_loss": 35.0, "take_profit": 52.0},
    "復華台灣科技優息":  {"shares": 15000, "cost": 20.12,   "stop_loss": 17.0, "take_profit": 26.0},
    "台積電":           {"shares": 25,    "cost": 1621.8,  "stop_loss": 1400.0, "take_profit": 2200.0},
    "台灣50":           {"shares": 400,   "cost": 70.13,   "stop_loss": 60.0, "take_profit": 95.0},
    "元大高股息":        {"shares": 910,   "cost": 38.66,   "stop_loss": 33.0, "take_profit": 50.0},
    "國泰永續高股息":    {"shares": 1163,  "cost": 22.47,   "stop_loss": 19.0, "take_profit": 30.0},
    "第一金":           {"shares": 3000,  "cost": 26.89,   "stop_loss": 23.0, "take_profit": 34.0},
    "振發":             {"shares": 2000,  "cost": 38.01,   "stop_loss": 32.0, "take_profit": 50.0},
    "昆盈":             {"shares": 5000,  "cost": 57.66,   "stop_loss": 48.0, "take_profit": 75.0},
}


def build_dividend_alert_message(watchlist: dict, days_ahead: int = 7) -> str | None:
    """偵測持股中 N 天內即將除息的標的，回傳提醒訊息"""
    today    = date.today()
    deadline = today + timedelta(days=days_ahead)
    alerts   = []
    for name in HOLDINGS:
        ticker = watchlist.get(name)
        if not ticker:
            continue
        try:
            info       = yf.Ticker(ticker).info
            ex_div_ts  = info.get("exDividendDate")
            if not ex_div_ts:
                continue
            ex_date   = date.fromtimestamp(int(ex_div_ts))
            if today <= ex_date <= deadline:
                div_amt   = info.get("dividendRate") or info.get("lastDividendValue") or 0
                days_left = (ex_date - today).days
                line = f"• {name}｜除息日 {ex_date.strftime('%m/%d')}（{days_left}天後）"
                if div_amt:
                    line += f"｜股利 ${div_amt:.2f}"
                alerts.append(line)
        except Exception:
            continue
    if not alerts:
        return None
    return "📅 【除息提醒】以下持股即將除息，請確認是否繼續持有\n" + "\n".join(alerts)


def calc_summary(all_data: dict, holdings: dict = None) -> dict:
    if holdings is None:
        holdings = HOLDINGS
    result = {}
    total_value = 0.0
    total_cost_value = 0.0
    total_day_change = 0.0

    for name, holding in holdings.items():
        shares = holding["shares"]
        cost   = holding["cost"]
        df = all_data.get(name)
        if df is None or len(df) < 2:
            continue
        price      = float(df.iloc[-1]["Close"])
        prev_price = float(df.iloc[-2]["Close"])
        change_pct = (price - prev_price) / prev_price * 100
        day_change = (price - prev_price) * shares
        value      = price * shares
        total_value     += value
        total_day_change += day_change

        pnl = pnl_pct = None
        if cost is not None:
            pnl     = (price - cost) * shares
            pnl_pct = (price - cost) / cost * 100
            total_cost_value += cost * shares

        stop_loss   = holding.get("stop_loss")
        take_profit = holding.get("take_profit")
        stop_alert  = stop_loss   is not None and price <= stop_loss
        take_alert  = take_profit is not None and price >= take_profit

        result[name] = {
            "shares": shares, "price": price, "cost": cost,
            "change_pct": change_pct, "day_change": day_change,
            "value": value, "pnl": pnl, "pnl_pct": pnl_pct,
            "stop_loss": stop_loss, "take_profit": take_profit,
            "stop_alert": stop_alert, "take_alert": take_alert,
        }

    total_pnl = total_value - total_cost_value if total_cost_value > 0 else None
    result["__total__"] = {
        "total_value": total_value,
        "total_day_change": total_day_change,
        "total_pnl": total_pnl,
    }
    return result


def build_alert_message(summary: dict) -> str | None:
    """停損/停利觸發時回傳獨立緊急訊息，無觸發則回傳 None"""
    stop_lines = []
    take_lines = []
    for name, d in summary.items():
        if name == "__total__":
            continue
        if d.get("stop_alert"):
            pnl_str = f"  損益：▼${abs(d['pnl']):,.0f}（{d['pnl_pct']:.1f}%）" if d.get("pnl") is not None else ""
            stop_lines.append(
                f"• {name}｜現價 ${d['price']:.2f} / 停損 ${d['stop_loss']:.2f}"
                + (f"\n{pnl_str}" if pnl_str else "")
            )
        if d.get("take_alert"):
            pnl_str = f"  損益：▲${abs(d['pnl']):,.0f}（+{d['pnl_pct']:.1f}%）" if d.get("pnl") is not None else ""
            take_lines.append(
                f"• {name}｜現價 ${d['price']:.2f} / 停利 ${d['take_profit']:.2f}"
                + (f"\n{pnl_str}" if pnl_str else "")
            )
    if not stop_lines and not take_lines:
        return None
    parts = []
    if stop_lines:
        parts.append("🔴 【停損警報】請立即評估是否出場\n" + "\n".join(stop_lines))
    if take_lines:
        parts.append("🎯 【停利提醒】建議考慮分批出場\n" + "\n".join(take_lines))
    return "\n\n".join(parts)


def build_portfolio_message(summary: dict) -> str:
    total = summary.pop("__total__", {})
    total_value      = total.get("total_value", 0)
    total_day_change = total.get("total_day_change", 0)
    total_pnl        = total.get("total_pnl")

    day_arrow = "▲" if total_day_change >= 0 else "▼"
    lines = [
        "【我的持股日報】",
        f"總市值：${total_value:,.0f}",
        f"今日損益：{day_arrow}${abs(total_day_change):,.0f}",
    ]
    if total_pnl is not None:
        pnl_arrow = "▲" if total_pnl >= 0 else "▼"
        lines.append(f"未實現損益：{pnl_arrow}${abs(total_pnl):,.0f}")
    lines.append("─────────────")

    for name, d in summary.items():
        weight = f"{d['value'] / total_value * 100:.1f}%" if total_value > 0 else "-"
        arrow = "▲" if d["change_pct"] >= 0 else "▼"
        line  = f"{name} {d['shares']:,}股｜${d['price']:.2f} {arrow}{abs(d['change_pct']):.1f}%｜佔比 {weight}"
        if d["pnl"] is not None:
            pa = "▲" if d["pnl"] >= 0 else "▼"
            line += f"\n  成本${d['cost']:.2f}｜損益{pa}${abs(d['pnl']):,.0f}({pa}{abs(d['pnl_pct']):.1f}%)"
        if d.get("stop_alert"):
            line += f"\n  ⚠️ 已觸及停損價 ${d['stop_loss']:.2f}"
        if d.get("take_alert"):
            line += f"\n  🎯 已達停利價 ${d['take_profit']:.2f}"
        lines.append(line)

    return "\n".join(lines)


def build_rebalance_alert(summary: dict, threshold: float = 0.25) -> str | None:
    """任一持股超過總資產 threshold 比例時推播警報"""
    total = sum(d["value"] for k, d in summary.items() if k != "__total__")
    if total <= 0:
        return None
    alerts = []
    for name, d in summary.items():
        if name == "__total__":
            continue
        weight = d["value"] / total
        if weight >= threshold:
            alerts.append(f"• {name}｜佔比 {weight*100:.1f}%（建議 < {threshold*100:.0f}%）")
    if not alerts:
        return None
    return f"⚖️ 【集中警報】以下持股比重過高，建議評估再平衡\n" + "\n".join(alerts)


def build_correlation_alert(all_data: dict, threshold: float = 0.85) -> str | None:
    """
    計算持股間的價格相關性，相關係數 > threshold 的配對視為高度重複風險
    all_data：fetch_all 的回傳值
    """
    import pandas as pd
    names  = [n for n in HOLDINGS if n in all_data]
    if len(names) < 2:
        return None

    closes = pd.DataFrame({n: all_data[n]["Close"] for n in names}).dropna()
    if len(closes) < 20:
        return None

    corr   = closes.pct_change().dropna().corr()
    alerts = []
    seen   = set()
    for i, a in enumerate(names):
        for b in names[i+1:]:
            pair = tuple(sorted([a, b]))
            if pair in seen:
                continue
            seen.add(pair)
            try:
                val = float(corr.loc[a, b])
            except Exception:
                continue
            if val >= threshold:
                alerts.append(f"• {a} ↔ {b}：相關係數 {val:.2f}（高度重複，等同押同一注）")

    if not alerts:
        return None
    return "🔗 【持股相關性警報】以下配對高度相關，建議檢視是否分散不足\n" + "\n".join(alerts)
