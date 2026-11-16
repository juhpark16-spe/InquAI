import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 개발 중에는 /api 요청을 FastAPI(8000)로 넘깁니다.
// 브라우저 입장에서는 같은 주소(localhost:5173)라 로그인 쿠키가 그대로 오갑니다.
// 127.0.0.1 로 적는 이유: Windows에서 localhost 는 IPv6를 먼저 시도해 요청마다 약 2초가 늦어짐
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
