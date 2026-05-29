"""隔日當沖評分引擎（含 Fix 1-3, 5-6, 8）"""
import pandas as pd
from scoring_config import load_multipliers


def is_tw_stock(ticker: str) -> bool:
    return ticker.endswith(".TW") or ticker.endswith(".TWO")


def calc_daytrade_score(
    df: pd.DataFrame,
    inst_data: dict = None,
    margin_data: dict = None,
) -> dict:
    """
    隔日當沖潛力評分（0-100）
    Fix 1: 成交金額篩選（取代股數）
    Fix 2: 量能加入漲跌方向判斷
    Fix 5: RSI6 短週期指標
    Fix 6: VWAP_MA20（改名釐清定位）
    Fix 8: 維度倍率可調整
    回傳: {"score": int, "breakdown": dict, "signals": list[str]}
    """
    result = {"score": 0, "breakdown": {}, "signals": []}
    if df is None or len(df) < 20:
        return result

    latest     = df.iloc[-1]
    prev       = df.iloc[-2] if len(df) > 1 else latest
    close      = float(latest["Close"])
    high_price = float(latest.get("High",  close))
    prev_close = float(prev["Close"])
    volume     = float(latest["Volume"])
    atr_raw    = float(latest.get("ATR", close * 0.02)) if pd.notna(latest.get("ATR")) else close * 0.02

    # Fix 1 ── 成交金額篩選（$30M以上才具流動性）
    turnover = close * volume
    if close < 10 or turnover < 30_000_000:
        return result

    # Fix 2 ── 方向分析（上影線 & 收黑）
    is_up_day    = close >= prev_close
    upper_shadow = high_price - max(close, prev_close)
    long_upper   = upper_shadow > atr_raw * 0.4

    score = 0
    breakdown = {}
    signals = []

    # ── 1. 量能面（基礎30分 + 方向修正）───────────────
    vol_ratio = float(latest.get("Vol_ratio", 1.0)) if pd.notna(latest.get("Vol_ratio")) else 1.0
    vol_score = 0
    if vol_ratio >= 3.0:
        vol_score = 30
        signals.append(f"爆量 {vol_ratio:.1f}x 均量")
    elif vol_ratio >= 2.0:
        vol_score = 22
        signals.append(f"大量 {vol_ratio:.1f}x 均量")
    elif vol_ratio >= 1.5:
        vol_score = 15
        signals.append(f"放量 {vol_ratio:.1f}x 均量")
    elif vol_ratio >= 1.0:
        vol_score = 8
    elif vol_ratio < 0.5:
        vol_score = -10
        signals.append("縮量萎縮")

    # Fix 2：方向修正
    if vol_score > 0:
        if not is_up_day:
            vol_score = max(0, int(vol_score * 0.4))
            signals.append("⚠️ 爆量收黑，留意主力出貨")
        elif long_upper:
            vol_score = int(vol_score * 0.7)
            signals.append("⚠️ 上影線長，高點賣壓明顯")
        elif is_up_day and not long_upper and vol_ratio >= 1.5:
            vol_score = min(33, vol_score + 3)
            signals.append("✅ 放量紅K無長上影，強勢收盤")
    breakdown["量能"] = vol_score
    score += vol_score

    # ── 2. 籌碼面（30分）─────────────────────────────
    chip_score = 0
    if inst_data:
        total_net   = inst_data.get("total_net",   0)
        foreign_net = inst_data.get("foreign_net", 0)
        if total_net > 2000:
            chip_score += 20
            signals.append(f"法人大買 {total_net:,}張")
        elif total_net > 500:
            chip_score += 14
            signals.append(f"法人買超 {total_net:,}張")
        elif total_net > 0:
            chip_score += 7
        elif total_net < -1000:
            chip_score -= 15
            signals.append(f"法人大賣 {abs(total_net):,}張")
        elif total_net < 0:
            chip_score -= 5
        if foreign_net > 1000:
            chip_score += 10
            signals.append(f"外資大買 {foreign_net:,}張")
        elif foreign_net > 200:
            chip_score += 5
    if margin_data:
        margin_change = margin_data.get("margin_change", 0)
        if margin_change > 200:
            chip_score += 5
            signals.append(f"融資增 {margin_change:,}張")
        elif margin_change < -500:
            chip_score -= 5
            signals.append(f"融資大減 {abs(margin_change):,}張")
    breakdown["籌碼"] = chip_score
    score += chip_score

    # ── 3. 技術面（20分 + VWAP & RSI6 加成）─────────
    tech_score = 0

    # RSI14
    rsi = float(latest.get("RSI", 50.0)) if pd.notna(latest.get("RSI")) else 50.0
    if 40 <= rsi <= 65:
        tech_score += 10
        signals.append(f"RSI健康 {rsi:.0f}")
    elif rsi < 35:
        tech_score += 5
        signals.append(f"RSI超賣反彈 {rsi:.0f}")
    elif rsi > 75:
        tech_score -= 10
        signals.append(f"RSI超買 {rsi:.0f}，追高風險")

    # Fix 5：RSI6 短週期輔助
    rsi6 = float(latest.get("RSI6", 50.0)) if pd.notna(latest.get("RSI6")) else 50.0
    if rsi6 < 20 and rsi > 30:
        tech_score += 3
        signals.append(f"短RSI超賣({rsi6:.0f})，回彈機率高")
    elif rsi6 > 80 and rsi > 70:
        tech_score -= 5
        signals.append(f"短RSI雙超買({rsi6:.0f})，回調風險")

    # 均線
    ma5  = float(latest.get("MA5",  close)) if pd.notna(latest.get("MA5"))  else close
    ma20 = float(latest.get("MA20", close)) if pd.notna(latest.get("MA20")) else close
    if ma5 > ma20:
        tech_score += 5

    # 布林通道
    bb_upper = float(latest.get("BB_upper", close * 1.04)) if pd.notna(latest.get("BB_upper")) else close * 1.04
    bb_lower = float(latest.get("BB_lower", close * 0.96)) if pd.notna(latest.get("BB_lower")) else close * 0.96
    bb_range = bb_upper - bb_lower
    if bb_range > 0:
        bb_pos = (close - bb_lower) / bb_range
        if bb_pos < 0.35:
            tech_score += 5
            signals.append(f"布林下軌區 {bb_pos*100:.0f}%")
        elif bb_pos > 0.9:
            tech_score -= 5

    # Fix 6：VWAP_MA20（改名後正確讀取）
    vwap     = float(latest.get("VWAP_MA20",   close)) if pd.notna(latest.get("VWAP_MA20"))   else close
    vwap_dev = float(latest.get("VWAP_MA_dev", 0.0))   if pd.notna(latest.get("VWAP_MA_dev")) else 0.0
    if close > vwap and 0 < vwap_dev < 3:
        tech_score += 5
        signals.append(f"站上VWAP_MA +{vwap_dev:.1f}%")
    elif close > vwap and vwap_dev >= 3:
        tech_score -= 3
        signals.append(f"VWAP_MA偏離過大 +{vwap_dev:.1f}%")
    elif close < vwap and vwap_dev > -4:
        tech_score += 2
        signals.append(f"VWAP_MA下方 {vwap_dev:.1f}%，注意反彈")

    breakdown["技術"] = tech_score
    score += tech_score

    # ── 4. 波動度面（20分）───────────────────────────
    atr_score = 0
    atr_pct   = float(latest.get("ATR_pct", 0.0)) if pd.notna(latest.get("ATR_pct")) else 0.0
    if 1.5 <= atr_pct <= 4.0:
        atr_score = 20
        signals.append(f"ATR {atr_pct:.1f}% 理想波動")
    elif 1.0 <= atr_pct < 1.5:
        atr_score = 10
        signals.append(f"ATR {atr_pct:.1f}% 波動偏低")
    elif atr_pct > 4.0:
        atr_score = 10
        signals.append(f"ATR {atr_pct:.1f}% 高波動，注意風控")
    breakdown["波動度"] = atr_score
    score += atr_score

    # Fix 8：套用維度倍率（回測後可動態調整）
    mults = load_multipliers()
    weighted = (
        breakdown["量能"]   * mults["量能"]   +
        breakdown["籌碼"]   * mults["籌碼"]   +
        breakdown["技術"]   * mults["技術"]   +
        breakdown["波動度"] * mults["波動度"]
    )
    result["score"]     = max(0, min(100, int(weighted)))
    result["breakdown"] = breakdown
    result["signals"]   = signals
    return result


