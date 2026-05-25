from dotenv import load_dotenv
load_dotenv()
from line_notifier import send

ok = send("股票儀表板連線測試成功！推播功能正常運作中。")
print("推播成功！" if ok else "推播失敗，請檢查 Token 和 User ID")
