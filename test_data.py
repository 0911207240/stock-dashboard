import yfinance as yf
import pandas as pd

stocks = {
    "台積電 (2330)": "2330.TW",
    "台灣50 ETF (0050)": "0050.TW",
    "蘋果 (AAPL)": "AAPL",
}

print("=== 股票資料抓取測試 ===\n")

for name, ticker in stocks.items():
    try:
        df = yf.download(ticker, period="5d", interval="1d", progress=False)
        if not df.empty:
            last_close = df["Close"].iloc[-1].item()
            print(f"[OK] {name}: {last_close:.2f}")
        else:
            print(f"[NO DATA] {name}")
    except Exception as e:
        print(f"[ERROR] {name}: {e}")

print("\n測試完成！")
