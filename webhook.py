"""LINE Webhook Server — 接收用戶訊息，回傳股票分析"""
import hashlib, hmac, base64, json, os, re
import pandas as pd
from flask import Flask, request, abort
from query_handler import resolve_query, build_multi_response, HELP_MSG

app = Flask(__name__)

LINE_TOKEN  = os.environ.get("LINE_TOKEN",  "")
LINE_SECRET = os.environ.get("LINE_SECRET", "")
PUSH_SECRET = os.environ.get("PUSH_SECRET", "")
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"


def _verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_SECRET:
        return True
    digest = hmac.new(LINE_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def _reply(reply_token: str, message):
    """message 為 str（文字）或 dict（Flex 等 LINE Message 物件）"""
    import urllib.request
    msg_obj = {"type": "text", "text": message} if isinstance(message, str) else message
    payload = json.dumps({
        "replyToken": reply_token,
        "messages": [msg_obj],
    }).encode("utf-8")
    req = urllib.request.Request(
        LINE_REPLY_URL,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {LINE_TOKEN}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[reply error] {e}")
        return False


def _build_flex(name: str, ticker: str) -> dict:
    """平行抓取所有資料，回傳 Flex Message dict"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from data_fetcher import fetch, fetch_institutional, fetch_margin_data, fetch_taiex_change
    from analyzer import add_indicators
    from daytrade_scorer import calc_daytrade_score, calc_entry_exit, is_tw_stock
    from fundamental_filter import is_fundamentally_weak
    from tdcc_holders import get_holder_signal
    from flex_builder import build_analysis_flex

    code   = ticker.replace(".TW", "").replace(".TWO", "")
    is_tw  = is_tw_stock(ticker)
    is_etf = code.startswith("00")

    # ── K線：主執行緒（yfinance 在 thread 內不穩定）───────
    df = fetch(ticker, period="6mo")
    # 台股主板抓不到，試上櫃 .TWO
    if (df is None or df.empty) and ticker.endswith(".TW"):
        ticker = ticker.replace(".TW", ".TWO")
        df = fetch(ticker, period="6mo")
    if df is None or df.empty:
        return None  # 快速失敗，不浪費 reply token 時間

    # name 若只是代碼（自動解析），嘗試從 TWSE 取回中文名
    raw_code = ticker.replace(".TW", "").replace(".TWO", "")
    if name == raw_code:
        try:
            import urllib.request as _ur, json as _j
            _url = (f"https://www.twse.com.tw/rwd/zh/company/searchTwsePubInfo"
                    f"?stockNo={raw_code}&response=json")
            _req = _ur.Request(_url, headers={"User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(_req, timeout=5) as _r:
                _d = _j.loads(_r.read())
            _rows = _d.get("data") or []
            if _rows:
                name = _rows[0][2] or name   # 欄位 2 = 公司簡稱
        except Exception:
            pass

    results: dict = {"kline": df}

    # ── 大盤強弱（主執行緒，yfinance，快速 5d）─────────────
    taiex_chg = None
    try:
        taiex_chg = fetch_taiex_change()
    except Exception:
        pass

    # ── 法人 / 融資 / 集保：平行（TWSE HTTP 請求）───────────
    if is_tw:
        side_tasks = {
            "inst":   lambda: fetch_institutional(code),
            "margin": lambda: fetch_margin_data(code),
            "holder": lambda: get_holder_signal(ticker),
        }
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fn): key for key, fn in side_tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    print(f"[fetch error] {key}: {e}")
                    results[key] = None

    # ── 基本面（yfinance，主執行緒）────────────────────
    results["weak"] = False
    if is_tw and not is_etf:
        try:
            results["weak"] = is_fundamentally_weak(ticker)
        except Exception:
            pass

    df      = add_indicators(results["kline"])
    latest  = df.iloc[-1]
    prev    = df.iloc[-2] if len(df) > 1 else latest
    close   = float(latest["Close"])
    high    = float(latest.get("High", close))
    chg_pct = (close - float(prev["Close"])) / float(prev["Close"]) * 100
    vol_r   = float(latest.get("Vol_ratio", 1.0)) if pd.notna(latest.get("Vol_ratio")) else 1.0
    date_str = df.index[-1].strftime("%m/%d")

    # 相對大盤強弱
    rs = round(chg_pct - taiex_chg, 1) if taiex_chg is not None else None

    def _s(row, key, default=0.0):
        v = row.get(key)
        return float(v) if v is not None and pd.notna(v) else default

    rsi      = _s(latest, "RSI",      50.0)
    rsi6     = _s(latest, "RSI6",     50.0)
    ma5      = _s(latest, "MA5",      close)
    ma20     = _s(latest, "MA20",     close)
    ma60     = _s(latest, "MA60",     close)
    atr_pct  = _s(latest, "ATR_pct",  0.0)
    bb_upper = _s(latest, "BB_upper", close * 1.04)
    bb_lower = _s(latest, "BB_lower", close * 0.96)
    bb_pos   = (close - bb_lower) / (bb_upper - bb_lower) * 100 \
               if bb_upper != bb_lower else 50.0

    # A — MACD 方向（判斷是否剛發生交叉）
    macd_v    = _s(latest, "MACD",        0.0)
    macd_sig  = _s(latest, "MACD_signal", 0.0)
    prev_macd = _s(prev,   "MACD",        0.0)
    prev_sig  = _s(prev,   "MACD_signal", 0.0)
    if prev_macd < prev_sig and macd_v > macd_sig:
        macd_tag = "黃金交叉 ✅"
    elif prev_macd > prev_sig and macd_v < macd_sig:
        macd_tag = "死亡交叉 ⚠️"
    elif macd_v > macd_sig:
        macd_tag = "多頭"
    else:
        macd_tag = "空頭"

    # B — KD 隨機指標
    k_val = _s(latest, "K", 50.0)
    d_val = _s(latest, "D", 50.0)

    # C — 距6月高低點
    high_6m    = float(df["High"].max())
    low_6m     = float(df["Low"].min())
    dist_high  = (close - high_6m) / high_6m * 100   # 負值，距高點幾 %
    dist_low   = (close - low_6m)  / low_6m  * 100   # 正值，距低點幾 %

    if ma5 > ma20 > ma60:
        ma_tag = "多頭排列✅"
    elif ma5 < ma20 < ma60:
        ma_tag = "空頭排列⚠️"
    else:
        ma_tag = "均線糾結"

    inst_data    = results.get("inst")   or {}
    margin_data  = results.get("margin") or {}
    holder_label = (results.get("holder") or {}).get("label", "")

    daytrade_score, entry_exit, top_signals = 0, None, []
    if is_tw and not is_etf:
        result = calc_daytrade_score(df, inst_data=inst_data, margin_data=margin_data)
        daytrade_score = result["score"]
        if daytrade_score > 0:
            entry_exit  = calc_entry_exit(df, daytrade_score)
            top_signals = result["signals"][:2]
            if results.get("weak"):
                top_signals.append("基本面偏弱")

    return build_analysis_flex(
        name=name, ticker=ticker, date_str=date_str,
        close=close, high=high, chg_pct=chg_pct, vol_ratio=vol_r,
        rs=rs,
        rsi=rsi, rsi6=rsi6, ma_tag=ma_tag,
        macd_tag=macd_tag, k_val=k_val, d_val=d_val,
        dist_high=dist_high, dist_low=dist_low,
        bb_pos=bb_pos, atr_pct=atr_pct,
        inst_data=inst_data, margin_data=margin_data,
        holder_label=holder_label,
        daytrade_score=daytrade_score,
        entry_exit=entry_exit,
        top_signals=top_signals,
    )


def _build_portfolio_message() -> dict:
    """抓持股即時資料，回傳 LINE message dict（含 Quick Reply）"""
    from data_fetcher import fetch, WATCHLIST
    from portfolio import HOLDINGS, calc_summary
    from datetime import datetime

    date_str = datetime.now().strftime("%m/%d")

    all_data = {}
    for name in HOLDINGS:
        ticker = WATCHLIST.get(name)
        if ticker:
            df = fetch(ticker, period="5d")
            if df is not None and not df.empty:
                all_data[name] = df

    summary = calc_summary(all_data)
    total   = summary.get("__total__", {})

    lines = [f"📊 持股快照（{date_str}）", ""]
    for name, d in summary.items():
        if name == "__total__":
            continue
        arrow = "▲" if d["change_pct"] >= 0 else "▼"
        line  = f"{name}　${d['price']:.1f} {arrow}{abs(d['change_pct']):.1f}%"
        if d.get("pnl") is not None:
            pa = "+" if d["pnl"] >= 0 else "-"
            line += f"\n  損益 {pa}${abs(d['pnl']):,.0f}（{pa}{abs(d['pnl_pct']):.1f}%）"
        alerts = []
        if d.get("stop_alert"):
            alerts.append("⚠️停損")
        if d.get("take_alert"):
            alerts.append("🎯停利達標")
        if alerts:
            line += "  " + " ".join(alerts)
        lines.append(line)

    lines.append("")
    tv  = total.get("total_value",      0)
    tdc = total.get("total_day_change", 0)
    tp  = total.get("total_pnl")
    tdc_arrow = "▲" if tdc >= 0 else "▼"
    lines.append(f"市值　　　${tv:,.0f}")
    lines.append(f"今日損益　{tdc_arrow}${abs(tdc):,.0f}")
    if tp is not None:
        tp_arrow = "▲" if tp >= 0 else "▼"
        lines.append(f"總損益　　{tp_arrow}${abs(tp):,.0f}")
    lines.append("\n⚠️ 資料 T+1，僅供參考")

    return {
        "type": "text",
        "text": "\n".join(lines),
        "quickReply": {
            "items": [
                {"type": "action", "action": {"type": "message", "label": "台積電", "text": "2330"}},
                {"type": "action", "action": {"type": "message", "label": "元大高股息", "text": "0056"}},
                {"type": "action", "action": {"type": "message", "label": "台灣50", "text": "0050"}},
                {"type": "action", "action": {"type": "message", "label": "說明", "text": "說明"}},
            ],
        },
    }


def _handle_message(event: dict):
    if event.get("type") != "message":
        return
    msg = event.get("message", {})
    if msg.get("type") != "text":
        return

    text        = msg.get("text", "").strip()
    reply_token = event.get("replyToken", "")

    # 說明指令
    if text.lower() in ("help", "幫助", "？", "?", "說明"):
        help_msg = {
            "type": "text",
            "text": HELP_MSG,
            "quickReply": {
                "items": [
                    {"type": "action", "action": {"type": "message", "label": "台積電", "text": "2330"}},
                    {"type": "action", "action": {"type": "message", "label": "00878", "text": "00878"}},
                    {"type": "action", "action": {"type": "message", "label": "0050", "text": "0050"}},
                    {"type": "action", "action": {"type": "message", "label": "持股", "text": "持股"}},
                ],
            },
        }
        _reply(reply_token, help_msg)
        return

    # 持股快照
    if text in ("持股", "持股快照", "portfolio"):
        msg = _build_portfolio_message()
        _reply(reply_token, msg)
        return

    # 列出提醒
    if text in ("提醒", "我的提醒", "alerts"):
        from alert_manager import list_alerts
        _reply(reply_token, list_alerts())
        return

    # 取消提醒：「2330 取消」或「台積電 取消」
    cancel_m = re.match(r'^(.+?)\s+取消$', text)
    if cancel_m:
        from alert_manager import cancel_alert
        query = cancel_m.group(1).strip()
        name, ticker = resolve_query(query)
        if name:
            _reply(reply_token, cancel_alert(ticker, name))
        else:
            _reply(reply_token, f"❓ 找不到「{query}」")
        return

    # 設定提醒：「2330 >1100」或「台積電 <1000」
    alert_m = re.match(r'^(.+?)\s*([><])\s*(\d+(?:\.\d+)?)$', text)
    if alert_m:
        from alert_manager import set_alert, check_and_trigger
        from data_fetcher import fetch
        query  = alert_m.group(1).strip()
        op     = alert_m.group(2)
        target = float(alert_m.group(3))
        name, ticker = resolve_query(query)
        if name is None:
            _reply(reply_token, f"❓ 找不到「{query}」")
            return
        # 先檢查現價是否已觸發
        df = fetch(ticker, period="5d")
        if df is not None and not df.empty:
            current = float(df.iloc[-1]["Close"])
            already = (op == ">" and current >= target) or (op == "<" and current <= target)
            if already:
                word = "已高於" if op == ">" else "已低於"
                _reply(reply_token,
                       f"⚠️ {name} 現價 ${current:.1f} {word}目標 ${target:.1f}\n"
                       f"請重新設定條件")
                return
        _reply(reply_token, set_alert(ticker, name, op, target))
        return

    # 多股比較：空格分隔 2-4 個代號
    tokens = text.split()
    if 2 <= len(tokens) <= 4:
        pairs = [resolve_query(t) for t in tokens]
        if all(name is not None for name, _ in pairs):
            _reply(reply_token, build_multi_response(pairs))
            return

    # 單股查詢 → Flex Message
    name, ticker = resolve_query(text)
    if name is None:
        _reply(reply_token,
               f"❓ 找不到「{text}」\n請輸入股票代號（如 2330）或名稱（如 台積電）")
        return

    flex = _build_flex(name, ticker)
    if flex:
        _reply(reply_token, flex)
    else:
        _reply(reply_token, f"❌ 找不到 {name}（{ticker}）的資料，請確認代號是否正確。")


def _check_alerts_push():
    """檢查所有設定中的提醒，有觸發就推播給使用者"""
    try:
        from alert_manager import _load, check_and_trigger
        if not _load():
            return
        from data_fetcher import fetch
        alerts = _load()
        prices = {}
        for ticker in alerts:
            df = fetch(ticker, period="5d")
            if df is not None and not df.empty:
                prices[ticker] = float(df.iloc[-1]["Close"])
        triggered = check_and_trigger(prices)
        if triggered and LINE_TOKEN:
            import urllib.request
            for msg in triggered:
                payload = json.dumps({
                    "to": os.environ.get("LINE_USER_ID", ""),
                    "messages": [{"type": "text", "text": msg}],
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.line.me/v2/bot/message/push",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {LINE_TOKEN}",
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    pass
    except Exception as e:
        print(f"[alert check] {e}")


@app.route("/webhook", methods=["POST"])
def webhook():
    body      = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")

    if not _verify_signature(body, signature):
        abort(400, "Invalid signature")

    try:
        events = json.loads(body).get("events", [])
    except Exception:
        abort(400, "Invalid JSON")

    for event in events:
        uid = event.get("source", {}).get("userId", "")
        if uid:
            print(f"[userId] {uid}")
        _handle_message(event)

    # 每次收到訊息時順帶檢查價格提醒
    _check_alerts_push()

    return "OK", 200


@app.route("/push", methods=["POST"])
def trigger_push():
    """定時推播觸發端點，需附帶 X-Push-Secret header"""
    if PUSH_SECRET:
        if request.headers.get("X-Push-Secret", "") != PUSH_SECRET:
            abort(403, "Invalid secret")
    try:
        from push_handler import run_push
        push_type = "morning"
        if request.is_json and request.json:
            push_type = request.json.get("type", "morning")
        result = run_push(push_type)
        return result, 200
    except Exception as e:
        print(f"[push error] {e}")
        return str(e), 500


@app.route("/", methods=["GET"])
def health():
    return "Stock Query Bot is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
