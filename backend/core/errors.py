"""공통 오류 응답: { "detail": "...", "code": "..." } (docs/api_spec.md 1장)."""

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

DEFAULT_CODES = {400: "INVALID_STATE", 401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND",
                 423: "ACCOUNT_LOCKED", 429: "TOO_MANY_REQUESTS"}


class AppError(HTTPException):
    """API 코드에서 raise AppError(404, "문의를 찾을 수 없습니다.", "NOT_FOUND") 처럼 씁니다."""

    def __init__(self, status_code: int, detail: str, code: str | None = None, **extra):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code or DEFAULT_CODES.get(status_code, "ERROR")
        self.extra = extra  # 예: 423 응답의 locked_until


def register_error_handlers(app: FastAPI) -> None:
    # 없는 주소(404) 같은 오류는 Starlette가 내므로 부모 클래스로 받아야 모두 같은 형식이 됨
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = getattr(exc, "code", None) or DEFAULT_CODES.get(exc.status_code, "ERROR")
        body = {"detail": exc.detail, "code": code, **getattr(exc, "extra", {})}
        return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))
