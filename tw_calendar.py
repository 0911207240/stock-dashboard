"""台灣股市交易日判斷，從 TWSE 抓本年度休市清單

2026-09 TWSE 把 /rwd/zh/holiday/holidaySchedule 下架（回 404 頁），舊版解析一直拿到空清單、
把所有平日都當交易日，9/25 中秋、9/28 教師節仍推了當沖候選。現改用新路徑，失敗再退回 OpenAPI。
清單裡也會列「開始交易日」「最後交易日」這類有開盤的日子，要排除，不能當休市。
"""
import json
import urllib.request
from datetime import date
from functools import lru_cache

_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json"
_OPENAPI_URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _is_closed(name: str) -> bool:
    return not name.strip().endswith("交易日")   # 「國曆新年開始交易日」「農曆春節前最後交易日」照常開盤


def _from_rwd() -> set[date]:
    # data 列：["2026-09-25", "中秋節", "說明"]
    rows = _get_json(_URL).get("data", [])
    return {date.fromisoformat(r[0].strip()) for r in rows if _is_closed(r[1])}


def _from_openapi() -> set[date]:
    # 列：{"Name": "中秋節", "Date": "1150925", ...}，民國年
    holidays = set()
    for r in _get_json(_OPENAPI_URL):
        d = r["Date"].strip()
        if _is_closed(r["Name"]):
            holidays.add(date(int(d[:-4]) + 1911, int(d[-4:-2]), int(d[-2:])))
    return holidays


@lru_cache(maxsize=4)
def _fetch_tw_holidays(_day: date = None) -> set[date]:
    """_day 只當快取鍵，同一天只抓一次"""
    for source in (_from_rwd, _from_openapi):
        try:
            holidays = source()
            if holidays:
                return holidays
        except Exception as e:
            print(f"[tw_calendar] {source.__name__} 失敗：{e}")
    print("[tw_calendar] ⚠️ 休市清單抓取失敗，平日一律視為交易日")
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
    holidays = _fetch_tw_holidays(date.today())
    if not holidays:
        return True                 # API 失敗時保守判斷為交易日，不漏推播
    return check_date not in holidays
