import pandas as pd
import ta

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    # RSI（14日標準 + 6日短週期，短RSI對當沖更靈敏）
    df["RSI"]  = ta.momentum.RSIIndicator(close, window=14).rsi()
    df["RSI6"] = ta.momentum.RSIIndicator(close, window=6).rsi()

    # MACD
    macd = ta.trend.MACD(close)
    df["MACD"] = macd.macd()
    df["MACD_signal"] = macd.macd_signal()
    df["MACD_diff"] = macd.macd_diff()

    # KD (Stochastic)
    stoch = ta.momentum.StochasticOscillator(high, low, close, window=9, smooth_window=3)
    df["K"] = stoch.stoch()
    df["D"] = stoch.stoch_signal()

    # 均線
    df["MA5"] = close.rolling(5).mean()
    df["MA20"] = close.rolling(20).mean()
    df["MA60"] = close.rolling(60).mean()

    # 成交量均線
    df["Vol_MA5"] = volume.rolling(5).mean()
    df["Vol_ratio"] = volume / df["Vol_MA5"]

    # 布林通道
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df["BB_upper"] = bb.bollinger_hband()
    df["BB_lower"] = bb.bollinger_lband()

    # 威廉指標 %R（-100~0，低於-80超賣，高於-20超買）
    df["WR"] = ta.momentum.WilliamsRIndicator(high, low, close, lbp=14).williams_r()

    # ATR 真實波幅（14日），轉成佔股價 % → 波段操作參考
    df["ATR"] = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    df["ATR_pct"] = df["ATR"] / close * 100

    # 滾動20日加權均價（注意：此為跨日成本均線，非盤內重置的標準VWAP）
    tp = (high + low + close) / 3
    df["VWAP_MA20"]   = (tp * volume).rolling(20).sum() / volume.rolling(20).sum()
    df["VWAP_MA_dev"] = (close - df["VWAP_MA20"]) / df["VWAP_MA20"] * 100

    # ADX 趨勢強度（14日）
    # ADX < 20 = 震盪盤無方向，訊號可信度低；> 25 才有明確趨勢
    adx_ind = ta.trend.ADXIndicator(high, low, close, window=14)
    df["ADX"]     = adx_ind.adx()
    df["ADX_pos"] = adx_ind.adx_pos()   # +DI 多方力道
    df["ADX_neg"] = adx_ind.adx_neg()   # -DI 空方力道

    # OBV 能量潮（主力進出場確認）
    # OBV 上升 = 主力買進；OBV 背離（股價漲但 OBV 跌）= 假突破警示
    df["OBV"]       = ta.volume.OnBalanceVolumeIndicator(close, volume).on_balance_volume()
    df["OBV_MA20"]  = df["OBV"].rolling(20).mean()
    df["OBV_slope"] = df["OBV"].diff(5)   # 5日斜率，正值代表主力持續進場

    return df

def detect_signals(df: pd.DataFrame) -> list[dict]:
    signals = []
    if len(df) < 2:
        return signals

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # RSI 超賣反彈
    if prev["RSI"] < 30 and latest["RSI"] >= 30:
        signals.append({"type": "buy", "indicator": "RSI", "msg": f"RSI 從超賣區回升 ({latest['RSI']:.1f})"})
    if prev["RSI"] > 70 and latest["RSI"] <= 70:
        signals.append({"type": "sell", "indicator": "RSI", "msg": f"RSI 從超買區回落 ({latest['RSI']:.1f})"})

    # MACD 黃金/死亡交叉
    if prev["MACD_diff"] < 0 and latest["MACD_diff"] >= 0:
        signals.append({"type": "buy", "indicator": "MACD", "msg": "MACD 黃金交叉"})
    if prev["MACD_diff"] > 0 and latest["MACD_diff"] <= 0:
        signals.append({"type": "sell", "indicator": "MACD", "msg": "MACD 死亡交叉"})

    # KD 黃金/死亡交叉
    if prev["K"] < prev["D"] and latest["K"] >= latest["D"] and latest["K"] < 50:
        signals.append({"type": "buy", "indicator": "KD", "msg": f"KD 黃金交叉 (K={latest['K']:.1f})"})
    if prev["K"] > prev["D"] and latest["K"] <= latest["D"] and latest["K"] > 50:
        signals.append({"type": "sell", "indicator": "KD", "msg": f"KD 死亡交叉 (K={latest['K']:.1f})"})

    # 均線多頭排列（今日剛形成，昨日尚未滿足）
    bull_now  = latest["MA5"] > latest["MA20"] > latest["MA60"]
    bull_prev = prev["MA5"]   > prev["MA20"]   > prev["MA60"]
    if bull_now and not bull_prev:
        signals.append({"type": "buy", "indicator": "MA", "msg": "均線剛形成多頭排列 (MA5>MA20>MA60)"})

    # 爆量
    if latest["Vol_ratio"] > 2:
        signals.append({"type": "watch", "indicator": "VOL", "msg": f"成交量爆量 ({latest['Vol_ratio']:.1f}x 均量)"})

    # 布林通道突破
    if prev["Close"].item() <= prev["BB_lower"].item() and latest["Close"].item() > latest["BB_lower"].item():
        signals.append({"type": "buy", "indicator": "BB", "msg": "布林通道下軌反彈"})
    if prev["Close"].item() >= prev["BB_upper"].item() and latest["Close"].item() < latest["BB_upper"].item():
        signals.append({"type": "sell", "indicator": "BB", "msg": "布林通道上軌回落"})

    # 威廉指標 %R
    if prev["WR"] < -80 and latest["WR"] >= -80:
        signals.append({"type": "buy", "indicator": "WR", "msg": f"威廉%R 超賣反彈 ({latest['WR']:.1f})"})
    if prev["WR"] > -20 and latest["WR"] <= -20:
        signals.append({"type": "sell", "indicator": "WR", "msg": f"威廉%R 超買回落 ({latest['WR']:.1f})"})

    return signals

