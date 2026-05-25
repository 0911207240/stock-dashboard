import urllib.request
import urllib.parse
import json
from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID


def send(message: str) -> bool:
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("[LINE] 尚未設定 Token 或 User ID")
        return False

    payload = json.dumps({
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as res:
            return res.status == 200
    except urllib.error.HTTPError as e:
        print(f"[LINE] 發送失敗：{e.code} {e.read().decode()}")
        return False


def build_signal_message(
    name: str,
    ticker: str,
    signals: list[dict],
    price: float,
    change_pct: float = 0.0,
    vol_ratio: float = 1.0,
    week52_pct: float | None = None,
) -> str:
    direction = "▲" if change_pct >= 0 else "▼"
    lines = [
        f"【股票訊號】{name} ({ticker})",
        f"收盤價：{price:.2f}  {direction}{abs(change_pct):.2f}%",
        f"量比：{vol_ratio:.1f}x 均量",
    ]
    if week52_pct is not None:
        lines.append(f"年度位置：{week52_pct:.0f}%（0%=年低 100%=年高）")
    lines.append("")
    for s in signals:
        label = "買進" if s["type"] == "buy" else ("賣出" if s["type"] == "sell" else "觀察")
        lines.append(f"[{label}] {s['msg']}")
    return "\n".join(lines)
