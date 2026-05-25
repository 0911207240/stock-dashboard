import streamlit as st
import pandas as pd
import altair as alt
from data_fetcher import fetch, fetch_all, fetch_taiex, WATCHLIST, SECTORS
from analyzer import add_indicators, detect_signals, score, calc_support_resistance, calc_week52, detect_pre_signals, pre_score
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

# ── 快取 ──────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_all(period: str, sector: str):
    return fetch_all(period, sector)

@st.cache_data(ttl=1800)
def load_one(ticker: str, period: str):
    return fetch(ticker, period=period)

@st.cache_data(ttl=1800)
def load_taiex(period: str):
    return fetch_taiex(period)

# ── 輔助函式 ──────────────────────────────────────────
def health_light(sc: int, rsi: float, week52_pct: float) -> str:
    if sc >= 2 and rsi < 70 and week52_pct < 85:
        return "🟢 強勢"
    elif sc <= -2 or rsi > 75 or week52_pct > 90:
        return "🔴 弱勢"
    else:
        return "🟡 觀察"

def recommendation(sc: int, rsi: float, week52_pct: float, pnl_pct) -> str:
    if sc >= 2 and rsi < 65 and week52_pct < 75:
        return "✅ 加碼"
    elif sc <= -2 or (rsi > 78 and week52_pct > 85):
        return "🔴 減碼"
    elif sc < -1 and pnl_pct is not None and pnl_pct < -8:
        return "❌ 賣出"
    else:
        return "⏸ 持有"

def relative_strength(stock_df: pd.DataFrame, taiex_df: pd.DataFrame) -> float | None:
    try:
        s_ret = (float(stock_df["Close"].iloc[-1]) / float(stock_df["Close"].iloc[0]) - 1) * 100
        t_ret = (float(taiex_df["Close"].iloc[-1]) / float(taiex_df["Close"].iloc[0]) - 1) * 100
        return round(s_ret - t_ret, 2)
    except Exception:
        return None

def prep_plot(df: pd.DataFrame) -> pd.DataFrame:
    df_plot = df.reset_index()
    df_plot = df_plot.rename(columns={df_plot.columns[0]: "Date"})
    df_plot["Date"] = pd.to_datetime(df_plot["Date"])
    for col in ["Close", "MA5", "MA20", "MA60", "RSI", "MACD_diff", "Volume", "BB_upper", "BB_lower"]:
        if col in df_plot.columns:
            df_plot[col] = pd.to_numeric(df_plot[col], errors="coerce")
    return df_plot

# ── Tabs ──────────────────────────────────────────
tab0, tab1, tab2, tab3, tab4 = st.tabs(["🌐 大盤展望", "💼 持股總覽", "🔍 市場掃描", "📊 個股分析", "🎯 卡位雷達"])

