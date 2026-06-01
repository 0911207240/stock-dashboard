import streamlit as st
import pandas as pd
import altair as alt
import plotly.graph_objects as go
import plotly.express as px
from data_fetcher import fetch, fetch_all, fetch_taiex, fetch_dividends, fetch_institutional, fetch_margin_data, WATCHLIST, SECTORS
from daytrade_scorer import get_daytrade_candidates, is_tw_stock
from scoring_config import load_multipliers, save_multipliers, reset_multipliers
from push_cooldown import get_status as cooldown_status, clear_cooldown
from analyzer import add_indicators, detect_signals, score, calc_support_resistance, calc_week52, detect_pre_signals, pre_score
from line_notifier import send, build_signal_message, build_daytrade_message
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

@st.cache_data(ttl=3600)
def load_margin(ticker):
    return fetch_margin_data(ticker)

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

def plot_candlestick(df, sr, cost=None, name=""):
    d = df.reset_index()
    d = d.rename(columns={d.columns[0]: "Date"})
    for col in ["Open","High","Low","Close","MA5","MA20","MA60","BB_upper","BB_lower"]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=d["Date"], open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        name="K棒",
        increasing_line_color="#e74c3c", decreasing_line_color="#2ecc71",
    ))
    for col_, color_, dash_, w_ in [
        ("MA5","#f39c12","dash",1.2), ("MA20","#e74c3c","dash",1.2),
        ("MA60","#aaaaaa","dot",1), ("BB_upper","#7f8ff4","dot",1), ("BB_lower","#7f8ff4","dot",1),
    ]:
        if col_ in d.columns:
            fig.add_trace(go.Scatter(x=d["Date"], y=d[col_], name=col_,
                                     line=dict(color=color_, width=w_, dash=dash_), opacity=0.8))
    fig.add_hline(y=sr["support_20"],    line_dash="dash", line_color="#2ecc71", line_width=1.5,
                  annotation_text=f"支撐 {sr['support_20']:.2f}", annotation_font_color="#2ecc71")
    fig.add_hline(y=sr["resistance_20"], line_dash="dash", line_color="#e74c3c", line_width=1.5,
                  annotation_text=f"壓力 {sr['resistance_20']:.2f}", annotation_font_color="#e74c3c")
    if cost:
        fig.add_hline(y=cost, line_dash="dot", line_color="#f1c40f", line_width=2,
                      annotation_text=f"成本 {cost:.2f}", annotation_font_color="#f1c40f")
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=420, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(title="日期"), yaxis=dict(title="價格"),
    )
    return fig


def plot_treemap(summary):
    data = [{"名稱": n, "市值": d["value"],
             "漲跌%": round(d["change_pct"], 2),
             "label": f"{n}\n{d['change_pct']:+.1f}%"}
            for n, d in summary.items() if d["value"] > 0]
    df_tm = pd.DataFrame(data)
    fig = px.treemap(df_tm, path=["名稱"], values="市值", color="漲跌%",
                     color_continuous_scale=["#8b0000","#1a1a2e","#006400"],
                     color_continuous_midpoint=0,
                     custom_data=["漲跌%","市值"])
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{customdata[0]:+.1f}%<br>$%{customdata[1]:,.0f}",
        textfont=dict(size=13), marker_line_width=2,
    )
    fig.update_layout(height=380, template="plotly_dark",
                      coloraxis_colorbar=dict(title="漲跌%"),
                      margin=dict(l=0, r=0, t=10, b=0))
    return fig


def plot_gauge(value, title, low=30, high=70, minv=0, maxv=100):
    if value is None: value = 50
    if   value <= low:  bar_color = "#2ecc71"
    elif value >= high: bar_color = "#e74c3c"
    else:               bar_color = "#f39c12"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={"text": title, "font": {"size": 15, "color": "white"}},
        number={"font": {"size": 28, "color": bar_color}},
        gauge={
            "axis": {"range": [minv, maxv], "tickcolor": "white",
                     "tickfont": {"color": "white", "size": 10}},
            "bar":  {"color": bar_color, "thickness": 0.25},
            "bgcolor": "#1a1a2e",
            "bordercolor": "#444",
            "steps": [
                {"range": [minv, low],  "color": "#1a3a2a"},
                {"range": [low, high],  "color": "#1a1a2e"},
                {"range": [high, maxv], "color": "#3a1a1a"},
            ],
            "threshold": {"line": {"color": "white", "width": 3},
                          "thickness": 0.75, "value": value},
        }
    ))
    fig.update_layout(height=200, template="plotly_dark",
                      margin=dict(l=20, r=20, t=50, b=10),
                      paper_bgcolor="#0e1117", plot_bgcolor="#0e1117")
    return fig


