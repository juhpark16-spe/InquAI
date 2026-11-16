"""공개 API 과다 호출 제한 (IP별, 서버 메모리). 서버 1대 기준의 간단한 방식입니다.

    @router.post("/inquiries", dependencies=[Depends(rate_limit("inquiry_create", 5, 60))])
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from backend.core.errors import AppError

_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = threading.Lock()


def reset() -> None:
    """테스트용: 기록 지우기."""
    with _lock:
        _hits.clear()


class FailureLock:
    """같은 대상(예: 이메일)에 실패가 window 안에 limit 번 쌓이면 잠급니다. 성공해도 기록은 남겨 둠
    (성공한 뒤 다른 비밀번호를 계속 시도하는 것도 막기 위해)."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self._fails: dict[str, deque] = defaultdict(deque)

    def _recent(self, key: str, now: float) -> deque:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def is_locked(self, key: str) -> bool:
        with _lock:
            return len(self._recent(key, time.monotonic())) >= self.limit

    def fail(self, key: str) -> None:
        with _lock:
            now = time.monotonic()
            self._recent(key, now).append(now)

    def reset(self) -> None:
        with _lock:
            self._fails.clear()


def rate_limit(name: str, limit: int, window_seconds: int):
    def check(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _lock:
            q = _hits[(name, ip)]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                raise AppError(429, "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.", "TOO_MANY_REQUESTS")
            q.append(now)

    return check
