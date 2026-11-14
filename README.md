# Solunet

행사 대행사의 현장 확인·집계·보고를 QR 하나로 자동화하는 도구.

## 구조
- `/` 소개 페이지 · `/demo` 발표용 시연(5단계: 현장 참여 → 결과보고서 → 회차 비교 → 다음 제안서 → 혼잡 시뮬레이션, ←/→·Space로 진행) · `/sim` 혼잡 시뮬레이션 · `/admin` 분석·보고서 · `/s/{행사}/{거점}` 참가자 QR 페이지
- `/qr-maker` QR 생성기(링크·위치·계좌 안내·와이파이, 브라우저 안에서만 처리) · `/admin/settings` 경품·혼잡 경고 기준·거점 위치 설정
- 경품 교환권 `/api/prize/*` · 혼잡 경고 `/api/crowd/{id}` · 제안서 초안 `/api/proposal/{id}` (숫자는 `app/design.py`가 정하고 AI는 문장만)
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
