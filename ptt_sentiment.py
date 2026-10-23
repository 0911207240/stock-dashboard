"""
PTT 股版輿情模組（輿情層）

流程：
  1. collect：抓股版近 N 小時的文章與推文（含每日盤中／盤後閒聊串），找出提到觀察清單個股的內容。
     原始文字只存在本機 ptt_raw.json（不進 git，股版發言不公開轉載），
     同時用規則法先標一版，寫進 ptt_sentiment.json（只有統計與標籤，沒有原文）。
  2. 標註：排程任務裡的 Claude 讀 ptt_raw.json，依 ptt_label_guide.md 把每檔標成
     「真實方向 × 強度 × 反串比例 × 類型」，存成 labels.json。
  3. apply：把 Claude 的標籤合併進 ptt_sentiment.json（來源標成 claude，覆蓋規則法）。
  4. 早盤掃描用 load_for_scan() 讀取，只寫進影子紀錄，不影響推播。

指令：
  python ptt_sentiment.py collect            # 抓取＋規則法標註
  python ptt_sentiment.py apply labels.json  # 合併 Claude 標籤
  python ptt_sentiment.py show               # 印出目前結果
"""
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(_DIR, "ptt_raw.json")          # 原文，不進 git
OUT_FILE = os.path.join(_DIR, "ptt_sentiment.json")    # 統計＋標籤，進 git
BASE = "https://www.ptt.cc"
BOARD = "Stock"
UA = {"User-Agent": "Mozilla/5.0 (stock-dashboard ptt_sentiment)"}
TIMEOUT = 15
TW = timezone(timedelta(hours=8))

MAX_SAMPLES = 40          # 每檔最多給 Claude 看幾則
MARKET_SAMPLES = 60       # 大盤情緒樣本數
SNIPPET_LEN = 90

DIRS = (-2, -1, 0, 1, 2)
KINDS = ("狂熱", "樂觀", "中性", "悲觀", "恐慌", "反串護航", "無共識")

# 鄉民對個股的常見暱稱（太短或容易誤判的不放，例如 GG 常指「完蛋」）
EXTRA_ALIASES = {
    "台積電": ["台G", "積積", "護國神山"],
    "鴻海": ["海公公"],
    "聯發科": ["發哥"],
    "台灣50": ["元大台灣50"],
    "長榮": ["長榮海"],
    "輝達": ["NVDA", "老黃家"],
    "超微半導體": ["AMD", "超微"],
    "美光": ["MU"],
    "華邦電": ["華邦"],
    "南亞科": ["南科"],
}

# 股名後面接這些字時不算（台灣大媽、台灣大學）
NOT_FOLLOWED = {"台灣大": "媽學道哥陸", "長榮": "航大", "華南": "部"}

# ── 規則法用的詞庫（只是保底；正式判讀交給 Claude） ──────────────
BULL = ["噴", "漲停", "歐印", "all in", "看多", "多單", "買爆", "加碼", "起飛", "上車", "賺爛", "續抱", "抄底", "反彈", "突破", "創新高", "大漲", "紅K"]
BEAR = ["崩", "跌停", "看空", "空單", "套牢", "停損", "砍", "逃", "下車", "賠爛", "畢業", "斷頭", "破底", "出貨", "大跌", "綠K", "韭菜", "住套房"]
SARCASM = ["丸子", "公園", "財富自由", "提早退休", "傳家寶", "穩了", "安啦", "不會跌", "必漲", "反指標", "反指", "反串", "倒貨", "樂觀惹", "樂觀了", "準備下地獄", "笑死", "XD", "哈哈"]
PANIC = ["救命", "完了", "怎麼辦", "睡不著", "要不要砍", "崩盤", "斷頭", "畢業", "下地獄", "恐慌", "QQ"]


# ═══════════════════════ 抓取 ═══════════════════════

