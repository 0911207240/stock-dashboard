import time
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
    # 高殖利率 ETF
    "國泰永續高股息": "00878.TW",
    "群益台灣精選高息": "00919.TW",
    "復華台灣科技優息": "00929.TW",
    "元大台灣高息低波": "00713.TW",
    "富邦特選高股息30": "00900.TW",
    # 輝達生態圈 - 台灣 AI 伺服器供應鏈
    "廣達": "2382.TW",
    "緯創": "3231.TW",
    "技嘉": "2376.TW",
    "微星": "2377.TW",
    "台達電": "2308.TW",
    "緯穎": "6669.TW",
    # 輝達生態圈 - 美股
    "超微半導體": "AMD",
    "博通": "AVGO",
    "美光": "MU",
    "超微電腦": "SMCI",
    "安謀控股": "ARM",
    # 台積電合作廠商 - 台灣供應鏈
    "環球晶圓": "6488.TW",
    "台勝科": "3532.TW",
    "中美矽晶": "5483.TW",
    "家登精密": "3680.TW",
    "漢唐集成": "2404.TW",
    "亞翔工程": "6139.TW",
    # 台積電合作廠商 - 美股設備商
    "ASML": "ASML",
    "應用材料": "AMAT",
    "科林研發": "LRCX",
    "KLA": "KLAC",
    # 台積電主要客戶 - 美股
    "高通": "QCOM",
    "英特爾": "INTC",
    # 光電
    "大立光": "3008.TW",
    "玉晶光": "3406.TW",
    "億光": "2393.TW",
    "晶元光電": "2448.TW",
    # 電腦周邊
    "宏碁": "2353.TW",
    "華碩": "2357.TW",
    "仁寶": "2324.TW",
    "英業達": "2356.TW",
    "和碩": "4938.TW",
    # 資訊服務 / 數位雲端
    "中華電": "2412.TW",
    "台灣大": "3045.TW",
    "Alphabet": "GOOGL",
    "Meta": "META",
    "亞馬遜": "AMZN",
    # 晶圓代工 / 電子零組件
    "世界先進": "5347.TW",
    "力積電": "6770.TW",
    "穩懋半導體": "3105.TW",
    "國巨": "2327.TW",
    "華新科": "2492.TW",
    # Apple 供應鏈
    "可成": "2474.TW",
    "美律": "2439.TW",
    "瑞儀": "6176.TW",
    "欣興": "3037.TW",
    # AI 美股
    "Palantir": "PLTR",
    "戴爾": "DELL",
    # 面板（低價高波動）
    "友達": "2409.TW",
    "群創": "3481.TW",
    # 記憶體（低價高波動）
    "華邦電": "2344.TW",
    "南亞科": "2408.TW",
    "旺宏": "2337.TW",
    # 鋼鐵補充（低價）
    "燁輝": "2023.TW",
    "東和鋼鐵": "2006.TW",
    "大成鋼": "2027.TW",
    "春源鋼鐵": "2010.TW",
    # 金融補充（低價）
    "永豐金": "2890.TW",
    "彰銀": "2801.TW",
    "臺企銀": "2834.TW",
    "開發金": "2883.TW",
    # 低價電子零組件
    "欣銓": "3264.TW",
    "漢磊": "3707.TW",
    "矽格": "6257.TW",
    # 低價傳產 / 其他
    "遠雄": "5522.TW",
    "中石化": "1314.TW",
    "亞化": "1308.TW",
    # 槓桿/反向 ETF（波段操作用）
    "台灣50正2": "00631L.TW",
    "台灣50反1": "00632R.TW",
    # IC 設計績優
    "瑞昱": "2379.TW",
    "聯詠": "3034.TW",
    "創意": "3443.TW",
    "世芯-KY": "3661.TW",
    "奇景光電": "3545.TW",
    # PCB / 銅箔基板績優
    "臻鼎-KY": "4958.TW",
    "健鼎": "3044.TW",
    "台光電": "2383.TW",
    "聯茂": "6213.TW",
    "華通": "2313.TW",
    # 網通設備績優
    "智邦": "2345.TW",
    "合勤控": "3704.TW",
    "啟碁": "6285.TW",
    "中磊": "5388.TW",
    # 電源 / 散熱績優
    "光寶科": "2301.TW",
    "群光": "2385.TW",
    "奇鋐": "3017.TW",
    "雙鴻": "3324.TW",
    "建準": "2421.TW",
    # 封裝測試績優
    "南茂": "8150.TW",
    "頎邦": "6148.TW",
    # 連接器 / 精密零件
    "正崴": "2392.TW",
    "鴻準": "2354.TW",
    # 工業電腦 / 其他績優
    "研華": "2395.TW",
    "振樺電": "8114.TW",
    # 個人持股（額外加入）
    "昆盈": "2365.TW",
    "金寶": "2312.TW",
    "盛群半導體": "6202.TW",
    "振發": "5426.TW",
    # 個股補充
    "佳世達": "2352.TW",
    "精星": "8183.TW",
    # IC 設計補充
    "矽統科技": "2363.TW",
    "威盛電子": "2388.TW",
    "凌陽科技": "2401.TW",
    "偉詮電": "2436.TW",
    "義隆電子": "2458.TW",
    "晶豪科技": "3006.TW",
    "聯陽半導體": "3014.TW",
    "智原": "3035.TW",
    "揚智": "3041.TW",
    "IC_3073": "3073.TW",
    "IC_3094": "3094.TW",
    "IC_3122": "3122.TW",
    "IC_3141": "3141.TW",
    "IC_3150": "3150.TW",
    "IC_3169": "3169.TW",
    # PCB 電子補充
    "富喬工業": "1815.TW",
    "楠梓電": "2316.TW",
    "敬鵬": "2355.TW",
    "燿華電子": "2367.TW",
    "金像電": "2368.TW",
    "毅嘉": "2402.TW",
    "銘異": "2429.TW",
    # 電池 / 電源電子
    "新普": "6121.TW",
    "加百裕": "3323.TW",
    "順達": "3211.TW",
    "東元電機": "1504.TW",
    "士電": "1503.TW",
    "碩天": "5309.TW",
    # IC 製造
    "嘉晶": "3016.TW",
    "宏捷科": "8086.TW",
    "精材": "3374.TW",
    # 光電設備
    "光磊": "2340.TW",
    "台灣光罩": "2338.TW",
    # 機殼
    "新日興": "3376.TW",
    "兆利": "3548.TW",
    "超眾": "6230.TW",
    # 光學元件 / 組裝
    "先進光": "3362.TW",
    "亞光": "3019.TW",
    "晶技": "3042.TW",
    # 其他光電
    "元太": "8069.TW",
    "錸德": "2349.TW",
    # 手機相關
    "宏達電": "2498.TW",
    "景碩": "3189.TW",
    # 網通設備補充
    "友訊": "2332.TW",
    "正文": "4906.TW",
    "亞旭": "6354.TW",
    # 電信服務
    "遠傳": "4904.TW",
    "亞太電信": "3682.TW",
    # 電子連接
    "宏致": "3605.TW",
    "嘉澤": "3533.TW",
    # 被動元件補充
    "禾伸堂": "3026.TW",
    "奇力新": "2456.TW",
    "信昌電": "6173.TW",
    # 面板業
    "彩晶": "6116.TW",
    "勝華": "2384.TW",
}

