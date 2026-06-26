"""早安日報 — 每天早上 07:30 推播一則綜合報告"""
import json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

_LOCK_FILE = Path("briefing_lock.json")


def _done_today() -> bool:
    try:
        return json.loads(_LOCK_FILE.read_text()).get("date") == datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return False


def _mark_done():
    _LOCK_FILE.write_text(json.dumps({"date": datetime.now().strftime("%Y-%m-%d")}))


def run_morning_briefing(notify: bool = True):
    if _done_today():
        print("[早安日報] 今日已推播，跳過")
        return

    now = datetime.now()
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M')}] 早安日報開始...")

    from exchange_rate import fetch_exchange_rates, format_exchange_rates
    from news_fetcher import fetch_daily_news, format_daily_news
    from social_trends import fetch_social_trends, format_social_trends
    from gmail_digest import fetch_gmail_summary, format_gmail_summary
    from us_market import fetch_us_overnight

    with ThreadPoolExecutor(max_workers=5) as ex:
        fx_future = ex.submit(fetch_exchange_rates)
        news_future = ex.submit(fetch_daily_news)
        trends_future = ex.submit(fetch_social_trends)
        gmail_future = ex.submit(fetch_gmail_summary)
        us_future = ex.submit(fetch_us_overnight)

    fx_data = fx_future.result()
    news_data = news_future.result()
    trends_data = trends_future.result()
    gmail_data = gmail_future.result()
    us_data = us_future.result()

    date_str = now.strftime("%m/%d (%a)")
    weekday_map = {"Mon": "一", "Tue": "二", "Wed": "三", "Thu": "四", "Fri": "五", "Sat": "六", "Sun": "日"}
    for eng, zh in weekday_map.items():
        date_str = date_str.replace(eng, zh)

    sections = [f"☀️ 早安日報 {date_str}"]

    us_summary = ""
    if us_data and us_data.get("summary"):
        us_summary = f"🌙 美股夜盤\n  {us_data['summary']}"
        sections.append(us_summary)

    fx_text = format_exchange_rates(fx_data)
    if fx_text:
        sections.append(fx_text)

    news_text = format_daily_news(news_data)
    if news_text:
        sections.append(news_text)

    trends_text = format_social_trends(trends_data)
    if trends_text:
        sections.append(trends_text)

    gmail_text = format_gmail_summary(gmail_data)
    if gmail_text:
        sections.append(gmail_text)

    combined = "\n\n".join(sections)
    print(f"  日報內容共 {len(combined)} 字")

    if notify:
        from line_notifier import send
        success = send(combined)
        print(f"  早安日報：{'已推播' if success else '推播失敗'}")
    else:
        print(combined)

    _mark_done()
    print("早安日報完成")


if __name__ == "__main__":
    run_morning_briefing()
