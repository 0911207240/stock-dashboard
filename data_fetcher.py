import yfinance as yf
import pandas as pd

WATCHLIST = {
    # 科技 / ETF
    "台積電": "2330.TW",
    "鴻海": "2317.TW",
    "聯發科": "2454.TW",
    "台灣50": "0050.TW",
    "元大高股息": "0056.TW",
    # 美股
    "蘋果": "AAPL",
    "輝達": "NVDA",
    "微軟": "MSFT",
    # 銀行 / 金控
    "國泰金": "2882.TW",
    "富邦金": "2881.TW",
    "兆豐金": "2886.TW",
    "玉山金": "2884.TW",
    "中信金": "2891.TW",
    "第一金": "2892.TW",
    "華南金": "2880.TW",
    "台新金": "2887.TW",
    "元大金": "2885.TW",
    "合庫金": "5880.TW",
    # 水泥
    "台泥": "1101.TW",
    "亞泥": "1102.TW",
    "嘉泥": "1103.TW",
    "環泥": "1104.TW",
    "信大水泥": "1109.TW",
    "東泥": "1110.TW",
    # 航運
    "長榮": "2603.TW",
    "陽明": "2609.TW",
    "萬海": "2615.TW",
    # 石化 / 台塑四寶
    "台塑": "1301.TW",
    "南亞": "1303.TW",
    "台化": "1326.TW",
    "台塑化": "6505.TW",
    # 鋼鐵
    "中鋼": "2002.TW",
    "豐興": "2015.TW",
    # 半導體供應鏈
    "日月光投控": "3711.TW",
    "聯電": "2303.TW",
    "京元電子": "2449.TW",
    # 生技醫療
    "台灣生技ETF": "00881.TW",
    "東洋": "4105.TW",
}

SECTORS = {
    "全部": list(WATCHLIST.keys()),
    "科技/ETF": ["台積電", "鴻海", "聯發科", "台灣50", "元大高股息"],
    "美股": ["蘋果", "輝達", "微軟"],
    "銀行/金控": ["國泰金", "富邦金", "兆豐金", "玉山金", "中信金", "第一金", "華南金", "台新金", "元大金", "合庫金"],
    "水泥": ["台泥", "亞泥", "嘉泥", "環泥", "信大水泥", "東泥"],
    "航運": ["長榮", "陽明", "萬海"],
    "石化": ["台塑", "南亞", "台化", "台塑化"],
    "鋼鐵": ["中鋼", "豐興"],
    "半導體供應鏈": ["日月光投控", "聯電", "京元電子"],
    "生技醫療": ["台灣生技ETF", "東洋"],
}

def fetch(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return df
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.dropna(inplace=True)
    return df

def fetch_all(period: str = "6mo", sector: str = "全部") -> dict[str, pd.DataFrame]:
    names = SECTORS.get(sector, list(WATCHLIST.keys()))
    result = {}
    for name in names:
        ticker = WATCHLIST.get(name)
        if not ticker:
            continue
        df = fetch(ticker, period=period)
        if not df.empty:
            result[name] = df
    return result