# ══════════════════════════════════════════════════
# Tab 0：大盤展望
# ══════════════════════════════════════════════════
with tab0:
    st.header("🌐 大盤展望")

    with st.spinner("載入大盤資料..."):
        taiex = load_taiex(period)

    if taiex.empty:
        st.error("無法取得大盤資料")
    else:
        taiex = add_indicators(taiex)
        taiex_latest = taiex.iloc[-1]
        taiex_prev   = taiex.iloc[-2]
        taiex_price  = float(taiex_latest["Close"])
        taiex_prev_p = float(taiex_prev["Close"])
        taiex_chg    = (taiex_price - taiex_prev_p) / taiex_prev_p * 100
        taiex_rsi    = float(taiex_latest["RSI"]) if pd.notna(taiex_latest["RSI"]) else 50.0
        taiex_k      = float(taiex_latest["K"])   if pd.notna(taiex_latest["K"])   else 50.0
        taiex_d      = float(taiex_latest["D"])   if pd.notna(taiex_latest["D"])   else 50.0
        taiex_macd   = float(taiex_latest["MACD_diff"]) if pd.notna(taiex_latest["MACD_diff"]) else 0.0
        taiex_w52    = calc_week52(taiex)
        taiex_sr     = calc_support_resistance(taiex)
        taiex_sigs   = detect_signals(taiex)
        taiex_score  = score(taiex_sigs)

        # 均線多空
        ma_bull = (taiex_latest["MA5"] > taiex_latest["MA20"] > taiex_latest["MA60"])

        # 大盤綜合評分（-10 ~ +10）
        mkt_score = 0
        mkt_score += taiex_score                              # 技術訊號
        mkt_score += 1 if ma_bull else -1                     # 均線排列
        mkt_score += 1 if taiex_rsi < 60 else (-1 if taiex_rsi > 72 else 0)
        mkt_score += 1 if taiex_k < 70 else (-1 if taiex_k > 80 else 0)
        mkt_score += 1 if taiex_macd > 0 else -1
        mkt_score += -1 if taiex_w52["week52_pct"] > 88 else (1 if taiex_w52["week52_pct"] < 30 else 0)

        # 市場建議
        if mkt_score >= 3:
            mkt_outlook = "🟢 積極做多"
            mkt_desc    = "技術面多項指標同步看多，可積極布局強勢股"
        elif mkt_score >= 1:
            mkt_outlook = "🟡 謹慎偏多"
            mkt_desc    = "大盤偏多但高檔，選股操作、分批布局為主"
        elif mkt_score >= -1:
            mkt_outlook = "🟡 觀望"
            mkt_desc    = "多空訊號混雜，減少操作、持股待變"
        elif mkt_score >= -3:
            mkt_outlook = "🟠 謹慎偏空"
            mkt_desc    = "技術轉弱，降低持股比例、避免追高"
        else:
            mkt_outlook = "🔴 防禦模式"
            mkt_desc    = "多項指標轉空，建議減碼、保留現金"

        # 頂部展望卡
        st.markdown(f"## {mkt_outlook}")
        st.info(mkt_desc)

        # 大盤指標列
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("加權指數",  f"{taiex_price:,.0f}", f"{taiex_chg:+.2f}%")
        c2.metric("RSI",      f"{taiex_rsi:.1f}")
        c3.metric("K值",      f"{taiex_k:.1f}")
        c4.metric("MACD方向", "↑ 多頭" if taiex_macd > 0 else "↓ 空頭")
        c5.metric("年度位置", f"{taiex_w52['week52_pct']:.0f}%")
        c6.metric("均線排列", "多頭 ✅" if ma_bull else "空頭 ❌")

        st.markdown(
            f"📌 近20日 支撐 `{taiex_sr['support_20']:,.0f}` ／ 壓力 `{taiex_sr['resistance_20']:,.0f}`　"
            f"｜　近60日 支撐 `{taiex_sr['support_60']:,.0f}` ／ 壓力 `{taiex_sr['resistance_60']:,.0f}`"
        )

        st.markdown("---")

        # 四面向評分卡
        st.subheader("市場訊號明細")
        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("**技術面**")
            for s in taiex_sigs:
                color = "green" if s["type"] == "buy" else ("red" if s["type"] == "sell" else "orange")
                label = "看多" if s["type"] == "buy" else ("看空" if s["type"] == "sell" else "觀察")
                st.markdown(f":{color}[**[{label}] {s['indicator']}**] — {s['msg']}")
            if not taiex_sigs:
                st.markdown("無明確訊號")
            st.markdown(f"均線排列：{'✅ 多頭' if ma_bull else '❌ 空頭'}")

        with col_r:
            st.markdown("**總經參考（最新）**")
            st.markdown("📦 外銷訂單年增 **+48%**（4月，連15紅）")
            st.markdown("🤖 AI伺服器出口爆發，資通訊年增 **+134%**")
            st.markdown("💡 半導體產值目標 **7兆元**")
            st.markdown("⚠️ 大盤高檔，注意獲利了結賣壓")
            st.caption("總經數據每月更新，以官方公布為準")

        st.markdown("---")

        # 大盤走勢圖
        st.subheader("加權指數走勢")
        df_taiex_plot = prep_plot(taiex)
        base_t = alt.Chart(df_taiex_plot).encode(x=alt.X("Date:T", title="日期"))
        t_price = base_t.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("Close:Q", title="指數"))
        t_ma20  = base_t.mark_line(color="orange", strokeDash=[4,2], strokeWidth=1).encode(y="MA20:Q")
        t_ma60  = base_t.mark_line(color="red",    strokeDash=[4,2], strokeWidth=1).encode(y="MA60:Q")
        t_sup   = alt.Chart(pd.DataFrame({"y": [taiex_sr["support_20"]]})).mark_rule(color="green", strokeDash=[6,3], strokeWidth=1.5).encode(y="y:Q")
        t_res   = alt.Chart(pd.DataFrame({"y": [taiex_sr["resistance_20"]]})).mark_rule(color="red", strokeDash=[6,3], strokeWidth=1.5).encode(y="y:Q")
        st.altair_chart(alt.layer(t_price, t_ma20, t_ma60, t_sup, t_res).properties(height=350), use_container_width=True)
        st.caption("🔵 指數　🟠 MA20　🔴 MA60　🟢 近20日支撐　🔴 近20日壓力")

        # 大盤 RSI
        st.subheader("大盤 RSI")
        t_rsi   = base_t.mark_line(color="purple").encode(y=alt.Y("RSI:Q", scale=alt.Scale(domain=[0,100]))).properties(height=130)
        t_r30   = alt.Chart(pd.DataFrame({"y": [30]})).mark_rule(color="green", strokeDash=[4,2]).encode(y="y:Q")
        t_r70   = alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(color="red",   strokeDash=[4,2]).encode(y="y:Q")
        st.altair_chart(alt.layer(t_rsi, t_r30, t_r70), use_container_width=True)

