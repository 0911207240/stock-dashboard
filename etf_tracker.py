import streamlit as st
import plotly.graph_objects as go
import json
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), "etf_state.json")

DEFAULT_ETFS = [
    {"id": "00929", "label": "00929", "freq": 1,    "freq_label": "月配", "default_div": 0.10, "step": 0.01},
    {"id": "00878", "label": "00878", "freq": 1,    "freq_label": "月配", "default_div": 0.08, "step": 0.01},
    {"id": "00919", "label": "00919", "freq": 1,    "freq_label": "月配", "default_div": 0.09, "step": 0.01},
    {"id": "0056",  "label": "0056",  "freq": 1/3,  "freq_label": "季配", "default_div": 1.0,  "step": 0.1},
]

COLORS = ["#1D9E75", "#378ADD", "#BA7517", "#D85A30", "#534AB7"]


def _load_history():
    if "etf_history" not in st.session_state:
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st.session_state.etf_history = json.load(f).get("history", [])
        except Exception:
            st.session_state.etf_history = []
    return st.session_state.etf_history


def _save_history(data):
    st.session_state.etf_history = data
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"history": data}, f, ensure_ascii=False)
    except Exception:
        pass


def render_dividend_calculator():
    st.subheader("配息試算")

    goal = st.number_input("月領目標（元）", value=10000, step=500, min_value=0, key="etf_goal")

    st.markdown("##### ETF 配息設定")
    cols = st.columns(2)
    sources = []
    for i, etf in enumerate(DEFAULT_ETFS):
        with cols[i % 2]:
            st.markdown(f"**{etf['label']}** `{etf['freq_label']}`")
            div_val = st.number_input(
                f"每股配息（元）", value=etf["default_div"], step=etf["step"],
                min_value=0.0, key=f"etf_div_{etf['id']}", format="%.2f"
            )
            shares = st.number_input(
                f"持有股數", value=0, step=1, min_value=0, key=f"etf_shares_{etf['id']}"
            )
            monthly = div_val * shares * etf["freq"]
            if shares > 0 and div_val > 0:
                sources.append({"label": etf["label"], "monthly": monthly})

    total = sum(s["monthly"] for s in sources)
    annual = total * 12
    gap = goal - total
    pct = min(100.0, (total / goal * 100) if goal > 0 else 0)

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("預估月配息", f"${total:,.0f}", f"達成 {pct:.1f}%")
    c2.metric("距離目標", "已達成!" if gap <= 0 else f"${gap:,.0f}", f"目標 ${goal:,.0f}")
    c3.metric("預估年配息", f"${annual:,.0f}")

    st.progress(min(pct / 100, 1.0))

    if sources:
        fig = go.Figure(go.Bar(
            x=[s["label"] for s in sources],
            y=[round(s["monthly"]) for s in sources],
            marker_color=COLORS[:len(sources)],
            text=[f"${s['monthly']:,.0f}" for s in sources],
            textposition="auto",
        ))
        fig.update_layout(
            template="plotly_dark", height=300,
            xaxis_title="ETF", yaxis_title="月配息（元）",
            margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)


