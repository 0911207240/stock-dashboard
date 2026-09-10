"""
網路呼叫逾時保護 — yfinance/curl_cffi 在 Yahoo 限流時可能整個卡住不回應
（無內建 timeout），導致單一 GitHub Actions job 從幾分鐘拖到 6 小時上限被取消。

用 daemon thread 包住呼叫：逾時就放棄等待、回傳預設值，卡住的執行緒丟在背景，
daemon=True 保證它不會阻塞程式結束（不像 ThreadPoolExecutor 的 worker 會在
atexit 被 join 住）。
"""
import socket
import threading

# call_with_timeout() below only makes the CALLER stop waiting after `timeout`
# seconds — it does not cancel the underlying HTTP request. If yfinance's
# shared session/connection pool is stuck on a socket read (Yahoo silently
# not responding, common under rate limiting), the abandoned daemon thread
# keeps holding that connection for however long the OS takes to give up
# (can be 15-30+ min), and every subsequent call queues up behind it on the
# same shared pool. A real socket-level timeout is required so the stuck
# read actually raises and frees the connection.
socket.setdefaulttimeout(15)


def call_with_timeout(fn, *args, timeout=10, default=None, **kwargs):
    box = {}

    def _target():
        try:
            box["value"] = fn(*args, **kwargs)
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive() or "error" in box:
        return default
    return box.get("value", default)
