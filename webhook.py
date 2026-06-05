"""LINE Webhook Server — 接收用戶訊息，回傳股票分析"""
import hashlib, hmac, base64, json, os
from flask import Flask, request, abort
from query_handler import resolve_query, build_query_response, HELP_MSG

app = Flask(__name__)

LINE_TOKEN  = os.environ.get("LINE_TOKEN",  "")
LINE_SECRET = os.environ.get("LINE_SECRET", "")
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"


def _verify_signature(body: bytes, signature: str) -> bool:
    if not LINE_SECRET:
        return True
    digest = hmac.new(LINE_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def _reply(reply_token: str, text: str):
    import urllib.request
    payload = json.dumps({
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[reply error] {e}")
        return False


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

    # 股票查詢
    name, ticker = resolve_query(text)
    if name is None:
        _reply(reply_token, f"❓ 找不到「{text}」\n請輸入股票代號（如 2330）或名稱（如 台積電）")
        return

    _reply(reply_token, f"🔍 查詢中…（{name}）")

    # 分析可能需要幾秒，LINE reply token 有 30 秒限制
    # 若分析結果太長自動截斷至 LINE 5000 字元上限
    response = build_query_response(name, ticker)
    if len(response) > 4900:
        response = response[:4900] + "\n…（內容過長已截斷）"
    _reply(reply_token, response)


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
        _handle_message(event)

    return "OK", 200


@app.route("/", methods=["GET"])
def health():
    return "Stock Query Bot is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
