"""每週行銷靈感：呼叫本機 Claude Code（無人模式）搜尋台灣近期案例，寫入 marketing_weekly.md

只在檔案超過 6 天沒更新時才產生，所以每天跑 morning_open.bat 也不會重複消耗用量。
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).parent / "marketing_weekly.md"
STALE_DAYS = 6

PROMPT = """你是台灣市場的行銷觀察員。請用 WebSearch 找出「近 30 天內台灣市場真的出現過」的 3 則行銷案例或手法，
類型不限（內容、廣告、文案、短影片、活動企劃、社群玩法皆可），不綁定特定品牌，挑讓任何品牌都借得走的手法。

每則固定四行，格式如下，不要加其他說明、前言或結語：
### 1. 手法名稱
- 是什麼：
- 為什麼有效：（說明機制）
- 可以怎麼借用：
- 來源：（網址；若是你的判斷，不附網址並標「推測」）

規則：
- 只寫搜尋到的事實，沒有來源的內容必須標「推測」，不得杜撰案例、數字或品牌名稱。
- 繁體中文。不用驚嘆號，不用「強化」「提升」兩個詞。
"""


def main():
    if OUT.exists():
        age = (datetime.now() - datetime.fromtimestamp(OUT.stat().st_mtime)).days
        if age < STALE_DAYS and "--force" not in sys.argv:
            print(f"行銷靈感 {age} 天前才更新，跳過")
            return
    r = subprocess.run(
        ["claude", "-p", PROMPT, "--allowedTools", "WebSearch", "WebFetch", "--output-format", "text"],
        capture_output=True, text=True, encoding="utf-8", timeout=600, cwd=str(OUT.parent),
    )
    text = r.stdout.strip()
    if r.returncode != 0 or "### 1." not in text:
        print(f"行銷靈感產生失敗（exit {r.returncode}）：{(r.stderr or text)[:300]}")
        return
    OUT.write_text(f"（產生於 {datetime.now():%Y-%m-%d %H:%M}，由 Claude 搜尋整理）\n\n{text}\n", encoding="utf-8")
    print(f"已寫入 {OUT}")


if __name__ == "__main__":
    main()
