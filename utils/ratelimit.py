"""
防滥用 / 限流工具 — 线程安全滑动窗口限流器。

供 dashboard.py (按钮) 与 lol.py (命令) 共用。
"""
import threading
import time as _time
from collections import defaultdict, deque


class RateLimiter:
    """In-memory sliding-window rate limiter (thread-safe)."""

    def __init__(self, max_calls: int, window: float):
        self.max_calls = max_calls
        self.window = window
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = _time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_calls:
                return False
            q.append(now)
            return True

    def reset(self, key: str):
        with self._lock:
            self._hits.pop(key, None)


# 按钮点击限流: 每人每 5 秒最多 3 次
BUTTON_RATE_LIMITER = RateLimiter(max_calls=3, window=5.0)
# 命令调用限流: 每人每 10 秒最多 2 次
COMMAND_RATE_LIMITER = RateLimiter(max_calls=2, window=10.0)
# 敏感操作异常检测: 每人每 60 秒最多 10 次 (报名/退赛/分队/下注等)
SENSITIVE_ACTION_LIMITER = RateLimiter(max_calls=10, window=60.0)
# 全局消息发送限流: 每 10 秒最多 20 条 (可选, 防 hack 刷屏)
GLOBAL_SEND_LIMITER = RateLimiter(max_calls=20, window=10.0)
