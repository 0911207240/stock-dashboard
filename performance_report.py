"""
績效部週報：讀 shadow_ledger.json，檢驗「分數與各項子分數到底有沒有預測力」。
全部是毛報酬（未扣手續費與稅）。樣本小於 MIN_N 的格子只標示筆數，不下結論。
"""
import json
import os
from datetime import datetime

import pandas as pd

LEDGER_FILE = os.path.join(os.path.dirname(__file__), "shadow_ledger.json")
REPORT_FILE = os.path.join(os.path.dirname(__file__), "performance_report.md")
MIN_N = 30
BANDS = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 101)]
FACTORS = [("vol", "量能"), ("chip", "籌碼"), ("tech", "技術"), ("atr_s", "波動度"),
           ("beta", "Beta"), ("rs5", "5日相對強弱"), ("rs20", "20日相對強弱"), ("mdd20", "20日回撤")]


def _load_df() -> pd.DataFrame:
    if not os.path.exists(LEDGER_FILE):
        return pd.DataFrame()
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for h in (1, 3, 5):
        df[f"r{h}"] = df["ret"].apply(lambda d, k=str(h): d.get(k) if isinstance(d, dict) else None)
    if "bear" not in df:
        df["bear"] = None
    df["bear_n"] = df["bear"].apply(lambda b: len(b) if isinstance(b, list) else None)
    return df


def _fmt(v, sign=True):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.2f}%" if sign else f"{v:.2f}%"


def _row(g: pd.DataFrame) -> str:
    n = len(g)
    if n < MIN_N:
        return f"{n} 筆（樣本不足）"
    sim = g[g["sim"].isin(["停損", "停利①", "停利②", "未觸發"])]["sim_ret"].dropna()
    win = f"{(sim > 0).mean() * 100:.0f}%" if len(sim) else "—"
    return (f"{n} 筆｜成交 {len(sim)}｜當沖勝率 {win}｜當沖均 {_fmt(sim.mean() if len(sim) else None)}"
            f"｜T+1 {_fmt(g['r1'].mean())}｜T+3 {_fmt(g['r3'].mean())}｜T+5 {_fmt(g['r5'].mean())}")


def _spearman(x: pd.Series, y: pd.Series):
    d = pd.concat([x, y], axis=1).dropna()
    if len(d) < MIN_N or d.iloc[:, 0].nunique() < 3:
        return None
    return d.iloc[:, 0].rank().corr(d.iloc[:, 1].rank())


def _desk_sections(df: pd.DataFrame, s: pd.DataFrame) -> list:
    out = []

    # 反方分析師：異議越多是否報酬越差
    out += ["", "【反方分析師】（異議越多，報酬是不是越差？）"]
    b = s[s["bear_n"].notna()]
    if b.empty:
        out.append("  尚無標註資料")
    else:
        for label, g in (("0 項異議", b[b["bear_n"] == 0]), ("1 項異議", b[b["bear_n"] == 1]),
                         ("2 項以上", b[b["bear_n"] >= 2])):
            out.append(f"  {label}：{_row(g)}")
        from collections import Counter
        from devils_advocate import OBJECTIONS
        cnt = Counter(code for lst in b["bear"] if isinstance(lst, list) for code in lst)
        if cnt:
            out.append("  最常見異議：" + "、".join(f"{OBJECTIONS.get(k, k)}×{v}" for k, v in cnt.most_common(3)))

    # 風控長：規則重播
    out += ["", "【風控長】（影子模式，未阻擋任何推播）"]
    try:
        import risk_officer as R
        hist = R.load_history()
        bt = R.backtest_rules(hist)
        names = {"normal": "正常", "caution": "降倉", "halt": "停手"}
        for k in ("normal", "caution", "halt"):
            v = bt[k]
            out.append(f"  {names[k]}日：{v['n']} 筆" + (f"｜平均 {_fmt(v['avg'])}" if v["avg"] is not None else ""))
        d = bt["delta_if_applied"]
        verdict = "規則有幫助" if d > 0 else "規則反而少賺，暫不啟用"
        out.append(f"  若套用（停手日不進場、降倉日半倉）：總報酬 {d:+.1f} 個百分點 → {verdict}")
    except Exception as e:
        out.append(f"  重播失敗：{e}")

    # 事後檢討官
    out += ["", "【事後檢討官】（近7日停損單分類）"]
    try:
        import post_mortem as PM
        from risk_officer import load_history as _lh
        r = PM.classify(df, _lh())
        if not r.get("n"):
            out.append("  近7日無停損單")
        else:
            out.append(f"  共 {r['n']} 筆停損")
            for k, v in r["cats"].items():
                out.append(f"  {k}：{len(v)} 筆（{'；'.join(v[:2])}{'…' if len(v) > 2 else ''}）")
            out.append("  最差三筆：" + "、".join(r["worst"]))
    except Exception as e:
        out.append(f"  分類失敗：{e}")
    return out


