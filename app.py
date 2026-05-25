import streamlit as st
import pandas as pd
import altair as alt
from data_fetcher import fetch, fetch_all, fetch_taiex, fetch_dividends, fetch_institutional, WATCHLIST, SECTORS
from analyzer import add_indicators, detect_signals, score, calc_support_resistance, calc_week52, detect_pre_signals, pre_score
from line_notifier import send, build_signal_message
from portfolio import HOLDINGS, calc_summary, build_portfolio_message
from signal_log import load_log, save_signal, update_and_load, win_rate
import copy

st.set_page_config(page_title="股票儀表板", layout="wide", page_icon="📈")

# ── 側邊欄 ──────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")
    period = st.selectbox("資料區間", ["3mo", "6mo", "1y", "2y"], index=2)
    import config
    st.markdown("---")
    st.caption("LINE 推播")
    line_token = st.text_input("Channel Access Token", value=config.LINE_CHANNEL_ACCESS_TOKEN, type="password")
    line_uid   = st.text_input("User ID", value=config.LINE_USER_ID)
    if st.button("儲存"):
        config.LINE_CHANNEL_ACCESS_TOKEN = line_token
        config.LINE_USER_ID = line_uid
        st.success("已儲存")
    if st.button("測試推播"):
        ok = send("股票儀表板連線測試成功！")
        st.success("推播成功！") if ok else st.error("失敗，請確認 Token")

# ── session state 持股 ──────────────────────────────
if "holdings" not in st.session_state:
    st.session_state.holdings = copy.deepcopy(HOLDINGS)

# ── 快取 ──────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_all(period, sector):
    return fetch_all(period, sector)

@st.cache_data(ttl=1800)
def load_one(ticker, period):
    return fetch(ticker, period=period)

@st.cache_data(ttl=1800)
def load_taiex(period):
    return fetch_taiex(period)

@st.cache_data(ttl=3600)
def load_dividends(ticker):
    return fetch_dividends(ticker)

@st.cache_data(ttl=3600)
def load_institutional(ticker):
    return fetch_institutional(ticker)

# ── 輔助函式 ──────────────────────────────────────────
def health_light(sc, rsi, week52_pct):
    if sc >= 2 and rsi < 70 and week52_pct < 85:
        return "🟢 強勢"
    elif sc <= -2 or rsi > 75 or week52_pct > 90:
        return "🔴 弱勢"
    return "🟡 觀察"

def recommendation(sc, rsi, week52_pct, pnl_pct):
    if sc >= 2 and rsi < 65 and week52_pct < 75:
        return "✅ 加碼"
    elif sc <= -2 or (rsi > 78 and week52_pct > 85):
        return "🔴 減碼"
    elif sc < -1 and pnl_pct is not None and pnl_pct < -8:
        return "❌ 賣出"
    return "⏸ 持有"

def relative_strength(stock_df, taiex_df):
    try:
        s = (float(stock_df["Close"].iloc[-1]) / float(stock_df["Close"].iloc[0]) - 1) * 100
        t = (float(taiex_df["Close"].iloc[-1]) / float(taiex_df["Close"].iloc[0]) - 1) * 100
        return round(s - t, 2)
    except Exception:
        return None

def prep_plot(df):
    df_plot = df.reset_index()
    df_plot = df_plot.rename(columns={df_plot.columns[0]: "Date"})
    df_plot["Date"] = pd.to_datetime(df_plot["Date"])
    for col in ["Close","MA5","MA20","MA60","RSI","MACD_diff","Volume","BB_upper","BB_lower"]:
        if col in df_plot.columns:
            df_plot[col] = pd.to_numeric(df_plot[col], errors="coerce")
    return df_plot

def row_color(row, col="漲跌%"):
    try:
        v = float(row[col])
        if v > 0: return ["background-color:#1a6b3a; color:#ffffff"] * len(row)
        if v < 0: return ["background-color:#8b1a1a; color:#ffffff"] * len(row)
    except Exception:
        pass
    return [""] * len(row)

