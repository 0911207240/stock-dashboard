"""台灣股市交易日判斷，從 TWSE 抓本年度休市清單"""
import json
import urllib.request
from datetime import date


def _fetch_tw_holidays() -> set[date]:
    url = "https://www.twse.com.tw/rwd/zh/holiday/holidaySchedule?response=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        holidays = set()
        for row in data.get("data", []):
            try:
                # 日期格式：民國年/月/日，例如 "114/01/01"
                parts = row[0].strip().split("/")
                y = int(parts[0]) + 1911
                m = int(parts[1])
                d = int(parts[2])
                holidays.add(date(y, m, d))
            except Exception:
                pass
        return holidays
    except Exception:
        return set()


def is_trading_day(check_date: date = None) -> bool:
    """
    True  → 今天是交易日，應執行掃描
    False → 週末或 TWSE 公告休市日，應跳過
    """
    if check_date is None:
        check_date = date.today()
    if check_date.weekday() >= 5:   # 週六=5, 週日=6
        return False
    holidays = _fetch_tw_holidays()
    if not holidays:
        return True                 # API 失敗時保守判斷為交易日，不漏推播
    return check_date not in holidays