# ══════════════════════════════════════════════════
# Tab 1：持股總覽
# ══════════════════════════════════════════════════
with tab1:
    st.header("我的持股")

    with st.spinner("載入中..."):
        all_data = load_all(period, "全部")
        taiex_df = load_taiex(period)
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
        pnl_color = "normal" if total_pnl >= 0 else "inverse"
        c3.metric("未實現損益", f"${total_pnl:+,.0f}")

    st.markdown("---")

    # 持股明細表（含健康燈號、操作建議、相對強弱）
    rows = []
    for name, d in summary.items():
        df_s = all_data.get(name)
        if df_s is None or df_s.empty:
            continue
        df_s = add_indicators(df_s)
        sigs = detect_signals(df_s)
        sc = score(sigs)
        latest = df_s.iloc[-1]
        rsi = float(latest["RSI"]) if pd.notna(latest["RSI"]) else 50.0
        w52 = calc_week52(df_s)
        w52_pct = w52["week52_pct"]
        rs = relative_strength(df_s, taiex_df) if not taiex_df.empty else None
        rec = recommendation(sc, rsi, w52_pct, d.get("pnl_pct"))
        health = health_light(sc, rsi, w52_pct)

        row = {
            "狀態": health,
            "名稱": name,
            "現價": round(d["price"], 2),
            "漲跌%": round(d["change_pct"], 2),
            "今日損益": round(d["day_change"], 0),
            "市值": round(d["value"], 0),
            "RSI": round(rsi, 1),
            "年度位置%": round(w52_pct, 0),
        }
        if d["cost"] is not None:
            row["損益%"] = round(d["pnl_pct"], 2)
            row["未實現損益"] = round(d["pnl"], 0)
        else:
            row["損益%"] = "-"
            row["未實現損益"] = "-"
        row["vs大盤"] = f"{rs:+.1f}%" if rs is not None else "-"
        row["操作建議"] = rec
        rows.append(row)

    df_port = pd.DataFrame(rows)

    def color_row(row):
        val = row.get("漲跌%", 0)
        try:
            val = float(val)
            if val > 0:
                return ["background-color:#1a6b3a; color:#ffffff"] * len(row)
            elif val < 0:
                return ["background-color:#8b1a1a; color:#ffffff"] * len(row)
        except Exception:
            pass
        return [""] * len(row)

    st.dataframe(df_port.style.apply(color_row, axis=1), use_container_width=True, hide_index=True)

    # 市值佔比圖
    st.subheader("市值佔比")
    pie_data = pd.DataFrame([{"名稱": name, "市值": d["value"]} for name, d in summary.items()])
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
        with st.spinner("掃描中..."):
            scan_data = load_all(period, sector)
            taiex_scan = load_taiex(period)
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
                rsi = float(latest["RSI"]) if pd.notna(latest["RSI"]) else 50.0
                w52 = calc_week52(df)
                rs = relative_strength(df, taiex_scan) if not taiex_scan.empty else None
                health = health_light(sc, rsi, w52["week52_pct"])
                rows.append({
                    "狀態": health,
                    "名稱": name,
                    "代碼": WATCHLIST[name],
                    "現價": round(price, 2),
                    "漲跌%": round(change_pct, 2),
                    "RSI": round(rsi, 1),
                    "K值": round(float(latest["K"]), 1) if pd.notna(latest["K"]) else "-",
                    "年度位置%": round(w52["week52_pct"], 0),
                    "vs大盤": f"{rs:+.1f}%" if rs is not None else "-",
                    "訊號分數": sc,
                    "訊號": " | ".join([s["msg"] for s in sigs]) if sigs else "無",
                })

            result_df = pd.DataFrame(rows).sort_values("訊號分數", ascending=False)
            filtered = result_df[result_df["訊號分數"].abs() >= min_sc]
            st.success(f"掃描完成，{len(filtered)} 檔達標（共 {len(result_df)} 檔）")

            def highlight(row):
                if row["訊號分數"] >= 2:
                    return ["background-color:#1a6b3a; color:#ffffff"] * len(row)
                elif row["訊號分數"] <= -2:
                    return ["background-color:#8b1a1a; color:#ffffff"] * len(row)
                return [""] * len(row)

            st.dataframe(filtered.style.apply(highlight, axis=1), use_container_width=True, hide_index=True)

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
        taiex_ind = load_taiex(period)

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
    rsi = float(latest["RSI"]) if pd.notna(latest["RSI"]) else 50.0
    w52 = calc_week52(df)
    sr = calc_support_resistance(df)
    rs = relative_strength(df, taiex_ind) if not taiex_ind.empty else None

    # 持股成本（如果有）
    holding = HOLDINGS.get(selected_name)
    cost = holding["cost"] if holding and holding["cost"] is not None else None
    pnl_pct = ((price - cost) / cost * 100) if cost else None

    # 健康燈號 + 操作建議
    health = health_light(sc, rsi, w52["week52_pct"])
    rec = recommendation(sc, rsi, w52["week52_pct"], pnl_pct)

    col_h, col_r = st.columns(2)
    col_h.markdown(f"### 健康狀態：{health}")
    col_r.markdown(f"### 操作建議：{rec}")

    st.markdown("---")

    # 指標列
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("收盤價", f"{price:.2f}", f"{change_pct:+.2f}%")
    c2.metric("RSI", f"{rsi:.1f}")
    c3.metric("K值", f"{float(latest['K']):.1f}" if pd.notna(latest["K"]) else "-")
    c4.metric("年度位置", f"{w52['week52_pct']:.0f}%")
    c5.metric("vs 大盤", f"{rs:+.1f}%" if rs is not None else "-")
    c6.metric("訊號分數", sc, delta="看多" if sc > 0 else ("看空" if sc < 0 else "中性"))

    # 支撐壓力資訊
    st.markdown(
        f"📌 **近20日** 支撐 `{sr['support_20']:.2f}` ／ 壓力 `{sr['resistance_20']:.2f}`　"
        f"｜　📌 **近60日** 支撐 `{sr['support_60']:.2f}` ／ 壓力 `{sr['resistance_60']:.2f}`"
    )

    if cost:
        pnl_arrow = "▲" if pnl_pct >= 0 else "▼"
        st.markdown(f"💰 **持股成本** `{cost:.2f}` ／ 損益 `{pnl_arrow}{abs(pnl_pct):.1f}%`")

    st.markdown("---")

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

    # 準備畫圖
    df_plot = prep_plot(df)
    base = alt.Chart(df_plot).encode(x=alt.X("Date:T", title="日期"))

    # 價格 + 均線 + 布林 + 成本線 + 支撐壓力
    st.subheader("價格走勢")
    price_line  = base.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("Close:Q", title="價格"))
    ma5_line    = base.mark_line(color="orange",  strokeDash=[4,2], strokeWidth=1).encode(y="MA5:Q")
    ma20_line   = base.mark_line(color="red",     strokeDash=[4,2], strokeWidth=1).encode(y="MA20:Q")
    ma60_line   = base.mark_line(color="gray",    strokeDash=[2,4], strokeWidth=1).encode(y="MA60:Q")
    bb_upper    = base.mark_line(color="#aaaaff", strokeDash=[2,2], strokeWidth=1).encode(y="BB_upper:Q")
    bb_lower    = base.mark_line(color="#aaaaff", strokeDash=[2,2], strokeWidth=1).encode(y="BB_lower:Q")

    layers = [price_line, ma5_line, ma20_line, ma60_line, bb_upper, bb_lower]

    # 支撐壓力線（近20日）
    layers.append(
        alt.Chart(pd.DataFrame({"y": [sr["support_20"]]}))
        .mark_rule(color="green", strokeDash=[6,3], strokeWidth=1.5)
        .encode(y="y:Q")
    )
    layers.append(
        alt.Chart(pd.DataFrame({"y": [sr["resistance_20"]]}))
        .mark_rule(color="red", strokeDash=[6,3], strokeWidth=1.5)
        .encode(y="y:Q")
    )

    # 成本線
    if cost:
        layers.append(
            alt.Chart(pd.DataFrame({"y": [cost]}))
            .mark_rule(color="gold", strokeDash=[8,4], strokeWidth=2)
            .encode(y="y:Q")
        )

    st.altair_chart(alt.layer(*layers).properties(height=350), use_container_width=True)

    # 圖例說明
    legend_items = "🔵 收盤　🟠 MA5　🔴 MA20　⚫ MA60　🟣 布林通道　🟢 支撐　🔴 壓力"
    if cost:
        legend_items += "　🟡 成本線"
    st.caption(legend_items)

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
    r30 = alt.Chart(pd.DataFrame({"y": [30]})).mark_rule(color="green", strokeDash=[4,2]).encode(y="y:Q")
    r70 = alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(color="red",   strokeDash=[4,2]).encode(y="y:Q")
    st.altair_chart(alt.layer(rsi_chart, r30, r70), use_container_width=True)

    # MACD
    st.subheader("MACD")
    macd_bar = base.mark_bar().encode(
        y=alt.Y("MACD_diff:Q", title="MACD Histogram"),
        color=alt.condition(alt.datum.MACD_diff > 0, alt.value("#2ecc71"), alt.value("#e74c3c"))
    ).properties(height=150)
    st.altair_chart(macd_bar, use_container_width=True)

