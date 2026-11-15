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
