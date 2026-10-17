"""把 morning_briefing.json（＋每週行銷靈感）轉成一頁 HTML，用預設瀏覽器打開"""
import html
import json
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "morning_page.html"
MARKETING = BASE / "marketing_weekly.md"
WEEKDAYS = "一二三四五六日"

CSS = """
:root{--bg:#f4f3ee;--fg:#1f1f1c;--card:#fff;--line:#e7e5dc;--mute:#7a786e;--acc:#1a7f5a;
--up:#d92d3a;--down:#14935f;--chip:#f0efe8;--warn:#b7791f;--shadow:0 1px 2px rgba(0,0,0,.04),0 6px 18px rgba(0,0,0,.05)}
@media (prefers-color-scheme:dark){:root{--bg:#121211;--fg:#ecebe5;--card:#1d1d1a;--line:#2f2e29;--mute:#9a988e;
--acc:#4cc38a;--up:#ff6b73;--down:#4cc38a;--chip:#2a2925;--warn:#e0a84a;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 system-ui,"Microsoft JhengHei","PingFang TC",sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 64px}
header{margin-bottom:18px}
.date{font-size:28px;font-weight:700;letter-spacing:.5px;margin:0}
.sub{color:var(--mute);font-size:13px;margin-top:2px}
.banner{margin:14px 0 0;padding:9px 14px;border-radius:10px;background:var(--chip);font-size:14px}
.warn{border:1px solid var(--warn);color:var(--warn);background:transparent}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 4px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:6px 14px;box-shadow:var(--shadow);
font-size:13px;display:flex;gap:8px;align-items:baseline}
.chip b{font-weight:600}
h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin:30px 0 10px;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:var(--shadow)}
.card h3{font-size:15px;margin:0 0 8px;font-weight:600}
.row{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-top:1px solid var(--line);font-size:14px}
.row:first-of-type{border-top:0}
.row .v{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.pct{font-weight:600;margin-left:8px;display:inline-block;min-width:62px}
.up{color:var(--up)}.down{color:var(--down)}.flat{color:var(--mute)}
ol,ul{margin:0;padding-left:20px}li{padding:3px 0}
.fx .big{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}
.fx .meta{color:var(--mute);font-size:13px}
.tag{display:inline-block;margin-top:6px;padding:2px 10px;border-radius:999px;font-size:12px;background:var(--chip)}
.tag.cheap{color:var(--down)}.tag.pricey{color:var(--warn)}
.tip .lab{display:inline-block;min-width:76px;color:var(--mute);font-size:12px}
.tip p{margin:6px 0;font-size:14px}
a{color:var(--acc);word-break:break-all}
.muted{color:var(--mute);font-size:13px}
@media (max-width:520px){.date{font-size:23px}.grid{grid-template-columns:1fr}}
"""


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def linkify(s: str) -> str:
    return re.sub(r'(https?://[^\s）)，、]+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', esc(s))


def _blocks(text: str) -> list[tuple[str, list[str]]]:
    """以空行切段；每段第一行為標題，其餘為條目（去掉編號與箭頭）"""
    out = []
    for blk in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in blk.splitlines() if l.strip()]
        if not lines:
            continue
        items = [re.sub(r"^(\d+\.\s*|→\s*)", "", l) for l in lines[1:]]
        out.append((lines[0], items))
    return out


def _pct_cls(p: float) -> str:
    return "up" if p > 0 else "down" if p < 0 else "flat"


_ITEM = re.compile(r"^(.*?)\s+([\d,\.]+)（([+-]?[\d.]+)%）$")


def parse_markets(text: str):
    groups = []
    for line in text.splitlines()[1:]:
        if "：" not in line:
            continue
        name, rest = line.strip().split("：", 1)
        items = []
        for part in rest.split("｜"):
            m = _ITEM.match(part.strip())
            if m:
                items.append((m.group(1), m.group(2), float(m.group(3))))
        if items:
            groups.append((name, items))
    return groups


def render_markets(text: str) -> str:
    groups = parse_markets(text)
    if not groups:
        return ""
    cards = []
    for name, items in groups:
        rows = "".join(
            f'<div class="row"><span>{esc(n)}</span><span class="v">{esc(v)}'
            f'<span class="pct {_pct_cls(p)}">{p:+.2f}%</span></span></div>' for n, v, p in items)
        cards.append(f'<div class="card"><h3>{esc(name)}</h3>{rows}</div>')
    return f'<h2>三大市場</h2><div class="grid">{"".join(cards)}</div>'


