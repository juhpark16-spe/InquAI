# InquAI 백엔드 (FastAPI + 분류 모델 + KURE FAQ 검색 + LangGraph 에이전트)
#
# - PyTorch는 CPU 버전 (GPU 없이 어디서나 실행. 문의 1건 분류는 CPU로도 1초 안쪽)
# - 학습된 분류 모델(models/)과 .env 는 이미지에 넣지 않고 실행할 때 연결합니다 (docker-compose.yml)
#   → 이미지를 어디에 올려도 AI Hub 데이터로 학습한 모델·API 키가 함께 나가지 않음
# - DB·첨부 사진·FAQ 벡터는 data 볼륨에 저장 (컨테이너를 지워도 남음)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 패키지 먼저 (코드만 바뀌면 이 층은 다시 설치하지 않음). GPU(+cu132) 버전을 같은 버전의 CPU 빌드로 바꿔 설치 (CI와 같은 방법)
COPY requirements.txt .
RUN sed -e '/download.pytorch.org/d' -e 's/+cu132/+cpu/' requirements.txt > /tmp/requirements-docker.txt \
 && pip install -r /tmp/requirements-docker.txt --extra-index-url https://download.pytorch.org/whl/cpu \
 && rm /tmp/requirements-docker.txt

# 관리자 권한 없이 실행할 사용자
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app/data /app/models /home/app/.cache/huggingface \
 && chown -R app:app /app/data /home/app/.cache

COPY backend ./backend
# FAQ 원본 (시연 DB를 만들 때 읽음). data 볼륨이 /app/data 를 덮으므로 따로 두고 시작할 때 복사
COPY data/faq ./defaults/faq
COPY data/test/written_pool.csv ./defaults/test/written_pool.csv
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)" || exit 1

ENTRYPOINT ["entrypoint.sh"]
