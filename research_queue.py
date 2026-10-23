"""
研究佇列：反向觀察名單一出現標的，就把要研究的股票和手上已有的資料打包好，
交給排程任務裡的 Claude 依 01–06 框架做深度研究。

來源：scan_results.json 的 ptt.watch（股版真心悲觀／恐慌＋法人買超，由 scanner 產生）
規則：
  - scan_results.json 必須是今天的掃描（台灣時間），否則佇列為空
  - 同一檔 10 天內研究過就跳過，避免天天重複
  - 一次最多 3 檔，依法人買超張數排序

指令：
  python research_queue.py            # 產生 research_queue.json 並印出
  python research_queue.py done 聯發科 台積電   # 記錄已研究，寫進 research_log.json
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

_DIR = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(_DIR, "scan_results.json")
LEDGER = os.path.join(_DIR, "shadow_ledger.json")
FUND = os.path.join(_DIR, "fundamental_cache.json")
QUEUE = os.path.join(_DIR, "research_queue.json")
LOG = os.path.join(_DIR, "research_log.json")
TW = timezone(timedelta(hours=8))
COOLDOWN_DAYS = 10
MAX_STOCKS = 3

FUND_KEYS = ("trailing_pe", "forward_pe", "price_to_book", "ev_to_ebitda", "peg",
             "gross_margins", "operating_margins", "return_on_equity", "revenue_growth", "earnings_growth",
             "debt_to_equity", "current_ratio", "cash_conversion", "free_cashflow", "fcf_yield",
             "insider_pct", "institution_pct", "target_upside", "recommendation", "fetched_date")


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _today() -> str:
    return datetime.now(TW).strftime("%Y-%m-%d")


def build() -> dict:
    scan = _load(SCAN, {})
    today = _today()
    out = {"date": today, "stocks": [], "skipped": [], "reason": ""}
    if scan.get("date") != today:
        out["reason"] = f"今天的掃描還沒跑完（scan_results.json 日期 {scan.get('date')}）"
        return _save(out)
    watch = (scan.get("ptt") or {}).get("watch") or []
    if not watch:
        out["reason"] = "今天反向觀察名單沒有標的"
        return _save(out)

    log = _load(LOG, [])
    cutoff = (datetime.now(TW) - timedelta(days=COOLDOWN_DAYS)).strftime("%Y-%m-%d")
    recent = {e["name"] for e in log if e.get("date", "") >= cutoff}

    from data_fetcher import WATCHLIST
    try:
        from portfolio import HOLDINGS
    except Exception:
        HOLDINGS = {}
    fund = _load(FUND, {})
    ledger = _load(LEDGER, [])

    for w in sorted(watch, key=lambda x: x.get("inst_net") or 0, reverse=True):
        name = w["name"]
        if name in recent:
            out["skipped"].append(f"{name}（{COOLDOWN_DAYS} 天內研究過）")
            continue
        if len(out["stocks"]) >= MAX_STOCKS:
            out["skipped"].append(f"{name}（超過每日 {MAX_STOCKS} 檔上限）")
            continue
        ticker = WATCHLIST.get(name, "")
        f = fund.get(ticker, {})
        hist = [e for e in ledger if e.get("name") == name][-10:]
        out["stocks"].append({
            "name": name, "ticker": ticker,
            "why": f"股版{w.get('kind')}（提及 {w.get('mentions')} 次）但法人買超 {w.get('inst_net')} 張",
            "ptt_note": w.get("note", ""),
            "holding": HOLDINGS.get(name),
            "fundamentals": {k: f.get(k) for k in FUND_KEYS if f.get(k) is not None},
            "fund_schema_ok": f.get("v") == 2,
            "recent_shadow": [{k: e.get(k) for k in ("date", "score", "rank", "bear", "kill", "ret", "sim", "regime")}
                              for e in hist],
        })
    if not out["stocks"]:
        out["reason"] = "名單上的標的最近都研究過了"
    return _save(out)


def _save(out: dict) -> dict:
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def mark_done(names: list[str]):
    log = _load(LOG, [])
    today = _today()
    for n in names:
        log.append({"date": today, "name": n})
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(log[-500:], f, ensure_ascii=False, indent=1)
    print(f"已記錄研究完成：{'、'.join(names)}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "done":
        mark_done(sys.argv[2:])
    else:
        q = build()
        if q["stocks"]:
            print(f"今天要研究 {len(q['stocks'])} 檔：" + "、".join(s["name"] for s in q["stocks"]))
            for s in q["stocks"]:
                print(f"  {s['name']}（{s['ticker']}）：{s['why']}" + ("｜持股中" if s["holding"] else ""))
        else:
            print(f"今天不用研究：{q['reason']}")
        if q["skipped"]:
            print("跳過：" + "、".join(q["skipped"]))
