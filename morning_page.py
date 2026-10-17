"""把 morning_briefing.json（＋每週行銷靈感）轉成一頁 HTML，用預設瀏覽器打開

版面邏輯：先給結論（標題＋今天先看三件事）→ 市場（加權為主視覺，另三個指數帶走勢線）
→ 匯率（1 年區間位置）→ 新聞 → 社群 → 本週一招。走勢資料開頁時由 yfinance 取得，
當天快取於 market_history_cache.json；抓不到就只省略圖，其餘照常顯示。
"""
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
CACHE = BASE / "market_history_cache.json"
WEEKDAYS = "一二三四五六日"

CHARTED = [("加權指數", "^TWII"), ("S&P 500", "^GSPC"), ("那斯達克", "^IXIC"), ("費城半導體", "^SOX")]
FX_NAMES = {"USD": "美元", "JPY": "日圓", "KRW": "韓元"}

CSS = """
:root{--bg:#fff;--fg:#14161a;--sub:#4b505a;--mute:#8a8f99;--line:#e8e8e4;--soft:#f6f6f3;--acc:#2b3a8c;
--up:#d3202f;--down:#0f8a56;--spark:#9aa0ab;--panel:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#0e1013;--fg:#eceef1;--sub:#b3b8c2;--mute:#7e848f;--line:#242830;
--soft:#171a20;--acc:#9db1ff;--up:#ff6b78;--down:#45c58c;--spark:#6c727e;--panel:#0e1013}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 "Noto Sans TC","Microsoft JhengHei","PingFang TC",system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
main{max-width:880px;margin:0 auto;padding:28px 20px 72px}
.bar{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:var(--mute);letter-spacing:.04em}
.bar b{color:var(--fg);font-weight:700;letter-spacing:.08em}.bar b::before{content:"";display:inline-block;width:8px;height:8px;
border-radius:50%;background:var(--acc);margin-right:8px}
.hero{padding:44px 0 36px}
h1{font-size:40px;line-height:1.25;font-weight:800;letter-spacing:-.01em;margin:0 0 14px}
.lede{font-size:17px;color:var(--sub);margin:0;max-width:640px}
.warn{margin:18px 0 0;padding:10px 14px;background:var(--soft);border-left:3px solid #b7791f;color:#8a5a12;font-size:14px}
.first{margin:0 0 28px;padding:0;list-style:none;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.first li{background:var(--soft);border-radius:14px;padding:16px 18px;display:grid;grid-template-columns:30px 1fr;gap:2px 12px;align-items:start}
.first .n{width:28px;height:28px;border-radius:50%;background:var(--acc);color:var(--bg);font-size:14px;font-weight:800;display:flex;align-items:center;justify-content:center}
.first .t{font-size:15.5px;font-weight:600;line-height:1.5}
.first .k{display:block;font-size:11px;font-weight:700;letter-spacing:.12em;color:var(--acc);margin-bottom:3px}
section{margin-top:56px;scroll-margin-top:60px}
.eyebrow{font-size:12px;font-weight:700;letter-spacing:.16em;color:var(--acc);margin:0 0 4px}
h2{font-size:26px;line-height:1.3;font-weight:800;margin:0 0 22px}
.big{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:28px;align-items:end;margin-bottom:28px}
.big .lab{font-size:14px;color:var(--sub);font-weight:600}
.big .val{font-size:60px;line-height:1.1;font-weight:800;letter-spacing:-.02em}
.big .dl{font-size:18px;font-weight:700;margin-left:10px}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.tile{background:var(--soft);border-radius:12px;padding:14px 16px 10px}
.tile .lab{font-size:13px;color:var(--sub);font-weight:600}
.tile .val{font-size:26px;line-height:1.2;font-weight:800;letter-spacing:-.01em}
.tile .dl{font-size:14px;font-weight:700;margin-left:6px}
.tile svg{margin-top:6px}
.spark{position:relative;display:block}
.spark svg{width:100%;height:auto;display:block;overflow:visible}
.cap{font-size:11px;letter-spacing:.08em;color:var(--mute);margin-top:4px}
.tip{position:absolute;pointer-events:none;background:var(--fg);color:var(--bg);font-size:12px;padding:3px 8px;border-radius:6px;
white-space:nowrap;transform:translate(-50%,-130%);opacity:0;transition:opacity .08s}
.up{color:var(--up)}.down{color:var(--down)}.flat{color:var(--mute)}
.others{columns:2;column-gap:40px;margin-top:8px}
.others>div{break-inside:avoid;margin-bottom:8px}
.others div.r{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--line);font-size:15px}
.others .v{font-variant-numeric:tabular-nums}
.others .h{font-size:12px;font-weight:700;letter-spacing:.12em;color:var(--mute);padding:14px 0 4px}
details{margin-top:18px;font-size:14px;color:var(--sub)}
summary{cursor:pointer;color:var(--mute)}
details table{width:100%;border-collapse:collapse;margin-top:10px;font-variant-numeric:tabular-nums}
details th,details td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}
details th:first-child,details td:first-child{text-align:left}
.fx{display:grid;grid-template-columns:72px minmax(0,1fr) 270px;gap:8px 28px;align-items:center;padding:16px 0;border-bottom:1px solid var(--line)}
.fx:first-of-type{border-top:1px solid var(--line)}
.fx .nm{font-weight:700}.fx .nm small{display:block;font-size:12px;color:var(--mute);font-weight:500}
.fx .now{font-size:22px;font-weight:800;text-align:right}
.rng{position:relative;height:6px;border-radius:3px;background:var(--line);margin:14px 0 18px}
.rng .m{position:absolute;top:-5px;width:16px;height:16px;border-radius:50%;background:var(--fg);border:2px solid var(--bg);
transform:translateX(-50%)}
.rng .a{position:absolute;top:-3px;width:2px;height:12px;background:var(--mute);transform:translateX(-50%)}
.rng .e{position:absolute;top:12px;font-size:11px;color:var(--mute);white-space:nowrap}
.fx .rd{font-size:14px;color:var(--sub);line-height:1.5}.fx .rd b{color:var(--fg)}
.fxnote{font-size:13px;color:var(--mute);margin-top:10px}
.news{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:30px 44px}
.news h3{font-size:12px;font-weight:700;letter-spacing:.14em;color:var(--acc);margin:0 0 6px}
.news ul{list-style:none;margin:0;padding:0}
.news li{padding:7px 0;border-bottom:1px solid var(--line);font-size:15px;line-height:1.55}
.subhead{font-size:12px;letter-spacing:.14em;color:var(--acc);margin:26px 0 10px}
.masonry{columns:2;column-gap:44px;margin-bottom:8px}
.masonry>div{break-inside:avoid;margin-bottom:26px}
.masonry h3{font-size:12px;font-weight:700;letter-spacing:.14em;color:var(--acc);margin:0 0 6px}
.masonry ul{list-style:none;margin:0;padding:0}
.masonry li{padding:7px 0;border-bottom:1px solid var(--line);font-size:15px;line-height:1.55}
.plain{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:0 44px}
.plain li{padding:7px 0;border-bottom:1px solid var(--line);break-inside:avoid;font-size:15px;line-height:1.55}
.src{color:var(--mute);font-size:12px;margin-left:8px;white-space:nowrap}
.bd{font-size:12px;color:var(--mute);margin:12px 0 2px;font-weight:600}.bd span{font-weight:400;margin-left:6px}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 26px}
.pill{background:var(--soft);border-radius:999px;padding:6px 14px;font-size:14px}
.pill small{color:var(--mute);margin-left:6px}
.lead{border-top:2px solid var(--fg);padding-top:18px;margin-bottom:6px}
.lead .no{font-size:13px;font-weight:700;letter-spacing:.14em;color:var(--acc)}
.lead h3{font-size:24px;line-height:1.35;font-weight:800;margin:4px 0 14px}
dl{display:grid;grid-template-columns:96px 1fr;gap:6px 14px;margin:0;font-size:15px}
dt{color:var(--mute);font-size:13px;padding-top:2px}dd{margin:0}
.more{margin-top:26px;border-top:1px solid var(--line)}
.more .it{padding:16px 0;border-bottom:1px solid var(--line)}
.more h3{font-size:17px;margin:0 0 6px}
a{color:var(--acc);word-break:break-all}
.small{font-size:13px;color:var(--mute)}
footer{margin-top:72px;padding-top:16px;border-top:1px solid var(--line)}
.meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
.meta span{font-size:12px;color:var(--sub);background:var(--soft);padding:3px 12px;border-radius:999px}
.nav{position:sticky;top:0;z-index:20;display:flex;gap:6px;padding:10px 0;background:color-mix(in srgb,var(--bg) 88%,transparent);
backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.nav a{color:var(--sub);text-decoration:none;font-size:14px;font-weight:600;padding:5px 14px;border-radius:999px}
.nav a.on,.nav a:hover{background:var(--acc);color:var(--bg)}
.news{gap:14px}
.news>div,.masonry>div{background:var(--soft);border-radius:14px;padding:16px 18px}
.masonry{column-gap:14px}.masonry>div{margin-bottom:14px}
.news li:last-child,.masonry li:last-child{border-bottom:0}
.masonry li{display:flex;justify-content:space-between;gap:10px}
.masonry li .src{align-self:flex-start;flex:none;max-width:42%;margin:3px 0 0;white-space:normal;text-align:right;line-height:1.5}
.push{flex:none;font-size:11px;font-weight:700;padding:1px 8px;border-radius:999px;background:var(--line);color:var(--sub);align-self:flex-start;margin-top:4px}
.push.hot{background:var(--up);color:#fff}
.cnt{margin-left:8px;font-weight:600;color:var(--mute)}
.fold{margin:6px 0 0}.fold summary{font-size:13px;padding:6px 0;color:var(--acc);cursor:pointer}.fold ul{margin-top:4px}
.src{display:inline-block;background:var(--line);color:var(--sub);border-radius:6px;padding:0 7px;font-size:11px;margin-left:8px;white-space:nowrap}
.lead{background:var(--soft);border:0;border-left:4px solid var(--acc);border-radius:14px;padding:20px 22px}
.more{border-top:0;margin-top:14px}
.more .it{background:var(--soft);border:0;border-radius:14px;padding:16px 20px;margin-top:12px}
.totop{position:fixed;right:20px;bottom:24px;width:42px;height:42px;border-radius:50%;border:0;background:var(--fg);color:var(--bg);
font-size:18px;cursor:pointer;opacity:0;pointer-events:none;transition:opacity .2s}
.totop.show{opacity:.85;pointer-events:auto}
@media (max-width:720px){h1{font-size:30px}.big{grid-template-columns:1fr}.big .val{font-size:46px}
.tiles{grid-template-columns:1fr}.first{grid-template-columns:1fr}.others{columns:1}.news{grid-template-columns:1fr}.plain{grid-template-columns:1fr}.masonry{columns:1}.fx{grid-template-columns:1fr}.fx .now{text-align:left}
dl{grid-template-columns:1fr}}
"""