SECTORS = {
    "全部": list(WATCHLIST.keys()),
    "科技/ETF": ["台積電", "鴻海", "聯發科", "台灣50", "元大高股息"],
    "美股": ["蘋果", "輝達", "微軟", "超微半導體", "博通", "美光", "超微電腦", "安謀控股", "高通", "英特爾", "Alphabet", "Meta", "亞馬遜", "Palantir", "戴爾"],
    "銀行/金控": ["國泰金", "富邦金", "兆豐金", "玉山金", "中信金", "第一金", "華南金", "台新金", "元大金", "合庫金"],
    "水泥": ["台泥", "亞泥", "嘉泥", "環泥", "信大水泥", "東泥"],
    "航運": ["長榮", "陽明", "萬海"],
    "石化": ["台塑", "南亞", "台化", "台塑化"],
    "鋼鐵": ["中鋼", "豐興"],
    "半導體供應鏈": ["日月光投控", "聯電", "京元電子"],
    "生技醫療": ["台灣生技ETF"],
    "高殖利率ETF": ["國泰永續高股息", "群益台灣精選高息", "復華台灣科技優息", "元大台灣高息低波", "富邦特選高股息30"],
    "輝達生態圈": ["輝達", "廣達", "緯創", "技嘉", "微星", "台達電", "緯穎", "超微半導體", "博通", "美光", "超微電腦", "安謀控股"],
    "台積電合作廠商": ["環球晶圓", "台勝科", "中美矽晶", "家登精密", "漢唐集成", "亞翔工程", "ASML", "應用材料", "科林研發", "KLA", "高通", "英特爾"],
    "光電": ["大立光", "玉晶光", "億光", "晶元光電"],
    "電腦周邊": ["宏碁", "華碩", "仁寶", "英業達", "和碩"],
    "資訊服務/雲端": ["中華電", "台灣大", "Alphabet", "Meta", "亞馬遜"],
    "晶圓代工/零組件": ["世界先進", "力積電", "穩懋半導體", "國巨", "華新科"],
    "Apple供應鏈": ["台積電", "鴻海", "大立光", "玉晶光", "和碩", "可成", "美律", "瑞儀", "欣興"],
    "AI概念": ["輝達", "台積電", "廣達", "緯創", "技嘉", "微星", "緯穎", "英業達", "台達電", "Alphabet", "Meta", "亞馬遜", "Palantir", "超微半導體", "博通", "安謀控股"],
    "低價波段($50以下)": ["友達", "群創", "華邦電", "南亞科", "旺宏", "燁輝", "東和鋼鐵", "大成鋼", "春源鋼鐵", "永豐金", "彰銀", "臺企銀", "開發金", "欣銓", "漢磊", "矽格", "中石化", "亞化", "遠雄", "聯電", "力積電", "穩懋半導體", "台新金", "元大金", "台灣企銀", "華南金", "中鋼", "台泥", "亞泥", "嘉泥", "環泥", "信大水泥", "國泰永續高股息", "群益台灣精選高息", "復華台灣科技優息", "富邦特選高股息30", "台灣50反1"],
    "槓桿ETF": ["台灣50正2", "台灣50反1"],
    "IC設計績優": ["台積電", "聯發科", "聯電", "瑞昱", "聯詠", "創意", "世芯-KY", "奇景光電"],
    "PCB/基板績優": ["臻鼎-KY", "健鼎", "台光電", "聯茂", "華通", "欣興"],
    "網通設備": ["智邦", "合勤控", "啟碁", "中磊"],
    "電源/散熱績優": ["台達電", "光寶科", "群光", "奇鋐", "雙鴻", "建準"],
    "封裝測試績優": ["日月光投控", "京元電子", "矽格", "欣銓", "南茂", "頎邦"],
    "連接器/精密零件": ["正崴", "鴻準", "可成"],
    "我的持股": ["台泥", "華南金", "南茂", "復華台灣科技優息", "台積電", "台灣50", "元大高股息", "金寶", "國泰永續高股息", "第一金", "盛群半導體", "振發", "昆盈"],
    "台灣電子績優": [
        "台積電", "鴻海", "聯發科", "廣達", "緯創", "英業達", "和碩",
        "瑞昱", "聯詠", "創意", "世芯-KY",
        "臻鼎-KY", "健鼎", "台光電", "聯茂", "欣興",
        "智邦", "合勤控", "啟碁",
        "台達電", "光寶科", "群光", "奇鋐", "雙鴻",
        "日月光投控", "聯電", "京元電子", "南茂", "頎邦",
        "正崴", "鴻準", "可成", "研華",
    ],
}

