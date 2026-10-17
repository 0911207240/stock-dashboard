"""把 morning_briefing.json（＋每週行銷靈感）轉成一頁 HTML，用預設瀏覽器打開"""
import html
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "morning_page.html"
MARKETING = BASE / "marketing_weekly.md"

SECTIONS = [
    ("markets", "三大市場"),
    ("us_summary", "美股夜盤"),
    ("fx", "匯率"),
    ("news", "新聞"),
    ("trends", "社群與趨勢"),
    ("gmail", "Gmail 摘要"),
]

CSS = """
:root{--bg:#fafaf7;--fg:#1d1d1b;--card:#fff;--line:#e6e4dc;--mute:#6b6a63;--acc:#1a7f5a}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe5;--card:#1f1f1c;--line:#34332e;--mute:#9a988e;--acc:#4cc38a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 system-ui,"Microsoft JhengHei",sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 56px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mute);font-size:14px;margin-bottom:20px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:0 0 14px}
h2{font-size:15px;margin:0 0 8px;color:var(--acc)}
pre{white-space:pre-wrap;word-break:break-word;margin:0;font:inherit}
.warn{border-color:#c98a1a;color:#c98a1a;margin-bottom:14px;padding:10px 14px;border:1px solid;border-radius:10px;font-size:14px}
"""


def _block(title: str, body: str) -> str:
    return f"<section><h2>{html.escape(title)}</h2><pre>{html.escape(body.strip())}</pre></section>"


def build() -> str:
    try:
        data = json.loads((BASE / "morning_briefing.json").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    today = datetime.now().strftime("%Y-%m-%d")
    parts = []
    if not data:
        parts.append('<div class="warn">找不到日報資料，請確認 git pull 是否成功。</div>')
    elif data.get("date") != today:
        parts.append(f'<div class="warn">今天的日報還沒產生，以下是 {html.escape(str(data.get("timestamp", "")))} 的內容。</div>')
    for key, title in SECTIONS:
        if data.get(key):
            parts.append(_block(title, data[key]))

    if MARKETING.exists():
        age = (datetime.now() - datetime.fromtimestamp(MARKETING.stat().st_mtime)).days
        if age <= 8:
            parts.append(_block("本週行銷靈感", MARKETING.read_text(encoding="utf-8")))

    stamp = html.escape(str(data.get("timestamp", "")))
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>早安日報</title>'
            f"<style>{CSS}</style></head><body><main><h1>早安日報</h1>"
            f'<div class="sub">資料時間 {stamp}</div>{"".join(parts)}</main></body></html>')


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"已產生 {OUT}")
    if "--no-open" not in sys.argv:
        webbrowser.open(OUT.as_uri())