_ITEM = re.compile(r"^(.*?)\s+([\d,\.]+)（([+-]?[\d.]+)%）$")
_FX = re.compile(r"^(\S+?)：([\d.]+)（均 ([\d.]+)，([+-]?[\d.]+)%）\s*(.*)$")


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def linkify(s: str) -> str:
    return re.sub(r"(https?://[^\s）)，、]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', esc(s))


def _clean(s: str) -> str:
    return re.sub(r"^[^\w一-鿿]+", "", s).strip()


def _cls(p: float) -> str:
    return "up" if p > 0 else "down" if p < 0 else "flat"  # 台灣慣例：紅漲綠跌


def _blocks(text: str) -> list[tuple[str, list[str]]]:
    out = []
    for blk in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in blk.splitlines() if l.strip()]
        if lines:
            out.append((_clean(lines[0]), [re.sub(r"^(\d+\.\s*|→\s*)", "", l) for l in lines[1:]]))
    return out


def parse_markets(text: str) -> list[tuple[str, list[tuple[str, str, float]]]]:
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
            groups.append((_clean(name), items))
    return groups


# ── 走勢資料（yfinance，當天快取）──────────────────────
def _fetch_history() -> dict:
    import yfinance as yf

    out = {"series": {}, "fx": {}}
    closes = yf.download([t for _, t in CHARTED], period="3mo", progress=False, auto_adjust=False)["Close"]
    for name, tk in CHARTED:
        s = closes[tk].dropna().tail(22)
        if len(s) >= 5:
            out["series"][name] = [[d.strftime("%m/%d"), round(float(v), 2)] for d, v in s.items()]

    fx = yf.download(["TWD=X", "JPY=X", "KRW=X"], period="1y", progress=False, auto_adjust=False)["Close"].dropna()
    twd = fx["TWD=X"]
    for code, ser in (("USD", twd), ("JPY", twd / fx["JPY=X"]), ("KRW", twd / fx["KRW=X"])):
        now = float(ser.iloc[-1])
        out["fx"][code] = {"now": now, "min": float(ser.min()), "max": float(ser.max()), "avg": float(ser.mean()),
                           "pct": float((ser <= now).mean() * 100)}
    return out


