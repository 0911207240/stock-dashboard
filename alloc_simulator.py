"""配置模擬：總資金不變（無新資金）的前提下，比較不同配置的月現金流穩定度

資料全部來自 yfinance 近 12 個月實際配息（沿用 dca_tracker._etf_info），不預測未來配息。
示範配置只是比較用的樣板，不是建議；可在下方自訂權重。
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dca_tracker

COLORS = ["#8a8f99", "#378ADD", "#1D9E75", "#BA7517", "#D85A30"]
SELL_TAX = 0.001      # ETF 證交稅 0.1%
FEE = 0.1425 / 100 * 0.28  # 手續費 2.8 折（單邊，未計最低 $1）

# 官方資料顯示配息大致隨淨值縮放、且資本利得占淨值近半的標的（2026/10/16 查證，見頁面說明）
CAPGAIN_ETFS = ("00929", "00919")
STRESS = {
    "基準": 0.0,
    "資本利得型 -25%": 0.25,
    "資本利得型 -50%": 0.50,
}

PRESETS = {
    "B 降低集中": {"00929": 35, "0056": 20, "00878": 20, "00919": 15, "0050": 10},
    "C 季配錯開": {"00929": 25, "0056": 25, "00878": 25, "00919": 25},
    "D 月配為主": {"00929": 40, "00940": 20, "00900": 20, "00939": 20},
}


def _cut_for(scen: str, codes: set) -> dict:
    """把選單的情境轉成 {代號: 折減比例}"""
    if scen.startswith("資本利得型標的配息 -25"):
        return {c: 0.25 for c in CAPGAIN_ETFS}
    if scen.startswith("資本利得型標的配息 -50"):
        return {c: 0.50 for c in CAPGAIN_ETFS}
    if scen.startswith("全部"):
        return {c: 0.25 for c in codes}
    return {}


def _monthly_income(amounts: dict, infos: dict, spread: bool, cut: dict | None = None) -> list[float]:
    """回傳 1~12 月的預估入帳；spread=True 時，月配標的（近 12 月 ≥10 筆）以年配息平均分攤"""
    m = [0.0] * 12
    for code, amt in amounts.items():
        info = infos.get(code)
        if not info or amt <= 0:
            continue
        shares = amt / info["price"] * (1 - (cut or {}).get(code, 0))
        pays = info["payouts"]
        if spread and len(pays) >= 10:
            for i in range(12):
                m[i] += shares * sum(a for _, a in pays) / 12
        else:
            for mo, a in pays:
                m[mo - 1] += shares * a
    return m


def _summary(name: str, amounts: dict, infos: dict, spread: bool, current: dict, total: float,
             cut: dict | None = None) -> dict:
    inc = _monthly_income(amounts, infos, spread, cut)
    annual = sum(inc)
    avg = annual / 12
    biggest_src = 0.0
    for code, amt in amounts.items():
        info = infos.get(code)
        if info and amt > 0:
            biggest_src = max(biggest_src, amt / info["price"] * (1 - (cut or {}).get(code, 0))
                              * sum(a for _, a in info["payouts"]))
    sells = sum(max(current.get(c, 0) - amounts.get(c, 0), 0) for c in set(current) | set(amounts))
    buys = sum(max(amounts.get(c, 0) - current.get(c, 0), 0) for c in set(current) | set(amounts))
    return {
        "name": name, "monthly": inc, "annual": annual, "avg": avg,
        "yield": annual / total * 100 if total else 0,
        "min": min(inc), "max": max(inc),
        "paying_months": sum(1 for x in inc if x > 0),
        "stable": min(inc) / avg * 100 if avg else 0,
        "top_weight": max(amounts.values()) / total * 100 if total else 0,
        "top_income_share": biggest_src / annual * 100 if annual else 0,
        "turnover": sells, "cost": sells * (SELL_TAX + FEE) + buys * FEE,
    }


def render():
    st.subheader("配置模擬")
    state = dca_tracker._load()
    holdings = state.get("holdings") or []
    if not any(h["持有股數"] > 0 for h in holdings):
        st.info("請先到「定期定額」子頁填入持股並儲存。")
        return

    st.caption("前提：總資金固定為你目前的持股市值，不加新資金；賣出再買入只是換標的。"
               "配息一律用近 12 個月實際紀錄，不預測未來。示範配置只是比較的樣板，不是買賣建議。")

    codes = {h["代號"] for h in holdings} | {c for p in PRESETS.values() for c in p}
    infos = {c: dca_tracker._etf_info(c) for c in sorted(codes)}
    missing = [c for c, v in infos.items() if v is None]
    if missing:
        st.warning(f"查不到報價：{', '.join(missing)}，含這些標的的配置不計入。")

    current = {h["代號"]: h["持有股數"] * infos[h["代號"]]["price"] for h in holdings if infos.get(h["代號"])}
    total = sum(current.values())
    st.metric("可配置總資金（目前市值）", f"${total:,.0f}")

    spread = st.checkbox(
        "月配標的以年配息平均分攤到 12 個月", value=True, key="alloc_spread",
        help="月配 ETF 近 12 個月的金額常因配息調升而前低後高，直接用會誤判成不穩定。"
             "勾選＝假設每月領一樣多；取消＝照近 12 個月實際月份與金額。季配標的一律照實際月份。")

    scen = st.selectbox(
        "配息情境", ["基準（近 12 個月實際）", "資本利得型標的配息 -25%", "資本利得型標的配息 -50%", "全部標的配息 -25%"],
        key="alloc_scen",
        help="資本利得型＝00929、00919：官方資料顯示它們的配息大致隨淨值縮放，且淨值近半是資本利得。"
             "市場回落時配息會跟著縮水，所以用折減來模擬。圖表與比較表都會套用這個情境。")
    cut = _cut_for(scen, set(infos) | set(codes))

    st.markdown("##### 自訂配置（權重合計不必剛好 100，會自動換算）")
    base = pd.DataFrame([{"代號": c, "配置%": w} for c, w in PRESETS["B 降低集中"].items()])
    custom = st.data_editor(base, num_rows="dynamic", hide_index=True, use_container_width=True, key="alloc_custom",
                            column_config={"配置%": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0)})

    scenarios = {"A 現況": current}
    for name, w in PRESETS.items():
        s = sum(w.values())
        scenarios[name] = {c: total * v / s for c, v in w.items() if infos.get(c)}
    cw = {str(r["代號"]).strip().upper(): float(r["配置%"] or 0) for r in custom.to_dict("records") if str(r.get("代號") or "").strip()}
    cw = {c: v for c, v in cw.items() if v > 0}
    for c in cw:
        if c not in infos:
            infos[c] = dca_tracker._etf_info(c)
    cs = sum(cw.values())
    if cs > 0:
        scenarios["E 自訂"] = {c: total * v / cs for c, v in cw.items() if infos.get(c)}

    rows = [_summary(n, a, infos, spread, current, total, cut) for n, a in scenarios.items() if a]
    if cut:
        st.info(f"目前顯示的是壓力情境：{scen}。切回「基準」可看近 12 個月實際結果。")

    # ── 月現金流圖 ──
    fig = go.Figure()
    for i, r in enumerate(rows):
        fig.add_trace(go.Bar(name=r["name"], x=[f"{m}月" for m in range(1, 13)], y=[round(v) for v in r["monthly"]],
                             marker_color=COLORS[i % len(COLORS)]))
    fig.update_layout(template="plotly_dark", barmode="group", height=360, bargap=0.25,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                      margin=dict(l=10, r=10, t=30, b=10), yaxis_title="預估月入帳（元）")
    st.plotly_chart(fig, use_container_width=True)

    # ── 比較表 ──
    table = pd.DataFrame([{
        "配置": r["name"],
        "年配息": f"${r['annual']:,.0f}",
        "月均": f"${r['avg']:,.0f}",
        "殖利率": f"{r['yield']:.2f}%",
        "有入帳月份": f"{r['paying_months']}／12",
        "最低月": f"${r['min']:,.0f}",
        "最高月": f"${r['max']:,.0f}",
        "最低月÷月均": f"{r['stable']:.0f}%",
        "最大單一標的": f"{r['top_weight']:.0f}%",
        "最大配息來源占比": f"{r['top_income_share']:.0f}%",
        "換手金額": f"${r['turnover']:,.0f}",
        "估算交易成本": f"${r['cost']:,.0f}",
    } for r in rows])
    st.dataframe(table, use_container_width=True, hide_index=True)

    with st.expander("指標怎麼看"):
        st.markdown(
            "- **最低月÷月均**：越接近 100%，每個月領得越平均；0% 代表至少有一個月完全沒有入帳。\n"
            "- **最大配息來源占比**：單一標的貢獻的配息比例。它若減配，整體現金流受影響的幅度大約是「占比 × 減配幅度」。\n"
            "- **估算交易成本**：賣出證交稅 0.1% ＋ 手續費 2.8 折（單邊約 0.04%），未計最低手續費、價差與滑價，實際以券商為準。\n"
            "- 殖利率與配息都是**過去 12 個月**的結果；配息會隨市況與基金操作變動，不保證延續。"
        )

    # ── 壓力情境對照：各配置在不同配息折減下的月均與最低月 ──
    st.markdown("##### 壓力情境對照")
    levels = [("基準", None), ("資本利得型 -25%", 0.25), ("資本利得型 -50%", 0.50), ("全部 -25%", "all")]
    recs = []
    for n, a in scenarios.items():
        if not a:
            continue
        rec = {"配置": n}
        for label, lv in levels:
            c = {} if lv is None else {k: 0.25 for k in a} if lv == "all" else {k: lv for k in CAPGAIN_ETFS}
            r = _summary(n, a, infos, spread, current, total, c)
            rec[label] = f"月均 ${r['avg']:,.0f}｜最低月 ${r['min']:,.0f}"
        recs.append(rec)
    st.dataframe(pd.DataFrame(recs), use_container_width=True, hide_index=True)
    st.caption("資本利得型＝00929、00919。折減是對該標的所有配息等比例打折，不是預測，只是看現金流對配息縮水的敏感度。"
               "沒有持有這兩檔的配置，在「資本利得型」兩欄不會變動。")

    with st.expander("00919／00929 配息來源：官方資料查證（截至 2026/10/16）"):
        st.markdown(
            "**每單位淨值組成**（官網每日淨值表）\n\n"
            "| | 淨值 | 面額 | 可分配收益 | 資本利得／平準金 | 資本利得占淨值 |\n|---|---|---|---|---|---|\n"
            "| 00919 | 32.92 | 15.00 | 1.70 | 16.22 | 49% |\n"
            "| 00929 | 29.75 | 15.00 | 1.16 | 13.59 | 46% |\n\n"
            "- **00919 一年前**淨值 21.42、資本利得 5.47（26%）；一年內淨值上漲約 54%，上漲幾乎全是資本利得。\n"
            "- **配息隨淨值縮放**：00919 每季配息從 0.54（2025）增加到 1.10（2026），當期配息率落在 2.4%～3.4%；"
            "00929 每月配息由約 0.10 增加到 0.38。\n"
            "- **可分配收益只夠發約 1.5 個季度（00919）／3 個月（00929）**，其餘要靠實現資本利得，因此行情轉弱時配息容易下修。\n"
            "- 「資本利得」含未實現部分，未實現利得不能發配息；已實現與未實現的比例，公開頁面查不到。\n"
            "- 這些是**淨值結構與配息規模的事實**，不代表動用本金；各期配息的官方拆分要看投信的收益分配公告。\n\n"
            "資料來源：群益投信官網（NAV 組成、配息查詢）、復華投信官網（00929 淨值組成）。數字會過期，請以官網最新為準。")
