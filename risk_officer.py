"""
風控長：判斷「現在該不該停手／降倉」。目前是影子模式：只記錄當天會給的等級與原因，
不阻擋推播。績效部用 backtest_rules() 對歷史推播重播，驗證這些規則若真的執行能少虧多少。

等級：normal 正常｜caution 降倉（建議半倉）｜halt 停手（建議當天不進場）
"""
import json
import os

RISK_LOG = os.path.join(os.path.dirname(__file__), "risk_log.json")
HISTORY = os.path.join(os.path.dirname(__file__), "daytrade_history.json")


def _traded(history: list) -> list:
    """已成交且有報酬的推播，依推播日排序。"""
    rows = [h for h in history if h.get("return_pct") is not None]
    rows.sort(key=lambda h: h.get("push_date", ""))
    return rows


def evaluate(history: list, regime: dict = None, as_of: str = None) -> dict:
    """依 as_of（含）之前已結案的推播判斷等級。as_of 缺省＝全部。"""
    rows = _traded(history)
    if as_of:
        rows = [h for h in rows if h["push_date"] < as_of]   # 當日以前才算已結案
    reasons, level = [], "normal"

    last5, last10 = rows[-5:], rows[-10:]
    if len(last10) >= 10 and sum(1 for h in last10 if h["return_pct"] < 0) >= 8:
        level = "halt"
        reasons.append("最近10筆成交有8筆以上虧損")
    elif len(last5) >= 5 and sum(1 for h in last5 if h["return_pct"] < 0) >= 4:
        level = "caution"
        reasons.append("最近5筆成交有4筆以上虧損")

    if rows:
        last_day = rows[-1]["push_date"]
        day = [h["return_pct"] for h in rows if h["push_date"] == last_day]
        if day and sum(day) / len(day) < -2:
            if level == "normal":
                level = "caution"
            reasons.append(f"上一個推播日平均 {sum(day)/len(day):.1f}%")

    if (regime or {}).get("state") == "空頭":
        if level == "normal":
            level = "caution"
        reasons.append("大盤空頭")

    return {"level": level, "reasons": reasons}


def log_today(history: list, regime: dict, date: str, n_push: int) -> dict:
    res = evaluate(history, regime)
    res.update({"date": date, "n_push": n_push, "regime": (regime or {}).get("state")})
    try:
        log = []
        if os.path.exists(RISK_LOG):
            with open(RISK_LOG, "r", encoding="utf-8") as f:
                log = json.load(f)
        log = [e for e in log if e.get("date") != date] + [res]
        with open(RISK_LOG, "w", encoding="utf-8") as f:
            json.dump(log[-500:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return res


def backtest_rules(history: list) -> dict:
    """逐推播日重播規則（regime 不可得，僅用績效規則）。
    回傳各等級日的筆數與平均報酬，並算出「若 halt 日不進場、caution 日半倉」的總報酬差。"""
    rows = _traded(history)
    days = sorted({h["push_date"] for h in rows})
    stat = {"normal": [], "caution": [], "halt": []}
    saved = 0.0
    for d in days:
        lvl = evaluate(history, None, as_of=d)["level"]
        rets = [h["return_pct"] for h in rows if h["push_date"] == d]
        stat[lvl].extend(rets)
        if lvl == "halt":
            saved -= sum(rets)            # 不進場 → 少掉這些報酬
        elif lvl == "caution":
            saved -= sum(rets) * 0.5      # 半倉
    out = {k: {"n": len(v), "avg": (sum(v) / len(v)) if v else None} for k, v in stat.items()}
    out["total_all"] = sum(sum(v) for v in stat.values())
    out["delta_if_applied"] = saved       # 正數＝套用規則後總報酬增加（%點）
    return out


def load_history() -> list:
    try:
        with open(HISTORY, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []
