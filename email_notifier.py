"""每日彙整 Email — 早盤掃描後寄一封完整報告到 Gmail"""
import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

_SCAN_RESULTS  = Path("scan_results.json")
_US_RESULTS    = Path("us_scan_results.json")
_BRIEFING_FILE = Path("morning_briefing.json")


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _pre(text: str) -> str:
    """把純文字段落轉成保留換行的 HTML 區塊"""
    return f'<pre style="white-space:pre-wrap;font-family:inherit;margin:0">{text}</pre>'


def _section(title: str, body_html: str) -> str:
    return (
        f'<h3 style="margin:24px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px">{title}</h3>'
        f'{body_html}'
    )


def build_email_html() -> tuple[str, str]:
    """回傳 (subject, html_body)，若無任何內容則 body 為空字串"""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    scan = _load(_SCAN_RESULTS)
    us_scan = _load(_US_RESULTS)
    briefing = _load(_BRIEFING_FILE)

    parts = []

    if briefing:
        rows = []
        for key, label in (("us_summary", "🌙 美股夜盤"), ("fx", "💱 匯率"),
                           ("news", "📰 新聞"), ("trends", "🔥 趨勢"), ("gmail", "📧 Gmail")):
            if briefing.get(key):
                rows.append(_pre(briefing[key]))
        if rows:
            parts.append(_section(f"☀️ 早安日報（{briefing.get('timestamp', '')}）", "".join(rows)))

    morning_report = scan.get("morning_report", {})
    if morning_report:
        rows = [_pre(text) for text in morning_report.values()]
        parts.append(_section(f"🔔 早盤警示彙整（{scan.get('morning_report_time', '')}）", "".join(rows)))

    buys  = scan.get("buy_signals", [])
    sells = scan.get("sell_signals", [])
    if buys or sells:
        rows = []
        for x in buys:
            sign = "+" if x['change_pct'] >= 0 else ""
            rows.append(f"<div>📈 <b>{x['name']}</b> ${x['price']:.2f}　{sign}{x['change_pct']}%　分數 {x['score']}"
                        f"<br><span style='color:#666'>{('、'.join(x['signals']))}</span></div>")
        for x in sells:
            rows.append(f"<div>📉 <b>{x['name']}</b> ${x['price']:.2f}　{x['change_pct']}%　分數 {x['score']}"
                        f"<br><span style='color:#666'>{('、'.join(x['signals']))}</span></div>")
        parts.append(_section(f"📊 技術訊號（{scan.get('timestamp', '')}）", "".join(rows)))

    daytrade = scan.get("daytrade", [])
    if daytrade:
        rows = ["<table style='border-collapse:collapse;width:100%'>"
                "<tr style='text-align:left'><th>名稱</th><th>分數</th><th>現價</th>"
                "<th>進場</th><th>停損</th><th>停利①</th><th>停利②</th></tr>"]
        for c in daytrade:
            rows.append(
                f"<tr><td>{c['name']}</td><td>{c['score']}</td><td>${c['price']}</td>"
                f"<td>{c.get('entry_mid', '-')}</td><td>{c.get('stop', '-')}</td>"
                f"<td>{c.get('tp1', '-')}</td><td>{c.get('tp2', '-')}</td></tr>"
            )
        rows.append("</table>")
        parts.append(_section("🎯 明日當沖候選", "".join(rows)))

    if us_scan.get("signals"):
        rows = []
        for x in us_scan["signals"][:10]:
            arrow = "▲" if x["change_pct"] >= 0 else "▼"
            rows.append(
                f"<div><b>{x['name']}</b> ${x['price']:.2f}　{arrow}{abs(x['change_pct'])}%　分數 {x['score']}"
                f"<br><span style='color:#666'>{('、'.join(x['signals'][:3]))}</span></div>"
            )
        parts.append(_section(f"🌙 美股夜盤訊號（{us_scan.get('timestamp', '')}）", "".join(rows)))

    weekly_report  = scan.get("weekly_report")
    monthly_report = scan.get("monthly_report")
    if weekly_report:
        parts.append(_section(f"📊 週報（{scan.get('weekly_report_date', '')}）", _pre(weekly_report)))
    if monthly_report:
        parts.append(_section(f"📅 月報（{scan.get('monthly_report_date', '')}）", _pre(monthly_report)))

    if not parts:
        return "", ""

    body = (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'font-size:14px;color:#222;max-width:640px">'
        f'<h2 style="margin:0 0 8px">📈 股票每日彙整 {date_str}</h2>'
        + "".join(parts) +
        '<p style="margin-top:24px;color:#999;font-size:12px">⚠️ 資料 T+1，僅供參考，不構成投資建議。</p>'
        '</div>'
    )
    subject = f"📈 股票每日彙整 {date_str}"
    return subject, body


def send_daily_email() -> bool:
    subject, html = build_email_html()
    if not html:
        print("[Email] 無內容可寄送，跳過")
        return False

    gmail_addr = os.getenv("GMAIL_ADDRESS")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    to_addr    = os.getenv("GMAIL_TO") or gmail_addr
    if not gmail_addr or not gmail_pass:
        print("[Email] 未設定 GMAIL_ADDRESS / GMAIL_APP_PASSWORD，跳過")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(gmail_addr, gmail_pass)
            server.sendmail(gmail_addr, [to_addr], msg.as_string())
        print(f"[Email] 已寄出：{subject}")
        return True
    except Exception as e:
        print(f"[Email] 寄送失敗：{e}")
        return False


if __name__ == "__main__":
    send_daily_email()