def build_report() -> str:
    df = _load_df()
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🏢 績效部週報（{today}）"]
    if df.empty:
        lines += ["", "影子紀錄尚無資料，等累積後再產出。"]
        return "\n".join(lines)

    days = df["date"].nunique()
    settled = df[df["sim"].notna()]
    lines += [
        "",
        f"【資料量】{len(df)} 筆候選／{days} 個交易日／已回填 T+1 {len(settled)} 筆、T+5 {int(df['r5'].notna().sum())} 筆",
        f"報酬皆為毛報酬；每格樣本 < {MIN_N} 筆只列筆數不下結論",
    ]

    lines += ["", "【分數區間 vs 報酬】（判斷分數有沒有區分力）"]
    for lo, hi in BANDS:
        g = df[(df["score"] >= lo) & (df["score"] < hi) & df["sim"].notna()]
        lines.append(f"  {lo}-{min(hi, 100)}分：{_row(g)}")

    lines += ["", "【推播 vs 沒推播】（挑選有沒有加分）"]
    s = df[df["sim"].notna()]
    for label, g in (("已推播", s[s["pushed"]]),
                     ("排名 1-10 未推播", s[(~s["pushed"]) & (s["rank"] <= 10)]),
                     ("排名 11-60", s[s["rank"] > 10])):
        lines.append(f"  {label}：{_row(g)}")

    lines += ["", "【子分數預測力】（與 T+3 報酬的等級相關，+ 越高代表越有用；高低三分位 T+3 差）"]
    d3 = df[df["r3"].notna()]
    if len(d3) < MIN_N:
        lines.append(f"  T+3 已回填 {len(d3)} 筆，尚不足 {MIN_N} 筆")
    else:
        for col, label in FACTORS:
            if col not in d3 or d3[col].notna().sum() < MIN_N:
                continue
            c = _spearman(d3[col], d3["r3"])
            spread = None
            try:
                q = pd.qcut(d3[col].rank(method="first"), 3, labels=["低", "中", "高"])
                spread = d3.groupby(q, observed=True)["r3"].mean()
                spread = spread.get("高") - spread.get("低")
            except Exception:
                pass
            cs = f"{c:+.2f}" if c is not None else "—"
            lines.append(f"  {label}：相關 {cs}｜高-低 {_fmt(spread)}")

    if s["regime"].notna().any():
        lines += ["", "【大盤狀態分組】"]
        for reg, g in s.groupby("regime"):
            lines.append(f"  {reg}：{_row(g)}")

    lines += _desk_sections(df, s)

    lines += ["", "解讀提醒：相關在 ±0.05 內視為沒有預測力；資料天數少於 20 個交易日時，任何差異都可能只是運氣。"]
    return "\n".join(lines)


def write_report() -> str:
    text = build_report()
    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
    return text


if __name__ == "__main__":
    print(write_report())
