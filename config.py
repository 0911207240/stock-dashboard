import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

def _clean(val: str) -> str:
    import re
    return re.sub(r'[\s﻿]', '', val or "")  # 同時去除空白和 UTF-8 BOM

try:
    import streamlit as st
    LINE_CHANNEL_ACCESS_TOKEN = _clean(st.secrets.get("LINE_TOKEN", os.getenv("LINE_TOKEN", "")))
    LINE_USER_ID = _clean(st.secrets.get("LINE_USER_ID", os.getenv("LINE_USER_ID", "")))
    IMGBB_API_KEY = _clean(st.secrets.get("IMGBB_API_KEY", os.getenv("IMGBB_API_KEY", "")))
except Exception:
    LINE_CHANNEL_ACCESS_TOKEN = _clean(os.getenv("LINE_TOKEN", ""))
    LINE_USER_ID = _clean(os.getenv("LINE_USER_ID", ""))
    IMGBB_API_KEY = _clean(os.getenv("IMGBB_API_KEY", ""))
