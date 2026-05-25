import pandas as pd
import ta

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].squeeze()
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    # RSI
    df["RSI"] = ta.momentum.RSIIndicator(close, window=14).rsi()

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

    # 均線多頭排列
    if latest["MA5"] > latest["MA20"] > latest["MA60"]:
        signals.append({"type": "buy", "indicator": "MA", "msg": "均線多頭排列 (MA5>MA20>MA60)"})

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
    """簡單評分：buy+1, sell-1, watch+0"""
    s = 0
    for sig in signals:
        if sig["type"] == "buy":
            s += 1
        elif sig["type"] == "sell":
            s -= 1
    return s