def load_history() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    cached = {}
    try:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        pass
    if cached.get("date") == today:
        return cached
    try:
        data = _fetch_history()
        data["date"] = today
        CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data
    except Exception as e:
        print(f"[頁面] 走勢資料取得失敗，改用舊快取或略過圖表：{e}")
        return cached


# ── 元件 ──────────────────────────────────────────────
def spark(name: str, pts: list, w: int, h: int, area: bool = False) -> str:
    vals = [p[1] for p in pts]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pad = 6
    xs = [pad + i * (w - 2 * pad) / (len(vals) - 1) for i in range(len(vals))]
    ys = [pad + (hi - v) / span * (h - 2 * pad) for v in vals]
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in zip(xs, ys))
    wash = (f'<path d="{d} L{xs[-1]:.1f} {h} L{xs[0]:.1f} {h} Z" fill="var(--spark)" opacity=".12"/>' if area else "")
    p = (vals[-1] - vals[-2]) / vals[-2] * 100
    data = html.escape(json.dumps({"p": pts, "w": w, "h": h, "pad": pad}, ensure_ascii=False), quote=True)
    return (f'<div class="spark" data-spark="{data}"><svg viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{esc(name)}近一個月走勢">{wash}'
            f'<path d="{d}" fill="none" stroke="var(--spark)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<line class="xh" y1="0" y2="{h}" stroke="var(--mute)" stroke-width="1" opacity="0"/>'
            f'<circle class="hd" r="4" fill="var(--fg)" stroke="var(--bg)" stroke-width="2" opacity="0"/>'
            f'<circle class="ed" cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="4.5" fill="var(--{_cls(p)})" stroke="var(--bg)" stroke-width="2"/>'
            f'</svg><div class="tip"></div></div>')


