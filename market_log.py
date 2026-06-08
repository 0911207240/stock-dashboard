"""市場大盤歷史快照 — 每日掃描後自動儲存，供復盤分析用"""
import json
from datetime import datetime
from pathlib import Path

MARKET_LOG_FILE = Path("market_log.json")
_MAX_ENTRIES = 365


def save_market_snapshot(
    taiex_close: float,
    taiex_chg_pct: float,
    regime: dict,
    futures_data: dict = None,
    top_sectors: list = None,
    portfolio_value: float = None,
    portfolio_pnl: float = None,
):
    try:
        log = json.loads(MARKET_LOG_FILE.read_text(encoding="utf-8")) if MARKET_LOG_FILE.exists() else []
    except Exception:
        log = []

    today = datetime.now().strftime("%Y-%m-%d")
    existing = next((e for e in log if e.get("date") == today), None)
    entry = existing if existing else {}

    entry.update({
        "date":          today,
        "taiex_close":   round(taiex_close, 2),
        "taiex_chg_pct": round(taiex_chg_pct, 2),
        "regime":        regime.get("state", ""),
        "regime_emoji":  regime.get("emoji", ""),
        "min_score":     40 + regime.get("min_score_adj", 0),
    })

    if futures_data:
        entry["futures_foreign_net"] = futures_data.get("foreign_net", 0)
        entry["futures_desc"]        = futures_data.get("futures_desc", "")

    if top_sectors:
        entry["top_sectors"] = [s["sector"] for s in top_sectors[:3]]

    if portfolio_value:
        entry["portfolio_value"] = round(portfolio_value, 0)

    if portfolio_pnl is not None:
        entry["portfolio_pnl"] = round(portfolio_pnl, 0)

    if not existing:
        log.append(entry)

    log = log[-_MAX_ENTRIES:]

    try:
        MARKET_LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[market_log] 儲存失敗：{e}")


def load_market_log() -> list:
    try:
        return json.loads(MARKET_LOG_FILE.read_text(encoding="utf-8")) if MARKET_LOG_FILE.exists() else []
    except Exception:
        return []
