"""定期定額追蹤：持股／每月加碼 → 月配目標差距、達標年月、未來 12 個月除息月曆

每股配息與除息月份取自 yfinance 近 12 個月實際配息紀錄，不手填、不預測成長。
持股資料存 dca_state.json（個人資料，已列入 .gitignore）。
"""
import json
import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from etf_facts import NONDIV_ASOF, nondiv, nondiv_label

STATE_FILE = os.path.join(os.path.dirname(__file__), "dca_state.json")
MAX_MONTHS = 600  # 試算上限 50 年

DEFAULT_HOLDINGS = [
    {"代號": "0056", "持有股數": 0, "平均成本": 0.0, "每月加碼股數": 0},
    {"代號": "00929", "持有股數": 0, "平均成本": 0.0, "每月加碼股數": 0},
    {"代號": "00878", "持有股數": 0, "平均成本": 0.0, "每月加碼股數": 0},
    {"代號": "00919", "持有股數": 0, "平均成本": 0.0, "每月加碼股數": 0},
]


def _load() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"儲存失敗：{e}")


@st.cache_data(ttl=3600, show_spinner=False)
def _etf_info(code: str) -> dict | None:
    """回傳 {price, payouts: [(月份, 每股配息)]}（近 12 個月）；查不到回 None"""
    for suffix in (".TW", ".TWO"):
        try:
            t = yf.Ticker(code + suffix)
            px = t.history(period="5d", auto_adjust=False)["Close"].dropna()
            if px.empty:
                continue
            divs = t.dividends
            since = datetime.now() - timedelta(days=365)
            payouts = []
            for ts, amt in divs.items():
                if ts.tz_localize(None) >= since and amt > 0:
                    payouts.append((ts.month, float(amt)))
            return {"price": float(px.iloc[-1]), "payouts": payouts}
        except Exception:
            continue
    return None


def _clean(df: pd.DataFrame) -> list[dict]:
    rows = []
    for r in df.to_dict("records"):
        code = str(r.get("代號") or "").strip().upper()
        if not code:
            continue
        rows.append({
            "代號": code,
            "持有股數": int(r.get("持有股數") or 0),
            "平均成本": float(r.get("平均成本") or 0),
            "每月加碼股數": int(r.get("每月加碼股數") or 0),
        })
    return rows


def _project(holdings, infos, goal, reinvest):
    """逐月推演。回傳 (達標第幾個月或 None, 每月序列[月平均配息])。
    假設：價格與每股配息維持近 12 個月水準不變。"""
    sh = {h["代號"]: float(h["持有股數"]) for h in holdings}
    series = []
    now_m = datetime.now().month
    for m in range(1, MAX_MONTHS + 1):
        cal_m = (now_m + m - 1) % 12 + 1
        for h in holdings:
            c = h["代號"]
            sh[c] += h["每月加碼股數"]
            info = infos.get(c)
            if reinvest and info:
                cash = sum(a for pm, a in info["payouts"] if pm == cal_m) * sh[c]
                sh[c] += cash / info["price"]
        monthly_avg = sum(
            sh[h["代號"]] * sum(a for _, a in infos[h["代號"]]["payouts"]) / 12
            for h in holdings if infos.get(h["代號"])
        )
        series.append(monthly_avg)
        if monthly_avg >= goal:
            return m, series
    return None, series


