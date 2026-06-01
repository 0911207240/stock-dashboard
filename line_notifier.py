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


def build_summary_message(found: list[dict], date_str: str) -> str:
    """將多檔訊號合成一則彙整報告"""
    buys  = [x for x in found if x["score"] > 0]
    sells = [x for x in found if x["score"] < 0]
    lines = [f"【{date_str} 技術訊號彙整】共 {len(found)} 檔"]

    if buys:
        lines.append(f"\n📈 買進訊號（{len(buys)} 檔）")
        for x in sorted(buys, key=lambda v: v["score"], reverse=True):
            arrow = "▲" if x["change_pct"] >= 0 else "▼"
            tag = "★持股 " if x.get("is_holding") else ""
            sig_msgs = "、".join(s["msg"] for s in x["signals"] if s["type"] == "buy")
            lines.append(f"  {tag}{x['name']} ${x['price']:.2f} {arrow}{abs(x['change_pct']):.1f}%")
            lines.append(f"    {sig_msgs}")

    if sells:
        lines.append(f"\n📉 賣出訊號（{len(sells)} 檔）")
        for x in sorted(sells, key=lambda v: v["score"]):
            arrow = "▲" if x["change_pct"] >= 0 else "▼"
            tag = "★持股 " if x.get("is_holding") else ""
            sig_msgs = "、".join(s["msg"] for s in x["signals"] if s["type"] == "sell")
            lines.append(f"  {tag}{x['name']} ${x['price']:.2f} {arrow}{abs(x['change_pct']):.1f}%")
            lines.append(f"    {sig_msgs}")

    watch = [x for x in found if x["score"] == 0]
    if watch:
        names = "、".join(x["name"] for x in watch)
        lines.append(f"\n👀 觀察中：{names}")

    return "\n".join(lines)


def build_daytrade_message(
    candidates: list[dict],
    date_str: str,
    regime: dict = None,
    concentration_warning: str = "",
) -> str:
    """建立隔日當沖 Top N 推播訊息（甜蜜點區間＋兩段停利＋停損）"""
    header = f"【{date_str} 明日當沖候選 Top{len(candidates)}】"
    if regime:
        header += f"\n{regime['emoji']} 大盤{regime['state']}｜門檻 {40 + regime['min_score_adj']}分"
    lines = [header, "量能＋籌碼＋技術＋波動度評分", ""]
    for i, c in enumerate(candidates, 1):
        arrow = "▲" if c["change_pct"] >= 0 else "▼"
        lines.append(f"{i}. {c['name']}（昨收 ${c['price']:.1f}）分數 {c['score']}")
        lines.append(f"   {arrow}{abs(c['change_pct']):.1f}%  量比{c['vol_ratio']:.1f}x  ATR {c.get('atr_pct', 0):.1f}%")
        lines.append(f"   📍甜蜜點 ${c.get('entry_low', '-')}～${c.get('entry_high', '-')}（參考 ${c.get('entry_mid', '-')}）")
        lines.append(f"   🛑停損 ${c.get('stop', '-')}（風險 -{c.get('risk_pct', 0):.1f}%）")
        lines.append(f"   🎯停利① ${c.get('tp1', '-')}（+{c.get('upside_pct1', 0):.1f}% RR={c.get('rr1', '-')}）出半倉")
        lines.append(f"   🎯停利② ${c.get('tp2', '-')}（+{c.get('upside_pct2', 0):.1f}% RR={c.get('rr2', '-')}）全出")
        if c.get("suggested_lots"):
            risk_amt = round((c["entry_mid"] - c["stop"]) * c["suggested_lots"] * 1000)
            lines.append(f"   💰建議 {c['suggested_lots']} 張（風控 ${risk_amt:,}，約總資產 1%）")
        top_sigs = c.get("signals", [])[:2]
        if top_sigs:
            lines.append(f"   → {' / '.join(top_sigs)}")
        lines.append("")
    if concentration_warning:
        lines.append(concentration_warning)
    lines.append("⚠️ 僅供參考，操作自負風險")
    return "\n".join(lines)


def build_signal_message(
    name: str,
    ticker: str,
    signals: list[dict],
    price: float,
    change_pct: float = 0.0,
    vol_ratio: float = 1.0,
    week52_pct: float | None = None,
    atr_pct: float = 0.0,
) -> str:
    direction = "▲" if change_pct >= 0 else "▼"
    if atr_pct >= 3:
        volatility = "高波動"
    elif atr_pct >= 1.5:
        volatility = "中波動"
    else:
        volatility = "低波動"
    lines = [
        f"【股票訊號】{name} ({ticker})",
        f"收盤價：{price:.2f}  {direction}{abs(change_pct):.2f}%",
        f"量比：{vol_ratio:.1f}x 均量  |  波動：{atr_pct:.1f}%/日({volatility})",
    ]
    if week52_pct is not None:
        lines.append(f"年度位置：{week52_pct:.0f}%（0%=年低 100%=年高）")
    lines.append("")
    for s in signals:
        label = "買進" if s["type"] == "buy" else ("賣出" if s["type"] == "sell" else "觀察")
        lines.append(f"[{label}] {s['msg']}")
    return "\n".join(lines)