def fmt(v: float, digits: int) -> str:
    return f"{v:,.{digits}f}"


def build_quotes(markets_text: str, hist: dict) -> dict:
    """name -> (數字字串, 漲跌幅%)；有走勢資料的用走勢最後兩筆，其餘用日報文字"""
    q = {n: (v, p) for _, items in parse_markets(markets_text) for n, v, p in items}
    for name, pts in (hist.get("series") or {}).items():
        last, prev = pts[-1][1], pts[-2][1]
        q[name] = (fmt(last, 0), (last - prev) / prev * 100)
    return q


def headline(q: dict) -> tuple[str, str]:
    us = [(n, q[n][1]) for n in ("S&P 500", "那斯達克", "費城半導體") if n in q]
    if us:
        sp = q.get("S&P 500", us[0])[1] if "S&P 500" in q else us[0][1]
        verb = ("重挫" if sp <= -2 else "收跌" if sp <= -0.5 else "震盪" if sp < 0.5 else "收漲" if sp < 2 else "大漲")
        lead_n, lead_p = max(us, key=lambda x: abs(x[1]))
        h1 = f"隔夜美股{verb}，{lead_n} {lead_p:+.2f}%"
    else:
        h1 = "早安，今天的市場重點"
    bits = []
    if "加權指數" in q:
        v, p = q["加權指數"]
        bits.append(f"加權指數前一交易日 {p:+.2f}%，收 {v}")
    asia = [q[n][1] for n in ("日經 225", "韓國 KOSPI", "香港恆生", "上證綜指") if n in q]
    if asia:
        bits.append(f"亞洲 {sum(1 for x in asia if x > 0)}／{len(asia)} 個主要市場收紅")
    if "台幣兌美元" in q:
        bits.append(f"美元兌台幣 {q['台幣兌美元'][0]}")
    return h1, "；".join(bits)


