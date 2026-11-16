"""모든 응답에 붙이는 기본 보안 헤더.

- X-Content-Type-Options: 브라우저가 응답 형식을 멋대로 추측하지 않게 (JSON을 스크립트로 실행하는 공격 방지)
- X-Frame-Options / frame-ancestors: 다른 사이트가 화면을 iframe 에 띄워 클릭을 유도하는 공격(클릭재킹) 방지
- Referrer-Policy: 다른 사이트로 이동할 때 주소 전체(검색어 등)를 넘기지 않음
- Content-Security-Policy: API 응답(JSON)은 스크립트·이미지를 불러올 일이 없어 전부 막음.
  Swagger 문서(/docs)는 CDN 스크립트를 써야 해서 CSP를 붙이지 않음 (배포에서는 API_DOCS=false 로 끔)
React 화면의 헤더는 배포할 때 웹 서버(Nginx 등)에서 같은 값으로 붙입니다 (개발 서버는 vite.config.ts).
"""

from fastapi import FastAPI, Request

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"


def add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api"):
            response.headers.setdefault("Content-Security-Policy", API_CSP)
        return response