def fetch_taiex(period: str = "1y") -> pd.DataFrame:
    return fetch("^TWII", period=period)


def fetch_taiex_change() -> float | None:
    """回傳加權指數最新一日漲跌幅（%），失敗回傳 None"""
    try:
        df = fetch("^TWII", period="5d")
        if df is None or len(df) < 2:
            return None
        last = float(df.iloc[-1]["Close"])
        prev = float(df.iloc[-2]["Close"])
        return (last / prev - 1) * 100
    except Exception:
        return None


_FETCH_RETRIES = 3
_FETCH_BACKOFF = (1, 3)   # 第1次重試等1秒，第2次等3秒


def fetch(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    from datetime import datetime
    last_err = None
    for attempt in range(_FETCH_RETRIES):
        try:
            df = yf.download(ticker, period=period, interval=interval, progress=False)
            if not df.empty:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df.dropna(inplace=True)
            if df.empty:
                if attempt < _FETCH_RETRIES - 1:
                    time.sleep(_FETCH_BACKOFF[min(attempt, len(_FETCH_BACKOFF) - 1)])
                continue
            # 資料過舊警告（超過 10 天代表 API 異常或長假）
            age = (datetime.now() - df.index[-1].to_pydatetime().replace(tzinfo=None)).days
            if age > 10:
                print(f"[WARN] {ticker} 資料過舊 {age} 天（{df.index[-1].date()}）")
            return df
        except Exception as e:
            last_err = e
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(_FETCH_BACKOFF[min(attempt, len(_FETCH_BACKOFF) - 1)])
    msg = str(last_err) if last_err else "資料為空"
    print(f"[WARN] {ticker} 抓取失敗（{_FETCH_RETRIES} 次）：{msg}")
    return pd.DataFrame()

def fetch_dividends(ticker: str) -> pd.Series:
    try:
        divs = yf.Ticker(ticker).dividends
        if divs.empty:
            return pd.Series(dtype=float)
        divs.index = divs.index.tz_localize(None)
        return divs.tail(8)
    except Exception:
        return pd.Series(dtype=float)


def fetch_institutional(stock_code: str) -> dict:
    """從 TWSE 抓三大法人最新買賣超，附連續天數與近期累計（僅限台股 .TW）"""
    import urllib.request, json as _json
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor, as_completed

    code = stock_code.replace(".TW", "").replace(".TWO", "")
    if "." in code:
        return {}

    def _int(s):
        try:
            return int(str(s).replace(",", ""))
        except Exception:
            return 0

    def _fetch_one(offset: int) -> dict | None:
        for delta in range(offset, offset + 4):
            date = (datetime.now() - timedelta(days=delta)).strftime("%Y%m%d")
            url  = (f"https://www.twse.com.tw/rwd/zh/fund/T86"
                    f"?date={date}&selectType=ALLBUT0999&response=json")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = _json.loads(resp.read())
                if data.get("stat") != "OK" or not data.get("data"):
                    continue
                for row in data["data"]:
                    if row[0].strip() == code:
                        return {
                            "date":        date,
                            "foreign_net": _int(row[4]),
                            "trust_net":   _int(row[7]),
                            "dealer_net":  _int(row[8]),
                            "total_net":   _int(row[9]),
                        }
            except Exception:
                continue
        return None

    # 同時抓最近 3 個交易日（各從 offset 0/4/8 開始往前找）
    history = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(_fetch_one, i * 4) for i in range(3)]
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                history.append(r)

    if not history:
        return {}

    history.sort(key=lambda x: x["date"], reverse=True)
    today = history[0].copy()

    if len(history) >= 2:
        # 連續買賣超方向
        direction = 1 if today["total_net"] >= 0 else -1
        consecutive = 0
        for h in history:
            if (h["total_net"] >= 0) == (direction > 0):
                consecutive += 1
            else:
                break
        n_day_net = sum(h["total_net"] for h in history)
        today["consecutive_days"] = consecutive * direction
        today["n_day_net"]        = n_day_net
        today["history_days"]     = len(history)

    return today


