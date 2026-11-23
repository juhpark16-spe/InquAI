# Docker로 실행하기

명령 한 줄로 InquAI 전체(화면 + 백엔드 + AI 모델)를 띄웁니다. 파이썬·Node 설치나 가상환경 없이 Docker Desktop만 있으면 됩니다.

```
브라우저 ─▶ web (nginx, :8080) ─┬─ 화면 파일 (React 빌드 결과)
                               └─ /api ─▶ backend (FastAPI, :8000, 밖으로 열지 않음)
                                            ├─ 분류 모델 2개 (models/, 읽기 전용 연결)
                                            ├─ KURE-v1 FAQ 검색 (hf-cache 볼륨)
                                            ├─ OpenAI (LLM 판단·답변·초안)
                                            └─ SQLite DB·첨부 사진·FAQ 벡터 (inquai-data 볼륨)
```

| 파일 | 하는 일 |
| --- | --- |
| `docker-compose.yml` | 두 컨테이너(backend, web)와 볼륨 정의 |
| `docker/backend.Dockerfile` | Python 3.12 + 패키지(PyTorch CPU 버전) + 백엔드 코드. 관리자 권한 없는 사용자로 실행 |
| `docker/entrypoint.sh` | 시작할 때 FAQ 원본 복사 → DB가 없으면 시연 DB 생성 → 서버 실행 |
| `docker/web.Dockerfile` | 화면 빌드(타입 검사 포함) → 결과만 nginx 이미지에 |
| `docker/nginx.conf` | 화면 제공, `/api`를 백엔드로 전달, 보안 헤더, 사진 업로드 크기 |
| `.dockerignore` | `.env`·AI Hub 데이터·학습 모델·개발 DB가 이미지에 들어가지 않게 |

## 1. 준비

저장소에 없는 세 가지가 필요합니다 (GitHub에 올리지 않는 파일).

1. **`.env`** — `.env.example`을 복사해 값을 채웁니다. 꼭 필요한 값:
   `OPENAI_API_KEY`, `JWT_SECRET_KEY`, `SEED_ADMIN_PASSWORD`, `SEED_AGENT_PASSWORD`
   (고객 로그인 시연은 `SEED_CUSTOMER_PASSWORD`도). DB 주소·CORS·쿠키 설정은 compose가 컨테이너용 값으로 덮어씁니다.
2. **`models/category_classifier`, `models/sentiment_classifier`** — 학습된 분류 모델 폴더 (docs/model_card.md).
   이미지에 넣지 않고 실행할 때 읽기 전용으로 연결합니다. AI Hub 데이터로 학습한 모델이라 이미지를 어디에 올려도 함께 나가지 않게 하려는 것입니다.
3. **Docker Desktop** 실행

## 2. 실행

```powershell
docker compose up -d --build
```

- 처음에는 이미지 빌드(PyTorch 등 내려받기)로 몇 분 걸립니다. 다음부터는 코드가 바뀐 부분만 다시 빌드합니다.
- 처음 실행하면 DB가 없으므로 **시연 DB**(계정·FAQ·모의 주문·최근 2주 시연 문의)를 자동으로 만듭니다.
- KURE-v1 모델(약 2.2GB)을 처음 한 번 내려받습니다. 이미 PC에 받아 둔 경우 아래처럼 실행하면 다시 받지 않습니다.
  ```powershell
  $env:HF_CACHE = "$env:USERPROFILE/.cache/huggingface"; docker compose up -d
  ```
- 준비가 끝나면 **http://localhost:8080** (관리자 화면은 /login). 준비 상태는 `docker compose ps`의 `healthy`로 확인합니다.

## 3. 자주 쓰는 명령

| 하려는 일 | 명령 |
| --- | --- |
| 서버 기록 보기 | `docker compose logs -f backend` |
| 멈추기 (데이터 유지) | `docker compose down` |
| 코드 고친 뒤 다시 띄우기 | `docker compose up -d --build` |
| 시연 DB 새로 만들기 | `docker compose exec backend python -m backend.database.seed_demo --reset` 후 `docker compose restart backend` |
| 분류 수정 기록 넣기 (재학습 화면용) | `docker compose exec backend python -m backend.training.seed_corrections` |
| 모든 데이터까지 지우기 | `docker compose down -v` (DB·사진·KURE 내려받은 것 모두 삭제) |

## 4. 개발 환경과 다른 점

- DB는 `inquai-data` 볼륨 안에 따로 있습니다. 개발 DB(`data/inquai.db`)와 섞이지 않습니다.
- PyTorch는 CPU 버전입니다 (GPU 없이 어디서나 실행. 문의 1건 분류는 CPU로도 짧음). 학습은 개발 환경(GPU)에서 합니다.
- 백엔드 8000 포트는 밖으로 열지 않고 nginx를 거쳐서만 접속합니다. nginx가 넘겨 준 실제 접속 IP(`X-Forwarded-For`)로 로그인 잠금·요청 제한·감사 로그를 기록합니다.
- 답변 알림 메일은 `.env`의 `MAIL_ENABLED`·SMTP 설정을 그대로 씁니다 (기본 꺼짐). 메일 속 문의 조회 링크는 `SHOP_URL=http://localhost:8080`으로 맞춥니다.
- `COOKIE_SECURE=false`는 http://localhost 시연용입니다. 실제로 배포할 때는 https 뒤에 두고 `true`, `API_DOCS=false`, `PASSWORD_MIN_LENGTH=8` 이상으로 바꿉니다.

## 5. CI 자동 확인 (`.github/workflows/ci.yml`의 "Docker 빌드")

main에 푸시할 때마다 GitHub에서 아래를 자동으로 확인합니다.

1. 이미지 2개(백엔드·화면)를 만듭니다. 패키지 설치 단계는 캐시에 저장해 두 번째부터 빨라집니다.
2. 백엔드 이미지에 `.env`, 학습 모델(`*.safetensors`), AI Hub 데이터(`data/raw`, 외부 테스트)가 없는지 확인합니다.
3. 실행할 때마다 새로 만든 무작위 비밀값으로 시험용 `.env`를 만들고, `docker compose up`으로 실제로 켭니다.
   학습 모델은 저장소에 없어서 `LOAD_MODELS=false`로 켭니다 (분류 모델 없이, FAQ 검색은 TF-IDF).
4. 화면(nginx)을 거쳐 `/api/health`가 응답하고 시연 DB(계정·FAQ·주문)가 만들어졌는지, 화면과 `/admin/drafts` 같은 하위 주소가 열리는지 확인합니다.
5. 실패하면 컨테이너 기록을 남기고, 끝나면 컨테이너와 볼륨을 지웁니다.

분류 모델·KURE·OpenAI까지 켜는 확인은 모델과 API 키가 있는 개발 PC에서 합니다.
