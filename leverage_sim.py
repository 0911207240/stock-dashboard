"""槓桿模擬：借錢（質押借款）買進某一檔 ETF 之後，每月扣掉利息的淨現金流、兩平利率與追繳門檻

配息一律用近 12 個月實際紀錄（沿用 dca_tracker._etf_info）；壓力情境用 etf_facts 的非股利占比折減。
不預測價格，也不構成借貸或買賣建議。利率、成數、維持率與額度請向券商或銀行確認。
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import alloc_simulator as sim
import dca_tracker
from etf_facts import nondiv, nondiv_label

CANDIDATES = ["00919", "00929", "0056", "00878", "0050", "00940", "00900", "00939"]


def _net_series(cur: dict, buy_code: str, loan: float, rate: float, infos: dict, cut: dict, spread: bool):
    """回傳 (借款前月入帳, 借款後月淨現金流, 每月利息)"""
    before = sim._monthly_income(cur, infos, spread, cut)
    after_amt = dict(cur)
    after_amt[buy_code] = after_amt.get(buy_code, 0) + loan
    interest = loan * rate / 12
    after = [x - interest for x in sim._monthly_income(after_amt, infos, spread, cut)]
    return before, after, interest


def render():
    st.subheader("槓桿模擬：借錢買進")
    state = dca_tracker._load()
    holdings = state.get("holdings") or []
    if not any(h["持有股數"] > 0 for h in holdings):
        st.info("請先到「定期定額」子頁填入持股並儲存。")
        return

    st.caption("情境：向券商或銀行做**質押借款**，把借到的錢全部買進下面選的 ETF，利息每月固定支付。"
               "配息用近 12 個月實際紀錄，不預測價格；這不是借貸或買賣建議。")

    infos = {h["代號"]: dca_tracker._etf_info(h["代號"]) for h in holdings}
    cur = {h["代號"]: h["持有股數"] * infos[h["代號"]]["price"] for h in holdings if infos.get(h["代號"])}
    mv0 = sum(cur.values())

    c1, c2, c3 = st.columns(3)
    loan = c1.number_input("借款金額（元）", value=100000, step=10000, min_value=0, key="lev_loan")
    rate_pct = c2.number_input("借款年利率（%）", value=3.0, step=0.1, min_value=0.0, max_value=20.0, key="lev_rate",
                               help="質押利率各家差很多：銀行與部分券商專案約 2.5% 起，券商牌告約 6.5%。請填你實際談到的利率。")
    code = c3.selectbox("買進標的", CANDIDATES, key="lev_code")

    c4, c5, c6 = st.columns(3)
    call_line = c4.number_input("追繳維持率（%）", value=130, step=5, min_value=100, max_value=200, key="lev_call",
                                help="多數來源說 130%，也有說 120%，各家不同。維持率＝擔保品市值÷借款金額。")
    scen = c5.selectbox("配息情境", sim.SCENARIOS, key="lev_scen")
    spread = c6.checkbox("月配標的平均分攤", value=False, key="lev_spread",
                         help="預設不勾選：照近 12 個月實際入帳月份算，才看得出季配標的某幾個月入帳不足以支付固定利息。")
    new_pledged = st.checkbox("新買進的股票也能拿去質押（擔保品含新買部位）", value=False, key="lev_newpledge",
                              help="預設不勾：擔保品只計原有持股，比較保守。實際依借款機構規定。")

    if code not in infos:
        infos[code] = dca_tracker._etf_info(code)
    if infos.get(code) is None:
        st.error(f"查不到 {code} 的報價，無法模擬。")
        return
    if loan <= 0:
        st.info("借款金額為 0，等同現況。請輸入借款金額。")
        return

    cut = sim._cut_for(scen, set(cur) | {code})
    rate = rate_pct / 100
    before, after, interest = _net_series(cur, code, loan, rate, infos, cut, spread)

    # 新增部位在這個情境下的殖利率＝兩平利率
    info = infos[code]
    y_new = sum(a for _, a in info["payouts"]) * (1 - cut.get(code, 0)) / info["price"] * 100
    carry = loan * (y_new - rate_pct) / 100
    neg_months = sum(1 for x in after if x < 0)
    d_cons = 1 - call_line / 100 * loan / mv0
    d_all = 1 - call_line / 100 * loan / (mv0 + loan)
    d_used = d_all if new_pledged else d_cons

    # ── 重點數字 ──
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("月均現金流", f"${sum(after) / 12:,.0f}", f"{(sum(after) - sum(before)) / 12:+,.0f} 相對現況")
    m2.metric("每月固定利息", f"${interest:,.0f}", f"年 ${loan * rate:,.0f}", delta_color="off", delta_arrow="off")
    m3.metric("兩平利率（新部位殖利率）", f"{y_new:.1f}%", f"你的利率 {rate_pct:.1f}%", delta_color="off", delta_arrow="off")
    m4.metric("追繳需跌", "已觸及" if d_used <= 0 else f"{d_used * 100:.0f}%",
              "含新買部位" if new_pledged else "僅原有持股", delta_color="off", delta_arrow="off")

    if y_new <= rate_pct:
        st.error(f"在「{scen}」情境下，新部位殖利率 {y_new:.1f}% 不高於利率 {rate_pct:.1f}%：借得越多，每年淨虧 ${abs(carry):,.0f}。")
    else:
        st.success(f"在「{scen}」情境下，新部位殖利率 {y_new:.1f}% 高於利率 {rate_pct:.1f}%，每年息差約 ${carry:,.0f}。"
                   f"這個差距完全取決於 {code} 的配息能否維持（其近 12 個月配息約 {nondiv_label(code)} 不是股利）。")
    if neg_months:
        st.warning(f"有 {neg_months} 個月的入帳不夠付當月利息（淨現金流為負）。")

    # ── 12 個月現金流 ──
    fig = go.Figure()
    xs = [f"{m}月" for m in range(1, 13)]
    fig.add_trace(go.Bar(name="現況（無借款）", x=xs, y=[round(v) for v in before], marker_color="#8a8f99"))
    fig.add_trace(go.Bar(name=f"借 {loan:,.0f} 買 {code}（扣利息後）", x=xs, y=[round(v) for v in after], marker_color="#1D9E75"))
    fig.update_layout(template="plotly_dark", barmode="group", height=330, bargap=0.25,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                      margin=dict(l=10, r=10, t=30, b=10), yaxis_title="每月淨現金流（元）")
    fig.add_hline(y=0, line_color="#6c7079", line_width=1)
    st.plotly_chart(fig, use_container_width=True)

    # ── 敏感度：借款額 × 利率 ──
    st.markdown("##### 敏感度：借款額 × 利率（月均淨現金流變化／最低月淨現金流）")
    loans = [50000, 100000, 150000, 200000]
    rates = [2.5, 3.0, 4.5, 6.5]
    grid = []
    for L in loans:
        row = {"借款額": f"${L:,.0f}（{L / mv0 * 100:.0f}%）"}
        for r in rates:
            b, a, _ = _net_series(cur, code, L, r / 100, infos, cut, spread)
            row[f"利率 {r}%"] = f"{(sum(a) - sum(b)) / 12:+,.0f}／{min(a):,.0f}"
        grid.append(row)
    st.dataframe(pd.DataFrame(grid), use_container_width=True, hide_index=True)
    st.caption(f"情境：{scen}。格內「月均變化／最低月」，單位元。括號是借款占現有市值的比例。最低月為負＝該月入帳不夠付利息。")

    with st.expander("這個模擬沒有考慮什麼"):
        st.markdown(
            f"- **價格變動**：只用配息算現金流，不模擬股價漲跌。追繳門檻是「需要跌多少」，不是預測。\n"
            f"- **標的的配息來源**：{code} 近 12 個月配息中約 {nondiv_label(code)} 不是股利（多為資本利得），"
            "整個組合與這個標的的重疊度與風險請看「配置模擬」。\n"
            "- **季配與月付利息的錯配**：季配標的入帳集中在特定月份，利息卻每月固定，所以最低月會比月均低很多。\n"
            "- **利率與額度會變**：質押利率多為機動、額度可能被調降；2026 年券商質借額度普遍緊縮，申辦前請向券商或銀行確認。\n"
            "- **融資不同**：融資成數約 6 成、追繳門檻很近（新部位跌約 22% 即達追繳線），不適用這個頁面的算法。\n"
            "- **稅與費用**：未計手續費、證交稅、補充保費與利息的稅務處理。")