def fetch_margin_data(stock_code: str) -> dict:
    """從 TWSE 抓融資融券資料（僅限台股 .TW）"""
    import urllib.request, json as _json
    from datetime import datetime, timedelta
    code = stock_code.replace(".TW", "").replace(".TWO", "")
    if "." in code:
        return {}
    for i in range(5):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        url  = (f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
                f"?date={date}&selectType=ALL&response=json")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            if data.get("stat") != "OK" or not data.get("data"):
                continue
            for row in data["data"]:
                if row[0].strip() == code and len(row) >= 13:
                    def _int(s):
                        try:
                            return int(str(s).replace(",", ""))
                        except Exception:
                            return 0
                    # 欄位順序: 代號,名稱,融資買,融資賣,現金償還,融資前日,融資今日,融資限額,融券賣,融券買,現券償還,融券前日,融券今日,融券限額,資券互抵
                    margin_prev  = _int(row[5])
                    margin_today = _int(row[6])
                    short_prev   = _int(row[11])
                    short_today  = _int(row[12])
                    return {
                        "date":           date,
                        "margin_buy":     _int(row[2]),
                        "margin_sell":    _int(row[3]),
                        "margin_balance": margin_today,
                        "margin_change":  margin_today - margin_prev,
                        "short_sell":     _int(row[8]),
                        "short_buy":      _int(row[9]),
                        "short_balance":  short_today,
                        "short_change":   short_today - short_prev,
                        "margin_ratio":   round(short_today / margin_today * 100, 1) if margin_today > 0 else 0,
                    }
        except Exception:
            continue
    return {}