def score(signals: list[dict]) -> int:
    s = 0
    for sig in signals:
        if sig["type"] == "buy":
            s += 1
        elif sig["type"] == "sell":
            s -= 1
    return s

def calc_support_resistance(df: pd.DataFrame) -> dict:
    close = df["Close"].squeeze()
    return {
        "support_20":    float(close.tail(20).min()),
        "resistance_20": float(close.tail(20).max()),
        "support_60":    float(close.tail(60).min()),
        "resistance_60": float(close.tail(60).max()),
    }

def detect_pre_signals(df: pd.DataFrame) -> list[dict]:
    """偵測尚未觸發、但即將發生的訊號（卡位用）"""
    pre = []
    if len(df) < 3:
        return pre
    latest = df.iloc[-1]
    prev   = df.iloc[-2]

    def fv(col, row=None):
        r = row if row is not None else latest
        v = r[col]
        return float(v) if pd.notna(v) else None

    rsi       = fv("RSI")
    macd_diff = fv("MACD_diff")
    macd_prev = fv("MACD_diff", prev)
    k, d      = fv("K"), fv("D")
    k_prev    = fv("K", prev)
    price     = fv("Close")
    bb_upper  = fv("BB_upper")
    bb_lower  = fv("BB_lower")

    if rsi and 30 <= rsi <= 45:
        pre.append({"msg": f"RSI 接近超賣區（{rsi:.1f}），反彈機率上升", "conf": 1})

    if macd_diff and macd_prev and macd_diff < 0 and macd_diff > macd_prev:
        pre.append({"msg": f"MACD 差值收斂中（{macd_diff:.3f}），接近黃金交叉", "conf": 1})

    if k and d and k_prev and k < d and k > k_prev and (d - k) < 5:
        pre.append({"msg": f"KD 即將黃金交叉（K={k:.1f} D={d:.1f}）", "conf": 2})

    if price:
        sr = calc_support_resistance(df)
        gap = abs(price - sr["support_20"]) / price * 100
        if gap < 3:
            pre.append({"msg": f"股價距近20日支撐僅 {gap:.1f}%（支撐 {sr['support_20']:.2f}）", "conf": 1})

    if bb_upper and bb_lower and price:
        bw = (bb_upper - bb_lower) / price * 100
        if bw < 6:
            pre.append({"msg": f"布林通道收窄（寬度 {bw:.1f}%），大波動即將出現", "conf": 1})

    return pre

def pre_score(pre_signals: list[dict]) -> int:
    return sum(s["conf"] for s in pre_signals)

def calc_week52(df: pd.DataFrame) -> dict:
    close = df["Close"].squeeze()
    year_high = float(close.max())
    year_low  = float(close.min())
    price     = float(close.iloc[-1])
    pct = (price - year_low) / (year_high - year_low) * 100 if year_high != year_low else 50.0
    return {"year_high": year_high, "year_low": year_low, "week52_pct": pct}