def render():
    st.subheader("定期定額追蹤")
    st.caption("只要填股數與每月加碼；每股配息、除息月份、股價自動取自 yfinance 近 12 個月實際紀錄。"
               "推演假設股價與配息不變，實際會浮動，僅作方向參考。")

    state = _load()
    c1, c2 = st.columns(2)
    goal = c1.number_input("月領目標（元）", value=int(state.get("goal", 15000)), step=500, min_value=0, key="dca_goal")
    reinvest = c2.checkbox("配息再投入", value=bool(state.get("reinvest", False)), key="dca_reinvest")

    base = pd.DataFrame(state.get("holdings") or DEFAULT_HOLDINGS)
    edited = st.data_editor(
        base, num_rows="dynamic", use_container_width=True, hide_index=True, key="dca_editor",
        column_config={
            "代號": st.column_config.TextColumn(help="台股代號，例如 0056"),
            "持有股數": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
            "平均成本": st.column_config.NumberColumn(min_value=0.0, step=0.01, format="%.2f", help="選填，用來算帳面損益"),
            "每月加碼股數": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
        },
    )
    if st.button("💾 儲存持股", key="dca_save"):
        _save({"goal": goal, "reinvest": reinvest, "holdings": _clean(edited)})
        st.success("已儲存（僅存本機 dca_state.json）")

    holdings = _clean(edited)
    if not any(h["持有股數"] > 0 or h["每月加碼股數"] > 0 for h in holdings):
        st.info("請先在上表填入各檔持有股數（可從國泰庫存畫面抄），按「儲存持股」。")
        return

    infos = {h["代號"]: _etf_info(h["代號"]) for h in holdings}
    missing = [c for c, v in infos.items() if v is None]
    if missing:
        st.warning(f"查不到報價：{', '.join(missing)}（已略過，不計入推演）")
    no_div = [c for c, v in infos.items() if v and not v["payouts"]]
    if no_div:
        st.warning(f"近 12 個月沒有配息紀錄：{', '.join(no_div)}（可能剛上市或資料缺漏，不計入配息）")

    # ── 現況 ──
    cost = mv = annual = nd_annual = 0.0
    rows = []
    for h in holdings:
        info = infos.get(h["代號"])
        if not info:
            continue
        per_year = sum(a for _, a in info["payouts"])
        c_ = h["持有股數"] * h["平均成本"]
        v_ = h["持有股數"] * info["price"]
        cost += c_
        mv += v_
        annual += h["持有股數"] * per_year
        nd_annual += h["持有股數"] * per_year * nondiv(h["代號"])
        rows.append({
            "代號": h["代號"], "股價": f"{info['price']:.2f}", "持有股數": h["持有股數"],
            "市值": f"${v_:,.0f}", "近12月每股配息": f"{per_year:.2f}",
            "年配息": f"${h['持有股數'] * per_year:,.0f}",
            "非股利占比": nondiv_label(h["代號"]),
            "除息月": "、".join(str(m) for m in sorted({m for m, _ in info["payouts"]})) or "—",
        })
    monthly_now = annual / 12
    gap = max(goal - monthly_now, 0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("目前月均配息", f"${monthly_now:,.0f}", f"達成 {monthly_now / goal * 100:.1f}%" if goal else None)
    m2.metric("距離目標", "已達成" if gap == 0 else f"${gap:,.0f}")
    m3.metric("持股市值", f"${mv:,.0f}")
    if cost > 0:
        m4.metric("帳面損益", f"${mv - cost:,.0f}", f"{(mv - cost) / cost * 100:+.1f}%", delta_color="inverse")
    else:
        m4.metric("帳面損益", "—", "未填平均成本")
    st.progress(min(monthly_now / goal, 1.0) if goal else 0.0)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    if annual > 0:
        st.caption(f"組合的配息中約 {nd_annual / annual * 100:.0f}% 不是股利（多為資本利得），市場回落時這部分最容易縮水。"
                   f"各檔占比為近 12 個月加權的上限估計（{NONDIV_ASOF} 查證，「約 50%」為未查證的預設值）。")

    # ── 達標推演 ──
    st.markdown("##### 預估達標")
    months, series = _project([h for h in holdings if infos.get(h["代號"])], infos, goal, reinvest)
    no_add = not any(h["每月加碼股數"] > 0 for h in holdings)
    if monthly_now >= goal:
        st.success("目前月均配息已達目標。")
    elif no_add and not reinvest and annual > 0 and mv > 0:
        port_yield = annual / mv
        need = goal * 12 / port_yield
        n1, n2, n3 = st.columns(3)
        n1.metric("組合殖利率（近 12 月）", f"{port_yield * 100:.2f}%")
        n2.metric(f"月領 ${goal:,.0f} 所需市值", f"${need:,.0f}")
        n3.metric("還差", f"${max(need - mv, 0):,.0f}")
        st.info("目前沒有每月加碼，也沒有勾選配息再投入，所以不會有「達標年月」。上面是以現有殖利率反推的所需本金；"
                "只調整配置、不加新資金，無法填補這個差距。若之後每月加碼，在上表填入股數即可推演。")
        series = None
    elif months is None:
        st.warning(f"依目前每月加碼，50 年內無法達到月領 ${goal:,.0f}。可提高加碼股數或目標。")
    else:
        n = datetime.now()
        t_idx = n.year * 12 + n.month - 1 + months
        st.success(f"依目前加碼速度，約 **{months // 12} 年 {months % 12} 個月後**（{t_idx // 12} 年 {t_idx % 12 + 1} 月前後）達到月領 ${goal:,.0f}。"
                   f"{'已含配息再投入。' if reinvest else '未含配息再投入。'}")
    if series:
        show = min(len(series), (months or 120) + 12)
        fig = go.Figure(go.Scatter(x=list(range(1, show + 1)), y=[round(v) for v in series[:show]],
                                   mode="lines", name="月均配息", line=dict(color="#1D9E75", width=2)))
        fig.add_hline(y=goal, line_dash="dash", line_color="#BA7517", annotation_text=f"目標 ${goal:,.0f}")
        fig.update_layout(template="plotly_dark", height=260, margin=dict(l=10, r=10, t=30, b=10),
                          xaxis_title="第幾個月", yaxis_title="月均配息（元）")
        st.plotly_chart(fig, use_container_width=True)

    # ── 未來 12 個月除息月曆 ──
    st.markdown("##### 未來 12 個月除息月曆")
    st.caption("以近 12 個月的除息月份與金額套用到未來；含每月加碼後的股數。實際入帳日約在除息後 3~4 週，且金額會變動。")
    sh = {h["代號"]: float(h["持有股數"]) for h in holdings}
    now_m = datetime.now()
    cal_rows, cal_totals = [], []
    for i in range(1, 13):
        y = now_m.year + (now_m.month + i - 1) // 12
        mo = (now_m.month + i - 1) % 12 + 1
        parts, total = [], 0.0
        for h in holdings:
            c = h["代號"]
            sh[c] += h["每月加碼股數"]
            info = infos.get(c)
            if not info:
                continue
            amt = sum(a for pm, a in info["payouts"] if pm == mo)
            if amt > 0 and sh[c] > 0:
                cash = amt * sh[c]
                total += cash
                parts.append(f"{c} ${cash:,.0f}")
        cal_totals.append(total)
        cal_rows.append({"月份": f"{y}-{mo:02d}", "預估除息金額": f"${total:,.0f}" if total else "—", "明細": "、".join(parts) or "—"})
    st.dataframe(pd.DataFrame(cal_rows), use_container_width=True, hide_index=True)