def _first(news: dict, cat: str) -> str:
    for head, items in news:
        if head == cat and items:
            return items[0]
    return ""


def render_first(data: dict) -> str:
    news = _blocks(data.get("news", ""))
    items = []
    if _first(news, "台股重大訊息"):
        items.append(("公司公告", _first(news, "台股重大訊息")))
    if _first(news, "財經市場"):
        items.append(("財經", _first(news, "財經市場")))
    fx = [l.strip() for l in (data.get("fx") or "").splitlines()[1:] if l.strip()]
    for l in fx:
        m = _FX.match(l)
        if m and m.group(5):
            items.append(("匯率", f"{m.group(1)}：{m.group(5)}"))
            break
    if not items:
        return ""
    lis = "".join(f'<li><div class="n">{i}</div><div class="t"><span class="k">{esc(k)}</span>{esc(t)}</div></li>'
                  for i, (k, t) in enumerate(items, 1))
    return f'<ol class="first">{lis}</ol>'


def render_markets(q: dict, hist: dict, markets_text: str) -> str:
    series = hist.get("series") or {}
    body = ""
    if "加權指數" in series:
        v, p = q["加權指數"]
        body += (f'<div class="big"><div><div class="lab">加權指數</div><div class="val">{v}'
                 f'<span class="dl {_cls(p)}">{p:+.2f}%</span></div></div><div>{spark("加權指數", series["加權指數"], 480, 96, area=True)}<div class="cap">近 1 個月收盤走勢</div></div></div>')
        tiles = ""
        for name, _ in CHARTED[1:]:
            if name in series:
                tv, tp = q[name]
                tiles += (f'<div class="tile"><div class="lab">{esc(name)}</div><div class="val">{tv}'
                          f'<span class="dl {_cls(tp)}">{tp:+.2f}%</span></div>{spark(name, series[name], 200, 44)}</div>')
        body += f'<div class="tiles">{tiles}</div>'
    charted = {n for n, _ in CHARTED if n in series}
    cols = ""
    for g, items in parse_markets(markets_text):
        rows = [(n, v, p) for n, v, p in items if n not in charted]
        if rows:
            cols += f'<div><div class="h">{esc(g)}</div>' + "".join(
                f'<div class="r"><span>{esc(n)}</span><span class="v">{esc(v)}<span class="{_cls(p)}" '
                f'style="margin-left:10px;font-weight:700">{p:+.2f}%</span></span></div>' for n, v, p in rows) + "</div>"
    if cols:
        body += f'<div class="others">{cols}</div>'
    trs = "".join(f"<tr><td>{esc(n)}</td><td>{esc(v)}</td><td class=\"{_cls(p)}\">{p:+.2f}%</td></tr>"
                  for _, items in parse_markets(markets_text) for n, v, p in items)
    body += f'<details><summary>查看完整數據表</summary><table><tr><th>指標</th><th>收盤</th><th>漲跌幅</th></tr>{trs}</table></details>'
    return f'<section><p class="eyebrow">市場</p><h2>隔夜發生了什麼事</h2>{body}</section>'


