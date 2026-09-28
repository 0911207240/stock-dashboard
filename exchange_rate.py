"""匯率模組 — 讀取 fx_daily.json（USD/JPY/KRW 今日值與 1 年均值）

台銀牌告 CSV 已改成機器人驗證頁抓不到，改用 fx_daily.py 由 yfinance 產生的資料。
檔案不是今天產生的（FX Daily workflow 延遲或失敗）就當場重算一次。
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fx_daily import OUT_FILE, build

_NAMES = {"USD": "美元", "JPY": "日圓", "KRW": "韓元"}
_DIGITS = {"USD": 2, "JPY": 4, "KRW": 5}


def fetch_exchange_rates() -> dict:
    today = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    try:
        data = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        if data.get("generated_at", "").startswith(today):
            return data
    except Exception:
        data = {}

    try:
        return build()
    except Exception as e:
        print(f"[匯率] 重算失敗：{e}")
        return data or {"rates": {}}


def format_exchange_rates(data: dict) -> str:
    rates = data.get("rates", {})
    if not rates:
        return "匯率：資料暫時無法取得"

    lines = [f"💱 今日匯率（vs 1 年均值，報價日 {data.get('data_date', '?')}）"]
    for code, name in _NAMES.items():
        r = rates.get(code)
        if not r:
            continue
        d = _DIGITS[code]
        line = f"  {name}：{r['now']:.{d}f}（均 {r['avg_1y']:.{d}f}，{r['dev_pct']:+.1f}%）"
        if r.get("signal"):
            line += f" {r['signal']}"
        lines.append(line)
    return "\n".join(lines)
