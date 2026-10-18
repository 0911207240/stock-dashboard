"""每月重查八檔 ETF 的配息來源占比，和 etf_facts.py 比對，變動大的寫進 etf_check.json

來源：ETF 資訊網各檔配息紀錄頁（整理自投信公告）。算法與 etf_facts 相同：
非股利占比＝1 − 54C 股利所得 − 5A 利息所得，以近 12 個月每期配息金額加權（上限估計）。
只比對、不改 etf_facts.py（它的數字會餵進配置與槓桿模擬，要人確認後再更新）。
用法：python etf_check.py        距上次查證滿 25 天才跑；--force 強制重查
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from etf_facts import LATEST_DIV_SHARE, NONDIV

OUT = Path(__file__).parent / "etf_check.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
MIN_DAYS = 25
NONDIV_DRIFT = 0.05   # 非股利占比和 etf_facts 差 5 個百分點以上才標示
LATEST_DRIFT = 0.10   # 最近一期股利占比差 10 個百分點以上才標示

ROW = re.compile(r"\|(\d{4})\|([\d.]+) 元\|(\d{4}/\d{2}/\d{2})\|[^|]*\|[^|]*\|([^|]*)\|")  # 最後買進日舊資料為「—」


def _page(code: str) -> str:
    html = requests.get(f"https://www.etfinfo.tw/etf/{code}/dividend", headers=UA, timeout=20).text
    html = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    txt = re.sub(r"<[^>]+>", "|", html)
    return re.sub(r"\|\s*(\|\s*)+", "|", txt)


def parse_rows(txt: str) -> list[dict]:
    rows = []
    for _, amt, ex, comp in ROW.findall(txt):
        m54, m5a = re.search(r"54C ([\d.]+)%", comp), re.search(r"5A ([\d.]+)%", comp)
        rows.append({"ex": ex, "amt": float(amt),
                     "div": float(m54.group(1)) / 100 if m54 else None,
                     "int": float(m5a.group(1)) / 100 if m5a else 0.0})
    rows.sort(key=lambda r: r["ex"], reverse=True)
    return rows


def summarize(rows: list[dict], today: datetime) -> dict | None:
    cut = (today - timedelta(days=365)).strftime("%Y/%m/%d")
    yr = [r for r in rows if r["ex"] >= cut and r["div"] is not None]
    if not yr:
        return None
    tot = sum(r["amt"] for r in yr)
    nondiv = sum(r["amt"] * (1 - r["div"] - r["int"]) for r in yr) / tot
    last = next((r for r in rows if r["div"] is not None), None)
    return {"nondiv": round(nondiv, 3), "periods": len(yr),
            "latest_div": last["div"], "latest_ex": last["ex"]}


def run(force: bool = False) -> dict:
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        if not force and time.time() - prev.get("ts", 0) < MIN_DAYS * 86400:
            return prev
    except Exception:
        prev = {}
    today, res, flags = datetime.now(), {}, []
    for code in NONDIV:
        try:
            s = summarize(parse_rows(_page(code)), today)
        except Exception as e:
            print(f"[配息查證] {code} 失敗：{e}")
            s = None
        if not s:
            res[code] = {"error": True}
            continue
        s["old_nondiv"], s["old_latest_div"] = NONDIV[code], LATEST_DIV_SHARE.get(code)
        res[code] = s
        if abs(s["nondiv"] - NONDIV[code]) >= NONDIV_DRIFT:
            flags.append(f"{code} 非股利占比 {NONDIV[code]*100:.0f}% → {s['nondiv']*100:.0f}%")
        old = LATEST_DIV_SHARE.get(code)
        if old is not None and abs(s["latest_div"] - old) >= LATEST_DRIFT:
            flags.append(f"{code} 最近一期股利占比 {old*100:.0f}% → {s['latest_div']*100:.0f}%（{s['latest_ex']} 除息）")
    data = {"ts": time.time(), "asof": today.strftime("%Y/%m/%d"), "baseline": "2026/10/17",
            "flags": flags, "etfs": res}
    if any("error" not in v for v in res.values()):  # 全部失敗就不覆蓋舊結果
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


if __name__ == "__main__":
    d = run(force="--force" in sys.argv)
    print(f"查證日 {d['asof']}（基準 {d['baseline']}）")
    for c, v in d["etfs"].items():
        if "error" in v:
            print(f"{c}  查不到")
        else:
            print(f"{c}  非股利 {v['old_nondiv']*100:.0f}% → {v['nondiv']*100:.0f}%（{v['periods']}期）｜最近一期股利 "
                  f"{(v['old_latest_div'] or 0)*100:.0f}% → {v['latest_div']*100:.1f}%（{v['latest_ex']}）")
    print("變動標示：", d["flags"] or "無")