def render_fx(data: dict, hist: dict) -> str:
    rng = hist.get("fx") or {}
    sigs = {}
    for l in (data.get("fx") or "").splitlines()[1:]:
        m = _FX.match(l.strip())
        if m:
            sigs[m.group(1)] = m.group(5)
    rows = ""
    for code, name in FX_NAMES.items():
        r = rng.get(code)
        if not r:
            continue
        pos = (r["now"] - r["min"]) / ((r["max"] - r["min"]) or 1) * 100
        avg = (r["avg"] - r["min"]) / ((r["max"] - r["min"]) or 1) * 100
        dg = 3 if code == "USD" else 5
        level = "接近 1 年高位" if r["pct"] >= 80 else "接近 1 年低位" if r["pct"] <= 20 else "落在 1 年區間中段"
        sig = sigs.get(name, "")
        rows += (f'<div class="fx"><div class="nm">{name}<small>兌台幣</small></div>'
                 f'<div><div class="rng"><span class="a" style="left:{avg:.1f}%"></span><span class="m" style="left:{pos:.1f}%"></span>'
                 f'<span class="e" style="left:0">{r["min"]:.{dg}f}</span><span class="e" style="right:0">{r["max"]:.{dg}f}</span></div></div>'
                 f'<div><div class="now">{r["now"]:.{dg}f}</div><div class="rd"><b>{level}</b>'
                 f'（高於過去一年 {r["pct"]:.0f}% 的日子）{("；" + esc(sig)) if sig else ""}</div></div></div>')
    if not rows:
        return ""
    return (f'<section><p class="eyebrow">匯率</p><h2>現在換匯划算嗎</h2>{rows}'
            '<p class="fxnote">圓點為現價，短直線為 1 年均值，兩端為過去一年最低與最高。位置只代表相對高低，不是買賣建議。</p></section>')


def render_news(data: dict) -> str:
    cols = ""
    for head, items in _blocks(data.get("news", "")):
        if items:
            first = "".join(f"<li>{esc(i)}</li>" for i in items[:3])
            rest = items[3:]
            fold = (f'<details class="fold"><summary>再看 {len(rest)} 則</summary><ul>'
                    + "".join(f"<li>{esc(i)}</li>" for i in rest) + "</ul></details>") if rest else ""
            cols += f'<div><h3>{esc(head)}<span class="cnt">{len(items)}</span></h3><ul>{first}</ul>{fold}</div>'
    return f'<section><p class="eyebrow">新聞</p><h2>今天值得看的</h2><div class="news">{cols}</div></section>' if cols else ""


def _live() -> dict:
    """本機即時社群資料；失敗就回空，不影響其他區塊"""
    try:
        import social_live

        return social_live.fetch_all()
    except Exception as e:
        print(f"[頁面] 即時社群資料抓取失敗：{e}")
        return {}


def render_social(data: dict, live: dict | None = None) -> str:
    live = live or {}
    pills, cols = "", ""
    for head, items in _blocks(data.get("trends", "")):
        if not items or (live.get("ptt") and "PTT" in head):  # 本機抓到 PTT 時，以本機結果為準
            continue
        if "熱搜" in head:
            for i in items:
                m = re.match(r"^(.*?)（搜尋量 (.*?)）$", i)
                pills += (f'<span class="pill">{esc(m.group(1))}<small>{esc(m.group(2))}</small></span>' if m
                          else f'<span class="pill">{esc(i)}</span>')
        else:
            cols += f'<div><h3>{esc(head)}</h3><ul>{"".join(f"<li>{esc(_clean(i))}</li>" for i in items)}</ul></div>'

    sub = '<h3 class="subhead">{}</h3>'
    out = ""
    if pills:
        out += sub.format("Google 台灣熱搜") + f'<div class="pills">{pills}</div>'

    gn = live.get("gnews") or []
    if gn:
        li = "".join(f'<li>{esc(t)}<span class="src">{esc(src)}</span></li>' for t, src in gn)
        out += sub.format("網路上正在被轉的新聞（Google 新聞台灣頭條）") + f'<ul class="plain">{li}</ul>'

    ptt = live.get("ptt") or {}
    try:
        from social_live import PTT_GROUPS
    except Exception:
        PTT_GROUPS = []
    groups = ""
    for theme, boards in PTT_GROUPS:
        inner = ""
        for board, name in boards:
            posts = ptt.get(board) or []
            if posts:
                inner += (f'<div class="bd">{esc(name)}<span>{esc(board)}</span></div><ul>'
                          + "".join(f'<li><span>{esc(t)}</span><span class="push{" hot" if n == "爆" else ""}">{esc(n)}</span></li>' for t, n in posts) + "</ul>")
        if inner:
            groups += f'<div><h3>PTT｜{esc(theme)}</h3>{inner}</div>'
    bh = live.get("bahamut") or []
    if bh:
        li = "".join(f'<li>{esc(t)}<span class="src">{esc(b)}</span></li>' for t, b, _ in bh)
        groups += f'<div><h3>巴哈姆特｜遊戲動漫熱門</h3><ul>{li}</ul></div>'
    if groups:
        out += sub.format("論壇正在討論什麼") + f'<div class="masonry">{groups}</div>'

    if cols:
        out += f'<div class="news" style="margin-top:22px">{cols}</div>'
    if not out:
        return ""
    note = (f'<p class="small" style="margin-top:14px">即時資料於 {esc(live.get("asof", ""))} 由本機抓取。'
            "PTT 取各看板近兩頁中推文數最高者；Dcard、Mobile01、Threads、IG、FB 沒有可用的公開資料，因此不在此列。</p>"
            if live else "")
    return f'<section><p class="eyebrow">社群</p><h2>大家在聊什麼</h2>{out}{note}</section>'


