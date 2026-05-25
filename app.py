import streamlit as st
import pandas as pd
import altair as alt
from data_fetcher import fetch, fetch_all, WATCHLIST, SECTORS
from analyzer import add_indicators, detect_signals, score
from line_notifier import send, build_signal_message
from portfolio import HOLDINGS, calc_summary
import config

st.set_page_config(page_title="股票儀表板", layout="wide", page_icon="📈")

# ── 側邊欄 ──────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")
    period = st.selectbox("資料區間", ["3mo", "6mo", "1y", "2y"], index=2)
    st.markdown("---")
    st.caption("LINE 推播")
    line_token = st.text_input("Channel Access Token", value=config.LINE_CHANNEL_ACCESS_TOKEN, type="password")
    line_uid = st.text_input("User ID", value=config.LINE_USER_ID)
    if st.button("儲存"):
        config.LINE_CHANNEL_ACCESS_TOKEN = line_token
        config.LINE_USER_ID = line_uid
        st.success("已儲存")
    if st.button("測試推播"):
        ok = send("股票儀表板連線測試成功！")
        st.success("推播成功！") if ok else st.error("失敗，請確認 Token")

# ── 快取資料抓取 ──────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_all(period: str, sector: str):
    return fetch_all(period, sector)

@st.cache_data(ttl=1800)
def load_one(ticker: str, period: str):
    return fetch(ticker, period=period)

# ── Tabs ──────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["💼 持股總覽", "🔍 市場掃描", "📊 個股分析"])

# ══════════════════════════════════════════════════
# Tab 1：持股總覽
# ══════════════════════════════════════════════════
with tab1:
    st.header("我的持股")

    with st.spinner("載入持股資料..."):
        all_data = load_all(period, "全部")
        summary = calc_summary(dict(all_data))

    total = summary.pop("__total__", {})
    total_value = total.get("total_value", 0)
    total_day_change = total.get("total_day_change", 0)
    total_pnl = total.get("total_pnl")

    # 總覽指標
    c1, c2, c3 = st.columns(3)
    c1.metric("總市值", f"${total_value:,.0f}")
    c2.metric("今日損益", f"${total_day_change:+,.0f}")
    if total_pnl is not None:
        c3.metric("未實現損益", f"${total_pnl:+,.0f}")

    st.markdown("---")

    # 持股明細表
    rows = []
    for name, d in summary.items():
        row = {
            "名稱": name,
            "股數": d["shares"],
            "現價": round(d["price"], 2),
            "漲跌%": round(d["change_pct"], 2),
            "今日損益": round(d["day_change"], 0),
            "市值": round(d["value"], 0),
        }
        if d["cost"] is not None:
            row["成本"] = d["cost"]
            row["損益%"] = round(d["pnl_pct"], 2)
            row["未實現損益"] = round(d["pnl"], 0)
        else:
            row["成本"] = "-"
            row["損益%"] = "-"
            row["未實現損益"] = "-"
        rows.append(row)

    df_port = pd.DataFrame(rows)

    def color_row(row):
        try:
            v = float(row["漲跌%"])
            if v > 0:
                return ["background-color:#d4edda"] * len(row)
            elif v < 0:
                return ["background-color:#f8d7da"] * len(row)
        except Exception:
            pass
        return [""] * len(row)

    st.dataframe(df_port.style.apply(color_row, axis=1), use_container_width=True, hide_index=True)

    # 市值佔比圖
    st.subheader("市值佔比")
    pie_data = pd.DataFrame([
        {"名稱": name, "市值": d["value"]} for name, d in summary.items()
    ])
    pie_chart = alt.Chart(pie_data).mark_arc(innerRadius=50).encode(
        theta=alt.Theta("市值:Q"),
        color=alt.Color("名稱:N", legend=alt.Legend(orient="right")),
        tooltip=["名稱", "市值"]
    ).properties(height=300)
    st.altair_chart(pie_chart, use_container_width=True)

# ══════════════════════════════════════════════════
# Tab 2：市場掃描
# ══════════════════════════════════════════════════
with tab2:
    st.header("市場掃描")

    col_a, col_b = st.columns([3, 1])
    with col_a:
        sector = st.selectbox("產業篩選", list(SECTORS.keys()))
    with col_b:
        min_sc = st.number_input("最低分數", min_value=1, max_value=5, value=2)

    if st.button("開始掃描", type="primary"):
        with st.spinner("掃描中，請稍候..."):
            scan_data = load_all(period, sector)
            rows = []
            for name, df in scan_data.items():
                df = add_indicators(df)
                sigs = detect_signals(df)
                sc = score(sigs)
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                price = float(latest["Close"])
                prev_price = float(prev["Close"])
                change_pct = (price - prev_price) / prev_price * 100
                rows.append({
                    "名稱": name,
                    "代碼": WATCHLIST[name],
                    "現價": round(price, 2),
                    "漲跌%": round(change_pct, 2),
                    "RSI": round(float(latest["RSI"]), 1) if pd.notna(latest["RSI"]) else "-",
                    "K值": round(float(latest["K"]), 1) if pd.notna(latest["K"]) else "-",
                    "訊號分數": sc,
                    "訊號": " | ".join([s["msg"] for s in sigs]) if sigs else "無",
                })

            result_df = pd.DataFrame(rows).sort_values("訊號分數", ascending=False)
            filtered = result_df[result_df["訊號分數"].abs() >= min_sc]

            st.success(f"掃描完成，{len(filtered)} 檔達標（共 {len(result_df)} 檔）")

            def highlight(row):
                sc_val = row["訊號分數"]
                if sc_val >= 2:
                    return ["background-color:#d4edda"] * len(row)
                elif sc_val <= -2:
                    return ["background-color:#f8d7da"] * len(row)
                return [""] * len(row)

            st.dataframe(
                filtered.style.apply(highlight, axis=1),
                use_container_width=True,
                hide_index=True
            )

            if st.button("推播達標訊號到 LINE"):
                sent = 0
                for _, r in filtered.iterrows():
                    if r["訊號"] != "無":
                        sigs_push = [{"type": "buy" if r["訊號分數"] > 0 else "sell", "msg": m}
                                     for m in r["訊號"].split(" | ")]
                        msg = build_signal_message(r["名稱"], r["代碼"], sigs_push, r["現價"], r["漲跌%"])
                        if send(msg):
                            sent += 1
                st.success(f"已推播 {sent} 則") if sent else st.warning("無訊號或推播失敗")

