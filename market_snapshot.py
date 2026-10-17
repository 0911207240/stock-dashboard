"""台灣／亞洲／國際三大市場報價（不依賴 streamlit，供早安日報與儀表板共用）"""
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

# 名稱, yfinance 代號, 小數位
MARKETS = {
    "🇹🇼 台灣": [
        ("加權指數", "^TWII", 0),
        ("台幣兌美元", "TWD=X", 3),
    ],
    "🌏 亞洲": [
        ("日經 225", "^N225", 0),
        ("韓國 KOSPI", "^KS11", 0),
        ("香港恆生", "^HSI", 0),
        ("上證綜指", "000001.SS", 0),
    ],
    "🌎 國際": [
        ("S&P 500", "^GSPC", 0),
        ("那斯達克", "^IXIC", 0),
        ("費城半導體", "^SOX", 0),
        ("美國 10 年債殖利率 %", "^TNX", 3),
        ("美元指數", "DX-Y.NYB", 2),
        ("WTI 原油", "CL=F", 2),
        ("黃金", "GC=F", 1),
    ],
}


def fetch_quote(ticker: str):
    """回傳 (最新收盤, 前一日收盤, 資料日 MM-DD)；抓不到回 None，不補值"""
    try:
        s = yf.download(ticker, period="10d", progress=False, auto_adjust=False)["Close"]
        if hasattr(s, "columns"):
            s = s.iloc[:, 0]
        s = s.dropna()
        if len(s) < 2:
            return None
        return float(s.iloc[-1]), float(s.iloc[-2]), s.index[-1].strftime("%m-%d")
    except Exception as e:
        print(f"[市場] {ticker} 抓取失敗：{e}")
        return None


def fetch_markets(quote=fetch_quote) -> dict:
    """{群組: [(名稱, 小數位, quote 或 None)]}"""
    flat = [(g, n, t, d) for g, items in MARKETS.items() for n, t, d in items]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda x: quote(x[2]), flat))
    out: dict = {g: [] for g in MARKETS}
    for (g, n, _, d), q in zip(flat, results):
        out[g].append((n, d, q))
    return out


def format_markets(data: dict) -> str:
    lines = ["📊 三大市場"]
    any_ok = False
    for group, rows in data.items():
        parts = []
        for name, digits, q in rows:
            if q is None:
                continue
            any_ok = True
            last, prev, _ = q
            parts.append(f"{name} {last:,.{digits}f}（{(last - prev) / prev * 100:+.2f}%）")
        if parts:
            lines.append(f"  {group}：" + "｜".join(parts))
    return "\n".join(lines) if any_ok else ""
