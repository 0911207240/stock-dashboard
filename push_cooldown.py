"""推播冷卻機制 — 防止同一股票重複推播造成通知疲乏"""
import json
import os
from datetime import datetime, timedelta

_DIR = os.path.dirname(__file__)
COOLDOWN_FILE = os.path.join(_DIR, "push_cooldown.json")
COOLDOWN_HOURS    = 48   # 預設冷卻時間
SCORE_SURGE_DELTA = 10   # 分數飆升超過此值可破冷卻


def _load() -> dict:
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save(data: dict):
    with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_cooled_down(name: str, new_score: int = 0) -> bool:
    """
    True  → 仍在冷卻期，應跳過推播
    False → 可以推播（冷卻期已過 或 分數大幅飆升）
    """
    data = _load()
    if name not in data:
        return False
    last = data[name]
    try:
        last_time  = datetime.fromisoformat(last["time"])
        last_score = int(last.get("score", 0))
    except Exception:
        return False

    if datetime.now() - last_time >= timedelta(hours=COOLDOWN_HOURS):
        return False                                # 冷卻期已過
    if new_score - last_score >= SCORE_SURGE_DELTA:
        return False                                # 分數大幅提升，破冷卻
    return True


def mark_pushed(name: str, score: int):
    """記錄推播時間與分數"""
    data = _load()
    data[name] = {"time": datetime.now().isoformat(), "score": int(score)}
    _save(data)


def clear_cooldown(name: str = None):
    """清除指定或全部冷卻記錄"""
    if name is None:
        if os.path.exists(COOLDOWN_FILE):
            os.remove(COOLDOWN_FILE)
    else:
        data = _load()
        data.pop(name, None)
        _save(data)


def get_status() -> list[dict]:
    """回傳目前所有冷卻狀態（供 UI 顯示）"""
    data = _load()
    rows = []
    now = datetime.now()
    for name, info in data.items():
        try:
            last_time  = datetime.fromisoformat(info["time"])
            last_score = info.get("score", "-")
            remaining  = COOLDOWN_HOURS - (now - last_time).total_seconds() / 3600
            rows.append({
                "名稱":       name,
                "上次推播":   last_time.strftime("%m/%d %H:%M"),
                "分數":       last_score,
                "剩餘冷卻h":  round(max(0, remaining), 1),
            })
        except Exception:
            pass
    rows.sort(key=lambda x: x["剩餘冷卻h"], reverse=True)
    return rows
