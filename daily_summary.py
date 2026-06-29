"""
daily_summary.py — 每日收盤彙整推播
整合：大盤狀況 + 技術訊號 + 隔日當沖候選 + 精選報導
每天只推一則，節省 LINE 額度

使用方式：
  python daily_summary.py          # 正常執行（有 lock，當天只推一次）
  python daily_summary.py --force  # 強制重推（忽略 lock）

建議在 GitHub Actions 設定收盤後執行，例如 UTC 07:00（台灣時間 15:00）
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

_LOCK_FILE = Path("summary_lock.json")

def _done_today() -> bool:
    try:
        return json.loads(_LOCK_FILE.read_text()).get("date") == datetime.now().strftime("%Y-%m-%d")
    except Exception:
        return False

def _mark_done():
    _LOCK_FILE.write_text(json.dumps({"date": datetime.now().strftime("%Y-%m-%d")}))

# ── 大盤狀況 ──────────────────────────────────────
def _fetch_market_summary() -> str:
    try:
        from data_fetcher import fetch_taiex
        from analyzer import add_indicators, detect_signals, score, calc_week52
        df = fetch_taiex("3mo")
        if df is None or df.empty:
            return ""
        df = add_indicators(df)
        latest = df.iloc[-1]
        prev   = df.iloc[-2]
        price  = float(latest["Close"])
        chg    = (price - float(prev["Close"])) / float(prev["Close"]) * 100
        rsi    = float(latest["RSI"]) if hasattr(latest, "RSI") else 50.0
        w52    = calc_week52(df)
        sigs   = detect_signals(df)
        sc     = score(sigs)

        if sc >= 3:   outlook = "🟢 積極做多"
        elif sc >= 1: outlook = "🟡 謹慎偏多"
        elif sc >= -1:outlook = "🟡 觀望"
        elif sc >= -3:outlook = "🟠 謹慎偏空"
        else:         outlook = "🔴 防禦模式"

        arrow = "▲" if chg >= 0 else "▼"
        return (
            f"🌐 大盤展望\n"
            f" 加權指數 {price:,.0f} {arrow}{abs(chg):.2f}%\n"
            f" RSI {rsi:.1f}｜年度位置 {w52['week52_pct']:.0f}%\n"
            f" {outlook}"
        )
    except Exception as e:
        print(f"[大盤] 抓取失敗：{e}")
        return ""

# ── 技術訊號彙整 ──────────────────────────────────
def _fetch_signal_summary() -> str:
    try:
        from data_fetcher import fetch_all, WATCHLIST
        from analyzer import add_indicators, detect_signals, score
        data = fetch_all("3mo", "全部")
        buys, sells = [], []
        for name, df in data.items():
            if df is None or df.empty:
                continue
            df  = add_indicators(df)
            sigs = detect_signals(df)
            sc   = score(sigs)
            price = float(df.iloc[-1]["Close"])
            if sc >= 2:
                top = sigs[0]["msg"] if sigs else ""
                buys.append(f" 📈 {name} ${price:.1f}｜{top}")
            elif sc <= -2:
                top = sigs[0]["msg"] if sigs else ""
                sells.append(f" 📉 {name} ${price:.1f}｜{top}")

        if not buys and not sells:
            return "📊 技術訊號\n 今日無明確訊號"

        lines = ["📊 技術訊號"]
        if buys:
            lines += buys[:5]
        if sells:
            lines += sells[:3]
        if len(buys) > 5:
            lines.append(f" …另 {len(buys)-5} 檔買進訊號略")
        return "\n".join(lines)
    except Exception as e:
        print(f"[訊號] 抓取失敗：{e}")
        return ""

# ── 隔日當沖候選 Top3 ─────────────────────────────
def _fetch_daytrade_summary() -> str:
    try:
        from data_fetcher import fetch_all, WATCHLIST
        from daytrade_scorer import get_daytrade_candidates
        data = fetch_all("3mo", "全部")
        candidates = get_daytrade_candidates(data, WATCHLIST, top_n=3)
        if not candidates:
            return "⚡ 明日當沖候選\n 今日無符合條件股票"

        lines = ["⚡ 明日當沖候選 Top3"]
        for i, c in enumerate(candidates, 1):
            arrow = "▲" if c["change_pct"] >= 0 else "▼"
            lines.append(
                f" {i}. {c['name']} 分數{c['score']}\n"
                f"    進場${c['entry']} 目標${c['target']} 停損${c['stop']}\n"
                f"    {arrow}{abs(c['change_pct']):.1f}% 量比{c['vol_ratio']:.1f}x"
            )
        return "\n".join(lines)
    except Exception as e:
        print(f"[當沖] 抓取失敗：{e}")
        return ""

# ── 精選報導（每日早安日報已有，收盤版只取重大訊息）──
def _fetch_twse_news() -> str:
    try:
        from news_fetcher import fetch_daily_news
        news = fetch_daily_news()
        items = news.get("台股重大訊息", [])
        if not items:
            return ""
        lines = ["🔔 台股重大訊息"]
        for a in items[:3]:
            lines.append(f" • {a['title']}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[重大訊息] 抓取失敗：{e}")
        return ""

# ── 組合成一則推播 ────────────────────────────────
def build_daily_summary() -> str:
    now = datetime.now()
    days = ["一", "二", "三", "四", "五", "六", "日"]
    date_str = f"{now.month}/{now.day}（{days[now.weekday()]}）"

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_market  = ex.submit(_fetch_market_summary)
        f_signal  = ex.submit(_fetch_signal_summary)
        f_daytrade= ex.submit(_fetch_daytrade_summary)
        f_twse    = ex.submit(_fetch_twse_news)
        market   = f_market.result()
        signal   = f_signal.result()
        daytrade = f_daytrade.result()
        twse     = f_twse.result()

    divider = "─" * 18
    sections = [f"📊 收盤報告 {date_str}", divider]
    for block in [market, signal, daytrade, twse]:
        if block:
            sections.append(block)
            sections.append(divider)
    sections.append("☀️ 早安日報明早 07:30 見")
    return "\n".join(sections)

# ── 主程式 ────────────────────────────────────────
def run(force: bool = False):
    if not force and _done_today():
        print("[收盤報告] 今日已推播，跳過（--force 可強制重推）")
        return

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 收盤報告開始...")
    msg = build_daily_summary()
    print(f" 報告字數：{len(msg)}")

    from line_notifier import send
    ok = send(msg)
    print(f" 推播：{'成功' if ok else '失敗'}")

    if ok:
        _mark_done()

if __name__ == "__main__":
    force = "--force" in sys.argv
    run(force=force)
