"""每日匯率抓取與訊息建構 — 供早盤 LINE 推播使用"""
from datetime import datetime
import yfinance as yf


def fetch_fx_rates() -> dict:
    """
    回傳 USD、JPY（每100圓）、EUR 對台幣匯率與昨日變動。
    任一幣別抓取失敗時略過，不影響其他幣別。
    """
    results = {}
    try:
        tickers = yf.download(
            ["USDTWD=X", "USDJPY=X", "EURUSD=X"],
            period="2d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        close = tickers["Close"] if "Close" in tickers.columns else tickers

        def _info(col):
            s = close[col].dropna()
            if len(s) < 1:
                return None
            rate = float(s.iloc[-1])
            chg_pct = (rate / float(s.iloc[-2]) - 1) * 100 if len(s) >= 2 else 0.0
            return {"rate": rate, "chg_pct": chg_pct}

        usd_info = _info("USDTWD=X")
        jpy_info = _info("USDJPY=X")
        eur_info = _info("EURUSD=X")

        if usd_info:
            results["USD"] = usd_info  # NT$ per 1 USD

        if usd_info and jpy_info:
            # 每100日圓對台幣 = (USDTWD / USDJPY) × 100
            usdtwd_rate = usd_info["rate"]
            usdjpy_rate = jpy_info["rate"]
            jpy100_rate = (usdtwd_rate / usdjpy_rate) * 100
            # 近似變動 = USD/TWD 變動 - USD/JPY 變動
            jpy100_chg = usd_info["chg_pct"] - jpy_info["chg_pct"]
            results["JPY100"] = {"rate": jpy100_rate, "chg_pct": jpy100_chg}

        if usd_info and eur_info:
            # EUR/TWD = EURUSD × USDTWD
            eur_twd_rate = eur_info["rate"] * usd_info["rate"]
            eur_twd_chg = eur_info["chg_pct"] + usd_info["chg_pct"]
            results["EUR"] = {"rate": eur_twd_rate, "chg_pct": eur_twd_chg}

    except Exception as e:
        print(f"[FX] 匯率抓取失敗：{e}")

    return results


def build_fx_message(rates: dict) -> str:
    """將 fetch_fx_rates() 結果組成 LINE 推播文字"""
    if not rates:
        return ""

    date_str = datetime.now().strftime("%m/%d")
    lines = [f"💱 今日匯率（{date_str}）", ""]

    specs = [
        ("USD",    "美元 USD", "NT$", "{:.2f}"),
        ("JPY100", "日圓¥100", "NT$", "{:.2f}"),
        ("EUR",    "歐元 EUR", "NT$", "{:.2f}"),
    ]
    for key, label, unit, fmt in specs:
        info = rates.get(key)
        if not info:
            continue
        rate     = info["rate"]
        chg_pct  = info["chg_pct"]
        arrow    = "▲" if chg_pct > 0.005 else ("▼" if chg_pct < -0.005 else "－")
        chg_str  = f"{arrow}{abs(chg_pct):.2f}%"
        lines.append(f"  {label}　{unit}{fmt.format(rate)}　{chg_str}")

    lines.append("\n⚠️ 資料來自 yfinance，僅供參考")
    return "\n".join(lines)
