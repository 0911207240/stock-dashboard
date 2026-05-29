"""
歷史回測模組
Fix 4：加入 0.3% 滑價模擬 + 大盤過濾（大盤跌>1.5% 當天跳過）
額外：計算各評分維度與報酬相關係數，供 Fix 8 動態調整權重
"""
import math
import pandas as pd


_SLIPPAGE = 0.003        # 0.3% 滑價（含買賣價差與市場衝擊）
_MARKET_FILTER_PCT = -1.5  # 大盤當日跌幅超過此值 → 不做多


def run_backtest(
    df: pd.DataFrame,
    ticker: str,
    name: str,
    min_score: int = 40,
    lookback_days: int = 90,
    taiex_chg_dict: dict = None,   # {date_str: change_pct}
    slippage: float = _SLIPPAGE,
) -> dict:
    """
    單股歷史回測。
    進出場：
    - 訊號日 EOD 評分 → 隔天開盤加滑價進場
    - HIGH >= target → 勝；LOW <= stop → 敗
    - 兩者同日 → 保守計敗；都未觸 → 收盤結算
    Fix 4：大盤跌超 1.5% 的交易日自動跳過。
    """
    from analyzer import add_indicators
    from daytrade_scorer import calc_daytrade_score, calc_entry_exit, is_tw_stock

    if not is_tw_stock(ticker) or df is None or len(df) < 30:
        return {}

    df = add_indicators(df.copy())
    start_idx = max(20, len(df) - lookback_days - 1)
    trades = []

    for i in range(start_idx, len(df) - 1):
        nxt      = df.iloc[i + 1]
        nxt_date = str(df.index[i + 1])[:10]

        # Fix 4：大盤過濾
        if taiex_chg_dict and taiex_chg_dict.get(nxt_date, 0) < _MARKET_FILTER_PCT:
            continue

        hist_df = df.iloc[: i + 1]
        result  = calc_daytrade_score(hist_df)
        if result["score"] < min_score:
            continue

        ee   = calc_entry_exit(hist_df, result["score"])
        tp1  = ee["tp1"]    # 用停利①作為保守勝出目標
        stop = ee["stop"]

        nxt_open  = float(nxt["Open"])
        nxt_high  = float(nxt["High"])
        nxt_low   = float(nxt["Low"])
        nxt_close = float(nxt["Close"])

        actual_entry = nxt_open * (1 + slippage)

        hit_tp   = nxt_high >= tp1
        hit_stop = nxt_low  <= stop

        if hit_tp and not hit_stop:
            outcome    = "win"
            exit_price = tp1
        elif hit_stop:                     # 含兩者同日 → 保守計敗
            outcome    = "loss"
            exit_price = stop
        else:                              # 收盤強制結算
            exit_price = nxt_close
            outcome    = "win" if exit_price > actual_entry else "loss"

        return_pct = (exit_price - actual_entry) / actual_entry * 100
        bd = result["breakdown"]

        trades.append({
            "date":        nxt_date,
            "score":       result["score"],
            "open":        round(nxt_open,       2),
            "entry":       round(actual_entry,   2),
            "exit":        round(exit_price,     2),
            "target":      target,
            "stop":        stop,
            "return_pct":  round(return_pct,     2),
            "outcome":     outcome,
            # 維度分數（供相關性分析）
            "vol_score":   bd.get("量能",   0),
            "chip_score":  bd.get("籌碼",   0),
            "tech_score":  bd.get("技術",   0),
            "atr_score":   bd.get("波動度", 0),
        })

    if not trades:
        return {}

    df_t   = pd.DataFrame(trades)
    wins   = df_t[df_t["outcome"] == "win"]
    losses = df_t[df_t["outcome"] == "loss"]

    win_rate = len(wins) / len(df_t) * 100
    avg_win  = wins["return_pct"].mean()   if len(wins)   > 0 else 0.0
    avg_loss = losses["return_pct"].mean() if len(losses) > 0 else 0.0

    gross_profit = avg_win  * len(wins)
    gross_loss   = abs(avg_loss * len(losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999.0

    returns = df_t["return_pct"] / 100
    sharpe  = round(returns.mean() / returns.std() * math.sqrt(252), 2) if returns.std() > 0 else 0.0

    consec = max_consec = 0
    for o in df_t["outcome"]:
        consec = consec + 1 if o == "loss" else 0
        max_consec = max(max_consec, consec)

    cum          = df_t["return_pct"].cumsum()
    max_drawdown = round((cum - cum.cummax()).min(), 2)

    return {
        "name":   name,
        "ticker": ticker,
        "trades": trades,
        "stats": {
            "total_trades":           len(df_t),
            "win_rate":               round(win_rate, 1),
            "avg_win_pct":            round(avg_win,  2),
            "avg_loss_pct":           round(avg_loss, 2),
            "profit_factor":          profit_factor,
            "total_return_pct":       round(df_t["return_pct"].sum(), 2),
            "sharpe":                 sharpe,
            "max_consecutive_losses": max_consec,
            "max_drawdown_pct":       max_drawdown,
        },
    }


def run_portfolio_backtest(
    all_data: dict,
    watchlist: dict,
    min_score: int = 40,
    lookback_days: int = 90,
    min_trades: int = 3,
    period: str = "1y",
) -> list[dict]:
    """批次回測所有台股，Fix 4：統一傳入大盤漲跌幅字典"""
    from daytrade_scorer import is_tw_stock
    from data_fetcher import fetch_taiex
    from analyzer import add_indicators as _ai

    # 抓大盤漲跌幅
    taiex_df = fetch_taiex(period=period)
    taiex_chg: dict = {}
    if not taiex_df.empty:
        chg = _ai(taiex_df)["Close"].pct_change() * 100
        taiex_chg = {str(d)[:10]: float(c) for d, c in chg.items() if pd.notna(c)}

    results = []
    for name, df in all_data.items():
        ticker = watchlist.get(name, "")
        if not is_tw_stock(ticker):
            continue
        r = run_backtest(df, ticker, name, min_score, lookback_days,
                         taiex_chg_dict=taiex_chg)
        if r and r.get("stats", {}).get("total_trades", 0) >= min_trades:
            results.append(r)

    results.sort(key=lambda x: x["stats"]["profit_factor"], reverse=True)
    return results


def aggregate_stats(results: list[dict]) -> dict:
    """彙整所有股票的回測統計"""
    if not results:
        return {}
    all_df = pd.concat(
        [pd.DataFrame(r["trades"]) for r in results if r.get("trades")],
        ignore_index=True,
    )
    if all_df.empty:
        return {}
    wins  = all_df[all_df["outcome"] == "win"]
    losses= all_df[all_df["outcome"] == "loss"]
    wr    = len(wins) / len(all_df) * 100
    aw    = wins["return_pct"].mean()   if len(wins)   > 0 else 0
    al    = losses["return_pct"].mean() if len(losses) > 0 else 0
    gp    = aw  * len(wins)
    gl    = abs(al * len(losses))
    return {
        "tested_stocks":    len(results),
        "total_trades":     len(all_df),
        "overall_win_rate": round(wr, 1),
        "overall_avg_win":  round(aw, 2),
        "overall_avg_loss": round(al, 2),
        "overall_pf":       round(gp / gl, 2) if gl > 0 else 999.0,
    }


def calc_dimension_correlation(results: list[dict]) -> dict:
    """
    計算各評分維度分數與實際報酬的相關係數。
    相關係數越高的維度對預測越重要，可用來調整 Fix 8 倍率。
    """
    all_trades = []
    for r in results:
        all_trades.extend(r.get("trades", []))
    if len(all_trades) < 10:
        return {}

    df = pd.DataFrame(all_trades)
    dims = {
        "量能": "vol_score",
        "籌碼": "chip_score",
        "技術": "tech_score",
        "波動度": "atr_score",
    }
    corrs = {}
    for label, col in dims.items():
        if col in df.columns:
            corr = df[col].corr(df["return_pct"])
            corrs[label] = round(corr, 3) if pd.notna(corr) else 0.0
    return corrs


def suggest_multipliers(corr_dict: dict) -> dict:
    """
    根據相關係數建議倍率（0.5–2.0）。
    相關性越高 → 倍率越高；負相關 → 降至 0.5。
    """
    from scoring_config import DEFAULTS
    if not corr_dict:
        return {k: 1.0 for k in DEFAULTS}

    pos = {k: max(0.0, v) for k, v in corr_dict.items()}
    total = sum(pos.values())
    if total == 0:
        return {k: 1.0 for k in DEFAULTS}

    avg = total / len(pos)
    suggested = {}
    for dim in DEFAULTS:
        c = corr_dict.get(dim, 0.0)
        if c <= 0:
            mult = 0.5
        else:
            mult = round(max(0.5, min(2.0, c / max(avg, 1e-6))), 2)
        suggested[dim] = mult
    return suggested


def auto_update_weights(
    all_data: dict,
    watchlist: dict,
    min_trades: int = 5,
    lookback_days: int = 90,
) -> dict:
    """
    執行全股回測 → 計算維度相關係數 → 更新 scoring_weights.json
    回傳摘要 dict，供 LINE 推播或 log 使用。
    只在累積交易筆數 >= min_trades * 股票數 的一半時才更新，避免樣本不足。
    """
    from scoring_config import save_multipliers, load_multipliers

    results = run_portfolio_backtest(
        all_data, watchlist,
        min_trades=min_trades,
        lookback_days=lookback_days,
    )
    if not results:
        return {"updated": False, "reason": "無足夠回測結果"}

    agg   = aggregate_stats(results)
    corrs = calc_dimension_correlation(results)
    if not corrs:
        return {"updated": False, "reason": "相關係數計算失敗（交易筆數不足）"}

    new_mults = suggest_multipliers(corrs)
    old_mults = load_multipliers()
    save_multipliers(new_mults)

    return {
        "updated":      True,
        "stocks_tested": agg.get("tested_stocks", 0),
        "total_trades":  agg.get("total_trades",  0),
        "win_rate":      agg.get("overall_win_rate", 0),
        "corr":          corrs,
        "old_weights":   old_mults,
        "new_weights":   new_mults,
    }