def render_marketing(text: str) -> str:
    m = re.match(r"^（(.*?)）", text.strip())
    stamp = m.group(1) if m else ""
    tips = []
    for part in re.split(r"^### ", text, flags=re.M)[1:]:
        lines = part.strip().splitlines()
        title = re.sub(r"^\d+\.\s*", "", lines[0])
        fields = {}
        for l in lines[1:]:
            lm = re.match(r"^-\s*(.*?)：(.*)$", l.strip())
            if lm:
                fields[lm.group(1)] = lm.group(2)
        tips.append((title, fields))
    if not tips:
        return ""

    def dl(f):
        return "<dl>" + "".join(f"<dt>{esc(k)}</dt><dd>{linkify(v)}</dd>" for k, v in f.items()) + "</dl>"

    t0, f0 = tips[0]
    out = f'<div class="lead"><div class="no">本週重點手法</div><h3>{esc(t0)}</h3>{dl(f0)}</div>'
    if len(tips) > 1:
        out += '<div class="more">' + "".join(f'<div class="it"><h3>{esc(t)}</h3>{dl(f)}</div>' for t, f in tips[1:]) + "</div>"
    note = f'<p class="small" style="margin-top:14px">{esc(stamp)}。未附來源者為推測。</p>' if stamp else ""
    return f'<section><p class="eyebrow">靈感</p><h2>本週可以偷學的一招</h2>{out}{note}</section>'


JS = """
(function(){
  var links=[].slice.call(document.querySelectorAll('.nav a'));
  if(links.length&&window.IntersectionObserver){
    var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){
      links.forEach(function(a){a.classList.toggle('on',a.getAttribute('href')=='#'+e.target.id)})}})},{rootMargin:'-25% 0px -65% 0px'});
    document.querySelectorAll('section[id]').forEach(function(x){io.observe(x)});
  }
  var up=document.querySelector('.totop');
  if(up){window.addEventListener('scroll',function(){up.classList.toggle('show',window.scrollY>600)});
    up.addEventListener('click',function(){window.scrollTo({top:0,behavior:'smooth'})});}
})();
document.querySelectorAll('.spark').forEach(function(el){
  var d=JSON.parse(el.dataset.spark),p=d.p,n=p.length,w=d.w,h=d.h,pad=d.pad;
  var v=p.map(function(x){return x[1]}),lo=Math.min.apply(null,v),hi=Math.max.apply(null,v),sp=(hi-lo)||1;
  var svg=el.querySelector('svg'),xh=el.querySelector('.xh'),hd=el.querySelector('.hd'),tip=el.querySelector('.tip');
  function X(i){return pad+i*(w-2*pad)/(n-1)}function Y(x){return pad+(hi-x)/sp*(h-2*pad)}
  el.addEventListener('mousemove',function(e){
    var r=svg.getBoundingClientRect(),f=(e.clientX-r.left)/r.width*w;
    var i=Math.max(0,Math.min(n-1,Math.round((f-pad)/(w-2*pad)*(n-1))));
    xh.setAttribute('x1',X(i));xh.setAttribute('x2',X(i));xh.setAttribute('opacity',1);
    hd.setAttribute('cx',X(i));hd.setAttribute('cy',Y(v[i]));hd.setAttribute('opacity',1);
    tip.textContent=p[i][0]+'　'+v[i].toLocaleString();
    tip.style.left=(X(i)/w*100)+'%';tip.style.top=(Y(v[i])/h*100)+'%';tip.style.opacity=1;});
  el.addEventListener('mouseleave',function(){xh.setAttribute('opacity',0);hd.setAttribute('opacity',0);tip.style.opacity=0;});
});
"""


