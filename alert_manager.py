"""價格提醒管理 — 儲存於 /tmp，服務重啟後清空（個人使用可接受）"""
import json
from pathlib import Path
from datetime import datetime

_FILE = Path("/tmp/auno_alerts.json")


def _load() -> dict:
    try:
        if _FILE.exists():
            return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save(data: dict):
    try:
        _FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def set_alert(ticker: str, name: str, direction: str, price: float) -> str:
    alerts = _load()
    alerts[ticker] = {
        "name": name,
        "direction": direction,
        "price": price,
        "set_at": datetime.now().strftime("%m/%d %H:%M"),
    }
    _save(alerts)
    word = "突破" if direction == ">" else "跌破"
    return f"✅ 提醒設定：{name} {word} ${price:.1f} 時通知"


def cancel_alert(ticker: str, name: str) -> str:
    alerts = _load()
    if ticker in alerts:
        del alerts[ticker]
        _save(alerts)
        return f"✅ 已取消 {name} 的提醒"
    return f"❌ {name} 目前沒有設定提醒"


def list_alerts() -> str:
    alerts = _load()
    if not alerts:
        return "📌 目前沒有設定任何提醒\n\n設定方式：\n  2330 >1100（突破提醒）\n  台積電 <1000（跌破提醒）"
    lines = ["📌 目前的提醒："]
    for ticker, a in alerts.items():
        sym = ">" if a["direction"] == ">" else "<"
        lines.append(f"  {a['name']} {sym} ${a['price']:.1f}  （{a['set_at']} 設）")
    lines.append("\n取消方式：輸入「代號 取消」，例如 2330 取消")
    return "\n".join(lines)


def check_and_trigger(prices: dict[str, float]) -> list[str]:
    """傳入 {ticker: price}，回傳已觸發的通知訊息列表，並移除已觸發的提醒"""
    alerts    = _load()
    triggered = []
    remaining = {}

    for ticker, a in alerts.items():
        current = prices.get(ticker)
        if current is None:
            remaining[ticker] = a
            continue

        hit = (a["direction"] == ">" and current >= a["price"]) or \
              (a["direction"] == "<" and current <= a["price"])

        if hit:
            word = "突破" if a["direction"] == ">" else "跌破"
            triggered.append(
                f"🔔 【價格提醒觸發】\n"
                f"{a['name']} 已{word} ${a['price']:.1f}\n"
                f"現價 ${current:.1f}\n"
                f"（{a['set_at']} 設定）"
            )
        else:
            remaining[ticker] = a

    if triggered:
        _save(remaining)

    return triggered
