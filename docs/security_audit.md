# 패키지 취약점 점검

설치된 패키지에 알려진 취약점이 있는지 확인한 기록입니다. 패키지를 올리거나 배포 전에 다시 돌립니다.

## 2026-11-17

| 대상 | 도구 | 검사 범위 | 결과 |
| --- | --- | --- | --- |
| 백엔드 (Python) | pip-audit 2.10.1 (PyPI 취약점 DB) | `.venv`에 실제 설치된 패키지 139개 (`pip freeze`, 하위 패키지 포함) | **chromadb 1.5.9에서 4건**, 나머지 138개는 0건 |
| 프론트엔드 (npm) | npm audit (npm 11.19.1) | `package-lock.json`의 176개 (운영 75, 개발 101) | **0건** |

### chromadb 취약점 4건 → 이 프로젝트는 해당 없음

| ID | 내용 | 조건 |
| --- | --- | --- |
| CVE-2026-45829 | 인증 없이 서버에서 코드 실행 (악성 모델 저장소 + `trust_remote_code`) | Chroma **HTTP 서버**의 `/api/v2/.../collections` 요청 |
| CVE-2026-45833 | 인증된 사용자가 서버에서 코드 실행 (같은 방식) | Chroma HTTP 서버, 컬렉션 수정 권한 |
| CVE-2026-45831 | 권한 검사가 테넌트·컬렉션을 확인하지 않음 | Chroma HTTP 서버의 `SimpleRBACAuthorizationProvider` |
| CVE-2026-45830 | 인증된 사용자가 다른 테넌트의 데이터를 읽고 씀 | Chroma HTTP 서버 |

- 4건 모두 **Chroma를 별도 HTTP 서버로 띄울 때**만 생깁니다. 아직 고친 버전은 없습니다 (fix 없음).
- InquAI는 `chromadb.PersistentClient`로 FastAPI 프로세스 **안에서** 파일(`data/chroma`)만 읽고 씁니다 (`backend/rag/embedding_search.py`).
  Chroma API 포트가 열리지 않고, 임베딩은 KURE-v1로 직접 계산해 넣으므로 Chroma가 외부 모델을 내려받지도 않습니다.
- 그래서 **지금 구성에서는 영향이 없습니다.** 다만 아래를 지킵니다.
  - Docker Compose에서 Chroma를 서버 컨테이너(`chroma run`, `chromadb/chroma` 이미지)로 따로 띄우지 않습니다.
  - Chroma 새 버전이 나와 취약점이 고쳐지면 올리고 FAQ 검색 평가(`docs/faq_search_eval.md`)를 다시 돌립니다.

## 다시 돌리는 방법

```bash
# 백엔드: 프로젝트 .venv를 건드리지 않도록 pip-audit은 따로 만든 환경에 설치
python -m venv /tmp/auditenv && /tmp/auditenv/bin/pip install pip-audit
.venv/Scripts/python.exe -m pip freeze --exclude-editable | sed 's/+cu[0-9]*//' > frozen.txt   # torch의 +cu132 표기 제거
/tmp/auditenv/bin/pip-audit -r frozen.txt --no-deps --disable-pip

# 프론트엔드
cd frontend && npm audit
```

- `pip-audit -r requirements.txt`로 돌리면 패키지를 다시 내려받아 의존성을 풀어야 해서 오래 걸립니다. 실제 설치된 버전을 그대로 검사하는 위 방법을 씁니다.
- 검사 때 패키지 이름·버전만 PyPI·npm 취약점 DB로 보내고, 코드나 데이터는 보내지 않습니다.
