"""板塊輪動偵測 — 計算各產業族群的1日/5日動能 + 法人資金流向，找出主流板塊"""
import pandas as pd

_SKIP_SECTORS = {"全部", "低價波段($50以下)", "槓桿ETF", "我的持股"}


def calc_sector_momentum(all_data: dict, sectors: dict) -> list[dict]:
    """
    計算各板塊的平均漲跌與動能分數
    momentum = avg_1d × 0.4 + avg_5d × 0.6
    回傳：按 momentum 排序的清單
    """
    result = []
    for sector_name, stocks in sectors.items():
        if sector_name in _SKIP_SECTORS:
            continue
        r1d, r5d = [], []
        for name in stocks:
            df = all_data.get(name)
            if df is None or len(df) < 6:
                continue
            close = df["Close"].squeeze()
            try:
                chg_1d = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
                chg_5d = (float(close.iloc[-1]) - float(close.iloc[-6])) / float(close.iloc[-6]) * 100
                r1d.append(chg_1d)
                r5d.append(chg_5d)
            except Exception:
                continue

        if len(r1d) < 2:
            continue

        avg_1d   = sum(r1d) / len(r1d)
        avg_5d   = sum(r5d) / len(r5d)
        breadth  = sum(1 for r in r1d if r > 0) / len(r1d) * 100
        momentum = avg_1d * 0.4 + avg_5d * 0.6

        result.append({
            "sector":   sector_name,
            "avg_1d":   round(avg_1d,   2),
            "avg_5d":   round(avg_5d,   2),
            "breadth":  round(breadth,  0),
            "count":    len(r1d),
            "momentum": round(momentum, 2),
        })

    result.sort(key=lambda x: x["momentum"], reverse=True)
    return result


def calc_sector_institutional_flow(
    inst_by_code: dict,
    watchlist: dict,
    sectors: dict,
) -> list[dict]:
    """
    依產業族群彙整法人買賣超（外資 + 投信 + 自營商合計）
    inst_by_code: {股票代號: {foreign_net, trust_net, dealer_net, total_net}}
    回傳：按法人合計淨買超排序的族群清單
    """
    result = []
    for sector_name, stocks in sectors.items():
        if sector_name in _SKIP_SECTORS:
            continue
        foreign_total = trust_total = dealer_total = total = count = 0
        for name in stocks:
            ticker = watchlist.get(name, "")
            code   = ticker.replace(".TW", "").replace(".TWO", "")
            data   = inst_by_code.get(code)
            if not data:
                continue
            foreign_total += data.get("foreign_net", 0)
            trust_total   += data.get("trust_net",   0)
            dealer_total  += data.get("dealer_net",  0)
            total         += data.get("total_net",   0)
            count         += 1

        if count == 0:
            continue

        result.append({
            "sector":        sector_name,
            "foreign_net":   foreign_total,
            "trust_net":     trust_total,
            "dealer_net":    dealer_total,
            "total_net":     total,
            "stock_count":   count,
        })

    result.sort(key=lambda x: x["total_net"], reverse=True)
    return result


def build_sector_flow_note(flow_list: list[dict], top_n: int = 3) -> str:
    """早盤推播用：產業法人資金流向摘要"""
    if not flow_list:
        return ""
    top    = [s for s in flow_list[:top_n] if s["total_net"] > 0]
    bottom = [s for s in flow_list[-top_n:] if s["total_net"] < 0]
    lines  = ["", "💼 法人資金板塊"]
    if top:
        lines.append("  流入：" + "  ".join(
            f"{s['sector']} +{s['total_net']:,}張" for s in top
        ))
    if bottom:
        lines.append("  流出：" + "  ".join(
            f"{s['sector']} {s['total_net']:,}張" for s in reversed(bottom)
        ))
    return "\n".join(lines)


def build_sector_morning_note(sector_list: list[dict], top_n: int = 3) -> str:
    """早盤推播用：一行板塊輪動摘要"""
    if not sector_list:
        return ""
    top    = sector_list[:top_n]
    bottom = sector_list[-1]
    parts  = [f"{s['sector']} {s['avg_1d']:+.1f}%（5日{s['avg_5d']:+.1f}%）" for s in top]
    lines  = ["", "📊 板塊動能 Top3"]
    lines += [f"  🔥 {p}" for p in parts]
    lines.append(f"  ❄️ 最弱：{bottom['sector']} {bottom['avg_1d']:+.1f}%")
    return "\n".join(lines)


def build_sector_weekly_report(sector_list: list[dict]) -> str:
    """週報用：完整板塊輪動分析（Top5 / Bottom3）"""
    if not sector_list:
        return ""
    lines = ["", "🔄 【板塊輪動】"]
    lines.append("強勢板塊（5日動能）")
    for i, s in enumerate(sector_list[:5], 1):
        breadth_bar = "▇" * int(s["breadth"] / 20)
        lines.append(
            f"  {i}. {s['sector']:10s}  5日{s['avg_5d']:+.1f}%  今{s['avg_1d']:+.1f}%  {breadth_bar}"
        )
    lines.append("弱勢板塊")
    for s in sector_list[-3:]:
        lines.append(f"  ⚠️ {s['sector']}  5日{s['avg_5d']:+.1f}%  今{s['avg_1d']:+.1f}%")
    return "\n".join(lines)


def calc_holding_correlation(all_data: dict, holdings: list[str], window: int = 20) -> list[dict]:
    """
    計算持股之間 window 日報酬相關性
    回傳：相關係數 > 0.75 的股票對（過度集中警示）
    """
    returns = {}
    for name in holdings:
        df = all_data.get(name)
        if df is None or len(df) < window + 1:
            continue
        close = df["Close"].squeeze()
        returns[name] = close.pct_change().dropna().tail(window)

    if len(returns) < 2:
        return []

    df_ret = pd.DataFrame(returns).dropna()
    if df_ret.empty or df_ret.shape[1] < 2:
        return []

    corr   = df_ret.corr()
    names  = list(returns.keys())
    alerts = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            try:
                c = float(corr.loc[names[i], names[j]])
                if abs(c) > 0.75:
                    alerts.append({
                        "a":    names[i],
                        "b":    names[j],
                        "corr": round(c, 2),
                    })
            except Exception:
                continue

    alerts.sort(key=lambda x: abs(x["corr"]), reverse=True)
    return alerts


def build_correlation_warning(alerts: list[dict]) -> str:
    """將相關性警示轉為推播文字"""
    if not alerts:
        return ""
    lines = ["", "⚠️ 【持倉集中度警示】以下持股高度相關，風險未有效分散："]
    for a in alerts[:5]:
        label = "正相關" if a["corr"] > 0 else "負相關"
        lines.append(f"  {a['a']} & {a['b']}  r={a['corr']:.2f}（{label}）")
    lines.append("  建議：減少其中一檔，或分散至低相關板塊")
    return "\n".join(lines)