# ── Tabs ──────────────────────────────────────────
tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🌐 大盤展望", "💼 持股管理", "🔍 市場掃描", "📊 個股分析", "🎯 卡位雷達", "📜 訊號歷史"
])

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
        taiex        = add_indicators(taiex)
        tl           = taiex.iloc[-1]
        tp           = taiex.iloc[-2]
        tprice       = float(tl["Close"])
        tchg         = (tprice - float(tp["Close"])) / float(tp["Close"]) * 100
        trsi         = float(tl["RSI"])  if pd.notna(tl["RSI"])       else 50.0
        tk           = float(tl["K"])    if pd.notna(tl["K"])          else 50.0
        tmacd        = float(tl["MACD_diff"]) if pd.notna(tl["MACD_diff"]) else 0.0
        tw52         = calc_week52(taiex)
        tsr          = calc_support_resistance(taiex)
        tsigs        = detect_signals(taiex)
        tsc          = score(tsigs)
        ma_bull      = tl["MA5"] > tl["MA20"] > tl["MA60"]

        mkt = tsc
        mkt += 1 if ma_bull else -1
        mkt += 1 if trsi < 60 else (-1 if trsi > 72 else 0)
        mkt += 1 if tk < 70  else (-1 if tk > 80  else 0)
        mkt += 1 if tmacd > 0 else -1
        mkt += -1 if tw52["week52_pct"] > 88 else (1 if tw52["week52_pct"] < 30 else 0)

        if   mkt >= 3:  outlook, desc = "🟢 積極做多", "技術面多項指標同步看多，可積極布局強勢股"
        elif mkt >= 1:  outlook, desc = "🟡 謹慎偏多", "大盤偏多但高檔，選股操作、分批布局為主"
        elif mkt >= -1: outlook, desc = "🟡 觀望",     "多空訊號混雜，減少操作、持股待變"
        elif mkt >= -3: outlook, desc = "🟠 謹慎偏空", "技術轉弱，降低持股比例、避免追高"
        else:           outlook, desc = "🔴 防禦模式", "多項指標轉空，建議減碼、保留現金"

        st.markdown(f"## {outlook}")
        st.info(desc)

        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("加權指數",  f"{tprice:,.0f}", f"{tchg:+.2f}%")
        c2.metric("RSI",       f"{trsi:.1f}")
        c3.metric("K值",       f"{tk:.1f}")
        c4.metric("MACD",      "↑ 多頭" if tmacd > 0 else "↓ 空頭")
        c5.metric("年度位置",  f"{tw52['week52_pct']:.0f}%")
        c6.metric("均線排列",  "多頭 ✅" if ma_bull else "空頭 ❌")

        st.markdown(
            f"📌 近20日 支撐 `{tsr['support_20']:,.0f}` ／ 壓力 `{tsr['resistance_20']:,.0f}`　"
            f"｜　近60日 支撐 `{tsr['support_60']:,.0f}` ／ 壓力 `{tsr['resistance_60']:,.0f}`"
        )
        st.markdown("---")

        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("**技術面訊號**")
            for s in tsigs:
                c = "green" if s["type"]=="buy" else ("red" if s["type"]=="sell" else "orange")
                lbl = "看多" if s["type"]=="buy" else ("看空" if s["type"]=="sell" else "觀察")
                st.markdown(f":{c}[**[{lbl}] {s['indicator']}**] — {s['msg']}")
            if not tsigs: st.markdown("無明確訊號")
            st.markdown(f"均線排列：{'✅ 多頭' if ma_bull else '❌ 空頭'}")
        with col_r:
            st.markdown("**總經參考（最新）**")
            st.markdown("📦 外銷訂單年增 **+48%**（4月，連15紅）")
            st.markdown("🤖 AI伺服器出口爆發，資通訊年增 **+134%**")
            st.markdown("💡 半導體產值目標 **7兆元**")
            st.markdown("⚠️ 大盤高檔，注意獲利了結賣壓")
            st.caption("總經數據每月更新，以官方公布為準")

        st.markdown("---")
        st.subheader("加權指數走勢")
        dtp  = prep_plot(taiex)
        bt   = alt.Chart(dtp).encode(x=alt.X("Date:T", title="日期"))
        layers_t = [
            bt.mark_line(color="#1f77b4", strokeWidth=2).encode(y=alt.Y("Close:Q", title="指數")),
            bt.mark_line(color="orange", strokeDash=[4,2], strokeWidth=1).encode(y="MA20:Q"),
            bt.mark_line(color="red",    strokeDash=[4,2], strokeWidth=1).encode(y="MA60:Q"),
            alt.Chart(pd.DataFrame({"y":[tsr["support_20"]]})).mark_rule(color="green",strokeDash=[6,3],strokeWidth=1.5).encode(y="y:Q"),
            alt.Chart(pd.DataFrame({"y":[tsr["resistance_20"]]})).mark_rule(color="red",strokeDash=[6,3],strokeWidth=1.5).encode(y="y:Q"),
        ]
        st.altair_chart(alt.layer(*layers_t).properties(height=350), use_container_width=True)
        st.caption("🔵 指數　🟠 MA20　🔴 MA60　🟢 近20日支撐　🔴 近20日壓力")

        st.subheader("大盤 RSI")
        trsi_chart = bt.mark_line(color="purple").encode(y=alt.Y("RSI:Q",scale=alt.Scale(domain=[0,100]))).properties(height=130)
        st.altair_chart(alt.layer(
            trsi_chart,
            alt.Chart(pd.DataFrame({"y":[30]})).mark_rule(color="green",strokeDash=[4,2]).encode(y="y:Q"),
            alt.Chart(pd.DataFrame({"y":[70]})).mark_rule(color="red",  strokeDash=[4,2]).encode(y="y:Q"),
        ), use_container_width=True)

