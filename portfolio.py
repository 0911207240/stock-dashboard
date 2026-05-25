# 個人持股設定（股數 + 成交均價）
# cost=None 表示尚未輸入成本，只顯示市值不顯示損益
HOLDINGS = {
    "台泥":             {"shares": 5250,  "cost": None},
    "華南金":           {"shares": 40,    "cost": None},
    "南茂":             {"shares": 2000,  "cost": 39.82},
    "復華台灣科技優息":  {"shares": 15000, "cost": 20.12},
    "台積電":           {"shares": 25,    "cost": 1621.8},
    "台灣50":           {"shares": 400,   "cost": 70.13},
    "元大高股息":        {"shares": 910,   "cost": 38.66},
    "金寶":             {"shares": 2000,  "cost": 32.0},
    "國泰永續高股息":    {"shares": 1163,  "cost": 22.47},
    "第一金":           {"shares": 3000,  "cost": 26.89},
    "盛群半導體":        {"shares": 600,   "cost": 61.17},
    "振發":             {"shares": 2000,  "cost": 38.01},
    "昆盈":             {"shares": 5000,  "cost": 57.66},
}


def calc_summary(all_data: dict) -> dict:
    result = {}
    total_value = 0.0
    total_cost_value = 0.0
    total_day_change = 0.0

    for name, holding in HOLDINGS.items():
        shares = holding["shares"]
        cost = holding["cost"]
        df = all_data.get(name)
        if df is None or len(df) < 2:
            continue
        price = float(df.iloc[-1]["Close"])
        prev_price = float(df.iloc[-2]["Close"])
        change_pct = (price - prev_price) / prev_price * 100
        day_change = (price - prev_price) * shares
        value = price * shares
        total_value += value
        total_day_change += day_change

        pnl = pnl_pct = None
        if cost is not None:
            pnl = (price - cost) * shares
            pnl_pct = (price - cost) / cost * 100
            total_cost_value += cost * shares

        result[name] = {
            "shares": shares,
            "price": price,
            "cost": cost,
            "change_pct": change_pct,
            "day_change": day_change,
            "value": value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
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
    total_value = total.get("total_value", 0)
    total_day_change = total.get("total_day_change", 0)
    total_pnl = total.get("total_pnl")

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
        line = f"{name} {d['shares']:,}股｜${d['price']:.2f} {arrow}{abs(d['change_pct']):.1f}%"
        if d["pnl"] is not None:
            pnl_arrow = "▲" if d["pnl"] >= 0 else "▼"
            line += f"\n  成本${d['cost']:.2f}｜損益{pnl_arrow}${abs(d['pnl']):,.0f}({pnl_arrow}{abs(d['pnl_pct']):.1f}%)"
        lines.append(line)

    return "\n".join(lines)
