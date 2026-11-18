# InquAI 화면 (React 빌드 → nginx)
# nginx가 화면 파일을 주고, /api 요청은 백엔드 컨테이너로 넘깁니다 (브라우저 입장에서는 같은 주소라 로그인 쿠키가 그대로 오감)

# 1단계: 화면 빌드 (타입 검사 포함)
FROM node:24-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2단계: 빌드 결과만 nginx에 (node·소스 코드는 최종 이미지에 없음)
FROM nginx:1.29-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
