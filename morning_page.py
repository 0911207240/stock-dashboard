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
:root{--bg:#f8f8f6;--panel:#fff;--fg:#16181d;--mute:#6c7079;--line:#dcdcd6;--rule:#16181d;--acc:#1f3a5f;
--up:#c8102e;--down:#0b7a4b;--warn:#9a6a00;--head:#f1f1ed}
@media (prefers-color-scheme:dark){:root{--bg:#0f1114;--panel:#161920;--fg:#e6e7ea;--mute:#8d929c;--line:#2a2e37;
--rule:#e6e7ea;--acc:#8fb2e6;--up:#ff6b78;--down:#46c28a;--warn:#e0b050;--head:#1c2029}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 "Noto Sans TC","Microsoft JhengHei","PingFang TC",system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
main{max-width:1040px;margin:0 auto;padding:32px 20px 56px;background:var(--panel);min-height:100vh;
border-left:1px solid var(--line);border-right:1px solid var(--line)}
.kicker{font-size:11px;letter-spacing:.22em;color:var(--acc);font-weight:600}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;
border-bottom:2px solid var(--rule);padding-bottom:12px}
h1{font-size:26px;font-weight:700;margin:2px 0 0;letter-spacing:.02em}
.stamp{font-size:12px;color:var(--mute);text-align:right}
.note{margin:12px 0 0;padding:8px 12px;border-left:3px solid var(--acc);background:var(--head);font-size:13px}
.note.warn{border-color:var(--warn);color:var(--warn)}
.strip{display:flex;flex-wrap:wrap;border-bottom:1px solid var(--line)}
.tick{flex:1 1 150px;padding:10px 14px;border-right:1px solid var(--line)}
.tick:last-child{border-right:0}
.tick .l{font-size:11px;color:var(--mute);letter-spacing:.06em}
.tick .n{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.tick .p{font-size:12px;font-weight:600;margin-left:6px;font-variant-numeric:tabular-nums}
section{margin-top:30px}
h2{font-size:13px;font-weight:700;letter-spacing:.12em;margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid var(--rule);
display:flex;gap:10px;align-items:baseline}
h2 i{font-style:normal;color:var(--acc);font-variant-numeric:tabular-nums}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:28px;align-items:start}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
caption{text-align:left;font-size:11px;letter-spacing:.1em;color:var(--mute);padding-bottom:4px;font-weight:600}
th{font-size:11px;font-weight:600;color:var(--mute);text-align:right;padding:6px 8px;background:var(--head);letter-spacing:.06em}
th:first-child{text-align:left}
th.l{text-align:left}
td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
td:first-child{text-align:left;white-space:normal}
.up{color:var(--up)}.down{color:var(--down)}.flat{color:var(--mute)}
td.pct,.p{font-weight:600}
td.txt{text-align:left;color:var(--mute);white-space:normal}
.blk h3{font-size:12px;font-weight:700;letter-spacing:.08em;color:var(--acc);margin:0 0 4px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.blk ul{list-style:none;margin:0;padding:0}
.blk li{padding:6px 0;border-bottom:1px solid var(--line);display:flex;gap:10px}
.blk li span.k{color:var(--mute);font-size:11px;min-width:14px;padding-top:2px;font-variant-numeric:tabular-nums}
.tip{display:grid;grid-template-columns:34px 1fr;gap:4px 12px;padding:12px 0;border-bottom:1px solid var(--line)}
.tip .no{font-size:22px;font-weight:700;color:var(--acc);line-height:1.1}
.tip h3{font-size:15px;margin:0 0 6px}
.tip dl{display:grid;grid-template-columns:78px 1fr;gap:3px 10px;margin:0}
.tip dt{color:var(--mute);font-size:12px;padding-top:1px}.tip dd{margin:0}
a{color:var(--acc);word-break:break-all}
.muted{color:var(--mute);font-size:12px}
footer{margin-top:36px;padding-top:12px;border-top:1px solid var(--line)}
@media (max-width:560px){h1{font-size:21px}.stamp{text-align:left}.tip dl{grid-template-columns:1fr}.tick{flex-basis:45%}}
"""

_sec_no = [0]


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def linkify(s: str) -> str:
    return re.sub(r'(https?://[^\s）)，、]+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', esc(s))


def _clean(s: str) -> str:
    """去掉標題開頭的 emoji 與符號"""
    return re.sub(r"^[^\w一-鿿]+", "", s).strip()


def _blocks(text: str) -> list[tuple[str, list[str]]]:
    """以空行切段；每段第一行為標題，其餘為條目（去掉編號與箭頭）"""
    out = []
    for blk in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in blk.splitlines() if l.strip()]
        if not lines:
            continue
        out.append((lines[0], [re.sub(r"^(\d+\.\s*|→\s*)", "", l) for l in lines[1:]]))
    return out


def _pct_cls(p: float) -> str:
    return "up" if p > 0 else "down" if p < 0 else "flat"  # 台灣慣例：紅漲綠跌


_ITEM = re.compile(r"^(.*?)\s+([\d,\.]+)（([+-]?[\d.]+)%）$")
_FX = re.compile(r"^(\S+?)：([\d.]+)（均 ([\d.]+)，([+-]?[\d.]+)%）\s*(.*)$")


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


def section(title: str, body: str) -> str:
    _sec_no[0] += 1
    return f"<section><h2><i>{_sec_no[0]:02d}</i>{esc(title)}</h2>{body}</section>"


def render_markets(text: str) -> str:
    tables = []
    for name, items in parse_markets(text):
        rows = "".join(
            f'<tr><td>{esc(n)}</td><td>{esc(v)}</td><td class="pct {_pct_cls(p)}">{p:+.2f}%</td></tr>'
            for n, v, p in items)
        tables.append(f"<table><caption>{esc(_clean(name))}</caption>"
                      f"<thead><tr><th>指標</th><th>收盤</th><th>漲跌幅</th></tr></thead><tbody>{rows}</tbody></table>")
    return section("市場概況", f'<div class="cols">{"".join(tables)}</div>') if tables else ""


def render_chips(text: str) -> str:
    want = ["加權指數", "S&P 500", "那斯達克", "費城半導體", "台幣兌美元"]
    found = {n: (v, p) for _, items in parse_markets(text) for n, v, p in items}
    ticks = [f'<div class="tick"><div class="l">{esc(n)}</div><span class="n">{esc(found[n][0])}</span>'
             f'<span class="p {_pct_cls(found[n][1])}">{found[n][1]:+.2f}%</span></div>' for n in want if n in found]
    return f'<div class="strip">{"".join(ticks)}</div>' if ticks else ""


def render_fx(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows = ""
    for l in lines[1:]:
        m = _FX.match(l)
        if not m:
            continue
        name, now, avg, dev, sig = m.groups()
        d = float(dev)
        # 相對均值為正 = 比均值便宜，用綠色；偏貴用紅色
        rows += (f'<tr><td>{esc(name)}</td><td>{now}</td><td>{avg}</td>'
                 f'<td class="pct {"down" if d > 0 else "up"}">{d:+.1f}%</td><td class="txt">{esc(sig)}</td></tr>')
    if not rows:
        return ""
    tbl = ('<table><thead><tr><th>幣別</th><th>現價（TWD）</th><th>1 年均值</th><th>相對均值</th>'
           f'<th class="l">判讀</th></tr></thead><tbody>{rows}</tbody></table>')
    cap = esc(_clean(lines[0]))
    return section("匯率", tbl + f'<div class="muted" style="margin-top:6px">{cap}。相對均值為正代表比均值便宜。</div>')


def render_lists(title: str, text: str) -> str:
    cols = []
    for head, items in _blocks(text):
        if not items:
            continue
        li = "".join(f'<li><span class="k">{n}</span><span>{esc(i)}</span></li>' for n, i in enumerate(items, 1))
        cols.append(f'<div class="blk"><h3>{esc(_clean(head))}</h3><ul>{li}</ul></div>')
    return section(title, f'<div class="cols">{"".join(cols)}</div>') if cols else ""


def render_marketing(text: str) -> str:
    stamp = ""
    m = re.match(r"^（(.*?)）", text.strip())
    if m:
        stamp = m.group(1)
    entries = []
    for n, part in enumerate(re.split(r"^### ", text, flags=re.M)[1:], 1):
        lines = part.strip().splitlines()
        title = re.sub(r"^\d+\.\s*", "", lines[0])
        dl = ""
        for l in lines[1:]:
            lm = re.match(r"^-\s*(.*?)：(.*)$", l.strip())
            if lm:
                dl += f"<dt>{esc(lm.group(1))}</dt><dd>{linkify(lm.group(2))}</dd>"
        entries.append(f'<div class="tip"><div class="no">{n}</div><div><h3>{esc(title)}</h3><dl>{dl}</dl></div></div>')
    if not entries:
        return ""
    sub = f'<div class="muted" style="margin-top:8px">{esc(stamp)}。未附來源者為推測。</div>' if stamp else ""
    return section("本週行銷靈感", "".join(entries) + sub)


def build() -> str:
    try:
        data = json.loads((BASE / "morning_briefing.json").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    _sec_no[0] = 0
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    title = f"{now.month} 月 {now.day} 日　週{WEEKDAYS[now.weekday()]}"
    stamp = esc(str(data.get("timestamp", "")))

    notes = []
    if not data:
        notes.append('<div class="note warn">找不到日報資料，請確認 git pull 是否成功。</div>')
    elif data.get("date") != today:
        notes.append(f'<div class="note warn">今天的日報尚未產生，以下為 {stamp} 的資料。</div>')
    if data.get("us_summary"):
        notes.append(f'<div class="note">{esc(_clean(data["us_summary"].replace("美股夜盤", "", 1)))}</div>')

    parts = []
    if data.get("markets"):
        parts.append(render_markets(data["markets"]))
    if data.get("fx"):
        parts.append(render_fx(data["fx"]))
    if data.get("news"):
        parts.append(render_lists("新聞", data["news"]))
    if data.get("trends"):
        parts.append(render_lists("社群與趨勢", data["trends"]))
    if MARKETING.exists():
        age = (now - datetime.fromtimestamp(MARKETING.stat().st_mtime)).days
        if age <= 8:
            parts.append(render_marketing(MARKETING.read_text(encoding="utf-8")))

    chips = render_chips(data["markets"]) if data.get("markets") else ""
    gmail = f"{esc(data['gmail'])}｜" if data.get("gmail") else ""
    foot = (f'<footer class="muted">{gmail}資料來源：Yahoo Finance、證交所開放資料、中央社、自由時報、Google 趨勢、PTT。'
            "報價可能延遲，內容僅供參考，不構成投資建議。</footer>")
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>早安日報</title>'
            f"<style>{CSS}</style></head><body><main>"
            f'<div class="top"><div><div class="kicker">MORNING BRIEFING</div><h1>{title}</h1></div>'
            f'<div class="stamp">資料時間<br>{stamp}</div></div>'
            f'{chips}{"".join(notes)}{"".join(parts)}{foot}</main></body></html>')


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"已產生 {OUT}")
    if "--no-open" not in sys.argv:
        webbrowser.open(OUT.as_uri())