# ══════════════════════════════════════════════════
# Tab 3：個股分析
# ══════════════════════════════════════════════════
with tab3:
    st.header("個股分析")

    selected_name = st.selectbox("選擇股票", list(WATCHLIST.keys()), key="stock_select")
    ticker = WATCHLIST[selected_name]

    with st.spinner(f"載入 {selected_name}..."):
        df = load_one(ticker, period)

    if df.empty:
        st.error("無法取得資料")
        st.stop()

    df = add_indicators(df)
    signals = detect_signals(df)
    sc = score(signals)
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    price = float(latest["Close"])
    prev_price = float(prev["Close"])
    change_pct = (price - prev_price) / prev_price * 100

    # 指標列
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("收盤價", f"{price:.2f}", f"{change_pct:+.2f}%")
    c2.metric("RSI", f"{float(latest['RSI']):.1f}" if pd.notna(latest["RSI"]) else "-")
    c3.metric("K值", f"{float(latest['K']):.1f}" if pd.notna(latest["K"]) else "-")
    c4.metric("D值", f"{float(latest['D']):.1f}" if pd.notna(latest["D"]) else "-")
    c5.metric("訊號分數", sc, delta="看多" if sc > 0 else ("看空" if sc < 0 else "中性"))

    # 訊號
    if signals:
        st.subheader("訊號")
        for s in signals:
            color = "green" if s["type"] == "buy" else ("red" if s["type"] == "sell" else "orange")
            label = "買進" if s["type"] == "buy" else ("賣出" if s["type"] == "sell" else "觀察")
            st.markdown(f":{color}[**[{label}] {s['indicator']}**] — {s['msg']}")
        if st.button("推播此訊號到 LINE"):
            msg = build_signal_message(selected_name, ticker, signals, price, change_pct)
            ok = send(msg)
            st.success("已推播！") if ok else st.error("推播失敗")
    else:
        st.info("目前無明確訊號")

    # 準備畫圖資料
    df_plot = df.reset_index()
    df_plot = df_plot.rename(columns={df_plot.columns[0]: "Date"})
    df_plot["Date"] = pd.to_datetime(df_plot["Date"])
    for col in ["Close", "MA5", "MA20", "MA60", "RSI", "MACD_diff", "Volume"]:
        if col in df_plot.columns:
            df_plot[col] = pd.to_numeric(df_plot[col], errors="coerce")

    base = alt.Chart(df_plot).encode(x=alt.X("Date:T", title="日期"))

    # 價格 + 均線
    st.subheader("價格走勢")
    price_line = base.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("Close:Q", title="價格"))
    ma5 = base.mark_line(color="orange", strokeDash=[4, 2], strokeWidth=1).encode(y="MA5:Q")
    ma20 = base.mark_line(color="red", strokeDash=[4, 2], strokeWidth=1).encode(y="MA20:Q")
    ma60 = base.mark_line(color="gray", strokeDash=[2, 4], strokeWidth=1).encode(y="MA60:Q")
    st.altair_chart(alt.layer(price_line, ma5, ma20, ma60).properties(height=300), use_container_width=True)

    # 成交量
    st.subheader("成交量")
    vol_chart = base.mark_bar(opacity=0.6).encode(
        y=alt.Y("Volume:Q", title="成交量"),
        color=alt.condition(
            alt.datum.Close >= alt.datum.MA5,
            alt.value("#2ecc71"), alt.value("#e74c3c")
        )
    ).properties(height=120)
    st.altair_chart(vol_chart, use_container_width=True)

    # RSI
    st.subheader("RSI")
    rsi_chart = base.mark_line(color="purple").encode(
        y=alt.Y("RSI:Q", scale=alt.Scale(domain=[0, 100]))
    ).properties(height=150)
    r30 = alt.Chart(pd.DataFrame({"y": [30]})).mark_rule(color="green", strokeDash=[4, 2]).encode(y="y:Q")
    r70 = alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(color="red", strokeDash=[4, 2]).encode(y="y:Q")
    st.altair_chart(alt.layer(rsi_chart, r30, r70), use_container_width=True)

    # MACD
    st.subheader("MACD")
    macd_bar = base.mark_bar().encode(
        y=alt.Y("MACD_diff:Q", title="MACD Histogram"),
        color=alt.condition(alt.datum.MACD_diff > 0, alt.value("#2ecc71"), alt.value("#e74c3c"))
    ).properties(height=150)
    st.altair_chart(macd_bar, use_container_width=True)