def render_compound_calculator():
    st.subheader("複利成長試算")

    c1, c2 = st.columns(2)
    init_capital = c1.number_input("初始本金（元）", value=100000, step=10000, min_value=0, key="comp_init")
    monthly_invest = c2.number_input("每月定投（元）", value=5000, step=1000, min_value=0, key="comp_monthly")

    annual_rate = st.slider("年化報酬率（%）", min_value=1.0, max_value=20.0, value=8.0, step=0.5, key="comp_rate")
    years = st.slider("投資年數", min_value=1, max_value=40, value=10, step=1, key="comp_years")
    reinvest = st.selectbox("配息再投入", ["是（複利最大化）", "否（配息提取）"], key="comp_reinvest") == "是（複利最大化）"

    monthly_rate = (1 + annual_rate / 100) ** (1 / 12) - 1
    labels, totals, principals = ["現在"], [init_capital], [init_capital]
    asset, principal = float(init_capital), float(init_capital)

    for y in range(1, years + 1):
        for _ in range(12):
            asset = asset * (1 + monthly_rate) + monthly_invest
            principal += monthly_invest
        labels.append(f"{y}年")
        totals.append(round(asset))
        principals.append(round(principal))

    profit = asset - principal
    roi = (profit / principal * 100) if principal > 0 else 0

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("最終資產", f"${asset:,.0f}", f"{years} 年後")
    c2.metric("總投入本金", f"${principal:,.0f}")
    c3.metric("複利獲利", f"${profit:,.0f}", f"報酬率 {roi:.1f}%")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=totals, name="總資產", fill="tozeroy",
        line=dict(color="#1D9E75", width=2),
        fillcolor="rgba(29,158,117,0.08)",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=principals, name="投入本金", fill="tozeroy",
        line=dict(color="#85B7EB", width=1.5, dash="dash"),
        fillcolor="rgba(133,183,235,0.06)",
    ))
    fig.update_layout(
        template="plotly_dark", height=320,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis=dict(title="金額（元）"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("* 試算採年化複利，實際報酬因市場波動而異，僅供參考")


def render_pledge_calculator():
    st.subheader("質押槓桿試算")

    c1, c2 = st.columns(2)
    stock_value = c1.number_input("股票市值（元）", value=500000, step=10000, min_value=0, key="pledge_value")
    pledge_ratio = c2.number_input("質押成數（%）", value=60, step=5, min_value=10, max_value=90, key="pledge_ratio")

    c3, c4 = st.columns(2)
    borrow = c3.number_input("實際借款（元）", value=200000, step=10000, min_value=0, key="pledge_borrow")
    loan_rate = c4.number_input("借款年利率（%）", value=3.5, step=0.1, min_value=1.0, max_value=20.0, key="pledge_rate")

    expected_return = st.number_input("預期年報酬（%）", value=8.0, step=0.5, min_value=0.0, key="pledge_return")

    max_loan = stock_value * pledge_ratio / 100
    interest = borrow * loan_rate / 100
    leverage = (stock_value + borrow) / stock_value if stock_value > 0 else 1
    pct = min(100.0, (borrow / max_loan * 100) if max_loan > 0 else 0)

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("可借款上限", f"${max_loan:,.0f}")
    c2.metric("年利息成本", f"${interest:,.0f}", f"月付 ${interest/12:,.0f}")

    if pct >= 75:
        level = "⚠️ 高度危險"
    elif pct >= 50:
        level = "⚠️ 警戒中"
    else:
        level = "✅ 安全區"
    c3.metric("槓桿倍率", f"{leverage:.2f}x", level)

    if pct < 50:
        bar_color = "#1D9E75"
    elif pct < 75:
        bar_color = "#BA7517"
    else:
        bar_color = "#D85A30"

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pct,
        number={"suffix": "%", "font": {"size": 28}},
        title={"text": "借款佔質押上限"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": bar_color},
            "bgcolor": "#1a1a2e",
            "steps": [
                {"range": [0, 50], "color": "#1a3a2a"},
                {"range": [50, 75], "color": "#3a3a1a"},
                {"range": [75, 100], "color": "#3a1a1a"},
            ],
        },
    ))
    fig.update_layout(template="plotly_dark", height=250, margin=dict(l=20, r=20, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)

    net = borrow * expected_return / 100 - interest
    if net >= 0:
        st.success(f"✅ 正套利 +${net:,.0f}/年｜借款 ${borrow:,.0f} × 預期報酬 {expected_return}% − 利息 {loan_rate}%")
    else:
        st.error(f"⚠️ 負套利 −${abs(net):,.0f}/年（虧損）｜借款 ${borrow:,.0f} × 預期報酬 {expected_return}% − 利息 {loan_rate}%")

    if pct >= 75:
        st.error("⚠️ 借款超過質押上限 75%，隨時可能被追繳或強制平倉！")
    elif pct >= 50:
        st.warning("⚠️ 進入警戒區，建議降低借款或增加股票市值做緩衝。")
    else:
        st.success("✅ 目前在安全區，保持借款不超過市值 40% 可有效降低風險。")

    with st.expander("槓桿原則提醒"):
        st.markdown("""
- **安全做法：** 借款不超過股票市值 30-40%，即便股價下跌 30% 也有足夠緩衝
- **警戒區（50-75%）：** 股價下跌 15-25% 可能面臨追繳保證金（Margin Call），建議預留現金 10%
- **危險區（>75%）：** 股價小幅波動即可能遭強制平倉，造成永久性虧損，強烈不建議
- 借款利率需低於投資報酬率才有正套利空間，建議槓桿倍數不超過 1.5x
""")


def render_monthly_records():
    st.subheader("月記錄")

    history = _load_history()

    with st.expander("➕ 新增月記錄", expanded=not bool(history)):
        c1, c2 = st.columns(2)
        month = c1.text_input("年月", placeholder="2025-04", key="hist_month")
        income = c2.number_input("股息收入（元）", value=0, step=100, min_value=0, key="hist_income")
        c3, c4 = st.columns(2)
        invest = c3.number_input("定投金額（元）", value=0, step=1000, min_value=0, key="hist_invest")
        target = c4.text_input("主要標的", placeholder="00929", key="hist_target")
        note = st.text_input("備註", placeholder="選填備註", key="hist_note")

        if st.button("新增這筆", type="primary", key="hist_add"):
            if not month or (income == 0 and invest == 0):
                st.error("請填寫年月及至少一項數值")
            else:
                history.append({
                    "month": month, "income": income, "invest": invest,
                    "target": target, "note": note,
                })
                history.sort(key=lambda x: x["month"])
                _save_history(history)
                st.rerun()

    if not history:
        st.info("尚無記錄，新增第一筆吧！")
        return

    total_income = sum(h["income"] for h in history)
    total_invest = sum(h["invest"] for h in history)
    avg = total_income / len(history) if history else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("累積股息", f"${total_income:,.0f}")
    c2.metric("累積定投", f"${total_invest:,.0f}")
    c3.metric("平均月股息", f"${avg:,.0f}")

    if len(history) >= 2:
        fig = go.Figure(go.Scatter(
            x=[h["month"] for h in history],
            y=[h["income"] for h in history],
            mode="lines+markers", name="月股息",
            line=dict(color="#1D9E75", width=2),
            fill="tozeroy", fillcolor="rgba(29,158,117,0.1)",
            marker=dict(size=6),
        ))
        fig.update_layout(
            template="plotly_dark", height=220,
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis=dict(title="股息（元）"),
        )
        st.plotly_chart(fig, use_container_width=True)

    import pandas as pd
    df = pd.DataFrame(history)
    df.columns = ["年月", "股息", "定投", "標的", "備註"]
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    if st.button("🗑️ 清除最後一筆", key="hist_delete_last"):
        if history:
            history.pop()
            _save_history(history)
            st.rerun()


def render():
    st.header("💰 ETF 追蹤")
    sub1, sub2, sub3, sub4 = st.tabs(["配息試算", "複利成長", "質押槓桿", "月記錄"])
    with sub1:
        render_dividend_calculator()
    with sub2:
        render_compound_calculator()
    with sub3:
        render_pledge_calculator()
    with sub4:
        render_monthly_records()
