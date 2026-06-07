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

    # ── ADX 趨勢強度篩選 ────────────────────────────────
    # 震盪盤中所有動能訊號可信度大幅下降，ADX<20 直接略過
    adx     = float(latest.get("ADX", 25.0)) if pd.notna(latest.get("ADX")) else 25.0
    adx_pos = float(latest.get("ADX_pos", 25.0)) if pd.notna(latest.get("ADX_pos")) else 25.0
    adx_neg = float(latest.get("ADX_neg", 25.0)) if pd.notna(latest.get("ADX_neg")) else 25.0
    if adx < 20:
        result["signals"] = [f"⚠️ ADX {adx:.0f}｜震盪盤無明確趨勢，跳過"]
        return result
    elif adx < 25:
        adx_mult = 0.75
        signals.append(f"⚠️ ADX {adx:.0f} 趨勢偏弱")
    else:
        adx_mult = 1.0
        direction = "多方主導" if adx_pos > adx_neg else "空方主導"
        signals.append(f"ADX {adx:.0f} 趨勢明確（{direction}）")

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
        trust_net   = inst_data.get("trust_net",   0)

        # 三大法人合計
        if total_net > 2000:
            chip_score += 15
            signals.append(f"法人大買 {total_net:,}張")
        elif total_net > 500:
            chip_score += 10
            signals.append(f"法人買超 {total_net:,}張")
        elif total_net > 0:
            chip_score += 5
        elif total_net < -1000:
            chip_score -= 15
            signals.append(f"法人大賣 {abs(total_net):,}張")
        elif total_net < 0:
            chip_score -= 5

        # 外資
        if foreign_net > 1000:
            chip_score += 8
            signals.append(f"外資大買 {foreign_net:,}張")
        elif foreign_net > 200:
            chip_score += 4
            signals.append(f"外資買超 {foreign_net:,}張")
        elif foreign_net < -500:
            chip_score -= 5
            signals.append(f"外資賣超 {abs(foreign_net):,}張")

        # 投信（穩定籌碼，買超代表中期信心）
        if trust_net > 200:
            chip_score += 7
            signals.append(f"投信大買 {trust_net:,}張")
        elif trust_net > 50:
            chip_score += 4
            signals.append(f"投信買超 {trust_net:,}張")
        elif trust_net < -100:
            chip_score -= 5
            signals.append(f"投信賣超 {abs(trust_net):,}張")

    if margin_data:
        margin_change = margin_data.get("margin_change", 0)
        short_change  = margin_data.get("short_change",  0)
        margin_ratio  = margin_data.get("margin_ratio",  0)

        # 融資
        if margin_change > 200:
            chip_score += 5
            signals.append(f"融資增 {margin_change:,}張")
        elif margin_change < -500:
            chip_score -= 5
            signals.append(f"融資大減 {abs(margin_change):,}張")

        # 融券（空方回補是軋空訊號，大增代表空方加壓）
        if short_change < -200:
            chip_score += 5
            signals.append(f"融券大減 {abs(short_change):,}張（空方回補）")
        elif short_change > 300:
            chip_score -= 8
            signals.append(f"融券大增 {short_change:,}張（空方加壓）")

        # 券資比（高券資比代表籌碼偏空，風險上升）
        if margin_ratio > 20:
            chip_score -= 5
            signals.append(f"⚠️ 券資比 {margin_ratio:.1f}%，籌碼偏空")
        elif margin_ratio > 10:
            signals.append(f"券資比 {margin_ratio:.1f}%，留意")
    # OBV 能量潮（主力進出場確認，補充法人資料）
    obv       = float(latest.get("OBV",       0)) if pd.notna(latest.get("OBV"))       else 0
    obv_ma    = float(latest.get("OBV_MA20",  0)) if pd.notna(latest.get("OBV_MA20"))  else 0
    obv_slope = float(latest.get("OBV_slope", 0)) if pd.notna(latest.get("OBV_slope")) else 0
    prev_obv  = float(prev.get("OBV",         0)) if pd.notna(prev.get("OBV"))         else 0

    if obv_ma != 0:
        if obv > obv_ma and obv_slope > 0:
            chip_score += 8
            signals.append("✅ OBV持續上升，主力持續布局")
        elif obv < obv_ma and obv_slope < 0:
            chip_score -= 8
            signals.append("⚠️ OBV持續下降，籌碼外流")
        elif obv > obv_ma:
            chip_score += 3
            signals.append("OBV站上均線，籌碼偏多")

        # 量價背離偵測
        if is_up_day and obv < prev_obv:
            chip_score -= 5
            signals.append("⚠️ 量價背離：股價漲但OBV跌，假突破風險")
        elif not is_up_day and obv > prev_obv:
            chip_score += 2
            signals.append("股價跌但OBV支撐，跌勢有限")

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

    # Fix 8：套用維度倍率（回測後可動態調整）+ ADX 趨勢修正
    mults = load_multipliers()
    weighted = (
        breakdown["量能"]   * mults["量能"]   +
        breakdown["籌碼"]   * mults["籌碼"]   +
        breakdown["技術"]   * mults["技術"]   +
        breakdown["波動度"] * mults["波動度"]
    )
    result["score"]     = max(0, min(100, int(weighted * adx_mult)))
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
    pre_analyzed: bool = False,
    market_df: pd.DataFrame = None,
    regime: dict = None,
) -> list[dict]:
    """從 all_data 篩出隔日當沖候選清單（僅台股，排除基本面偏弱）"""
    from analyzer import add_indicators, calc_beta_rs, calc_mdd
    from fundamental_filter import is_fundamentally_weak
    from signal_log import get_stock_win_rate
    from earnings_calendar import has_earnings_risk
    regime_state = (regime or {}).get("state", "盤整")

    candidates = []
    for name, df in all_data.items():
        ticker = watchlist.get(name, "")
        if not is_tw_stock(ticker) or df is None or df.empty:
            continue
        if is_fundamentally_weak(ticker):
            continue
        earnings_risk = has_earnings_risk(name, ticker, days_ahead=3)

        if not pre_analyzed:
            df = add_indicators(df)
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

        # Beta 係數 + 相對強弱 RS
        brs  = calc_beta_rs(df, market_df)
        beta = brs["beta"]
        rs5  = brs["rs5"]
        rs20 = brs["rs20"]

        # Beta / RS 大盤連動加分（regime 感知）
        beta_bonus = 0
        beta_sigs  = []
        if regime_state == "多頭":
            if beta > 1.3:
                beta_bonus = 5
                beta_sigs.append(f"✅ 高β {beta:.1f}，多頭市場加成")
            elif beta < 0.7:
                beta_bonus = -5
                beta_sigs.append(f"⚠️ 低β {beta:.1f}，多頭反應遲鈍")
        elif regime_state == "空頭":
            if beta < 0.8:
                beta_bonus = 3
                beta_sigs.append(f"🛡️ 低β {beta:.1f}，空頭防禦性佳")
            elif beta > 1.3:
                beta_bonus = -5
                beta_sigs.append(f"⚠️ 高β {beta:.1f}，空頭跌幅放大")

        rs_bonus = 0
        if rs5 > 1.2 and rs20 > 1.2:
            rs_bonus = 5
            beta_sigs.append(f"✅ 持續強於大盤（RS5={rs5:.1f}x RS20={rs20:.1f}x）")
        elif rs5 < 0.8 and rs20 < 0.8:
            rs_bonus = -3
            beta_sigs.append(f"⚠️ 持續弱於大盤（RS5={rs5:.1f}x）")
        elif rs5 > 1.2:
            beta_sigs.append(f"近期強於大盤（RS5={rs5:.1f}x）")

        # MDD 最大回撤風控
        mdd_data  = calc_mdd(df, window=20)
        mdd_20    = mdd_data["mdd_20"]
        mdd_60    = mdd_data["mdd_60"]
        mdd_bonus = 0
        mdd_sig   = ""
        if mdd_20 > 20:
            mdd_bonus = -10
            mdd_sig   = f"⛔ 近20日MDD {mdd_20:.1f}%，籌碼極不穩定"
        elif mdd_20 > 15:
            mdd_bonus = -5
            mdd_sig   = f"⚠️ 近20日MDD {mdd_20:.1f}%，回撤偏大"
        elif mdd_20 > 10:
            mdd_bonus = -2
            mdd_sig   = f"近20日MDD {mdd_20:.1f}%，留意波動"
        elif mdd_20 < 5:
            mdd_bonus = 3
            mdd_sig   = f"✅ 近20日MDD {mdd_20:.1f}%，走勢穩健"
        if mdd_sig:
            beta_sigs.append(mdd_sig)

        # 財報前 3 日降低評分（不確定性過高）
        earnings_penalty = -15 if earnings_risk else 0
        if earnings_risk:
            beta_sigs.append("⚠️ 財報 3 日內，波動風險極高")

        adjusted_score = max(0, min(100, result["score"] + beta_bonus + rs_bonus + mdd_bonus + earnings_penalty))

        # 凱利公式：根據個股歷史勝率動態調整倉位建議（半凱利，上限 1.5x）
        wr_data    = get_stock_win_rate(name)
        kelly_mult = 1.0
        hist_wr    = wr_data.get("win_rate")
        if hist_wr is not None:
            p   = hist_wr / 100
            q   = 1 - p
            b   = max(ee["rr2"], 1.0)
            raw = max(0.0, (p * b - q) / b)
            kelly_mult = round(min(raw * 2, 1.5), 1)

        candidates.append({
            "name":        name,
            "ticker":      ticker,
            "score":       adjusted_score,
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
            "kelly_mult":  kelly_mult,
            "hist_wr":     hist_wr,
            "beta":        beta,
            "rs5":         rs5,
            "rs20":        rs20,
            "mdd_20":        mdd_20,
            "mdd_60":        mdd_60,
            "earnings_risk": earnings_risk,
            "beta_sigs":     beta_sigs,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_n]