def calc_entry_exit(df: pd.DataFrame, score: int) -> dict:
    """
    進場甜蜜點區間 + 兩段停利 + 停損
    甜蜜點低：BB下軌/MA5/VWAP_MA20 三者取最靠近昨收的支撐，最多允許回檔1.5%
    甜蜜點高：昨收 +0.5%（小幅追漲可接受）
    停損：區間中點 - 0.8×ATR，不低於前日低點 - 0.3×ATR，且不超過入場的2%
    停利①：RR=1.5，建議出半倉
    停利②：RR=2.0(score≥60) / 1.8(score≥40) / 1.5(其他)，全出
    """
    latest   = df.iloc[-1]
    close    = float(latest["Close"])
    low_1    = float(latest["Low"])

    atr      = float(latest.get("ATR",       close * 0.02)) if pd.notna(latest.get("ATR"))      else close * 0.02
    bb_lower = float(latest.get("BB_lower",  close * 0.96)) if pd.notna(latest.get("BB_lower")) else close * 0.96
    ma5      = float(latest.get("MA5",       close))        if pd.notna(latest.get("MA5"))      else close
    vwap     = float(latest.get("VWAP_MA20", close))        if pd.notna(latest.get("VWAP_MA20")) else close

    # 甜蜜點：取三支撐中最靠近昨收的（最大值），限縮在昨收-1.5%以內
    supports = [s for s in [bb_lower, ma5, vwap] if s < close]
    nearest  = max(supports) if supports else close * 0.985
    entry_low  = round(max(nearest, close * 0.985), 2)
    entry_high = round(close * 1.005, 2)
    entry_mid  = round((entry_low + close) / 2, 2)

    # 停損：中點 - 0.8×ATR，但不低於前日最低-0.3×ATR；且限制最大虧損2%
    stop = round(max(
        entry_mid - atr * 0.8,
        low_1     - atr * 0.3,
        entry_mid * 0.98,
    ), 2)

    risk = max(entry_mid - stop, 0.01)

    # 兩段停利
    rr2  = 2.0 if score >= 60 else (1.8 if score >= 40 else 1.5)
    tp1  = round(entry_mid + risk * 1.5, 2)
    tp2  = round(entry_mid + risk * rr2,  2)

    return {
        "entry_low":   entry_low,
        "entry_high":  entry_high,
        "entry_mid":   entry_mid,
        "stop":        stop,
        "tp1":         tp1,
        "tp2":         tp2,
        "rr1":         round((tp1 - entry_mid) / risk, 1),
        "rr2":         round((tp2 - entry_mid) / risk, 1),
        "risk_pct":    round(risk / entry_mid * 100, 2),
        "upside_pct1": round((tp1 - entry_mid) / entry_mid * 100, 2),
        "upside_pct2": round((tp2 - entry_mid) / entry_mid * 100, 2),
    }


