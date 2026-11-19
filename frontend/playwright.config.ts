// 화면 자동 테스트 (Playwright). 실행: npm run test:e2e   (docs/testing.md)
//
// 테스트할 때마다 시험용 백엔드(임시 DB, 가짜 분석기, backend/tests/e2e_server.py)와
// 화면 개발 서버를 새 포트(8001, 5174)로 켜므로, 개발 중인 서버(8000, 5173)·개발 DB와 섞이지 않습니다.
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const ROOT = fileURLToPath(new URL("..", import.meta.url)); // 프로젝트 루트
// Windows 개발 PC는 프로젝트 가상환경의 Python, CI(리눅스)는 설치된 python
const PY = process.env.PYTHON ?? (process.platform === "win32" ? `"${join(ROOT, ".venv", "Scripts", "python.exe")}"` : "python");
const API_PORT = 8001;
const WEB_PORT = 5174;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // 같은 시험용 DB를 쓰고, 문의 등록에 요청 제한(1분 5건)이 있어 차례로 실행
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    trace: "retain-on-failure", // 실패하면 화면 기록을 남김 (npx playwright show-trace)
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${PY} -m backend.tests.e2e_server --port ${API_PORT}`,
      cwd: ROOT,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { PYTHONIOENCODING: "utf-8" },
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      timeout: 60_000,
      reuseExistingServer: false,
      env: { API_PROXY: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
