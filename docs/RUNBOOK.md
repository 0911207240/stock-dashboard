# 股票儀表板 營運手冊

## 排程一覽（台灣時間；GitHub 排程常延遲 1–4 小時）
| Workflow | 排程 | 作用 | 失敗時 |
|---|---|---|---|
| US Stock Scan | 週二–六 05:30 | 美股掃描 | LINE 通知 |
| Morning Briefing | 週一–五 07:30 | 早安日報 | LINE 通知 |
| Daily Stock Scan | 週一–五 06:30 | 台股掃描與推播 | LINE 通知，30 分鐘逾時 |
| Health Check | 週一–五 10:30 | 檢查上述三者，必要時補跑 Daily Scan，異常才推 LINE | 見 ops_log.json |

## 健康檢查判斷
- 今日該跑的排程沒有成功：失敗、未執行、仍在執行中，都列為異常。
- 掃描結果日期不是今天，或價格資料完整度 < 80%（`scan_results.json` 的 `coverage`）。
- Daily Scan 今日失敗/未執行且尚未補跑 → 自動補跑一次（每天最多一次）。
- 每次執行都寫入 `ops_log.json`（保留 90 天），可看歷史趨勢。

## 常見問題
- **Daily Scan 卡住/逾時**：先看 log 中 faulthandler 每 10 分鐘的堆疊；歷史原因是 Yahoo 限流導致 yfinance 無回應。
- **價格快取**：`tw-price-cache-*`（台股）、`us-price-cache-*`（美股），失敗也會保存，隔天增量補資料。
- **狀態檔推送失敗**：Actions 會顯示 `::warning::`，檢查 push_cooldown.json 等是否遺失。
- **套件升級**：yfinance 鎖定 1.7.0，升級需手動改 requirements.txt 並先手動跑一次驗證。

## 需要的 Secrets
LINE_TOKEN、LINE_USER_ID、GMAIL_ADDRESS、GMAIL_APP_PASSWORD、GMAIL_TO