# ══════════════════════════════════════════════════
# Tab 1：持股管理
# ══════════════════════════════════════════════════
with tab1:
    st.header("💼 持股管理")

    with st.spinner("載入持股資料..."):
        all_data   = load_all(period, "全部")
        taiex_port = load_taiex(period)
        summary    = calc_summary(dict(all_data), st.session_state.holdings)

    total = summary.pop("__total__", {})
    c1,c2,c3 = st.columns(3)
    c1.metric("總市值",     f"${total.get('total_value',0):,.0f}")
    c2.metric("今日損益",   f"${total.get('total_day_change',0):+,.0f}")
    if total.get("total_pnl") is not None:
        c3.metric("未實現損益", f"${total['total_pnl']:+,.0f}")

    # 停損停利警報
    alerts = [(n, d) for n, d in summary.items() if d.get("stop_alert") or d.get("take_alert")]
    if alerts:
        st.markdown("---")
        for name, d in alerts:
            if d.get("stop_alert"):
                st.error(f"⚠️ 停損警報：{name} 現價 ${d['price']:.2f} 已跌破停損 ${d['stop_loss']:.2f}")
            if d.get("take_alert"):
                st.success(f"🎯 停利達標：{name} 現價 ${d['price']:.2f} 已達停利 ${d['take_profit']:.2f}")

    st.markdown("---")

    # 持股明細
    rows = []
    for name, d in summary.items():
        df_s = all_data.get(name)
        if df_s is None or df_s.empty: continue
        df_s   = add_indicators(df_s)
        sigs   = detect_signals(df_s)
        sc     = score(sigs)
        latest = df_s.iloc[-1]
        rsi    = float(latest["RSI"]) if pd.notna(latest["RSI"]) else 50.0
        w52    = calc_week52(df_s)
        rs     = relative_strength(df_s, taiex_port) if not taiex_port.empty else None
        rec    = recommendation(sc, rsi, w52["week52_pct"], d.get("pnl_pct"))
        health = health_light(sc, rsi, w52["week52_pct"])
        row = {
            "狀態": health, "名稱": name,
            "現價": round(d["price"],2), "漲跌%": round(d["change_pct"],2),
            "今日損益": round(d["day_change"],0), "市值": round(d["value"],0),
            "RSI": round(rsi,1), "年度位置%": round(w52["week52_pct"],0),
        }
        if d["cost"] is not None:
            row["損益%"]    = round(d["pnl_pct"],2)
            row["未實現損益"] = round(d["pnl"],0)
        else:
            row["損益%"] = "-"; row["未實現損益"] = "-"
        row["vs大盤"] = f"{rs:+.1f}%" if rs is not None else "-"
        row["操作建議"] = rec
        sl = d.get("stop_loss");  tp = d.get("take_profit")
        row["停損"] = f"${sl:.2f}" if sl else "-"
        row["停利"] = f"${tp:.2f}" if tp else "-"
        rows.append(row)

    df_port = pd.DataFrame(rows)
    st.dataframe(df_port.style.apply(row_color, axis=1), use_container_width=True, hide_index=True)

    # 市值佔比
    st.subheader("市值佔比")
    pie_data  = pd.DataFrame([{"名稱":n,"市值":d["value"]} for n,d in summary.items()])
    pie_chart = alt.Chart(pie_data).mark_arc(innerRadius=50).encode(
        theta=alt.Theta("市值:Q"),
        color=alt.Color("名稱:N", legend=alt.Legend(orient="right")),
        tooltip=["名稱","市值"]
    ).properties(height=280)
    st.altair_chart(pie_chart, use_container_width=True)

    # 除權息日曆
    st.markdown("---")
    st.subheader("📅 持股除權息紀錄")
    div_rows = []
    for name, holding in st.session_state.holdings.items():
        ticker = WATCHLIST.get(name)
        if not ticker: continue
        divs = load_dividends(ticker)
        if divs.empty: continue
        for dt, amt in divs.items():
            div_rows.append({"名稱": name, "除息日": str(dt)[:10], "每股配息": round(float(amt),4)})
    if div_rows:
        df_div = pd.DataFrame(div_rows).sort_values("除息日", ascending=False)
        st.dataframe(df_div, use_container_width=True, hide_index=True)
    else:
        st.info("無除權息資料")

    # 持股編輯
    st.markdown("---")
    st.subheader("✏️ 編輯持股")
    with st.expander("新增 / 修改持股"):
        col_a, col_b = st.columns(2)
        with col_a:
            e_name  = st.selectbox("股票名稱", list(WATCHLIST.keys()), key="edit_name")
            e_shares = st.number_input("股數", min_value=1, value=1000, step=100)
            e_cost   = st.number_input("成本價（0=不設定）", min_value=0.0, value=0.0, step=0.1)
        with col_b:
            e_sl = st.number_input("停損價（0=不設定）", min_value=0.0, value=0.0, step=0.1)
            e_tp = st.number_input("停利價（0=不設定）", min_value=0.0, value=0.0, step=0.1)
        if st.button("儲存至本次持股"):
            st.session_state.holdings[e_name] = {
                "shares":      e_shares,
                "cost":        e_cost   if e_cost  > 0 else None,
                "stop_loss":   e_sl     if e_sl    > 0 else None,
                "take_profit": e_tp     if e_tp    > 0 else None,
            }
            st.success(f"✅ 已更新 {e_name}")
            st.rerun()

    with st.expander("移除持股"):
        rm_name = st.selectbox("選擇要移除的股票", list(st.session_state.holdings.keys()), key="rm_name")
        if st.button("確認移除"):
            st.session_state.holdings.pop(rm_name, None)
            st.success(f"已移除 {rm_name}")
            st.rerun()

