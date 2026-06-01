"""評分維度權重倍率設定 — 可依回測相關係數動態調整"""
import json
import os

_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(_DIR, "scoring_weights.json")

DEFAULTS: dict[str, float] = {
    "量能":   1.0,
    "籌碼":   1.0,
    "技術":   1.0,
    "波動度": 1.0,
}


def load_multipliers() -> dict[str, float]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            return {k: float(saved.get(k, v)) for k, v in DEFAULTS.items()}
        except Exception:
            pass
    return DEFAULTS.copy()


def save_multipliers(multipliers: dict[str, float]):
    data = {k: round(float(multipliers.get(k, DEFAULTS[k])), 2) for k in DEFAULTS}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def reset_multipliers() -> dict[str, float]:
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
    return DEFAULTS.copy()
