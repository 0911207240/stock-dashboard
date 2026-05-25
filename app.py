import streamlit as st
import pandas as pd
import altair as alt
from data_fetcher import fetch, fetch_all, WATCHLIST, SECTORS
from analyzer import add_indicators, detect_signals, score
from line_notifier import send, build_signal_message
import config

st.set_page_config(page_title="股票儀表板", layout="wide")
st.title("股票投資儀表板")

# ── 側邊欄設定 ──────────────────────────────────────────
with st.sidebar:
    st.header("設定")
    period = st.selectbox("資料區間", ["3mo", "6mo", "1y", "2y"], index=1)
    st.markdown("---")
    st.header("LINE 通知設定")
    line_token = st.text_input("Channel Access Token", value=config.LINE_CHANNEL_ACCESS_TOKEN, type="password")
    line_uid = st.text_input("User ID", value=config.LINE_USER_ID)
    if st.button("儲存 LINE 設定"):
        config.LINE_CHANNEL_ACCESS_TOKEN = line_token
        config.LINE_USER_ID = line_uid
        st.success("已儲存！")
    if st.button("測試推播"):
        ok = send("股票儀表板連線測試成功！")
        st.success("推播成功！") if ok else st.error("推播失敗，請確認 Token 和 User ID")
    st.markdown("---")
    st.header("自選股")
    custom_name = st.text_input("名稱", placeholder="e.g. 聯電")
    custom_ticker = st.text_input("代碼", placeholder="e.g. 2303.TW")
    if st.button("加入自選") and custom_ticker:
        WATCHLIST[custom_name or custom_ticker] = custom_ticker
        st.success(f"已加入：{custom_ticker}")

# ── 總覽掃描 ──────────────────────────────────────────
st.header("市場掃描總覽")

sector = st.selectbox("產業篩選", list(SECTORS.keys()), index=0)

if st.button("開始掃描", type="primary"):
    with st.spinner("掃描中..."):
        all_data = fetch_all(period, sector)
        rows = []
        for name, df in all_data.items():
            df = add_indicators(df)
            sigs = detect_signals(df)
            sc = score(sigs)
            latest = df.iloc[-1]
            rows.append({
                "名稱": name,
                "代碼": WATCHLIST[name],
                "收盤價": round(float(latest["Close"]), 2),
                "RSI": round(float(latest["RSI"]), 1) if pd.notna(latest["RSI"]) else "-",
                "MACD差": round(float(latest["MACD_diff"]), 3) if pd.notna(latest["MACD_diff"]) else "-",
                "K值": round(float(latest["K"]), 1) if pd.notna(latest["K"]) else "-",
                "訊號分數": sc,
                "訊號": " | ".join([s["msg"] for s in sigs]) if sigs else "無",
            })

        result_df = pd.DataFrame(rows).sort_values("訊號分數", ascending=False)

        def highlight(row):
            if row["訊號分數"] >= 2:
                return ["background-color: #d4edda"] * len(row)
            elif row["訊號分數"] <= -2:
                return ["background-color: #f8d7da"] * len(row)
            return [""] * len(row)

        st.dataframe(result_df.style.apply(highlight, axis=1), use_container_width=True)

        if st.button("推播所有訊號到 LINE"):
            sent = 0
            for item in rows:
                if item["訊號分數"] != 0 and item["訊號"] != "無":
                    sigs = [{"type": "buy" if item["訊號分數"] > 0 else "sell", "msg": m}
                            for m in item["訊號"].split(" | ")]
                    msg = build_signal_message(item["名稱"], item["代碼"], sigs, item["收盤價"])
                    if send(msg):
                        sent += 1
            st.success(f"已推播 {sent} 則訊號") if sent else st.warning("無訊號可推播或推播失敗")

st.markdown("---")

# ── 個股詳細分析 ──────────────────────────────────────────
st.header("個股詳細分析")

selected_name = st.selectbox("選擇股票", list(WATCHLIST.keys()))
ticker = WATCHLIST[selected_name]

with st.spinner(f"載入 {selected_name} 資料..."):
    df = fetch(ticker, period=period)

if df.empty:
    st.error("無法取得資料，請確認代碼是否正確")
    st.stop()

df = add_indicators(df)
signals = detect_signals(df)
sc = score(signals)

# 指標摘要
latest = df.iloc[-1]
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("收盤價", f"{float(latest['Close']):.2f}")
col2.metric("RSI", f"{float(latest['RSI']):.1f}" if pd.notna(latest["RSI"]) else "-")
col3.metric("K值", f"{float(latest['K']):.1f}" if pd.notna(latest["K"]) else "-")
col4.metric("D值", f"{float(latest['D']):.1f}" if pd.notna(latest["D"]) else "-")
col5.metric("訊號分數", sc, delta="看多" if sc > 0 else ("看空" if sc < 0 else "中性"))

# 訊號清單
if signals:
    st.subheader("目前訊號")
    for s in signals:
        color = "green" if s["type"] == "buy" else ("red" if s["type"] == "sell" else "orange")
        label = "買進" if s["type"] == "buy" else ("賣出" if s["type"] == "sell" else "觀察")
        st.markdown(f":{color}[**[{label}] {s['indicator']}**] {s['msg']}")
    if st.button("推播此股訊號到 LINE"):
        msg = build_signal_message(selected_name, ticker, signals, float(latest["Close"]))
        ok = send(msg)
        st.success("已推播！") if ok else st.error("推播失敗，請先設定 LINE Token")
else:
    st.info("目前無明確訊號")

# K線 + 均線圖
st.subheader("價格走勢")
df_plot = df.reset_index()
df_plot["Date"] = pd.to_datetime(df_plot["Date"])
df_plot["Close"] = df_plot["Close"].astype(float)
df_plot["MA5"] = df_plot["MA5"].astype(float)
df_plot["MA20"] = df_plot["MA20"].astype(float)

base = alt.Chart(df_plot).encode(x=alt.X("Date:T", title="日期"))
price_line = base.mark_line(color="#1f77b4").encode(y=alt.Y("Close:Q", title="價格"))
ma5_line = base.mark_line(color="orange", strokeDash=[4, 2]).encode(y="MA5:Q")
ma20_line = base.mark_line(color="red", strokeDash=[4, 2]).encode(y="MA20:Q")
chart = alt.layer(price_line, ma5_line, ma20_line).properties(height=300)
st.altair_chart(chart, use_container_width=True)

# RSI 圖
st.subheader("RSI")
df_plot["RSI"] = df_plot["RSI"].astype(float)
rsi_chart = alt.Chart(df_plot).mark_line(color="purple").encode(
    x=alt.X("Date:T"),
    y=alt.Y("RSI:Q", scale=alt.Scale(domain=[0, 100]))
).properties(height=150)
rsi_line30 = alt.Chart(pd.DataFrame({"y": [30]})).mark_rule(color="green", strokeDash=[4, 2]).encode(y="y:Q")
rsi_line70 = alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(color="red", strokeDash=[4, 2]).encode(y="y:Q")
st.altair_chart(alt.layer(rsi_chart, rsi_line30, rsi_line70), use_container_width=True)

# MACD 圖
st.subheader("MACD")
df_plot["MACD_diff"] = df_plot["MACD_diff"].astype(float)
macd_bar = alt.Chart(df_plot).mark_bar().encode(
    x="Date:T",
    y=alt.Y("MACD_diff:Q", title="MACD Histogram"),
    color=alt.condition(alt.datum.MACD_diff > 0, alt.value("#2ecc71"), alt.value("#e74c3c"))
).properties(height=150)
st.altair_chart(macd_bar, use_container_width=True)