def fetch_all_institutional() -> dict[str, dict]:
    """一次 API 抓取所有台股三大法人資料，回傳 {stock_code: {...}}"""
    import urllib.request, json as _json
    from datetime import datetime, timedelta
    for i in range(5):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        url  = (f"https://www.twse.com.tw/rwd/zh/fund/T86"
                f"?date={date}&selectType=ALLBUT0999&response=json")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read())
            if data.get("stat") != "OK" or not data.get("data"):
                continue
            def _int(s):
                try: return int(str(s).replace(",", ""))
                except: return 0
            return {
                row[0].strip(): {
                    "date":        date,
                    "foreign_net": _int(row[4]),
                    "trust_net":   _int(row[7]),
                    "dealer_net":  _int(row[8]),
                    "total_net":   _int(row[9]),
                }
                for row in data["data"]
            }
        except Exception:
            continue
    return {}


def fetch_all_margin() -> dict[str, dict]:
    """一次 API 抓取所有台股融資融券資料，回傳 {stock_code: {...}}"""
    import urllib.request, json as _json
    from datetime import datetime, timedelta
    for i in range(5):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        url  = (f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
                f"?date={date}&selectType=ALL&response=json")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read())
            if data.get("stat") != "OK" or not data.get("data"):
                continue
            def _int(s):
                try: return int(str(s).replace(",", ""))
                except: return 0
            result = {}
            for row in data["data"]:
                if len(row) < 13:
                    continue
                code = row[0].strip()
                mp   = _int(row[5]); mt = _int(row[6])
                sp   = _int(row[11]); st = _int(row[12])
                result[code] = {
                    "date":           date,
                    "margin_buy":     _int(row[2]),
                    "margin_sell":    _int(row[3]),
                    "margin_balance": mt,
                    "margin_change":  mt - mp,
                    "short_sell":     _int(row[8]),
                    "short_buy":      _int(row[9]),
                    "short_balance":  st,
                    "short_change":   st - sp,
                    "margin_ratio":   round(st / mt * 100, 1) if mt > 0 else 0,
                }
            return result
        except Exception:
            continue
    return {}


def fetch_taifex_futures() -> dict:
    """從 TAIFEX 抓外資台指期（TXF）淨未平倉口數"""
    import urllib.request, re
    from datetime import datetime, timedelta

    def _int(s):
        try:
            return int(str(s).replace(",", "").strip())
        except Exception:
            return None

    for i in range(5):
        date_str = (datetime.now() - timedelta(days=i)).strftime("%Y/%m/%d")
        url = (
            "https://www.taifex.com.tw/cht/3/futContractsDate"
            f"?queryType=2&marketCode=0&dateaddcnt=0&commodity_id=TXF&queryDate={date_str}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            pos = html.find("外資及陸資")
            if pos < 0:
                continue

            # 從外資行起取後 2000 字元，抓出所有數字（含負號）
            segment = html[pos: pos + 2000]
            raw_nums = re.findall(r'>([\-]?[\d,]+)<', segment)
            nums = [_int(n) for n in raw_nums if _int(n) is not None]

            # 欄位順序：多方口數, 多方金額, 空方口數, 空方金額, 淨額口數, 淨額金額
            if len(nums) >= 5:
                return {
                    "date":          date_str,
                    "foreign_long":  nums[0],
                    "foreign_short": nums[2],
                    "foreign_net":   nums[4],
                }
        except Exception:
            continue
    return {}


def fetch_all(period: str = "6mo", sector: str = "全部", max_workers: int = 20) -> dict[str, pd.DataFrame]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    names = SECTORS.get(sector, list(WATCHLIST.keys()))
    pairs = [(name, WATCHLIST[name]) for name in names if name in WATCHLIST]

    result = {}
    def _fetch_one(name, ticker):
        df = fetch(ticker, period=period)
        return name, df

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, name, ticker): name for name, ticker in pairs}
        for future in as_completed(futures):
            name, df = future.result()
            if not df.empty:
                result[name] = df
    return result
