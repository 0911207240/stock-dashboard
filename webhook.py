"""LINE Webhook Server — 接收用戶訊息，回傳股票分析"""
import hashlib, hmac, base64, json, os
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
    """抓資料、計算指標，回傳 Flex Message dict"""
    from data_fetcher import fetch, fetch_institutional, fetch_margin_data
    from analyzer import add_indicators
    from daytrade_scorer import calc_daytrade_score, calc_entry_exit, is_tw_stock
    from fundamental_filter import is_fundamentally_weak
    from tdcc_holders import get_holder_signal
    from flex_builder import build_analysis_flex

    df = fetch(ticker, period="6mo")
    if df is None or df.empty:
        return None

    df      = add_indicators(df)
    latest  = df.iloc[-1]
    prev    = df.iloc[-2] if len(df) > 1 else latest
    close   = float(latest["Close"])
    chg_pct = (close - float(prev["Close"])) / float(prev["Close"]) * 100
    vol_r   = float(latest.get("Vol_ratio", 1.0)) if pd.notna(latest.get("Vol_ratio")) else 1.0
    date_str = df.index[-1].strftime("%m/%d")

    def _s(key, default=0.0):
        v = latest.get(key)
        return float(v) if v is not None and pd.notna(v) else default

    rsi      = _s("RSI",      50.0)
    rsi6     = _s("RSI6",     50.0)
    ma5      = _s("MA5",      close)
    ma20     = _s("MA20",     close)
    ma60     = _s("MA60",     close)
    atr_pct  = _s("ATR_pct",  0.0)
    bb_upper = _s("BB_upper", close * 1.04)
    bb_lower = _s("BB_lower", close * 0.96)
    bb_pos   = (close - bb_lower) / (bb_upper - bb_lower) * 100 \
               if bb_upper != bb_lower else 50.0

    if ma5 > ma20 > ma60:
        ma_tag = "多頭排列✅"
    elif ma5 < ma20 < ma60:
        ma_tag = "空頭排列⚠️"
    else:
        ma_tag = "均線糾結"

    inst_data, margin_data, holder_label = {}, {}, ""
    if is_tw_stock(ticker):
        code        = ticker.replace(".TW", "").replace(".TWO", "")
        inst_data   = fetch_institutional(code) or {}
        margin_data = fetch_margin_data(code) or {}
        holder      = get_holder_signal(ticker)
        holder_label = holder.get("label", "")

    daytrade_score, entry_exit, top_signals = 0, None, []
    is_etf = ticker.replace(".TW", "").replace(".TWO", "").startswith("00")
    if is_tw_stock(ticker) and not is_etf:
        result = calc_daytrade_score(df, inst_data=inst_data, margin_data=margin_data)
        daytrade_score = result["score"]
        if daytrade_score > 0:
            entry_exit   = calc_entry_exit(df, daytrade_score)
            top_signals  = result["signals"][:2]
            if is_fundamentally_weak(ticker):
                top_signals.append("基本面偏弱")

    return build_analysis_flex(
        name=name, ticker=ticker, date_str=date_str,
        close=close, chg_pct=chg_pct, vol_ratio=vol_r,
        rsi=rsi, rsi6=rsi6, ma_tag=ma_tag,
        bb_pos=bb_pos, atr_pct=atr_pct,
        inst_data=inst_data, margin_data=margin_data,
        holder_label=holder_label,
        daytrade_score=daytrade_score,
        entry_exit=entry_exit,
        top_signals=top_signals,
    )


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
        _reply(reply_token, HELP_MSG)
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
