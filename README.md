# Solunet

축제 회차 개선 플랫폼 — 작년 데이터로 올해 축제를 다시 설계하고, 성과를 숫자로 보고합니다.

## 구조
- `/` 소개 페이지 · `/admin` 관리자 대시보드 · `/s/{축제}/{거점}` 방문객 QR 페이지
- `app/stats.py` 집계(코드 계산) · `app/design.py` 규칙 기반 설계안 · `app/ai.py` LLM 문장 작성(숫자 대조 검증)
- 저장소: `DATABASE_URL` 있으면 PostgreSQL, `MONGODB_URI` 있으면 MongoDB, 둘 다 없으면 메모리

## 로컬 실행
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# http://localhost:8000/admin → "예시 데이터 불러오기"
```

## 환경변수
| 이름 | 용도 |
|---|---|
| `DATABASE_URL` | PostgreSQL (Render 무료 DB, render.yaml이 자동 연결) |
| `MONGODB_URI` | (선택) MongoDB 사용 시 |
| `GITHUB_MODELS_TOKEN` | AI 보고서·설계 설명 — GitHub 토큰(models:read)으로 무료 사용. 없으면 템플릿 문장 |
| `ANTHROPIC_API_KEY` | (선택) 다른 LLM 사용 시 |
| `SENTRY_DSN` | 에러 추적 (선택) |

## 배포 (Render)
Render → New → Blueprint → 이 저장소 선택 (render.yaml 자동 적용) → 환경변수 입력.
도메인: Settings → Custom Domains → `www.solunet.software` → Name.com에 CNAME 추가.
