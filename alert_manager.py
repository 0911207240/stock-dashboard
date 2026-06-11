"""價格提醒管理
有設定 SUPABASE_URL + SUPABASE_KEY → 寫 Supabase（永久）
否則 → 寫 /tmp JSON（重啟清空，fallback）
"""
import os, json, requests
from pathlib import Path
from datetime import datetime

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_USE_DB       = bool(_SUPABASE_URL and _SUPABASE_KEY)
_TABLE        = "price_alerts"
_FILE         = Path(__file__).parent / "price_alerts.json"


# ── Supabase REST 工具 ────────────────────────────────────

def _headers() -> dict:
    return {
        "apikey":        _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type":  "application/json",
    }

def _url(qs: str = "") -> str:
    return f"{_SUPABASE_URL}/rest/v1/{_TABLE}{qs}"


def _db_load() -> dict:
    try:
        r = requests.get(_url("?select=*"), headers=_headers(), timeout=5)
        return {row["ticker"]: {
            "name":      row["name"],
            "direction": row["direction"],
            "price":     row["price"],
            "set_at":    row["set_at"],
        } for row in r.json()}
    except Exception:
        return {}

def _db_upsert(ticker: str, name: str, direction: str,
               price: float, set_at: str):
    data = {"ticker": ticker, "name": name,
            "direction": direction, "price": price, "set_at": set_at}
    h = {**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    requests.post(_url(), json=data, headers=h, timeout=5)

def _db_delete(ticker: str):
    requests.delete(_url(f"?ticker=eq.{ticker}"),
                    headers=_headers(), timeout=5)


# ── /tmp fallback ─────────────────────────────────────────

def _file_load() -> dict:
    try:
        if _FILE.exists():
            return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _file_save(data: dict):
    try:
        _FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ── 統一介面 ──────────────────────────────────────────────

def _load() -> dict:
    return _db_load() if _USE_DB else _file_load()


def set_alert(ticker: str, name: str, direction: str, price: float) -> str:
    set_at = datetime.now().strftime("%m/%d %H:%M")
    if _USE_DB:
        _db_upsert(ticker, name, direction, price, set_at)
    else:
        alerts = _file_load()
        alerts[ticker] = {"name": name, "direction": direction,
                          "price": price, "set_at": set_at}
        _file_save(alerts)
    word = "突破" if direction == ">" else "跌破"
    return f"✅ 提醒設定：{name} {word} ${price:.1f} 時通知"


def cancel_alert(ticker: str, name: str) -> str:
    alerts = _load()
    if ticker not in alerts:
        return f"❌ {name} 目前沒有設定提醒"
    if _USE_DB:
        _db_delete(ticker)
    else:
        del alerts[ticker]
        _file_save(alerts)
    return f"✅ 已取消 {name} 的提醒"


def list_alerts() -> str:
    alerts = _load()
    if not alerts:
        return ("📌 目前沒有設定任何提醒\n\n"
                "設定方式：\n  2330 >1100（突破提醒）\n  台積電 <1000（跌破提醒）")
    lines = ["📌 目前的提醒："]
    for ticker, a in alerts.items():
        sym = ">" if a["direction"] == ">" else "<"
        lines.append(f"  {a['name']} {sym} ${a['price']:.1f}  （{a['set_at']} 設）")
    lines.append("\n取消方式：輸入「代號 取消」，例如 2330 取消")
    return "\n".join(lines)


def check_and_trigger(prices: dict[str, float]) -> list[str]:
    alerts    = _load()
    triggered = []
    remaining = {}

    for ticker, a in alerts.items():
        current = prices.get(ticker)
        if current is None:
            remaining[ticker] = a
            continue
        hit = (a["direction"] == ">" and current >= a["price"]) or \
              (a["direction"] == "<" and current <= a["price"])
        if hit:
            word = "突破" if a["direction"] == ">" else "跌破"
            triggered.append(
                f"🔔 【價格提醒觸發】\n"
                f"{a['name']} 已{word} ${a['price']:.1f}\n"
                f"現價 ${current:.1f}\n"
                f"（{a['set_at']} 設定）"
            )
            if _USE_DB:
                _db_delete(ticker)
        else:
            remaining[ticker] = a

    if triggered and not _USE_DB:
        _file_save(remaining)

    return triggered
