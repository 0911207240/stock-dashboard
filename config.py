import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    import streamlit as st
    LINE_CHANNEL_ACCESS_TOKEN = st.secrets.get("LINE_TOKEN", os.getenv("LINE_TOKEN", "")).strip()
    LINE_USER_ID = st.secrets.get("LINE_USER_ID", os.getenv("LINE_USER_ID", "")).strip()
except Exception:
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_TOKEN", "").strip()
    LINE_USER_ID = os.getenv("LINE_USER_ID", "").strip()
