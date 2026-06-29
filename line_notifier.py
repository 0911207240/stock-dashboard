import urllib.request
import urllib.parse
import json
import os
from datetime import datetime
from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID

_MSG_LIMIT = 4900   # LINE 單則文字上限 5000，留緩衝
_BATCH     = 5      # LINE 每次推播最多 5 則


def _fallback_to_drive(message: str) -> bool:
    """LINE 額度用完（429）時，將訊息備援寫入 Google Drive"""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaInMemoryUpload
        from google.oauth2.service_account import Credentials

        creds_json = os.getenv("GOOGLE_CREDENTIALS")
        folder_id  = os.getenv("GDRIVE_FOLDER_ID")
        if not creds_json or not folder_id:
            print("[Drive] 未設定 GOOGLE_CREDENTIALS 或 GDRIVE_FOLDER_ID，跳過備援")
            return False

        creds = Credentials.from_service_account_info(
            json.loads(creds_json),
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        now      = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"stock_report_{now}.txt"
        media    = MediaInMemoryUpload(message.encode("utf-8"), mimetype="text/plain")
        service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media,
        ).execute()
        print(f"[Drive] 備援寫入成功：{filename}")
        return True
    except Exception as e:
        print(f"[Drive] 備援寫入失敗：{e}")
        return False


