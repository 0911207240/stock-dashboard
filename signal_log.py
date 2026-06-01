import json
import os
from datetime import datetime, timedelta

LOG_FILE         = os.path.join(os.path.dirname(__file__), "signal_history.json")
DAYTRADE_LOG     = os.path.join(os.path.dirname(__file__), "daytrade_history.json")


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


# ── 當沖推播結果追蹤 ──────────────────────────────────────

def _load_dt_log() -> list:
    if not os.path.exists(DAYTRADE_LOG):
        return []
    try:
        with open(DAYTRADE_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_dt_log(data: list):
    try:
        with open(DAYTRADE_LOG, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_daytrade_signal(candidates: list[dict]):
    """推播當沖候選時記錄進場目標，供隔日驗證"""
    log = _load_dt_log()
    today = datetime.now().strftime("%Y-%m-%d")
    for c in candidates:
        log.append({
            "push_date":  today,
            "name":       c["name"],
            "ticker":     c["ticker"],
            "score":      c["score"],
            "price":      c["price"],
            "entry_mid":  c.get("entry_mid",  c["price"]),
            "stop":       c.get("stop",       0),
            "tp1":        c.get("tp1",        0),
            "tp2":        c.get("tp2",        0),
            "result":     None,
            "exit_price": None,
            "return_pct": None,
        })
    _save_dt_log(log[-500:])


def update_daytrade_results(all_data: dict) -> list:
    """
    用最新 OHLC 回查未結案的當沖推播，判斷結果：
    - 停利② (High >= tp2)
    - 停利① (High >= tp1 but < tp2)
    - 停損   (Low <= stop)
    - 同日停損+停利 → 保守計停損
    - 3 個交易日內未觸及任何目標 → 未觸發（以收盤價結算）
    """
    log = _load_dt_log()
    changed = False
    for entry in log:
        if entry.get("result"):
            continue
        df = all_data.get(entry["name"])
        if df is None or df.empty:
            continue

        try:
            after = df[df.index.strftime("%Y-%m-%d") > entry["push_date"]]
        except Exception:
            continue
        if after.empty:
            continue

        nxt       = after.iloc[0]
        high      = float(nxt["High"])
        low       = float(nxt["Low"])
        close_nxt = float(nxt["Close"])
        stop      = entry["stop"]
        tp1       = entry["tp1"]
        tp2       = entry["tp2"]
        entry_mid = entry["entry_mid"]

        if low <= stop and high >= tp1:
            result, exit_price = "停損", stop          # 同日保守計停損
        elif high >= tp2:
            result, exit_price = "停利②", tp2
        elif high >= tp1:
            result, exit_price = "停利①", tp1
        elif low <= stop:
            result, exit_price = "停損", stop
        elif len(after) >= 3:
            result, exit_price = "未觸發", close_nxt   # 3日內未觸發以收盤結算
        else:
            continue                                    # 仍在等待中

        entry["result"]     = result
        entry["exit_price"] = round(exit_price, 2)
        entry["return_pct"] = round((exit_price - entry_mid) / entry_mid * 100, 2)
        changed = True

    if changed:
        _save_dt_log(log)
    return log


def calc_weekly_performance(taiex_df=None, weeks: int = 1) -> dict:
    """
    計算最近 N 週的當沖推播報酬 vs 大盤（TAIEX）
    taiex_df：已呼叫 add_indicators 的 DataFrame（可選）
    回傳：
      period_days     : 統計天數
      trades          : 已結案筆數
      avg_return      : 平均每筆報酬 %
      total_return    : 累計報酬 %（等權加總）
      taiex_return    : 大盤同期漲跌 %
      excess_return   : 超額報酬 %（avg_return - taiex_return/trade_days）
      win_rate        : 勝率 %
    """
    log  = _load_dt_log()
    days = weeks * 7
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    recent = [
        e for e in log
        if e.get("push_date", "") >= cutoff and e.get("result") and e["result"] != "未觸發"
    ]

    if not recent:
        base = {"period_days": days, "trades": 0, "avg_return": 0.0,
                "total_return": 0.0, "taiex_return": 0.0, "excess_return": 0.0, "win_rate": 0.0}
        return base

    returns   = [e.get("return_pct", 0) for e in recent]
    avg_ret   = round(sum(returns) / len(returns), 2)
    total_ret = round(sum(returns), 2)
    wins      = sum(1 for r in returns if r > 0)
    win_rate  = round(wins / len(returns) * 100, 1)

    # 大盤同期報酬
    taiex_ret = 0.0
    if taiex_df is not None and not taiex_df.empty:
        try:
            subset = taiex_df[taiex_df.index.strftime("%Y-%m-%d") >= cutoff]
            if len(subset) >= 2:
                taiex_ret = round(
                    (float(subset.iloc[-1]["Close"]) - float(subset.iloc[0]["Close"]))
                    / float(subset.iloc[0]["Close"]) * 100, 2
                )
        except Exception:
            pass

    return {
        "period_days":   days,
        "trades":        len(recent),
        "avg_return":    avg_ret,
        "total_return":  total_ret,
        "taiex_return":  taiex_ret,
        "excess_return": round(avg_ret - taiex_ret / max(days, 1), 2),
        "win_rate":      win_rate,
    }


def calc_monthly_performance(taiex_df=None) -> dict:
    """
    計算本自然月（1日至今）的當沖推播報酬 vs 大盤
    回傳格式與 calc_weekly_performance 相同，另加 month_str（如 "6月"）
    """
    now    = datetime.now()
    cutoff = now.replace(day=1).strftime("%Y-%m-%d")
    log    = _load_dt_log()

    recent = [
        e for e in log
        if e.get("push_date", "") >= cutoff and e.get("result") and e["result"] != "未觸發"
    ]

    month_str = f"{now.month}月"
    base = {"month_str": month_str, "trades": 0, "avg_return": 0.0,
            "total_return": 0.0, "taiex_return": 0.0, "excess_return": 0.0,
            "win_rate": 0.0, "tp1": 0, "tp2": 0, "stop": 0}

    if not recent:
        return base

    returns  = [e.get("return_pct", 0) for e in recent]
    avg_ret  = round(sum(returns) / len(returns), 2)
    total_ret= round(sum(returns), 2)
    wins     = sum(1 for r in returns if r > 0)
    tp1_n    = sum(1 for e in recent if e.get("result") == "停利①")
    tp2_n    = sum(1 for e in recent if e.get("result") == "停利②")
    stop_n   = sum(1 for e in recent if e.get("result") == "停損")

    taiex_ret = 0.0
    if taiex_df is not None and not taiex_df.empty:
        try:
            subset = taiex_df[taiex_df.index.strftime("%Y-%m-%d") >= cutoff]
            if len(subset) >= 2:
                taiex_ret = round(
                    (float(subset.iloc[-1]["Close"]) - float(subset.iloc[0]["Close"]))
                    / float(subset.iloc[0]["Close"]) * 100, 2
                )
        except Exception:
            pass

    return {
        "month_str":    month_str,
        "trades":       len(recent),
        "avg_return":   avg_ret,
        "total_return": total_ret,
        "taiex_return": taiex_ret,
        "excess_return":round(avg_ret - taiex_ret, 2),
        "win_rate":     round(wins / len(recent) * 100, 1),
        "tp1":          tp1_n,
        "tp2":          tp2_n,
        "stop":         stop_n,
    }


def daytrade_win_rate(log: list = None) -> dict:
    """計算當沖推播勝率（排除未觸發）"""
    if log is None:
        log = _load_dt_log()
    decided = [e for e in log if e.get("result") and e["result"] != "未觸發"]
    if not decided:
        return {"total": 0, "tp1": 0, "tp2": 0, "stop": 0, "win_rate": 0.0, "avg_return": 0.0}
    tp1_n  = sum(1 for e in decided if e["result"] == "停利①")
    tp2_n  = sum(1 for e in decided if e["result"] == "停利②")
    stop_n = sum(1 for e in decided if e["result"] == "停損")
    avg_r  = sum(e.get("return_pct", 0) for e in decided) / len(decided)
    return {
        "total":      len(decided),
        "tp1":        tp1_n,
        "tp2":        tp2_n,
        "stop":       stop_n,
        "win_rate":   round((tp1_n + tp2_n) / len(decided) * 100, 1),
        "avg_return": round(avg_r, 2),
    }


def get_stock_win_rate(name: str) -> dict:
    """
    回傳指定個股的歷史當沖推播勝率
    不足 5 筆 → 回傳 None（樣本不足，不調整評分）
    """
    log     = _load_dt_log()
    decided = [e for e in log
               if e.get("name") == name and e.get("result") and e["result"] != "未觸發"]
    if len(decided) < 5:
        return {"name": name, "total": len(decided), "win_rate": None, "avg_return": None}
    wins    = sum(1 for e in decided if e["result"] in ("停利①", "停利②"))
    avg_r   = sum(e.get("return_pct", 0) for e in decided) / len(decided)
    return {
        "name":       name,
        "total":      len(decided),
        "win_rate":   round(wins / len(decided) * 100, 1),
        "avg_return": round(avg_r, 2),
    }
