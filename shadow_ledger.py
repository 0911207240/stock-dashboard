"""
影子紀錄（記帳基礎）：每個交易日把掃描出的前 N 檔候選（不論有沒有推播）連同各項子分數記下來，
之後回填 T+1 當沖模擬結果與 T+1/T+3/T+5 收盤報酬。只記錄，不影響任何推播邏輯。

signal_date = 掃描當下價格資料的最後一個交易日（掃描在盤前跑，等於前一個收盤日）。
"""
import json
import os

import pandas as pd

LEDGER_FILE = os.path.join(os.path.dirname(__file__), "shadow_ledger.json")
MAX_RECORDS = 30000
HORIZONS = (1, 3, 5)


def _load() -> list:
    if not os.path.exists(LEDGER_FILE):
        return []
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(data: list):
    try:
        with open(LEDGER_FILE, "w", encoding="utf-8") as f:
            json.dump(data[-MAX_RECORDS:], f, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        pass


def _num(v, nd=2):
    try:
        if v is None or pd.isna(v):
            return None
        return round(float(v), nd)
    except Exception:
        return None


def record_candidates(candidates: list[dict], all_data: dict, pushed_names: set, regime: dict):
    """記下當日候選。同一 signal_date + ticker 不重複記（午盤再掃時略過）。"""
    if not candidates:
        return 0
    log = _load()
    seen = {(e["date"], e["ticker"]) for e in log}
    added = 0
    for rank, c in enumerate(candidates, 1):
        df = all_data.get(c["name"])
        if df is None or df.empty:
            continue
        try:
            sig_date = df.index[-1].strftime("%Y-%m-%d")
        except Exception:
            continue
        key = (sig_date, c["ticker"])
        if key in seen:
            continue
        seen.add(key)
        log.append({
            "date":       sig_date,
            "name":       c["name"],
            "ticker":     c["ticker"],
            "rank":       rank,
            "score":      c["score"],
            "vol":        _num(c.get("vol_score")),
            "chip":       _num(c.get("chip_score")),
            "tech":       _num(c.get("tech_score")),
            "atr_s":      _num(c.get("atr_score")),
            "beta":       _num(c.get("beta")),
            "rs5":        _num(c.get("rs5"), 3),
            "rs20":       _num(c.get("rs20"), 3),
            "mdd20":      _num(c.get("mdd_20")),
            "vol_ratio":  _num(c.get("vol_ratio")),
            "atr_pct":    _num(c.get("atr_pct")),
            "earn_risk":  bool(c.get("earnings_risk")),
            "regime":     (regime or {}).get("state"),
            "pushed":     c["name"] in pushed_names,
            "price":      _num(c.get("price")),
            "entry_mid":  _num(c.get("entry_mid")),
            "stop":       _num(c.get("stop")),
            "tp1":        _num(c.get("tp1")),
            "tp2":        _num(c.get("tp2")),
            "sim":        None,      # T+1 當沖模擬結果（規則同 daytrade_history）
            "sim_ret":    None,      # 模擬毛報酬 %
            "ret":        {},        # {"1": %, "3": %, "5": %} 收盤對收盤報酬
        })
        added += 1
    if added:
        _save(log)
    return added


def settle(all_data: dict) -> int:
    """回填尚未完成的紀錄。回傳本次更新筆數。"""
    log = _load()
    changed = 0
    for e in log:
        if e.get("sim") is not None and all(str(h) in e["ret"] for h in HORIZONS):
            continue
        df = all_data.get(e["name"])
        if df is None or df.empty:
            continue
        try:
            after = df[df.index.strftime("%Y-%m-%d") > e["date"]]
        except Exception:
            continue
        if after.empty:
            continue
        base = e["price"]
        if not base:
            continue

        # T+1 / T+3 / T+5 收盤對收盤
        for h in HORIZONS:
            k = str(h)
            if k not in e["ret"] and len(after) >= h:
                e["ret"][k] = round((float(after.iloc[h - 1]["Close"]) - base) / base * 100, 2)
                changed += 1

        # T+1 當沖模擬（與 signal_log.update_daytrade_results 相同規則）
        if e.get("sim") is None:
            nxt = after.iloc[0]
            o, hi, lo, cl = (float(nxt[c]) for c in ("Open", "High", "Low", "Close"))
            em, stop, tp1, tp2 = e["entry_mid"], e["stop"], e["tp1"], e["tp2"]
            if not em or lo > em:
                e["sim"], e["sim_ret"] = "未成交", None
            else:
                fill = min(o, em)
                if stop and lo <= stop:
                    res, ex = "停損", stop
                elif tp2 and hi >= tp2:
                    res, ex = "停利②", tp2
                elif tp1 and hi >= tp1:
                    res, ex = "停利①", tp1
                else:
                    res, ex = "未觸發", cl
                e["sim"] = res
                e["sim_ret"] = round((ex - fill) / fill * 100, 2)
            changed += 1
    if changed:
        _save(log)
    return changed