def render_chips(text: str) -> str:
    want = ["加權指數", "S&P 500", "那斯達克", "費城半導體", "台幣兌美元"]
    found = {n: (v, p) for _, items in parse_markets(text) for n, v, p in items}
    chips = [f'<div class="chip"><b>{esc(n)}</b>{esc(found[n][0])}'
             f'<span class="{_pct_cls(found[n][1])}">{found[n][1]:+.2f}%</span></div>' for n in want if n in found]
    return f'<div class="chips">{"".join(chips)}</div>' if chips else ""


_FX = re.compile(r"^(\S+?)：([\d.]+)（均 ([\d.]+)，([+-]?[\d.]+)%）\s*(.*)$")


def render_fx(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return ""
    cards = []
    for l in lines[1:]:
        m = _FX.match(l)
        if not m:
            continue
        name, now, avg, dev, sig = m.groups()
        d = float(dev)
        cls = "cheap" if d > 0 else "pricey"
        tag = f'<span class="tag {cls}">{esc(sig)}</span>' if sig else ""
        cards.append(f'<div class="card fx"><h3>{esc(name)}</h3><div class="big">{now}</div>'
                     f'<div class="meta">1 年均值 {avg}｜{d:+.1f}%</div>{tag}</div>')
    note = esc(re.sub(r"^💱\s*", "", lines[0]))
    return f'<h2>匯率</h2><div class="grid">{"".join(cards)}</div><div class="muted" style="margin-top:6px">{note}</div>'


def render_lists(title: str, text: str, ordered: bool = True) -> str:
    cards = []
    for head, items in _blocks(text):
        if not items:
            continue
        tag = "ol" if ordered else "ul"
        li = "".join(f"<li>{esc(i)}</li>" for i in items)
        cards.append(f'<div class="card"><h3>{esc(head)}</h3><{tag}>{li}</{tag}></div>')
    return f'<h2>{esc(title)}</h2><div class="grid">{"".join(cards)}</div>' if cards else ""


def render_marketing(text: str) -> str:
    stamp = ""
    m = re.match(r"^（(.*?)）", text.strip())
    if m:
        stamp = m.group(1)
    cards = []
    for part in re.split(r"^### ", text, flags=re.M)[1:]:
        lines = part.strip().splitlines()
        title = re.sub(r"^\d+\.\s*", "", lines[0])
        body = ""
        for l in lines[1:]:
            lm = re.match(r"^-\s*(.*?)：(.*)$", l.strip())
            if lm:
                body += f'<p><span class="lab">{esc(lm.group(1))}</span>{linkify(lm.group(2))}</p>'
            elif l.strip():
                body += f'<p class="muted">{linkify(l.strip())}</p>'
        cards.append(f'<div class="card tip"><h3>{esc(title)}</h3>{body}</div>')
    if not cards:
        return ""
    sub = f'<div class="muted" style="margin-top:6px">{esc(stamp)}</div>' if stamp else ""
    return f'<h2>本週行銷靈感</h2><div class="grid">{"".join(cards)}</div>{sub}'


def build() -> str:
    try:
        data = json.loads((BASE / "morning_briefing.json").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    title = f"{now.month} 月 {now.day} 日　週{WEEKDAYS[now.weekday()]}"
    stamp = esc(str(data.get("timestamp", "")))

    banners = []
    if not data:
        banners.append('<div class="banner warn">找不到日報資料，請確認 git pull 是否成功。</div>')
    elif data.get("date") != today:
        banners.append(f'<div class="banner warn">今天的日報還沒產生，以下是 {stamp} 的內容。</div>')
    if data.get("us_summary"):
        banners.append(f'<div class="banner">{esc(data["us_summary"].replace("🌙 美股夜盤", "").strip())}</div>')

    parts = []
    if data.get("markets"):
        parts.append(render_markets(data["markets"]))
    if data.get("fx"):
        parts.append(render_fx(data["fx"]))
    if data.get("news"):
        parts.append(render_lists("新聞", data["news"]))
    if data.get("trends"):
        parts.append(render_lists("社群與趨勢", data["trends"], ordered=False))
    if MARKETING.exists():
        age = (now - datetime.fromtimestamp(MARKETING.stat().st_mtime)).days
        if age <= 8:
            parts.append(render_marketing(MARKETING.read_text(encoding="utf-8")))
    if data.get("gmail"):
        parts.append(f'<p class="muted" style="margin-top:28px">{esc(data["gmail"])}</p>')

    chips = render_chips(data["markets"]) if data.get("markets") else ""
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>早安日報</title>'
            f"<style>{CSS}</style></head><body><main><header>"
            f'<h1 class="date">☀️ {title}</h1><div class="sub">早安日報｜資料時間 {stamp}</div>'
            f'{"".join(banners)}{chips}</header>{"".join(parts)}</main></body></html>')


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"已產生 {OUT}")
    if "--no-open" not in sys.argv:
        webbrowser.open(OUT.as_uri())
