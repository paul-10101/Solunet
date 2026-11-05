# Solunet

축제 회차 개선 플랫폼 — 작년 데이터로 올해 축제를 다시 설계하고, 성과를 숫자로 보고합니다.

## 구조
- `/` 소개 페이지 · `/admin` 관리자 대시보드 · `/s/{축제}/{거점}` 방문객 QR 페이지
- `app/stats.py` 집계(코드 계산) · `app/design.py` 규칙 기반 설계안 · `app/ai.py` LLM 문장 작성(숫자 대조 검증)
- 저장소: `MONGODB_URI` 있으면 MongoDB, 없으면 메모리

## 로컬 실행
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# http://localhost:8000/admin → "예시 데이터 불러오기"
```

## 환경변수
| 이름 | 용도 |
|---|---|
| `MONGODB_URI` | MongoDB Atlas 연결 문자열 |
| `ANTHROPIC_API_KEY` | AI 보고서·설계 설명 (없으면 템플릿 문장) |
| `SENTRY_DSN` | 에러 추적 (선택) |

## 배포 (Heroku)
```bash
heroku create solunet
heroku ps:type eco
git push heroku main
heroku domains:add www.solunet.software
heroku certs:auto:enable
```
