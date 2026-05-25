import json
import os
from datetime import datetime, timedelta

LOG_FILE = os.path.join(os.path.dirname(__file__), "signal_history.json")


def load_log() -> list:
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_signal(name: str, ticker: str, signal_type: str, price: float, signals: list):
    log = load_log()
    log.append({
        "date":            datetime.now().strftime("%Y-%m-%d"),
        "name":            name,
        "ticker":          ticker,
        "type":            signal_type,
        "price_at_signal": round(price, 2),
        "signals":         [s["msg"] for s in signals],
        "price_now":       None,
        "return_pct":      None,
        "result":          None,
    })
    log = log[-300:]
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def update_and_load(all_data: dict) -> list:
    log = load_log()
    changed = False
    for entry in log:
        if entry.get("result"):
            continue
        name = entry["name"]
        df   = all_data.get(name)
        if df is None or df.empty:
            continue
        current = float(df.iloc[-1]["Close"])
        sig_p   = entry["price_at_signal"]
        ret     = (current - sig_p) / sig_p * 100
        try:
            days = (datetime.now() - datetime.strptime(entry["date"], "%Y-%m-%d")).days
        except Exception:
            days = 0
        entry["price_now"]  = round(current, 2)
        entry["return_pct"] = round(ret, 2)
        if days >= 10:
            win = (entry["type"] == "buy" and ret > 0) or (entry["type"] == "sell" and ret < 0)
            entry["result"] = "✅ 勝" if win else "❌ 敗"
        changed = True
    if changed:
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return log


def win_rate(log: list) -> dict:
    decided = [e for e in log if e.get("result")]
    if not decided:
        return {"total": 0, "win": 0, "rate": 0.0}
    wins = sum(1 for e in decided if "勝" in e["result"])
    return {"total": len(decided), "win": wins, "rate": round(wins / len(decided) * 100, 1)}
