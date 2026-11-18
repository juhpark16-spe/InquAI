#!/bin/sh
# 백엔드 컨테이너 시작:
#   1) FAQ 원본·재학습 시연 문장을 data 볼륨에 복사 (이미지에 든 최신 파일)
#   2) DB가 없으면(처음 실행) 시연 DB를 만듦: 계정·FAQ·모의 주문·최근 2주 시연 문의 (backend/database/seed_demo.py)
#   3) 서버 실행. nginx(web 컨테이너) 뒤에 있으므로 X-Forwarded-For 로 실제 접속 IP를 읽음 (로그인 잠금·요청 제한·감사 로그)
set -e

mkdir -p /app/data/faq /app/data/test
cp /app/defaults/faq/faqs.csv /app/data/faq/faqs.csv
cp /app/defaults/test/written_pool.csv /app/data/test/written_pool.csv   # 재학습 시연 (seed_corrections)

if [ ! -f /app/data/inquai.db ]; then
  echo "[InquAI] DB가 없어 시연 DB를 만듭니다."
  python -m backend.database.seed_demo --reset
fi

exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
