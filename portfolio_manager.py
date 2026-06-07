"""動態持股管理 — Supabase 永久儲存，/tmp JSON fallback

Supabase 建表 SQL（只需執行一次）:
  CREATE TABLE portfolio_holdings (
    ticker      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    shares      INTEGER NOT NULL DEFAULT 0,
    cost        FLOAT,
    stop_loss   FLOAT,
    take_profit FLOAT,
    updated_at  TEXT
  );
"""
import os, json, requests
from pathlib import Path
from datetime import datetime

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_USE_DB       = bool(_SUPABASE_URL and _SUPABASE_KEY)
_TABLE        = "portfolio_holdings"
_FILE         = Path("/tmp/auno_holdings.json")

_SEED = {
    "1101.TW":  {"name": "台泥",             "shares": 5250,  "cost": None,   "stop_loss": None,   "take_profit": None},
    "2880.TW":  {"name": "華南金",            "shares": 40,    "cost": None,   "stop_loss": None,   "take_profit": None},
    "8150.TW":  {"name": "南茂",              "shares": 2000,  "cost": 39.82,  "stop_loss": 35.0,   "take_profit": 52.0},
    "00929.TW": {"name": "復華台灣科技優息",  "shares": 15000, "cost": 20.12,  "stop_loss": 17.0,   "take_profit": 26.0},
    "2330.TW":  {"name": "台積電",            "shares": 25,    "cost": 1621.8, "stop_loss": 1400.0, "take_profit": 2200.0},
    "0050.TW":  {"name": "台灣50",            "shares": 400,   "cost": 70.13,  "stop_loss": 60.0,   "take_profit": 95.0},
    "0056.TW":  {"name": "元大高股息",        "shares": 910,   "cost": 38.66,  "stop_loss": 33.0,   "take_profit": 50.0},
    "00878.TW": {"name": "國泰永續高股息",    "shares": 1163,  "cost": 22.47,  "stop_loss": 19.0,   "take_profit": 30.0},
    "2892.TW":  {"name": "第一金",            "shares": 3000,  "cost": 26.89,  "stop_loss": 23.0,   "take_profit": 34.0},
    "4744.TW":  {"name": "振發",              "shares": 2000,  "cost": 38.01,  "stop_loss": 32.0,   "take_profit": 50.0},
    "2364.TW":  {"name": "昆盈",              "shares": 5000,  "cost": 57.66,  "stop_loss": 48.0,   "take_profit": 75.0},
}


# ── Supabase REST ─────────────────────────────────────────

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
            "name":        row["name"],
            "shares":      row["shares"],
            "cost":        row.get("cost"),
            "stop_loss":   row.get("stop_loss"),
            "take_profit": row.get("take_profit"),
        } for row in r.json()}
    except Exception:
        return {}

def _db_upsert(ticker: str, record: dict):
    h = {**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    requests.post(_url(), json={"ticker": ticker, **record,
                                "updated_at": datetime.now().strftime("%m/%d %H:%M")},
                  headers=h, timeout=5)

def _db_delete(ticker: str):
    requests.delete(_url(f"?ticker=eq.{ticker}"), headers=_headers(), timeout=5)


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
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── 統一介面 ──────────────────────────────────────────────

def load() -> dict:
    """回傳 {ticker: {name, shares, cost, stop_loss, take_profit}}，空時回傳種子資料"""
    data = _db_load() if _USE_DB else _file_load()
    if not data:
        data = _SEED.copy()
        if _USE_DB:
            for ticker, rec in data.items():
                _db_upsert(ticker, rec)
        else:
            _file_save(data)
    return data

def _save_one(ticker: str, record: dict):
    if _USE_DB:
        _db_upsert(ticker, record)
    else:
        data = _file_load() or _SEED.copy()
        data[ticker] = record
        _file_save(data)

def _delete_one(ticker: str):
    if _USE_DB:
        _db_delete(ticker)
    else:
        data = _file_load() or _SEED.copy()
        data.pop(ticker, None)
        _file_save(data)


# ── 高階指令 ──────────────────────────────────────────────

def add_shares(ticker: str, name: str, shares: int, cost: float | None = None) -> str:
    """加倉：增加股數，可選填成本（加權平均）"""
    data = load()
    rec  = data.get(ticker, {"name": name, "shares": 0, "cost": None,
                              "stop_loss": None, "take_profit": None})
    old_shares = rec["shares"]
    old_cost   = rec.get("cost")

    if cost is not None and old_cost is not None and old_shares > 0:
        new_cost = (old_cost * old_shares + cost * shares) / (old_shares + shares)
        rec["cost"] = round(new_cost, 2)
    elif cost is not None:
        rec["cost"] = cost

    rec["shares"] = old_shares + shares
    rec["name"]   = name
    _save_one(ticker, rec)

    cost_str = f"，成本 ${rec['cost']:.2f}" if rec.get("cost") else ""
    return (f"✅ {name} 加倉 {shares} 股\n"
            f"目前持股：{rec['shares']} 股{cost_str}")


def reduce_shares(ticker: str, name: str, shares: int) -> str:
    """減倉：扣除股數（不得低於 0）"""
    data = load()
    rec  = data.get(ticker)
    if not rec or rec["shares"] <= 0:
        return f"❌ {name} 目前沒有持股記錄"
    if shares > rec["shares"]:
        return f"⚠️ {name} 持股 {rec['shares']} 股，無法減倉 {shares} 股"
    rec["shares"] -= shares
    if rec["shares"] == 0:
        _delete_one(ticker)
        return f"✅ {name} 已全數出清，移除持股記錄"
    _save_one(ticker, rec)
    return f"✅ {name} 減倉 {shares} 股，剩餘 {rec['shares']} 股"


def clear_position(ticker: str, name: str) -> str:
    """清倉：移除整筆持股"""
    data = load()
    if ticker not in data:
        return f"❌ {name} 沒有持股記錄"
    _delete_one(ticker)
    return f"✅ {name} 清倉完成，已移除持股記錄"


def set_field(ticker: str, name: str, field: str, value: float) -> str:
    """設定成本 / 停損 / 停利"""
    data = load()
    rec  = data.get(ticker)
    if not rec:
        return f"❌ {name} 沒有持股記錄，請先加倉後再設定"
    rec[field] = value
    _save_one(ticker, rec)
    label = {"cost": "成本", "stop_loss": "停損", "take_profit": "停利"}.get(field, field)
    return f"✅ {name} {label}已設為 ${value:.2f}"