# ══════════════════════════════════════════════════
# Tab 2：市場掃描
# ══════════════════════════════════════════════════
with tab2:
    st.header("🔍 市場掃描")
    col_a, col_b = st.columns([3,1])
    with col_a: sector  = st.selectbox("產業篩選", list(SECTORS.keys()))
    with col_b: min_sc  = st.number_input("最低分數", min_value=1, max_value=5, value=2)

    if st.button("開始掃描", type="primary"):
        with st.spinner("掃描中..."):
            scan_data   = load_all(period, sector)
            taiex_scan  = load_taiex(period)
            rows = []
            for name, df in scan_data.items():
                df    = add_indicators(df)
                sigs  = detect_signals(df)
                sc    = score(sigs)
                lat   = df.iloc[-1]; prv = df.iloc[-2] if len(df)>1 else lat
                price = float(lat["Close"])
                chg   = (price - float(prv["Close"])) / float(prv["Close"]) * 100
                rsi   = float(lat["RSI"]) if pd.notna(lat["RSI"]) else 50.0
                w52   = calc_week52(df)
                rs    = relative_strength(df, taiex_scan) if not taiex_scan.empty else None
                rows.append({
                    "狀態": health_light(sc, rsi, w52["week52_pct"]),
                    "名稱": name, "代碼": WATCHLIST[name],
                    "現價": round(price,2), "漲跌%": round(chg,2),
                    "RSI": round(rsi,1),
                    "年度位置%": round(w52["week52_pct"],0),
                    "vs大盤": f"{rs:+.1f}%" if rs is not None else "-",
                    "訊號分數": sc,
                    "訊號": " | ".join([s["msg"] for s in sigs]) if sigs else "無",
                })

            result_df = pd.DataFrame(rows).sort_values("訊號分數", ascending=False)
            filtered  = result_df[result_df["訊號分數"].abs() >= min_sc]
            st.success(f"掃描完成，{len(filtered)} 檔達標（共 {len(result_df)} 檔）")

            def hl(row):
                if row["訊號分數"] >= 2:  return ["background-color:#1a6b3a; color:#ffffff"]*len(row)
                if row["訊號分數"] <= -2: return ["background-color:#8b1a1a; color:#ffffff"]*len(row)
                return [""]*len(row)

            st.dataframe(filtered.style.apply(hl, axis=1), use_container_width=True, hide_index=True)

            if st.button("推播達標訊號到 LINE"):
                sent = 0
                for _, r in filtered.iterrows():
                    if r["訊號"] != "無":
                        sp = [{"type":"buy" if r["訊號分數"]>0 else "sell","msg":m} for m in r["訊號"].split(" | ")]
                        if send(build_signal_message(r["名稱"],r["代碼"],sp,r["現價"],r["漲跌%"])): sent+=1
                st.success(f"已推播 {sent} 則") if sent else st.warning("無訊號或推播失敗")