def _get(url: str) -> str:
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, cookies={"over18": "1"}, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
        time.sleep(1 + i)
    return ""


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _index_posts(html: str) -> list[dict]:
    out = []
    for blk in re.findall(r'<div class="r-ent">(.*?)<div class="mark">', html, re.S):
        a = re.search(r'<a href="(/bbs/%s/M\.(\d+)\.A\.[0-9A-F]+\.html)">([^<]*)</a>' % BOARD, blk)
        if not a:
            continue
        nrec = _strip((re.search(r'<div class="nrec">(.*?)</div>', blk, re.S) or [None, ""])[1])
        out.append({"url": a.group(1), "ts": int(a.group(2)), "title": a.group(3).strip(), "nrec": nrec})
    return out


def _article(url: str) -> dict:
    html = _get(BASE + url)
    if not html:
        return {}
    body = re.search(r'<div id="main-content"[^>]*>(.*?)(?:<span class="f2">※ 發信站|<div class="push")', html, re.S)
    body_txt = _strip(body.group(1)) if body else ""
    body_txt = re.sub(r"^作者.*?時間 \S+ \S+ \S+ \S+ \d{4}", "", body_txt).strip()
    pushes = []
    for tag, txt, tm in re.findall(
            r'<div class="push">\s*<span class="[^"]*push-tag">([^<]*)</span>\s*<span class="[^"]*push-userid">[^<]*</span>\s*'
            r'<span class="[^"]*push-content">([^<]*)</span>\s*(?:<span class="push-ipdatetime">([^<]*)</span>)?', html):
        tag = tag.strip()
        pushes.append({"tag": "推" if tag == "推" else "噓" if tag == "噓" else "→",
                       "text": txt.lstrip(": ").strip(), "time": (tm or "").strip()})
    return {"body": body_txt[:3000], "pushes": pushes}


def _category(title: str) -> str:
    m = re.search(r"\[([^\]]+)\]", title)
    return m.group(1) if m else ""


def build_aliases(watchlist: dict) -> list[tuple[str, str]]:
    """回傳 (關鍵字, 股名) 清單，長的先比對，避免「台塑」吃掉「台塑化」。"""
    pairs = []
    for name, ticker in watchlist.items():
        pairs.append((name, name))
        code = ticker.split(".")[0]
        if re.fullmatch(r"\d{4,6}", code) and not (len(code) == 4 and 1990 <= int(code) <= 2035):
            pairs.append((code, name))           # 2023、2027 這類代號跟年份撞，只認股名
        elif re.fullmatch(r"[A-Z]{2,5}", code) and len(code) >= 3:
            pairs.append((code, name))
        for a in EXTRA_ALIASES.get(name, []):
            pairs.append((a, name))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def find_stocks(text: str, aliases: list[tuple[str, str]]) -> set[str]:
    found, t = set(), text
    for key, name in aliases:
        if key.isdigit():
            pat = r"(?<!\d)%s(?!\d)" % key
        elif key.isascii():
            pat = r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(key)
        else:
            pat = re.escape(key) + ("(?![%s])" % NOT_FOLLOWED[key] if key in NOT_FOLLOWED else "")
        if re.search(pat, t):
            found.add(name)
            t = re.sub(pat, " ", t)
    return found


