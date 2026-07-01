"""Gmail 每日摘要模組 — 透過 Gmail API 整理重要未讀信件

支援兩種認證方式：
  1. Service Account（推薦，伺服器端）：設定 GOOGLE_SERVICE_ACCOUNT_JSON
  2. OAuth2（本機互動）：設定 GMAIL_CREDENTIALS_JSON

財經關鍵字過濾：自動標記與財報、股利、法說會相關信件
"""
import json
import time
from pathlib import Path
from datetime import datetime

_CACHE_FILE = Path("gmail_cache.json")
_CACHE_TTL = 3600

_FINANCE_KEYWORDS = [
    "財報", "股利", "除息", "法說", "配息", "股東會", "盈餘",
    "EPS", "營收", "季報", "年報", "分紅", "增資", "減資",
    "股息", "台積電", "聯發科", "投資", "基金", "ETF",
    "dividend", "earnings", "revenue", "quarterly",
]


def _load_cache() -> dict:
    try:
        data = json.loads(_CACHE_FILE.read_text())
        if time.time() - data.get("ts", 0) < _CACHE_TTL:
            return data
    except Exception:
        pass
    return {}


def _save_cache(data: dict):
    data["ts"] = time.time()
    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False))


def _get_service_account_creds():
    """嘗試用 Service Account 建立 Gmail 憑證（需要 domain-wide delegation）"""
    import os
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json:
        try:
            import streamlit as st
            sa_json = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        except Exception:
            pass
    if not sa_json:
        return None

    user_email = os.environ.get("GMAIL_DELEGATED_USER", "")
    if not user_email:
        try:
            import streamlit as st
            user_email = st.secrets.get("GMAIL_DELEGATED_USER", "")
        except Exception:
            pass
    if not user_email:
        return None

    from google.oauth2.service_account import Credentials
    info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        subject=user_email,
    )
    return creds


def _is_finance_related(subject: str, sender: str) -> bool:
    """判斷信件是否與財經相關"""
    text = (subject + sender).lower()
    return any(kw.lower() in text for kw in _FINANCE_KEYWORDS)


def fetch_gmail_summary() -> dict:
    """
    使用 Gmail API 抓取今日未讀重要信件摘要。
    支援 Service Account 或 OAuth2 兩種認證方式。
    若未設定則回傳空結果。
    """
    import os
    creds_path = os.environ.get("GMAIL_CREDENTIALS_JSON", "")
    token_path = os.environ.get("GMAIL_TOKEN_JSON", "gmail_token.json")

    # 優先嘗試 Service Account
    creds = _get_service_account_creds()

    if creds is None and not creds_path:
        return {"emails": [], "note": "Gmail 尚未設定（需要 OAuth 憑證或 Service Account）"}

    cached = _load_cache()
    if cached.get("emails"):
        return cached

    try:
        from googleapiclient.discovery import build

        # OAuth2 fallback
        if creds is None:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
            if Path(token_path).exists():
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    return {"emails": [], "note": "Gmail token 過期，請重新授權"}

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        today = datetime.now().strftime("%Y/%m/%d")
        query = f"is:unread after:{today} category:primary"
        results = service.users().messages().list(
            userId="me", q=query, maxResults=20
        ).execute()

        messages = results.get("messages", [])
        emails = []
        finance_emails = []

        for msg in messages[:15]:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()

            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "未知寄件者")
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            subject = headers.get("Subject", "（無主旨）")
            is_finance = _is_finance_related(subject, sender)

            entry = {"from": sender, "subject": subject, "finance": is_finance}
            emails.append(entry)
            if is_finance:
                finance_emails.append(entry)

        result = {
            "emails": emails,
            "finance_emails": finance_emails,
            "total_unread": len(messages),
        }
        _save_cache(result)
        return result

    except ImportError:
        return {"emails": [], "note": "需安裝 google-api-python-client"}
    except Exception as e:
        print(f"[Gmail] 抓取失敗：{e}")
        return {"emails": [], "note": str(e)}


def format_gmail_summary(data: dict) -> str:
    note = data.get("note", "")
    if note:
        return f"📧 Gmail：{note}"

    emails = data.get("emails", [])
    if not emails:
        return "📧 Gmail：今日無新未讀信件"

    total = data.get("total_unread", len(emails))
    finance = data.get("finance_emails", [])
    lines = [f"📧 Gmail 未讀摘要（{total} 封）"]

    if finance:
        lines.append(f"  💹 財經相關（{len(finance)} 封）：")
        for e in finance[:3]:
            lines.append(f"    • {e['from']}：{e['subject']}")

    other = [e for e in emails if not e.get("finance")]
    if other:
        lines.append(f"  📩 其他未讀：")
        for e in other[:3]:
            lines.append(f"    • {e['from']}：{e['subject']}")

    if total > 6:
        lines.append(f"  ...還有 {total - 6} 封未讀")

    return "\n".join(lines)


def is_configured() -> bool:
    """檢查 Gmail 是否已設定"""
    import os
    has_sa = bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") and
                  os.environ.get("GMAIL_DELEGATED_USER"))
    has_oauth = bool(os.environ.get("GMAIL_CREDENTIALS_JSON"))
    if not has_sa and not has_oauth:
        try:
            import streamlit as st
            has_sa = bool(st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON") and
                          st.secrets.get("GMAIL_DELEGATED_USER"))
            has_oauth = bool(st.secrets.get("GMAIL_CREDENTIALS_JSON"))
        except Exception:
            pass
    return has_sa or has_oauth
