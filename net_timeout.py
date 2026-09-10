"""
網路呼叫逾時保護 — yfinance/curl_cffi 在 Yahoo 限流時可能整個卡住不回應
（無內建 timeout），導致單一 GitHub Actions job 從幾分鐘拖到 6 小時上限被取消。

用 daemon thread 包住呼叫：逾時就放棄等待、回傳預設值，卡住的執行緒丟在背景，
daemon=True 保證它不會阻塞程式結束（不像 ThreadPoolExecutor 的 worker 會在
atexit 被 join 住）。
"""
import threading

# call_with_timeout() below only makes the CALLER stop waiting after `timeout`
# seconds — it does NOT cancel the underlying call. yfinance shares one
# YfData instance (and one threading.Lock guarding crumb/cookie fetch)
# across every yf.Ticker(...) in the process. If `timeout` is shorter than
# yfinance's own internal request budget (its .get() defaults to 30s per
# HTTP call, and a single .info call can issue several), the caller gives
# up and moves on to the next ticker WHILE the abandoned thread is still
# running and still holding that shared lock — every subsequent ticker
# then queues up behind it until that one orphaned call finally finishes,
# which is what produced the 20-60 min silent stalls in Actions runs.
# (socket-level timeouts don't help here: yfinance's HTTP client is
# curl_cffi, which bypasses Python's `socket` module entirely.)
#
# Fix: give `timeout` enough headroom that we essentially never abandon a
# call before it would have finished on its own — see call sites, all
# raised from 15-20s to 45s+.


def call_with_timeout(fn, *args, timeout=45, default=None, **kwargs):
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