# ══════════════════════════════════════════════════
# Tab 3：個股分析
# ══════════════════════════════════════════════════
with tab3:
    st.header("📊 個股分析")

    col_sel, col_cmp = st.columns([2,2])
    with col_sel:
        selected_name = st.selectbox("主要股票", list(WATCHLIST.keys()), key="stock_select")
    with col_cmp:
        compare_names = st.multiselect("多股比較（可選 1-4 支）",
                                       [n for n in WATCHLIST.keys() if n != selected_name],
                                       max_selections=4, key="compare")

    ticker = WATCHLIST[selected_name]
    with st.spinner(f"載入 {selected_name}..."):
        df        = load_one(ticker, period)
        taiex_ind = load_taiex(period)

    if df.empty:
        st.error("無法取得資料"); st.stop()

    df       = add_indicators(df)
    signals  = detect_signals(df)
    sc       = score(signals)
    latest   = df.iloc[-1]; prev = df.iloc[-2]
    price    = float(latest["Close"])
    chg      = (price - float(prev["Close"])) / float(prev["Close"]) * 100
    rsi      = float(latest["RSI"]) if pd.notna(latest["RSI"]) else 50.0
    w52      = calc_week52(df)
    sr       = calc_support_resistance(df)
    rs       = relative_strength(df, taiex_ind) if not taiex_ind.empty else None
    holding  = st.session_state.holdings.get(selected_name)
    cost     = holding["cost"] if holding and holding.get("cost") else None
    pnl_pct  = ((price - cost) / cost * 100) if cost else None
    health   = health_light(sc, rsi, w52["week52_pct"])
    rec      = recommendation(sc, rsi, w52["week52_pct"], pnl_pct)

    col_h, col_r = st.columns(2)
    col_h.markdown(f"### 健康狀態：{health}")
    col_r.markdown(f"### 操作建議：{rec}")
    st.markdown("---")

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("收盤價",  f"{price:.2f}", f"{chg:+.2f}%")
    c2.metric("RSI",     f"{rsi:.1f}")
    c3.metric("K值",     f"{float(latest['K']):.1f}" if pd.notna(latest["K"]) else "-")
    c4.metric("年度位置", f"{w52['week52_pct']:.0f}%")
    c5.metric("vs 大盤", f"{rs:+.1f}%" if rs is not None else "-")
    c6.metric("訊號分數", sc, delta="看多" if sc>0 else ("看空" if sc<0 else "中性"))

    st.markdown(
        f"📌 近20日 支撐 `{sr['support_20']:.2f}` ／ 壓力 `{sr['resistance_20']:.2f}`　"
        f"｜　近60日 支撐 `{sr['support_60']:.2f}` ／ 壓力 `{sr['resistance_60']:.2f}`"
    )
    if cost:
        pa = "▲" if pnl_pct >= 0 else "▼"
        st.markdown(f"💰 持股成本 `{cost:.2f}` ／ 損益 `{pa}{abs(pnl_pct):.1f}%`")
    st.markdown("---")

    # 訊號
    if signals:
        st.subheader("訊號")
        for s in signals:
            c_ = "green" if s["type"]=="buy" else ("red" if s["type"]=="sell" else "orange")
            lbl= "買進"  if s["type"]=="buy" else ("賣出" if s["type"]=="sell" else "觀察")
            st.markdown(f":{c_}[**[{lbl}] {s['indicator']}**] — {s['msg']}")
        col_pb, col_log = st.columns(2)
        with col_pb:
            if st.button("推播此訊號到 LINE"):
                msg = build_signal_message(selected_name, ticker, signals, price, chg)
                st.success("已推播！") if send(msg) else st.error("推播失敗")
        with col_log:
            sig_type = "buy" if sc > 0 else "sell"
            if st.button("記錄此訊號到歷史"):
                save_signal(selected_name, ticker, sig_type, price, signals)
                st.success("已記錄")
    else:
        st.info("目前無明確訊號")

    # 三大法人
    st.markdown("---")
    st.subheader("🏦 三大法人（最新交易日）")
    if ".TW" in ticker or ".TWO" in ticker:
        with st.spinner("查詢法人資料..."):
            inst = load_institutional(ticker)
        if inst:
            ci1,ci2,ci3,ci4 = st.columns(4)
            def fmt(v): return f"{'▲' if v>0 else '▼'}{abs(v):,} 張" if v else "0"
            ci1.metric("外資買賣超", fmt(inst.get("foreign_net",0)))
            ci2.metric("投信買賣超", fmt(inst.get("trust_net",0)))
            ci3.metric("自營商買賣超", fmt(inst.get("dealer_net",0)))
            ci4.metric("三大法人合計", fmt(inst.get("total_net",0)))
            st.caption(f"資料日期：{inst.get('date','')}")
        else:
            st.info("無法取得法人資料（可能假日或美股）")
    else:
        st.info("三大法人資料僅支援台股")

    # 除權息
    st.markdown("---")
    st.subheader("💰 配息紀錄")
    divs = load_dividends(ticker)
    if not divs.empty:
        df_div = pd.DataFrame({"除息日": divs.index.astype(str).str[:10], "每股配息": divs.values})
        st.dataframe(df_div.sort_values("除息日", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("無配息資料")

    # 價格走勢圖
    st.markdown("---")
    df_plot = prep_plot(df)
    base    = alt.Chart(df_plot).encode(x=alt.X("Date:T", title="日期"))

    st.subheader("價格走勢")
    layers = [
        base.mark_line(color="#1f77b4",strokeWidth=2).encode(y=alt.Y("Close:Q",title="價格")),
        base.mark_line(color="orange", strokeDash=[4,2],strokeWidth=1).encode(y="MA5:Q"),
        base.mark_line(color="red",    strokeDash=[4,2],strokeWidth=1).encode(y="MA20:Q"),
        base.mark_line(color="gray",   strokeDash=[2,4],strokeWidth=1).encode(y="MA60:Q"),
        base.mark_line(color="#aaaaff",strokeDash=[2,2],strokeWidth=1).encode(y="BB_upper:Q"),
        base.mark_line(color="#aaaaff",strokeDash=[2,2],strokeWidth=1).encode(y="BB_lower:Q"),
        alt.Chart(pd.DataFrame({"y":[sr["support_20"]]})).mark_rule(color="green",strokeDash=[6,3],strokeWidth=1.5).encode(y="y:Q"),
        alt.Chart(pd.DataFrame({"y":[sr["resistance_20"]]})).mark_rule(color="red",strokeDash=[6,3],strokeWidth=1.5).encode(y="y:Q"),
    ]
    if cost:
        layers.append(
            alt.Chart(pd.DataFrame({"y":[cost]})).mark_rule(color="gold",strokeDash=[8,4],strokeWidth=2).encode(y="y:Q")
        )
    st.altair_chart(alt.layer(*layers).properties(height=350), use_container_width=True)
    legend = "🔵 收盤　🟠 MA5　🔴 MA20　⚫ MA60　🟣 布林　🟢 支撐　🔴 壓力"
    if cost: legend += "　🟡 成本線"
    st.caption(legend)

    # 多股比較
    if compare_names:
        st.markdown("---")
        st.subheader("📈 多股比較（標準化至 100）")
        norm_frames = []
        base_price = float(df["Close"].iloc[0])
        norm_main  = prep_plot(df)[["Date","Close"]].copy()
        norm_main["價格(標準化)"] = norm_main["Close"] / base_price * 100
        norm_main["股票"] = selected_name
        norm_frames.append(norm_main[["Date","價格(標準化)","股票"]])

        for cname in compare_names:
            cticker = WATCHLIST.get(cname)
            if not cticker: continue
            cdf = load_one(cticker, period)
            if cdf.empty: continue
            cp = prep_plot(cdf)[["Date","Close"]].copy()
            cp["價格(標準化)"] = cp["Close"] / float(cp["Close"].iloc[0]) * 100
            cp["股票"] = cname
            norm_frames.append(cp[["Date","價格(標準化)","股票"]])

        all_norm = pd.concat(norm_frames, ignore_index=True)
        cmp_chart = alt.Chart(all_norm).mark_line().encode(
            x=alt.X("Date:T", title="日期"),
            y=alt.Y("價格(標準化):Q", title="標準化價格（起始=100）"),
            color=alt.Color("股票:N"),
            tooltip=["Date:T","股票:N","價格(標準化):Q"]
        ).properties(height=300)
        st.altair_chart(cmp_chart, use_container_width=True)
        st.caption("所有股票起始點統一為 100，方便比較相對漲跌幅")

    # RSI & MACD
    st.subheader("成交量")
    vol = base.mark_bar(opacity=0.6).encode(
        y=alt.Y("Volume:Q",title="成交量"),
        color=alt.condition(alt.datum.Close>=alt.datum.MA5,alt.value("#2ecc71"),alt.value("#e74c3c"))
    ).properties(height=120)
    st.altair_chart(vol, use_container_width=True)

    st.subheader("RSI")
    rsi_c = base.mark_line(color="purple").encode(y=alt.Y("RSI:Q",scale=alt.Scale(domain=[0,100]))).properties(height=150)
    st.altair_chart(alt.layer(
        rsi_c,
        alt.Chart(pd.DataFrame({"y":[30]})).mark_rule(color="green",strokeDash=[4,2]).encode(y="y:Q"),
        alt.Chart(pd.DataFrame({"y":[70]})).mark_rule(color="red",  strokeDash=[4,2]).encode(y="y:Q"),
    ), use_container_width=True)

    st.subheader("MACD")
    macd_b = base.mark_bar().encode(
        y=alt.Y("MACD_diff:Q",title="MACD Histogram"),
        color=alt.condition(alt.datum.MACD_diff>0,alt.value("#2ecc71"),alt.value("#e74c3c"))
    ).properties(height=150)
    st.altair_chart(macd_b, use_container_width=True)

# ══════════════════════════════════════════════════
# Tab 4：卡位雷達
# ══════════════════════════════════════════════════
with tab4:
    st.header("🎯 卡位雷達")
    st.caption("偵測尚未觸發、但技術面正在醞釀的股票，提早卡位。")

    col_s, col_c = st.columns([3,1])
    with col_s: radar_sector = st.selectbox("篩選產業", list(SECTORS.keys()), key="radar_sector")
    with col_c: capital      = st.number_input("可用資金（元）", min_value=10000, max_value=10000000, value=300000, step=10000)

    def position_advice(ps, atr_pct, w52_pct, cap):
        if   ps >= 3: base, label = 0.12, "🔴 重倉"
        elif ps == 2: base, label = 0.07, "🟡 標準倉"
        else:         base, label = 0.03, "🟢 試水位"
        vol_f = max(0.5, 1.0 - max(0, atr_pct-1.5)*0.08)
        pos_f = max(0.5, 1.0 - max(0, w52_pct-50)/120)
        return {"label": label, "amount": int(cap*base*vol_f*pos_f // 1000) * 1000}

    if st.button("開始雷達掃描", type="primary"):
        with st.spinner("掃描預警訊號中..."):
            radar_data = load_all(period, radar_sector)
            rows = []
            for name, df in radar_data.items():
                df   = add_indicators(df)
                pre  = detect_pre_signals(df)
                ps   = pre_score(pre)
                if ps == 0: continue
                lat  = df.iloc[-1]; prv = df.iloc[-2]
                price= float(lat["Close"])
                chg  = (price-float(prv["Close"]))/float(prv["Close"])*100
                rsi  = float(lat["RSI"]) if pd.notna(lat["RSI"]) else 50.0
                atr  = float(lat["ATR_pct"]) if pd.notna(lat["ATR_pct"]) else 2.0
                w52  = calc_week52(df)
                pos  = position_advice(ps, atr, w52["week52_pct"], capital)
                rows.append({
                    "名稱": name, "代碼": WATCHLIST[name],
                    "現價": round(price,2), "漲跌%": round(chg,2),
                    "RSI": round(rsi,1), "年度位置%": round(w52["week52_pct"],0),
                    "波動%/日": round(atr,1), "預警分數": ps,
                    "建議倉位": pos["label"], "建議金額": f"${pos['amount']:,}",
                    "預警訊號": " ／ ".join([s["msg"] for s in pre]),
                })
            if not rows:
                st.info("目前無預警股票")
            else:
                result = pd.DataFrame(rows).sort_values("預警分數", ascending=False)
                st.success(f"找到 {len(result)} 檔預警股票")

                def rc(row):
                    ps = row["預警分數"]
                    if ps >= 3: return ["background-color:#1a6b3a; color:#ffffff"]*len(row)
                    if ps == 2: return ["background-color:#7a5a00; color:#ffffff"]*len(row)
                    return [""]*len(row)

                st.dataframe(result.style.apply(rc, axis=1), use_container_width=True, hide_index=True)
                st.markdown("---")
                c1,c2,c3 = st.columns(3)
                c1.markdown("🟢 **試水位**\n預警分數 1，先小量卡位觀察")
                c2.markdown("🟡 **標準倉**\n預警分數 2，正常布局")
                c3.markdown("🔴 **重倉**\n預警分數 3+，多指標同步醞釀")
                st.caption("建議金額依波動率與年度位置自動折扣，不構成投資建議，請自行判斷風險。")

# ══════════════════════════════════════════════════
# Tab 5：訊號歷史
# ══════════════════════════════════════════════════
with tab5:
    st.header("📜 訊號歷史")
    st.caption("記錄過去發出的買賣訊號及後續報酬（訊號發出 10 日後結算勝負）。")

    with st.spinner("更新歷史績效..."):
        hist_data = load_all(period, "全部")
        log       = update_and_load(dict(hist_data))

    if not log:
        st.info("尚無訊號記錄。在「個股分析」頁面點「記錄此訊號到歷史」開始累積。")
    else:
        wr = win_rate(log)
        c1,c2,c3 = st.columns(3)
        c1.metric("總記錄筆數", len(log))
        c2.metric("已結算筆數", wr["total"])
        c3.metric("勝率", f"{wr['rate']}%" if wr["total"] > 0 else "-")

        st.markdown("---")
        df_log = pd.DataFrame([{
            "日期":      e["date"],
            "股票":      e["name"],
            "方向":      "買進" if e["type"]=="buy" else "賣出",
            "訊號時價格": e["price_at_signal"],
            "現價":      e.get("price_now", "-"),
            "報酬%":     e.get("return_pct", "-"),
            "結果":      e.get("result") or "待結算",
            "訊號":      "、".join(e.get("signals", [])),
        } for e in reversed(log)])

        def log_color(row):
            r = row.get("結果","")
            if "勝" in str(r): return ["background-color:#1a6b3a; color:#ffffff"]*len(row)
            if "敗" in str(r): return ["background-color:#8b1a1a; color:#ffffff"]*len(row)
            return [""]*len(row)

        st.dataframe(df_log.style.apply(log_color, axis=1), use_container_width=True, hide_index=True)

        if st.button("清除所有歷史"):
            import os
            from signal_log import LOG_FILE
            try:
                os.remove(LOG_FILE)
                st.success("已清除")
                st.rerun()
            except Exception:
                st.error("清除失敗")
