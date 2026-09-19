"""每日健康檢查（營運監督）

由 .github/workflows/health_check.yml 在台灣時間上午執行：
1. 檢查三個排程（Daily Scan / US Scan / Morning Briefing）今日是否成功
2. 檢查掃描結果是否為最新、資料完整度是否足夠
3. Daily Scan 今日失敗或沒跑，且今天尚未補跑過 → 自動補跑一次
4. 有異常才推播 LINE（一則彙整）；每次都寫入 ops_log.json 累積紀錄
"""
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "0911207240/stock-dashboard")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
LINE_TOKEN = os.environ.get("LINE_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
TZ = timezone(timedelta(hours=8))
MIN_COVERAGE = 0.8          # 價格資料完整度低於此比例視為異常
OPS_LOG = Path("ops_log.json")
OPS_LOG_KEEP = 90

WORKFLOWS = {
    "daily_scan.yml": "台股每日掃描",
    "us_scan.yml": "美股掃描",
    "morning_briefing.yml": "早安日報",
}


def _gh(path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def _to_local(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)


def _runs_today(workflow: str, today: date) -> list[dict]:
    try:
        runs = _gh(f"actions/workflows/{workflow}/runs?per_page=10").get("workflow_runs", [])
    except Exception as e:
        print(f"[health] 無法取得 {workflow} 執行紀錄: {e}")
        return []
    return [r for r in runs if _to_local(r["created_at"]).date() == today]


def _expects_run_today(workflow: str, today: date) -> bool:
    """該排程今天是否預期要跑（交易日才跑的排程）。"""
    from tw_calendar import is_trading_day
    if workflow == "us_scan.yml":
        # 美股掃描在台灣時間清晨跑，反映前一個美股交易日（週二到週六早上）
        return today.weekday() in (1, 2, 3, 4, 5)
    return is_trading_day(today)


def check(today: date) -> tuple[list[str], dict]:
    issues: list[str] = []
    summary: dict = {}

    for wf, label in WORKFLOWS.items():
        if not _expects_run_today(wf, today):
            summary[wf] = "非預期執行日"
            continue
        runs = _runs_today(wf, today)
        done = [r for r in runs if r["status"] == "completed"]
        ok = [r for r in done if r["conclusion"] == "success"]
        running = [r for r in runs if r["status"] != "completed"]
        if ok:
            summary[wf] = "成功"
        elif running:
            summary[wf] = "執行中"
            issues.append(f"{label}：仍在執行中（可能延遲或卡住）")
        elif done:
            summary[wf] = "失敗"
            issues.append(f"{label}：今日執行失敗（{done[0]['html_url']}）")
        else:
            summary[wf] = "未執行"
            issues.append(f"{label}：今日尚未執行（GitHub 排程可能延遲）")

    # 掃描結果新鮮度與資料完整度
    try:
        from tw_calendar import is_trading_day
        if is_trading_day(today) and summary.get("daily_scan.yml") == "成功":
            sr = json.loads(Path("scan_results.json").read_text(encoding="utf-8"))
            if sr.get("date") != today.isoformat():
                issues.append(f"掃描結果日期為 {sr.get('date')}，不是今天（資料可能未更新）")
            cov = sr.get("coverage") or {}
            if cov.get("total"):
                ratio = cov["fetched"] / cov["total"]
                summary["coverage"] = f"{cov['fetched']}/{cov['total']}"
                if ratio < MIN_COVERAGE:
                    issues.append(f"價格資料不完整：只抓到 {cov['fetched']}/{cov['total']} 檔")
    except Exception as e:
        print(f"[health] 讀取掃描結果失敗: {e}")

    return issues, summary


def rerun_daily_scan_if_needed(today: date, summary: dict) -> str | None:
    """Daily Scan 今日失敗或未執行、且今天尚未補跑過 → 觸發一次補跑。"""
    from tw_calendar import is_trading_day
    if not is_trading_day(today) or summary.get("daily_scan.yml") not in ("失敗", "未執行"):
        return None
    runs = _runs_today("daily_scan.yml", today)
    if any(r["event"] == "workflow_dispatch" for r in runs):
        return "今日已補跑過一次，不再重複觸發"
    try:
        _gh("actions/workflows/daily_scan.yml/dispatches", "POST", {"ref": "main"})
        return "已自動補跑台股每日掃描一次"
    except Exception as e:
        return f"自動補跑失敗：{e}"


def notify(text: str):
    if not (LINE_TOKEN and LINE_USER_ID):
        print("[health] 未設定 LINE_TOKEN/LINE_USER_ID，略過推播")
        return
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=json.dumps({"to": LINE_USER_ID, "messages": [{"type": "text", "text": text}]}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        print(f"[health] LINE 推播失敗: {e}")


def write_ops_log(today: date, issues: list[str], summary: dict, action: str | None):
    try:
        log = json.loads(OPS_LOG.read_text(encoding="utf-8")) if OPS_LOG.exists() else []
    except Exception:
        log = []
    log = [e for e in log if e.get("date") != today.isoformat()]
    log.append({"date": today.isoformat(), "summary": summary, "issues": issues, "action": action})
    OPS_LOG.write_text(json.dumps(log[-OPS_LOG_KEEP:], ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    today = datetime.now(TZ).date()
    issues, summary = check(today)
    action = rerun_daily_scan_if_needed(today, summary) if issues else None
    write_ops_log(today, issues, summary, action)

    print(json.dumps({"date": today.isoformat(), "summary": summary, "issues": issues, "action": action},
                     ensure_ascii=False, indent=2))
    if issues:
        lines = [f"⚠️ 系統健康檢查 {today.strftime('%m/%d')}"] + [f"• {i}" for i in issues]
        if action:
            lines.append(f"→ {action}")
        lines.append(f"https://github.com/{REPO}/actions")
        notify("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
