"""市場匯率分頁：匯率（讀 fx_daily.json）＋台灣／亞洲／國際三大市場報價（yfinance）"""
import json
import os

import pandas as pd
import streamlit as st
from market_snapshot import MARKETS, fetch_quote

FX_FILE = os.path.join(os.path.dirname(__file__), "fx_daily.json")

@st.cache_data(ttl=900, show_spinner=False)
def _quote(ticker: str):
    return fetch_quote(ticker)


def _render_fx():
    st.subheader("💱 匯率（對台幣）")
    try:
        with open(FX_FILE, "r", encoding="utf-8") as f:
            fx = json.load(f)
    except Exception:
        st.info("尚無匯率資料，請先 git pull（fx_daily.json 由 GitHub Actions 每日更新）。")
        return

    names = {"USD": "美元", "JPY": "日圓", "KRW": "韓元"}
    cols = st.columns(3)
    for col, (code, r) in zip(cols, fx["rates"].items()):
        digits = 3 if code == "USD" else 5
        # dev_pct 正值 = 比 1 年均值便宜；台灣慣例紅漲綠跌，此處「便宜」用綠色
        col.metric(
            f"{names.get(code, code)} {code}",
            f"{r['now']:.{digits}f}",
            f"{r['dev_pct']:+.2f}% 相對 1 年均值",
            delta_color="normal",
        )
        col.caption(f"1 年均值 {r['avg_1y']:.{digits}f}｜{r['signal'] or '在均值附近'}")
    st.caption(f"報價日 {fx['data_date']}（週末沿用週五）｜單位：{fx['unit']}｜正值代表比均值便宜")


def _render_group(title: str, items):
    st.subheader(title)
    rows = []
    for name, ticker, digits in items:
        q = _quote(ticker)
        if q is None:
            rows.append({"項目": name, "最新": "—", "漲跌": "—", "漲跌幅": "—", "日期": "—"})
            continue
        last, prev, day = q
        chg = last - prev
        rows.append({
            "項目": name,
            "最新": f"{last:,.{digits}f}",
            "漲跌": f"{chg:+,.{digits}f}",
            "漲跌幅": f"{chg / prev * 100:+.2f}%",
            "日期": day,
        })
    df = pd.DataFrame(rows)

    def _color(v):
        # 台灣慣例：紅漲綠跌
        if isinstance(v, str) and v.startswith("+"):
            return "color: #e5484d"
        if isinstance(v, str) and v.startswith("-"):
            return "color: #30a46c"
        return ""

    st.dataframe(df.style.map(_color, subset=["漲跌", "漲跌幅"]),
                 use_container_width=True, hide_index=True)


def render():
    st.header("🌏 市場與匯率")
    st.caption("資料來源：yfinance（延遲報價，快取 15 分鐘）；抓不到的項目顯示「—」，不補值。")
    _render_fx()
    st.markdown("---")
    for title, items in MARKETS.items():
        _render_group(title, items)
    st.caption("台灣慣例：紅色上漲、綠色下跌。亞洲與美國市場的資料日可能與台灣不同天，請看「日期」欄。")