def row_color(row, col="漲跌%"):
    try:
        v = float(row[col])
        if v > 0: return ["background-color:#1a6b3a; color:#ffffff"] * len(row)
        if v < 0: return ["background-color:#8b1a1a; color:#ffffff"] * len(row)
    except Exception:
        pass
    return [""] * len(row)

# ── Tabs ──────────────────────────────────────────
tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🌐 大盤展望", "💼 持股管理", "🔍 市場掃描", "📊 個股分析", "🎯 卡位雷達", "📜 訊號歷史", "⚡ 隔日當沖"
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

    # 持股熱力地圖
    st.subheader("持股熱力地圖（大小=市值　顏色=漲跌幅）")
    st.plotly_chart(plot_treemap(summary), use_container_width=True)

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

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("收盤價",   f"{price:.2f}", f"{chg:+.2f}%")
    c2.metric("年度位置", f"{w52['week52_pct']:.0f}%")
    c3.metric("vs 大盤",  f"{rs:+.1f}%" if rs is not None else "-")
    c4.metric("訊號分數", sc, delta="看多" if sc>0 else ("看空" if sc<0 else "中性"))
    c5.metric("ATR波動",  f"{float(latest['ATR_pct']):.1f}%/日" if pd.notna(latest.get('ATR_pct')) else "-")

    # RSI / KD 儀表板
    g1, g2, g3 = st.columns(3)
    with g1:
        k_val = float(latest["K"]) if pd.notna(latest["K"]) else None
        st.plotly_chart(plot_gauge(rsi, "RSI"), use_container_width=True)
    with g2:
        st.plotly_chart(plot_gauge(k_val, "K 值"), use_container_width=True)
    with g3:
        d_val = float(latest["D"]) if pd.notna(latest["D"]) else None
        st.plotly_chart(plot_gauge(d_val, "D 值"), use_container_width=True)

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

    # 蠟燭圖
    st.markdown("---")
    st.subheader("K 棒走勢圖")
    st.plotly_chart(plot_candlestick(df, sr, cost, selected_name), use_container_width=True)
    st.caption("🔴 紅K=收漲　🟢 綠K=收跌（台灣慣例）　🟡 成本線　🟢 支撐　🔴 壓力")

    df_plot = prep_plot(df)
    base    = alt.Chart(df_plot).encode(x=alt.X("Date:T", title="日期"))

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

