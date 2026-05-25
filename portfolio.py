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
        arrow = "▲" if d["change_pct"] >= 0 else "▼"
        line  = f"{name} {d['shares']:,}股｜${d['price']:.2f} {arrow}{abs(d['change_pct']):.1f}%"
        if d["pnl"] is not None:
            pa = "▲" if d["pnl"] >= 0 else "▼"
            line += f"\n  成本${d['cost']:.2f}｜損益{pa}${abs(d['pnl']):,.0f}({pa}{abs(d['pnl_pct']):.1f}%)"
        if d.get("stop_alert"):
            line += f"\n  ⚠️ 已觸及停損價 ${d['stop_loss']:.2f}"
        if d.get("take_alert"):
            line += f"\n  🎯 已達停利價 ${d['take_profit']:.2f}"
        lines.append(line)

    return "\n".join(lines)
