# 個人持股設定（股數）
HOLDINGS = {
    "台泥":           5250,
    "華南金":           40,
    "南茂":           2000,
    "復華台灣科技優息": 15000,
    "第一金":         3000,
    "昆盈":           5000,
    "金寶":           2000,
}


def calc_summary(all_data: dict) -> dict:
    """計算持股市值與今日漲跌"""
    result = {}
    total_value = 0.0
    total_change_value = 0.0

    for name, shares in HOLDINGS.items():
        df = all_data.get(name)
        if df is None or len(df) < 2:
            continue
        price = float(df.iloc[-1]["Close"])
        prev_price = float(df.iloc[-2]["Close"])
        change_pct = (price - prev_price) / prev_price * 100
        value = price * shares
        change_value = (price - prev_price) * shares
        total_value += value
        total_change_value += change_value
        result[name] = {
            "shares": shares,
            "price": price,
            "change_pct": change_pct,
            "value": value,
            "change_value": change_value,
        }

    result["__total__"] = {
        "total_value": total_value,
        "total_change_value": total_change_value,
    }
    return result


def build_portfolio_message(summary: dict) -> str:
    total = summary.pop("__total__", {})
    total_value = total.get("total_value", 0)
    total_change = total.get("total_change_value", 0)
    direction = "▲" if total_change >= 0 else "▼"

    lines = [
        "【我的持股日報】",
        f"總市值：${total_value:,.0f}",
        f"今日損益：{direction}${abs(total_change):,.0f}",
        "─────────────",
    ]
    for name, d in summary.items():
        arrow = "▲" if d["change_pct"] >= 0 else "▼"
        lines.append(
            f"{name}  {d['shares']:,}股"
            f"  ${d['price']:.2f} {arrow}{abs(d['change_pct']):.1f}%"
            f"  (${d['value']:,.0f})"
        )
    return "\n".join(lines)
