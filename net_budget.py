"""
外部資料源時間預算：雲端 IP 可能被慢速掐住，累計耗時或連續失敗過多就停用該來源，
本次執行後續呼叫直接回傳空值（訊號視為中性），避免整個掃描被拖到逾時。
"""
import time


class Budget:
    def __init__(self, total_sec: float = 90, max_consec_fail: int = 5):
        self.total_sec = total_sec
        self.max_consec_fail = max_consec_fail
        self.spent = 0.0
        self.fails = 0

    def ok(self) -> bool:
        return self.spent < self.total_sec and self.fails < self.max_consec_fail

    def call(self, fn, default):
        """執行 fn()；預算用盡回傳 default。fn 內部吞例外時以空結果視為失敗。"""
        if not self.ok():
            return default
        t0 = time.monotonic()
        try:
            result = fn()
        except Exception:
            self.fails += 1
            return default
        finally:
            self.spent += time.monotonic() - t0
        self.fails = 0 if result else self.fails + 1
        return result