# ══════════════════════════════════════════════════
# Tab 6：隔日當沖
# ══════════════════════════════════════════════════
with tab6:
    st.header("⚡ 隔日當沖選股")
    st.caption("每日收盤後根據量能、籌碼、技術、波動度四維度評分，篩出明天最值得盯的台股。")

    col_s, col_n = st.columns([3, 1])
    with col_s:
        dt_sector = st.selectbox("篩選產業", list(SECTORS.keys()), key="dt_sector")
    with col_n:
        dt_top_n = st.number_input("顯示前N名", min_value=5, max_value=30, value=10, step=5, key="dt_top_n")

    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        use_inst = st.checkbox("載入三大法人資料（更準確，較慢）", value=False, key="dt_use_inst")
    with col_opt2:
        use_margin = st.checkbox("載入融資融券資料（較慢）", value=False, key="dt_use_margin")

    st.markdown("**評分說明**：量能(30) ＋ 籌碼(30) ＋ 技術(20) ＋ 波動度(20) ＝ 滿分 100")
    st.markdown("🟢 60+ 強烈關注　🟡 40-59 候補觀察　─ <40 一般")

    if st.button("🔍 開始評分", type="primary", key="dt_scan"):
        with st.spinner("載入行情資料..."):
            dt_data = load_all(period, dt_sector)

        inst_cache = {}
        if use_inst:
            tw_names = [n for n in dt_data if is_tw_stock(WATCHLIST.get(n, ""))]
            prog = st.progress(0, text="載入法人資料...")
            for idx, name in enumerate(tw_names):
                ticker = WATCHLIST[name]
                inst = load_institutional(ticker)
                if inst:
                    inst_cache[name] = inst
                prog.progress((idx + 1) / max(len(tw_names), 1), text=f"法人資料 {idx+1}/{len(tw_names)}")
            prog.empty()

        margin_cache = {}
        if use_margin:
            tw_names = [n for n in dt_data if is_tw_stock(WATCHLIST.get(n, ""))]
            prog2 = st.progress(0, text="載入融資融券資料...")
            for idx, name in enumerate(tw_names):
                ticker = WATCHLIST[name]
                mg = load_margin(ticker)
                if mg:
                    margin_cache[name] = mg
                prog2.progress((idx + 1) / max(len(tw_names), 1), text=f"融資融券 {idx+1}/{len(tw_names)}")
            prog2.empty()

        with st.spinner("評分中..."):
            candidates = get_daytrade_candidates(
                dt_data, WATCHLIST,
                inst_cache=inst_cache if use_inst else None,
                margin_cache=margin_cache if use_margin else None,
                top_n=int(dt_top_n),
            )

        if not candidates:
            st.info("無符合條件的當沖候選股（台股且成交量 > 500 張）")
        else:
            st.success(f"找到 {len(candidates)} 檔候選股")

            rows = []
            for c in candidates:
                arrow = "▲" if c["change_pct"] >= 0 else "▼"
                rows.append({
                    "名稱":      c["name"],
                    "代碼":      c["ticker"],
                    "當沖分數":  c["score"],
                    "昨收":      round(c["price"], 2),
                    "昨漲跌%":   f"{arrow}{abs(c['change_pct']):.1f}%",
                    "📍進場參考":  c["entry"],
                    "🎯目標出場":  c["target"],
                    "🛑停損":     c["stop"],
                    "風報比":    f"{c['rr_ratio']}:1",
                    "獲利空間%": f"+{c['upside_pct']:.1f}%",
                    "量比":      f"{c['vol_ratio']:.1f}x",
                    "ATR%":     round(c["atr_pct"], 1),
                    "量能":      c["vol_score"],
                    "籌碼":      c["chip_score"],
                    "技術":      c["tech_score"],
                    "波動度":    c["atr_score"],
                    "關鍵訊號":  "、".join(c["signals"][:3]),
                })

            df_dt = pd.DataFrame(rows)

            def dt_color(row):
                sc = row["當沖分數"]
                if sc >= 60: return ["background-color:#1a6b3a; color:#ffffff"] * len(row)
                if sc >= 40: return ["background-color:#7a5a00; color:#ffffff"] * len(row)
                return [""] * len(row)

            st.dataframe(df_dt.style.apply(dt_color, axis=1), use_container_width=True, hide_index=True)

            # 推播
            st.markdown("---")
            if st.button("📲 推播 Top5 到 LINE", key="dt_push"):
                msg = build_daytrade_message(candidates[:5], __import__("datetime").datetime.now().strftime("%m/%d"))
                st.success("已推播！") if send(msg) else st.error("推播失敗，請確認 LINE Token")

            # 分數結構圖（前三名）
            if len(candidates) >= 1:
                st.markdown("---")
                st.subheader("Top 3 評分結構")
                top3 = candidates[:3]
                cols_pie = st.columns(len(top3))
                for c, col in zip(top3, cols_pie):
                    with col:
                        st.markdown(f"**{c['name']}**　總分 **{c['score']}**")
                        bd_vals = {
                            "量能":   max(0, c["vol_score"]),
                            "籌碼":   max(0, c["chip_score"]),
                            "技術":   max(0, c["tech_score"]),
                            "波動度": max(0, c["atr_score"]),
                        }
                        if sum(bd_vals.values()) > 0:
                            fig_pie = px.pie(
                                values=list(bd_vals.values()),
                                names=list(bd_vals.keys()),
                                color_discrete_sequence=["#3498db", "#2ecc71", "#e74c3c", "#f39c12"],
                            )
                            fig_pie.update_layout(
                                height=220, template="plotly_dark",
                                margin=dict(l=10, r=10, t=10, b=10),
                                showlegend=True,
                            )
                            st.plotly_chart(fig_pie, use_container_width=True)

    # ── 回測驗證區塊 ──────────────────────────────────
    st.markdown("---")
    st.subheader("📈 歷史回測驗證")
    st.caption("以過去 N 日每日 EOD 評分 → 隔天開盤進場 → 目標/停損/收盤結算，驗證評分模型實際勝率。")

    with st.expander("⚙️ 回測設定 & 執行", expanded=False):
        col_bt1, col_bt2, col_bt3 = st.columns(3)
        with col_bt1:
            bt_sector   = st.selectbox("回測產業", list(SECTORS.keys()), key="bt_sector")
        with col_bt2:
            bt_min_sc   = st.slider("最低觸發分數", 30, 70, 40, 5, key="bt_min_sc")
        with col_bt3:
            bt_lookback = st.selectbox("回測天數", [60, 90, 120, 180], index=1, key="bt_lookback")

        if st.button("▶ 開始回測", type="primary", key="bt_run"):
            from backtest import run_portfolio_backtest, aggregate_stats
            with st.spinner("回測中，請稍候（資料量越大越慢）..."):
                bt_data    = load_all(period, bt_sector)
                bt_results = run_portfolio_backtest(
                    bt_data, WATCHLIST,
                    min_score=bt_min_sc,
                    lookback_days=bt_lookback,
                )

            if not bt_results:
                st.info("無足夠交易次數的回測結果（每檔至少需 3 筆訊號）")
            else:
                agg = aggregate_stats(bt_results)
                st.markdown("#### 彙整統計")
                ca, cb, cc, cd, ce = st.columns(5)
                ca.metric("回測檔數",   agg["tested_stocks"])
                cb.metric("總交易次數", agg["total_trades"])
                cc.metric("整體勝率",   f"{agg['overall_win_rate']}%",
                          delta="良好" if agg["overall_win_rate"] >= 55 else "需改善")
                cd.metric("整體獲利因子", agg["overall_pf"],
                          delta="穩定" if agg["overall_pf"] >= 1.5 else "偏低")
                ce.metric("平均獲利 / 虧損",
                          f"+{agg['overall_avg_win']:.1f}% / {agg['overall_avg_loss']:.1f}%")

                st.markdown("#### 各股明細（按獲利因子排序）")
                bt_rows = []
                for r in bt_results:
                    s = r["stats"]
                    bt_rows.append({
                        "名稱":        r["name"],
                        "交易次數":    s["total_trades"],
                        "勝率%":       s["win_rate"],
                        "均獲利%":     s["avg_win_pct"],
                        "均虧損%":     s["avg_loss_pct"],
                        "獲利因子":    s["profit_factor"],
                        "總報酬%":     s["total_return_pct"],
                        "Sharpe":      s["sharpe"],
                        "最大回撤%":   s["max_drawdown_pct"],
                        "最大連敗":    s["max_consecutive_losses"],
                    })
                df_bt = pd.DataFrame(bt_rows)

                def bt_color(row):
                    pf = row["獲利因子"]
                    if pf >= 2.0: return ["background-color:#1a6b3a; color:#fff"] * len(row)
                    if pf >= 1.5: return ["background-color:#7a5a00; color:#fff"] * len(row)
                    if pf < 1.0:  return ["background-color:#5a1a1a; color:#fff"] * len(row)
                    return [""] * len(row)

                st.dataframe(df_bt.style.apply(bt_color, axis=1),
                             use_container_width=True, hide_index=True)

                # 維度相關性 & 建議權重（Fix 8）
                st.markdown("---")
                st.markdown("#### 📐 評分維度相關性分析")
                from backtest import calc_dimension_correlation, suggest_multipliers
                corrs = calc_dimension_correlation(bt_results)
                if corrs:
                    corr_df = pd.DataFrame([
                        {"維度": k, "與報酬相關係數": v,
                         "解讀": "正向有效" if v > 0.05 else ("負向" if v < 0 else "關聯弱")}
                        for k, v in corrs.items()
                    ])
                    st.dataframe(corr_df, use_container_width=True, hide_index=True)
                    suggested = suggest_multipliers(corrs)
                    st.markdown("**建議倍率調整**：" +
                                "　".join(f"{k} → {v}x" for k, v in suggested.items()))
                    if st.button("✨ 套用建議權重", key="apply_weights"):
                        save_multipliers(suggested)
                        st.success("已套用！重新跑評分即可生效。")
                else:
                    st.info("交易次數不足，無法計算相關係數")

                # 最佳股票的逐筆明細
                st.markdown("---")
                best = bt_results[0]
                st.markdown(f"#### 最佳股票：{best['name']} — 逐筆交易紀錄")
                df_detail = pd.DataFrame(best["trades"])
                def detail_color(row):
                    return (["background-color:#1a6b3a; color:#fff"] * len(row)
                            if row["outcome"] == "win"
                            else ["background-color:#5a1a1a; color:#fff"] * len(row))
                st.dataframe(df_detail.style.apply(detail_color, axis=1),
                             use_container_width=True, hide_index=True)

    st.markdown("---")
    st.caption("⚠️ 本工具所有訊號僅供學習與參考，不構成任何投資建議。當沖有極高風險，請自行評估承受能力。")