def get_daytrade_candidates(
    all_data: dict,
    watchlist: dict,
    inst_cache:   dict = None,
    margin_cache: dict = None,
    top_n: int = 10,
) -> list[dict]:
    """從 all_data 篩出隔日當沖候選清單（僅台股）"""
    from analyzer import add_indicators

    candidates = []
    for name, df in all_data.items():
        ticker = watchlist.get(name, "")
        if not is_tw_stock(ticker) or df is None or df.empty:
            continue

        df     = add_indicators(df)
        result = calc_daytrade_score(
            df,
            inst_data=(inst_cache   or {}).get(name),
            margin_data=(margin_cache or {}).get(name),
        )
        if result["score"] == 0:
            continue

        latest = df.iloc[-1]
        prev   = df.iloc[-2] if len(df) > 1 else latest
        price  = float(latest["Close"])
        chg    = (price - float(prev["Close"])) / float(prev["Close"]) * 100
        vr     = float(latest.get("Vol_ratio", 1.0)) if pd.notna(latest.get("Vol_ratio")) else 1.0
        atr    = float(latest.get("ATR_pct",   0.0)) if pd.notna(latest.get("ATR_pct"))   else 0.0
        bd     = result["breakdown"]
        ee     = calc_entry_exit(df, result["score"])

        candidates.append({
            "name":        name,
            "ticker":      ticker,
            "score":       result["score"],
            "price":       price,
            "change_pct":  chg,
            "vol_ratio":   vr,
            "atr_pct":     atr,
            "vol_score":   bd.get("量能",   0),
            "chip_score":  bd.get("籌碼",   0),
            "tech_score":  bd.get("技術",   0),
            "atr_score":   bd.get("波動度", 0),
            "signals":     result["signals"],
            "entry_low":   ee["entry_low"],
            "entry_high":  ee["entry_high"],
            "entry_mid":   ee["entry_mid"],
            "stop":        ee["stop"],
            "tp1":         ee["tp1"],
            "tp2":         ee["tp2"],
            "rr1":         ee["rr1"],
            "rr2":         ee["rr2"],
            "risk_pct":    ee["risk_pct"],
            "upside_pct1": ee["upside_pct1"],
            "upside_pct2": ee["upside_pct2"],
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_n]