def collect(hours: int = 30, max_pages: int = 20, watchlist: dict = None) -> dict:
    if watchlist is None:
        from data_fetcher import WATCHLIST as watchlist
    aliases = build_aliases(watchlist)
    cutoff = time.time() - hours * 3600
    url, posts, chats = f"/bbs/{BOARD}/index.html", [], []
    for _ in range(max_pages):
        html = _get(BASE + url)
        if not html:
            break
        page = _index_posts(html)
        for p in page:
            if "[公告]" in p["title"]:
                continue
            if "閒聊" in p["title"]:
                chats.append(p)          # 閒聊串常是前一天開的，靠推文時間判斷，不卡發文時間
            elif p["ts"] >= cutoff:
                posts.append(p)
        prev = re.search(r'href="(/bbs/%s/index\d+\.html)">[^<]*上頁' % BOARD, html)
        dated = [p for p in page if "[公告]" not in p["title"]]
        if not prev or (dated and max(p["ts"] for p in dated) < cutoff):
            break
        url = prev.group(1)
        time.sleep(0.5)

    chats = sorted({c["url"]: c for c in chats}.values(), key=lambda c: c["ts"], reverse=True)[:3]
    stocks: dict[str, dict] = {}
    market = {"push": 0, "boo": 0, "arrow": 0, "samples": []}

    def slot(name):
        return stocks.setdefault(name, {"ticker": watchlist.get(name, ""), "posts": 0, "post_nrec": 0,
                                        "push": 0, "boo": 0, "arrow": 0, "samples": []})

    def add_sample(s, kind, tag, text):
        if len(s["samples"]) < MAX_SAMPLES * 3:
            s["samples"].append({"kind": kind, "tag": tag, "text": text[:SNIPPET_LEN]})

    for p in posts:
        art = _article(p["url"])
        time.sleep(0.4)
        if not art:
            continue
        cat = _category(p["title"])
        in_title = find_stocks(p["title"], aliases)
        in_body = find_stocks(art["body"][:600], aliases)
        if len(in_body) > 5:
            in_body = set()                      # 買賣超排行這類清單文，內文提到的不算
        named = in_title | in_body
        nrec = 100 if p["nrec"] == "爆" else -int(p["nrec"][1:]) * 10 if p["nrec"].startswith("X") and p["nrec"][1:].isdigit() \
            else -100 if p["nrec"] == "XX" else int(p["nrec"]) if p["nrec"].isdigit() else 0
        for n in named:
            s = slot(n)
            s["posts"] += 1
            s["post_nrec"] += nrec
            add_sample(s, f"文章[{cat}]", "", p["title"])
        for pu in art["pushes"]:
            # 推文沒寫股名時，只有標題明確只講一檔才算在那檔頭上
            hit = find_stocks(pu["text"], aliases) | (in_title if len(in_title) == 1 else set())
            for n in hit:
                s = slot(n)
                s[{"推": "push", "噓": "boo", "→": "arrow"}[pu["tag"]]] += 1
                add_sample(s, f"推文[{cat}]", pu["tag"], pu["text"])

    for c in chats:
        art = _article(c["url"])
        time.sleep(0.4)
        if not art:
            continue
        recent = [pu for pu in art["pushes"] if _push_recent(pu["time"], cutoff)]
        for pu in recent:
            market[{"推": "push", "噓": "boo", "→": "arrow"}[pu["tag"]]] += 1
            for n in find_stocks(pu["text"], aliases):
                s = slot(n)
                s[{"推": "push", "噓": "boo", "→": "arrow"}[pu["tag"]]] += 1
                add_sample(s, "閒聊串", pu["tag"], pu["text"])
        step = max(1, len(recent) // MARKET_SAMPLES)
        market["samples"] += [{"tag": pu["tag"], "text": pu["text"][:SNIPPET_LEN]} for pu in recent[::step]]
    market["samples"] = market["samples"][-MARKET_SAMPLES:]

    for s in stocks.values():
        s["mentions"] = s["posts"] + s["push"] + s["boo"] + s["arrow"]
        s["samples"] = _pick_samples(s["samples"])

    raw = {
        "collected_at": datetime.now(TW).strftime("%Y-%m-%d %H:%M"),
        "window_hours": hours,
        "n_posts": len(posts), "n_chat_threads": len(chats),
        "market": market,
        "stocks": dict(sorted(stocks.items(), key=lambda kv: kv[1]["mentions"], reverse=True)),
    }
    with open(RAW_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=1)
    return raw


def _push_recent(tm: str, cutoff: float) -> bool:
    """推文時間只有 MM/DD HH:MM，補上年份後比對。無時間的一律算進來。"""
    m = re.search(r"(\d{2})/(\d{2}) (\d{2}):(\d{2})", tm or "")
    if not m:
        return True
    now = datetime.now(TW)
    try:
        dt = datetime(now.year, int(m[1]), int(m[2]), int(m[3]), int(m[4]), tzinfo=TW)
        if dt > now + timedelta(days=1):
            dt = dt.replace(year=now.year - 1)
        return dt.timestamp() >= cutoff
    except ValueError:
        return True


def _pick_samples(samples: list) -> list:
    """噓文、推文、文章標題都留一些，避免只看到單一立場。"""
    if len(samples) <= MAX_SAMPLES:
        return samples
    groups = {"噓": [], "推": [], "→": [], "": []}
    for x in samples:
        groups.get(x["tag"], groups["→"]).append(x)
    out, i = [], 0
    while len(out) < MAX_SAMPLES and any(groups.values()):
        for k in ("", "噓", "推", "→"):
            if groups[k] and len(out) < MAX_SAMPLES:
                out.append(groups[k].pop(len(groups[k]) // 2 if i % 2 else -1))
        i += 1
    return out


# ═══════════════════════ 規則法標註（保底） ═══════════════════════

def _hits(text: str, words: list) -> int:
    return sum(1 for w in words if w in text)


def rule_label(s: dict) -> dict:
    """
    保底判讀：推噓比＋詞庫。看得出方向，但分不太出反串，所以 sarcasm 只是粗估。
    樂觀詞跟反串詞出現在同一句、或出現在噓文裡，視為反串，方向反轉。
    """
    bull = bear = sarc = panic = 0
    for x in s.get("samples", []):
        t = x["text"]
        b, r, sc = _hits(t, BULL), _hits(t, BEAR), _hits(t, SARCASM)
        is_sarc = sc > 0 and (b > 0 or x["tag"] == "噓")
        if is_sarc:
            sarc += 1
            b, r = r, b                          # 反串：字面多 → 實際空，反之亦然
        bull += b
        bear += r
        panic += _hits(t, PANIC) if not is_sarc else 0
    n = max(1, len(s.get("samples", [])))
    tot_votes = s.get("push", 0) + s.get("boo", 0)
    boo_ratio = s.get("boo", 0) / tot_votes if tot_votes else 0
    net = (bull - bear) / max(1, bull + bear)
    net -= (boo_ratio - 0.2)                     # 噓多於兩成往空方修正
    d = 2 if net > 0.6 else 1 if net > 0.2 else -2 if net < -0.6 else -1 if net < -0.2 else 0
    mentions = s.get("mentions", 0)
    strength = 3 if mentions >= 80 else 2 if mentions >= 30 else 1 if mentions >= 8 else 0
    sarc_share = round(sarc / n, 2)
    if mentions < 5:
        kind = "無共識"
    elif sarc_share >= 0.4 and d >= 0:
        kind = "反串護航"
    elif d <= -1 and panic / n >= 0.15:
        kind = "恐慌"
    elif d == 2 and strength >= 2:
        kind = "狂熱"
    else:
        kind = {2: "樂觀", 1: "樂觀", 0: "中性", -1: "悲觀", -2: "悲觀"}[d]
    return {"dir": d, "strength": strength, "sarcasm": sarc_share, "kind": kind, "note": "", "src": "rule"}


# ═══════════════════════ 輸出與合併 ═══════════════════════

def _stats(s: dict) -> dict:
    votes = s.get("push", 0) + s.get("boo", 0)
    return {"ticker": s.get("ticker", ""), "mentions": s.get("mentions", 0), "posts": s.get("posts", 0),
            "push": s.get("push", 0), "boo": s.get("boo", 0),
            "boo_ratio": round(s["boo"] / votes, 2) if votes else None}


def build_output(raw: dict, labels: dict = None, market_label: dict = None) -> dict:
    labels = labels or {}
    stocks = {}
    for name, s in raw["stocks"].items():
        if s.get("mentions", 0) < 3:
            continue
        lab = labels.get(name) or rule_label(s)
        stocks[name] = {**_stats(s), **lab}
    m = raw["market"]
    mvotes = m["push"] + m["boo"]
    out = {
        "date": raw["collected_at"][:10],
        "collected_at": raw["collected_at"],
        "window_hours": raw["window_hours"],
        "n_posts": raw["n_posts"],
        "market": {"push": m["push"], "boo": m["boo"],
                   "boo_ratio": round(m["boo"] / mvotes, 2) if mvotes else None,
                   **(market_label or rule_label({**m, "mentions": mvotes}))},
        "stocks": stocks,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def _valid(lab: dict) -> dict | None:
    try:
        d, st, sc = int(lab["dir"]), int(lab["strength"]), float(lab["sarcasm"])
        kind = lab["kind"]
        if d not in DIRS or st not in (0, 1, 2, 3) or not 0 <= sc <= 1 or kind not in KINDS:
            return None
        return {"dir": d, "strength": st, "sarcasm": round(sc, 2), "kind": kind,
                "note": str(lab.get("note", ""))[:60], "src": "claude"}
    except Exception:
        return None


def apply_labels(path: str) -> dict:
    """合併 Claude 標籤：{"market": {...}, "stocks": {股名: {...}}}。格式錯的那檔退回規則法。"""
    with open(RAW_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    with open(path, encoding="utf-8") as f:
        given = json.load(f)
    labels, bad = {}, []
    for name, lab in (given.get("stocks") or {}).items():
        v = _valid(lab)
        if v and name in raw["stocks"]:
            labels[name] = v
        else:
            bad.append(name)
    mk = _valid(given.get("market") or {})
    out = build_output(raw, labels, mk)
    print(f"已合併 Claude 標籤 {len(labels)} 檔；格式不符退回規則法：{bad or '無'}")
    return out


# ═══════════════════════ 給掃描用 ═══════════════════════

def load_for_scan(max_age_days: int = 4) -> dict:
    """回傳 {股名: 標籤}；檔案太舊（超過 max_age_days，涵蓋週末）回傳空。"""
    try:
        with open(OUT_FILE, encoding="utf-8") as f:
            d = json.load(f)
        age = (datetime.now(TW).date() - datetime.strptime(d["date"], "%Y-%m-%d").date()).days
        if age > max_age_days:
            return {}
        return {"_market": d.get("market", {}), **d.get("stocks", {})}
    except Exception:
        return {}


def contrarian_watch(ptt: dict, inst_by_code: dict) -> list[dict]:
    """
    反向觀察名單：股版真心悲觀／恐慌（反串比例低），但法人當天買超。
    只是觀察來源，不是買進訊號；一律記錄，等影子紀錄驗證。
    """
    out = []
    for name, p in ptt.items():
        if name.startswith("_") or p.get("kind") not in ("恐慌", "悲觀") or (p.get("sarcasm") or 0) >= 0.3:
            continue
        code = (p.get("ticker") or "").split(".")[0]
        inst = inst_by_code.get(code) or {}
        if (inst.get("total_net") or 0) > 0:
            out.append({"name": name, "kind": p["kind"], "mentions": p.get("mentions"),
                        "inst_net": inst.get("total_net"), "note": p.get("note", "")})
    return sorted(out, key=lambda x: x["inst_net"], reverse=True)


def summary(d: dict = None, top: int = 10) -> str:
    if d is None:
        with open(OUT_FILE, encoding="utf-8") as f:
            d = json.load(f)
    m = d["market"]
    lines = [f"PTT 股版輿情 {d['collected_at']}（近 {d['window_hours']} 小時，{d['n_posts']} 篇文）",
             f"大盤：{m['kind']}（方向 {m['dir']:+d}，噓比 {m.get('boo_ratio')}，反串 {m['sarcasm']:.0%}，{m['src']}）"]
    for name, s in list(d["stocks"].items())[:top]:
        lines.append(f"  {name}：{s['kind']} 方向{s['dir']:+d} 強度{s['strength']} 反串{s['sarcasm']:.0%}"
                     f"｜提及{s['mentions']} 噓比{s['boo_ratio']}｜{s['src']}" + (f"｜{s['note']}" if s.get("note") else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "collect"
    if cmd == "collect":
        raw = collect()
        out = build_output(raw)
        print(f"抓到 {raw['n_posts']} 篇文、{raw['n_chat_threads']} 個閒聊串，{len(out['stocks'])} 檔有討論")
        print(summary(out))
    elif cmd == "apply":
        print(summary(apply_labels(sys.argv[2])))
    elif cmd == "show":
        print(summary())
    else:
        print(__doc__)
