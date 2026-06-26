"""Gmail 每日摘要模組 — 透過 Gmail API 整理重要未讀信件"""
import json
import time
from pathlib import Path
from datetime import datetime

_CACHE_FILE = Path("gmail_cache.json")
_CACHE_TTL = 3600


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


def fetch_gmail_summary() -> dict:
    """
    使用 Gmail API 抓取今日未讀重要信件摘要。
    需要 GMAIL_CREDENTIALS_JSON 環境變數（OAuth2 憑證）。
    若未設定則回傳空結果。
    """
    import os
    creds_path = os.environ.get("GMAIL_CREDENTIALS_JSON", "")
    token_path = os.environ.get("GMAIL_TOKEN_JSON", "gmail_token.json")

    if not creds_path:
        return {"emails": [], "note": "Gmail 尚未設定（需要 OAuth 憑證）"}

    cached = _load_cache()
    if cached.get("emails"):
        return cached

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
        creds = None

        if Path(token_path).exists():
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                return {"emails": [], "note": "Gmail token 過期，請重新授權"}

        service = build("gmail", "v1", credentials=creds)

        today = datetime.now().strftime("%Y/%m/%d")
        query = f"is:unread after:{today} category:primary"
        results = service.users().messages().list(
            userId="me", q=query, maxResults=10
        ).execute()

        messages = results.get("messages", [])
        emails = []
        for msg in messages[:8]:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject"]
            ).execute()

            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "未知寄件者")
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            subject = headers.get("Subject", "（無主旨）")

            emails.append({"from": sender, "subject": subject})

        result = {"emails": emails, "total_unread": len(messages)}
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
    lines = [f"📧 Gmail 未讀摘要（{total} 封）"]
    for e in emails[:5]:
        lines.append(f"  • {e['from']}：{e['subject']}")
    if total > 5:
        lines.append(f"  ...還有 {total - 5} 封未讀")

    return "\n".join(lines)
