"""Google Sheets 雙向同步 — 持股清單 ↔ Google Sheets

環境變數需求（設定在 Streamlit Secrets 或 .env）：
  GOOGLE_SERVICE_ACCOUNT_JSON  — Service Account JSON 金鑰（整個 JSON 字串）
  SHEETS_PORTFOLIO_ID          — 試算表 ID（URL 中 /d/XXXX/ 的部分）

Sheets 結構（自動建立）：
  工作表 "持股清單"：ticker | 名稱 | 股數 | 成本 | 停損 | 停利 | 更新時間
  工作表 "自選股"  ：名稱  | ticker
"""
import os, json
from datetime import datetime

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_PORTFOLIO_SHEET = "持股清單"
_WATCHLIST_SHEET = "自選股"


def _get_creds():
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json:
        try:
            import streamlit as st
            sa_json = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        except Exception:
            pass
    if not sa_json:
        raise ValueError("未設定 GOOGLE_SERVICE_ACCOUNT_JSON")

    from google.oauth2.service_account import Credentials
    info = json.loads(sa_json)
    return Credentials.from_service_account_info(info, scopes=_SCOPES)


def _get_service():
    from googleapiclient.discovery import build
    creds = _get_creds()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _get_sheet_id() -> str:
    sid = os.environ.get("SHEETS_PORTFOLIO_ID", "")
    if not sid:
        try:
            import streamlit as st
            sid = st.secrets.get("SHEETS_PORTFOLIO_ID", "")
        except Exception:
            pass
    if not sid:
        raise ValueError("未設定 SHEETS_PORTFOLIO_ID")
    return sid


def _ensure_sheets(service, spreadsheet_id: str):
    """確保必要工作表存在，不存在則建立"""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    needed = [_PORTFOLIO_SHEET, _WATCHLIST_SHEET]
    requests = []
    for title in needed:
        if title not in existing:
            requests.append({"addSheet": {"properties": {"title": title}}})
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests}
        ).execute()


# ── 持股清單 ──────────────────────────────────────────────────────────────────

_PORTFOLIO_HEADERS = ["ticker", "名稱", "股數", "成本", "停損", "停利", "更新時間"]


def push_portfolio(holdings: dict) -> bool:
    """把持股清單推送到 Google Sheets，覆蓋現有資料"""
    try:
        service = _get_service()
        sid = _get_sheet_id()
        _ensure_sheets(service, sid)

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows = [_PORTFOLIO_HEADERS]
        for ticker, info in holdings.items():
            rows.append([
                ticker,
                info.get("name", ""),
                info.get("shares", 0),
                info.get("cost", "") or "",
                info.get("stop_loss", "") or "",
                info.get("take_profit", "") or "",
                now,
            ])

        range_name = f"{_PORTFOLIO_SHEET}!A1"
        service.spreadsheets().values().clear(
            spreadsheetId=sid,
            range=f"{_PORTFOLIO_SHEET}!A:G"
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": rows}
        ).execute()
        return True
    except Exception as e:
        print(f"[sheets] push_portfolio 失敗：{e}")
        return False


def pull_portfolio() -> dict:
    """從 Google Sheets 讀取持股清單，回傳與 portfolio_manager 相同格式"""
    try:
        service = _get_service()
        sid = _get_sheet_id()
        result = service.spreadsheets().values().get(
            spreadsheetId=sid,
            range=f"{_PORTFOLIO_SHEET}!A:G"
        ).execute()
        rows = result.get("values", [])
        if len(rows) < 2:
            return {}

        holdings = {}
        for row in rows[1:]:  # 跳過標題
            if not row:
                continue
            def _v(i, default=None):
                v = row[i].strip() if i < len(row) else ""
                if v == "":
                    return default
                try:
                    return float(v)
                except ValueError:
                    return v

            ticker = (row[0].strip() if row else "")
            if not ticker:
                continue
            holdings[ticker] = {
                "name":        row[1].strip() if len(row) > 1 else ticker,
                "shares":      int(float(row[2])) if len(row) > 2 and row[2].strip() else 0,
                "cost":        _v(3),
                "stop_loss":   _v(4),
                "take_profit": _v(5),
            }
        return holdings
    except Exception as e:
        print(f"[sheets] pull_portfolio 失敗：{e}")
        return {}


# ── 自選股 ────────────────────────────────────────────────────────────────────

_WATCHLIST_HEADERS = ["名稱", "ticker"]


def push_watchlist(watchlist: dict) -> bool:
    """把自選股清單（{名稱: ticker}）推送到 Sheets"""
    try:
        service = _get_service()
        sid = _get_sheet_id()
        _ensure_sheets(service, sid)

        rows = [_WATCHLIST_HEADERS] + [[name, ticker] for name, ticker in watchlist.items()]
        service.spreadsheets().values().clear(
            spreadsheetId=sid, range=f"{_WATCHLIST_SHEET}!A:B"
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"{_WATCHLIST_SHEET}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": rows}
        ).execute()
        return True
    except Exception as e:
        print(f"[sheets] push_watchlist 失敗：{e}")
        return False


def pull_watchlist() -> dict:
    """從 Sheets 讀取自選股，回傳 {名稱: ticker}"""
    try:
        service = _get_service()
        sid = _get_sheet_id()
        result = service.spreadsheets().values().get(
            spreadsheetId=sid,
            range=f"{_WATCHLIST_SHEET}!A:B"
        ).execute()
        rows = result.get("values", [])
        if len(rows) < 2:
            return {}
        return {
            row[0].strip(): row[1].strip()
            for row in rows[1:]
            if len(row) >= 2 and row[0].strip() and row[1].strip()
        }
    except Exception as e:
        print(f"[sheets] pull_watchlist 失敗：{e}")
        return {}


def is_configured() -> bool:
    """檢查 Google Sheets 是否已設定"""
    try:
        _get_creds()
        _get_sheet_id()
        return True
    except Exception:
        return False