def build() -> str:
    try:
        data = json.loads((BASE / "morning_briefing.json").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    now = datetime.now()
    hist = load_history() if data.get("markets") else {}
    q = build_quotes(data.get("markets", ""), hist) if data.get("markets") else {}
    h1, lede = headline(q) if q else ("早安，今天的市場重點", "")

    warn = ""
    if not data:
        warn = '<div class="warn">找不到日報資料，請確認 git pull 是否成功。</div>'
    elif data.get("date") != now.strftime("%Y-%m-%d"):
        warn = f'<div class="warn">今天的日報尚未產生，以下為 {esc(data.get("timestamp", ""))} 的資料。</div>'

    parts = [render_first(data)] if data.get("news") else []
    if data.get("markets"):
        parts.append(render_markets(q, hist, data["markets"]))
    parts.append(render_fx(data, hist))
    parts.append(render_news(data))
    live = _live()
    parts.append(render_social(data, live))
    if MARKETING.exists() and (now - datetime.fromtimestamp(MARKETING.stat().st_mtime)).days <= 8:
        parts.append(render_marketing(MARKETING.read_text(encoding="utf-8")))

    ids = {"市場": "market", "匯率": "fx", "新聞": "news", "社群": "social", "靈感": "idea"}
    nav_items, anchored = [], []
    for ph in parts:
        mm = re.search(r'<section><p class="eyebrow">(.*?)</p>', ph)
        if mm and mm.group(1) in ids:
            sid = ids[mm.group(1)]
            ph = ph.replace("<section>", f'<section id="{sid}">', 1)
            nav_items.append(f'<a href="#{sid}">{mm.group(1)}</a>')
        anchored.append(ph)
    first_html = ""
    if anchored and anchored[0].startswith('<ol class="first"'):
        first_html = anchored.pop(0)
    parts = anchored
    nav = f'<nav class="nav">{"".join(nav_items)}</nav>' if nav_items else ""
    meta = "".join(f"<span>{esc(t)}</span>" for t in (
        f"日報資料 {data.get('timestamp', '')}" if data.get("timestamp") else "",
        f"即時社群 {live.get('asof', '')}" if live.get("asof") else "") if t)
    meta = f'<div class="meta">{meta}</div>' if meta else ""
    gmail = f"{esc(_clean(data['gmail']))}｜" if data.get("gmail") else ""
    foot = (f'<footer class="small">{gmail}資料來源：Yahoo Finance、證交所開放資料、中央社、自由時報、Google 趨勢、PTT。'
            f'資料時間 {esc(data.get("timestamp", ""))}。報價可能延遲，內容僅供參考，不構成投資建議。</footer>')
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>早安日報</title>'
            f"<style>{CSS}</style></head><body><main>"
            f'<div class="bar"><b>早安日報</b><span>{now.month} 月 {now.day} 日　週{WEEKDAYS[now.weekday()]}</span></div>'
            f'<div class="hero"><h1>{esc(h1)}</h1><p class="lede">{esc(lede)}</p>{meta}{warn}</div>'
            f'{first_html}{nav}{"".join(parts)}{foot}</main><button class="totop" aria-label="回到頂端">↑</button>'
            f'<script>{JS}</script></body></html>')


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"已產生 {OUT}")
    if "--no-open" not in sys.argv:
        webbrowser.open(OUT.as_uri())
