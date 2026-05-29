import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

def _clean(val: str) -> str:
    import re
    return re.sub(r'\s+', '', val or "")

try:
    import streamlit as st
    LINE_CHANNEL_ACCESS_TOKEN = _clean(st.secrets.get("LINE_TOKEN", os.getenv("LINE_TOKEN", "")))
    LINE_USER_ID = _clean(st.secrets.get("LINE_USER_ID", os.getenv("LINE_USER_ID", "")))
except Exception:
    LINE_CHANNEL_ACCESS_TOKEN = _clean(os.getenv("LINE_TOKEN", ""))
    LINE_USER_ID = _clean(os.getenv("LINE_USER_ID", ""))