# ══════════════════════════════════════════════════
# Tab 4：卡位雷達
# ══════════════════════════════════════════════════
with tab4:
    st.header("🎯 卡位雷達")
    st.caption("偵測尚未觸發、但技術面正在醞釀的股票，提早卡位。")

    col_s, col_c = st.columns([3, 1])
    with col_s:
        radar_sector = st.selectbox("篩選產業", list(SECTORS.keys()), key="radar_sector")
    with col_c:
        capital = st.number_input("可用資金（元）", min_value=10000, max_value=10000000,
                                   value=300000, step=10000)

    def position_advice(pscore: int, atr_pct: float, w52_pct: float, capital: int) -> dict:
        if pscore >= 3:
            base, label, risk = 0.12, "🔴 重倉", "高"
        elif pscore == 2:
            base, label, risk = 0.07, "🟡 標準倉", "中"
        else:
            base, label, risk = 0.03, "🟢 試水位", "低"
        vol_factor = max(0.5, 1.0 - max(0, atr_pct - 1.5) * 0.08)
        pos_factor = max(0.5, 1.0 - max(0, w52_pct - 50) / 120)
        amount = capital * base * vol_factor * pos_factor
        shares_ref = int(amount // 1000) * 1000
        return {"label": label, "amount": shares_ref, "risk": risk}

    if st.button("開始雷達掃描", type="primary"):
        with st.spinner("掃描預警訊號中..."):
            radar_data = load_all(period, radar_sector)
            rows = []
            for name, df in radar_data.items():
                df = add_indicators(df)
                pre = detect_pre_signals(df)
                ps  = pre_score(pre)
                if ps == 0:
                    continue
                latest  = df.iloc[-1]
                prev    = df.iloc[-2]
                price   = float(latest["Close"])
                chg     = (price - float(prev["Close"])) / float(prev["Close"]) * 100
                rsi     = float(latest["RSI"]) if pd.notna(latest["RSI"]) else 50.0
                atr_pct = float(latest["ATR_pct"]) if pd.notna(latest["ATR_pct"]) else 2.0
                w52     = calc_week52(df)
                pos     = position_advice(ps, atr_pct, w52["week52_pct"], capital)
                rows.append({
                    "名稱":      name,
                    "代碼":      WATCHLIST[name],
                    "現價":      round(price, 2),
                    "漲跌%":     round(chg, 2),
                    "RSI":       round(rsi, 1),
                    "年度位置%": round(w52["week52_pct"], 0),
                    "波動%/日":  round(atr_pct, 1),
                    "預警分數":  ps,
                    "建議倉位":  pos["label"],
                    "建議金額":  f"${pos['amount']:,}",
                    "預警訊號":  " ／ ".join([s["msg"] for s in pre]),
                })

            if not rows:
                st.info("目前無預警股票，市場訊號不明顯")
            else:
                result = pd.DataFrame(rows).sort_values("預警分數", ascending=False)
                st.success(f"找到 {len(result)} 檔預警股票")

                def radar_color(row):
                    ps = row["預警分數"]
                    if ps >= 3:
                        return ["background-color:#1a6b3a; color:#ffffff"] * len(row)
                    elif ps == 2:
                        return ["background-color:#7a5a00; color:#ffffff"] * len(row)
                    return [""] * len(row)

                st.dataframe(result.style.apply(radar_color, axis=1),
                             use_container_width=True, hide_index=True)

                st.markdown("---")
                st.subheader("倉位建議說明")
                col1, col2, col3 = st.columns(3)
                col1.markdown("🟢 **試水位**\n預警分數 1，先小量卡位觀察")
                col2.markdown("🟡 **標準倉**\n預警分數 2，正常布局")
                col3.markdown("🔴 **重倉**\n預警分數 3+，多指標同步醞釀，可積極卡位")
                st.caption(
                    "建議金額 = 可用資金 × 倉位比例 × 波動折扣 × 位置折扣。"
                    "高波動或年度位置偏高的股票，金額會自動縮小。"
                    "以上為技術面分析，不構成投資建議，請自行判斷風險。"
                )
