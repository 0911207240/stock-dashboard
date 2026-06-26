"""匯率抓取模組 — 台銀牌告匯率"""
import json
import time
from pathlib import Path
from datetime import datetime

import requests

_CACHE_FILE = Path("exchange_cache.json")
_CACHE_TTL = 3600

_BOT_URL = "https://rate.bot.com.tw/xrt/flcsv/0/day"

_TARGETS = {
    "USD": "美金",
    "JPY": "日圓",
    "EUR": "歐元",
    "CNY": "人民幣",
}


def _load_cache() -> dict:
    try:
        data = json.loads(_CACHE_FILE.read_text())
        if time.time() - data.get("ts", 0) < _CACHE_TTL:
            return data
    except Exception:
        pass
    return {}


def _save_cache(data: dict):
    data["ts"] = time.time()
    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False))


def fetch_exchange_rates() -> dict:
    cached = _load_cache()
    if cached.get("rates"):
        return cached

    try:
        resp = requests.get(_BOT_URL, timeout=10)
        resp.encoding = "utf-8"
        lines = resp.text.strip().split("\n")
    except Exception as e:
        print(f"[匯率] 抓取失敗：{e}")
        return cached if cached else {"rates": {}}

    rates = {}
    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) < 13:
            continue
        currency = cols[0].strip().strip('"')
        for code, name in _TARGETS.items():
            if code in currency or name in currency:
                try:
                    cash_buy = float(cols[2].strip().strip('"'))
                    cash_sell = float(cols[12].strip().strip('"'))
                    spot_buy = float(cols[3].strip().strip('"'))
                    spot_sell = float(cols[13].strip().strip('"'))
                    rates[code] = {
                        "name": name,
                        "cash_buy": cash_buy,
                        "cash_sell": cash_sell,
                        "spot_buy": spot_buy,
                        "spot_sell": spot_sell,
                    }
                except (ValueError, IndexError):
                    pass
                break

    result = {"rates": rates, "date": datetime.now().strftime("%Y-%m-%d")}
    _save_cache(result)
    return result


def format_exchange_rates(data: dict) -> str:
    rates = data.get("rates", {})
    if not rates:
        return "匯率：資料暫時無法取得"

    lines = ["💱 今日匯率（台銀牌告）"]
    for code in ["USD", "JPY", "EUR", "CNY"]:
        r = rates.get(code)
        if not r:
            continue
        if code == "JPY":
            lines.append(f"  {r['name']}：買 {r['spot_buy']:.4f} / 賣 {r['spot_sell']:.4f}")
        else:
            lines.append(f"  {r['name']}：買 {r['spot_buy']:.3f} / 賣 {r['spot_sell']:.3f}")
    return "\n".join(lines)
