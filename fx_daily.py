"""每日匯率：USD/JPY/KRW 對台幣的今日值與 1 年均值，寫入 fx_daily.json 供雲端 routine 讀取

雲端 routine 環境擋金融 API，改由 GitHub Actions 抓 yfinance 後存進 repo。
偏離 dev：正值 = 今日比均值便宜，負值 = 比均值貴。
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

OUT_FILE = Path(__file__).parent / "fx_daily.json"
SIGNAL_PCT = 2.0

_SIGNALS = {
    "USD": ("美元相對便宜，換匯或買美股時機", "美元偏貴，換匯可稍候"),
    "JPY": ("日圓相對便宜，AUNO 日本進貨時機", "日圓偏貴，進貨可稍候"),
    "KRW": ("韓元相對便宜，韓國商品進貨時機", "韓元偏貴，可稍候"),
}


def _close(ticker: str, start: datetime, end: datetime):
    s = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)["Close"]
    if hasattr(s, "columns"):   # 新版 yfinance 單檔也回 DataFrame
        s = s.iloc[:, 0]
    return s.dropna()


def build() -> dict:
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    end = now.replace(tzinfo=None) + timedelta(days=1)
    start = end - timedelta(days=366)

    twd = _close("TWD=X", start, end)   # 1 USD = ? TWD
    jpy = _close("JPY=X", start, end)   # 1 USD = ? JPY
    krw = _close("KRW=X", start, end)   # 1 USD = ? KRW
    idx = twd.index.intersection(jpy.index).intersection(krw.index)
    if len(idx) < 200:
        raise RuntimeError(f"匯率資料不足：只有 {len(idx)} 個共同交易日")
    twd, jpy, krw = twd[idx], jpy[idx], krw[idx]

    series = {"USD": twd, "JPY": twd / jpy, "KRW": twd / krw}
    rates = {}
    for code, s in series.items():
        now_v, avg_v = float(s.iloc[-1]), float(s.mean())
        dev = (avg_v - now_v) / avg_v * 100
        cheap, pricey = _SIGNALS[code]
        signal = cheap if dev > SIGNAL_PCT else pricey if dev < -SIGNAL_PCT else ""
        rates[code] = {"now": now_v, "avg_1y": avg_v, "dev_pct": round(dev, 2), "signal": signal}

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "data_date": idx[-1].strftime("%Y-%m-%d"),   # 最後一筆報價日（週末沿用週五）
        "unit": "1 外幣 = X 台幣",
        "rates": rates,
    }


if __name__ == "__main__":
    data = build()
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for code, r in data["rates"].items():
        print(f"{code} {r['now']:.5f}（均 {r['avg_1y']:.5f}，{r['dev_pct']:+.2f}%）{r['signal']}")
    print(f"報價日 {data['data_date']}，已寫入 {OUT_FILE.name}")