def _split_message(message: str) -> list[str]:
    """超過 _MSG_LIMIT 時按換行切割成多段，每段不超過限制"""
    if len(message) <= _MSG_LIMIT:
        return [message]
    chunks, current, current_len = [], [], 0
    for line in message.split("\n"):
        line_len = len(line) + 1
        if current_len + line_len > _MSG_LIMIT and current:
            chunks.append("\n".join(current))
            current, current_len = [line], line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _push_batch(messages: list[dict]) -> bool:
    """向 LINE API 推播一批訊息（最多 5 則）"""
    payload = json.dumps({
        "to": LINE_USER_ID,
        "messages": messages,
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
        body = e.read().decode()
        print(f"[LINE] 發送失敗：{e.code} {body}")
        if e.code == 429:
            print("[LINE] 本月免費推播額度已用完，啟動 Google Drive 備援")
            combined = "\n".join(m["text"] for m in messages if m.get("type") == "text")
            _fallback_to_drive(combined)
        return False


def send(message: str) -> bool:
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("[LINE] 尚未設定 Token 或 User ID")
        return False

    chunks = _split_message(message)
    if len(chunks) > 1:
        print(f"[LINE] 訊息過長（{len(message)} 字），已切分為 {len(chunks)} 則")

    success = True
    for i in range(0, len(chunks), _BATCH):
        batch = [{"type": "text", "text": c} for c in chunks[i:i + _BATCH]]
        if not _push_batch(batch):
            success = False
    return success


def send_messages(messages: list[dict]) -> bool:
    """推播預先組好的 LINE 訊息物件（image / flex 等非文字型別）"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("[LINE] 尚未設定 Token 或 User ID")
        return False
    success = True
    for i in range(0, len(messages), _BATCH):
        if not _push_batch(messages[i:i + _BATCH]):
            success = False
    return success


_MAX_BUY  = 15   # 買進訊號最多顯示幾檔
_MAX_SELL =  5   # 賣出訊號最多顯示幾檔


def build_summary_message(found: list[dict], date_str: str) -> str:
    """將多檔訊號合成一則彙整報告（買進最多 _MAX_BUY 檔、賣出最多 _MAX_SELL 檔）"""
    buys  = sorted([x for x in found if x["score"] > 0], key=lambda v: v["score"], reverse=True)
    sells = sorted([x for x in found if x["score"] < 0], key=lambda v: v["score"])
    lines = [f"【{date_str} 技術訊號彙整】共 {len(found)} 檔"]

    if buys:
        shown = buys[:_MAX_BUY]
        omit  = len(buys) - len(shown)
        lines.append(f"\n📈 買進訊號（{len(buys)} 檔{'，顯示前'+str(_MAX_BUY) if omit else ''}）")
        for x in shown:
            arrow = "▲" if x["change_pct"] >= 0 else "▼"
            tag = "★持股 " if x.get("is_holding") else ""
            sig_msgs = "、".join(s["msg"] for s in x["signals"] if s["type"] == "buy")
            lines.append(f"  {tag}{x['name']} ${x['price']:.2f} {arrow}{abs(x['change_pct']):.1f}%")
            lines.append(f"    {sig_msgs}")
        if omit:
            lines.append(f"  …另 {omit} 檔略")

    if sells:
        shown = sells[:_MAX_SELL]
        omit  = len(sells) - len(shown)
        lines.append(f"\n📉 賣出訊號（{len(sells)} 檔{'，顯示前'+str(_MAX_SELL) if omit else ''}）")
        for x in shown:
            arrow = "▲" if x["change_pct"] >= 0 else "▼"
            tag = "★持股 " if x.get("is_holding") else ""
            sig_msgs = "、".join(s["msg"] for s in x["signals"] if s["type"] == "sell")
            lines.append(f"  {tag}{x['name']} ${x['price']:.2f} {arrow}{abs(x['change_pct']):.1f}%")
            lines.append(f"    {sig_msgs}")
        if omit:
            lines.append(f"  …另 {omit} 檔略")

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
    sector_note: str = "",
) -> str:
    """建立隔日當沖 Top N 推播訊息（甜蜜點區間＋兩段停利＋停損）"""
    header = f"【{date_str} 明日當沖候選 Top{len(candidates)}】"
    if regime:
        header += f"\n{regime['emoji']} 大盤{regime['state']}｜門檻 {40 + regime['min_score_adj']}分"
        if regime.get("futures_desc"):
            header += f"\n{regime['futures_desc']}"
    if sector_note:
        header += sector_note
    lines = [header, "量能＋籌碼＋技術＋波動度＋Beta＋MDD評分", ""]
    for i, c in enumerate(candidates, 1):
        arrow = "▲" if c["change_pct"] >= 0 else "▼"
        beta     = c.get("beta", 1.0)
        rs5      = c.get("rs5",  1.0)
        beta_tag = f"β{beta:.1f}" if beta != 1.0 else ""
        rs_tag   = f" RS5={rs5:.1f}x" if rs5 != 1.0 else ""
        lines.append(f"{i}. {c['name']}（昨收 ${c['price']:.1f}）分數 {c['score']}  {beta_tag}{rs_tag}")
        lines.append(f"   {arrow}{abs(c['change_pct']):.1f}%  量比{c['vol_ratio']:.1f}x  ATR {c.get('atr_pct', 0):.1f}%")
        lines.append(f"   📍甜蜜點 ${c.get('entry_low', '-')}～${c.get('entry_high', '-')}（參考 ${c.get('entry_mid', '-')}）")
        mdd_20 = c.get("mdd_20", 0)
        mdd_tag = f"  MDD {mdd_20:.1f}%" if mdd_20 > 10 else ""
        lines.append(f"   🛑停損 ${c.get('stop', '-')}（風險 -{c.get('risk_pct', 0):.1f}%{mdd_tag}）")
        lines.append(f"   🎯停利① ${c.get('tp1', '-')}（+{c.get('upside_pct1', 0):.1f}% RR={c.get('rr1', '-')}）出半倉")
        lines.append(f"   🎯停利② ${c.get('tp2', '-')}（+{c.get('upside_pct2', 0):.1f}% RR={c.get('rr2', '-')}）全出")
        if c.get("suggested_lots"):
            kelly_mult = c.get("kelly_mult", 1.0)
            adj_lots   = max(1, round(c["suggested_lots"] * kelly_mult))
            risk_amt   = round((c["entry_mid"] - c["stop"]) * adj_lots * 1000)
            kelly_note = f"  凱利×{kelly_mult}" if kelly_mult != 1.0 else ""
            lines.append(f"   💰建議 {adj_lots} 張（風控 ${risk_amt:,}，約總資產 1%{kelly_note}）")
        hist_wr = c.get("hist_wr")
        if hist_wr is not None:
            lines.append(f"   📈歷史勝率 {hist_wr:.0f}%（{c.get('kelly_mult', 1.0)}x 倉位）")
        beta_sigs = c.get("beta_sigs", [])
        top_sigs  = (c.get("signals", [])[:2] + beta_sigs[:1])
        if top_sigs:
            lines.append(f"   → {' / '.join(top_sigs)}")
        lines.append("")
    if concentration_warning:
        lines.append(concentration_warning)
    lines.append("⚠️ 僅供參考，操作自負風險")
    return "\n".join(lines)


def build_weekly_message(weekly: list[dict], date_str: str,
                         sector_report: str = "", corr_warning: str = "") -> str:
    """週報：漲跌排行 + 強勢/弱勢股彙整"""
    sorted_w = sorted(weekly, key=lambda x: x["chg_w"], reverse=True)
    gainers  = [x for x in sorted_w if x["chg_w"] > 0][:5]
    losers   = [x for x in reversed(sorted_w) if x["chg_w"] < 0][:5]

    # 強勢股：本週漲 + 多頭排列 + MACD 多
    strong = [x for x in sorted_w
              if x["chg_w"] > 1 and x["trend"] == "多" and x["macd_bull"]][:5]
    # 弱勢股：本週跌 + 空頭排列
    weak = [x for x in sorted_w
            if x["chg_w"] < -1 and x["trend"] == "空"][:5]

    lines = [f"📊 【週報 {date_str}】監測 {len(weekly)} 檔", ""]

    if gainers:
        lines.append("🔥 本週漲幅 Top5")
        for i, x in enumerate(gainers, 1):
            lines.append(f"  {i}. {x['name']} ${x['close']:.1f}  +{x['chg_w']:.1f}%")
        lines.append("")

    if losers:
        lines.append("📉 本週跌幅 Top5")
        for i, x in enumerate(losers, 1):
            lines.append(f"  {i}. {x['name']} ${x['close']:.1f}  {x['chg_w']:.1f}%")
        lines.append("")

    if strong:
        lines.append("✅ 強勢股（漲＋多頭＋MACD多）")
        for x in strong:
            lines.append(f"  {x['name']}  RSI {x['rsi']:.0f}  週漲 +{x['chg_w']:.1f}%")
        lines.append("")

    if weak:
        lines.append("⚠️ 弱勢股（跌＋空頭排列）")
        for x in weak:
            lines.append(f"  {x['name']}  RSI {x['rsi']:.0f}  週跌 {x['chg_w']:.1f}%")
        lines.append("")

    if sector_report:
        lines.append(sector_report)
    if corr_warning:
        lines.append(corr_warning)
    lines.append("")
    lines.append("⚠️ 資料 T+1，僅供參考")
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
