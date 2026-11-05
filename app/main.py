import os
import random
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, design, stats
from .store import make_store, now

if os.getenv("SENTRY_DSN"):
    import sentry_sdk

    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.2)

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
app = FastAPI(title="Solunet API")
db = make_store()


# ---------- 모델 ----------
class Scan(BaseModel):
    festival: str
    checkpoint: str
    session: str = Field(min_length=6, max_length=64)  # 익명 세션 ID (개인정보 없음)


class ExitReason(BaseModel):
    festival: str
    checkpoint: str
    session: str = Field(min_length=6, max_length=64)
    reason: str = Field(max_length=40)
    comment: str = Field(default="", max_length=300)


def _festival(fid):
    f = db.get_festival(fid)
    if not f:
        raise HTTPException(404, "축제를 찾을 수 없습니다")
    return f


def _stats(f, edition):
    return stats.compute_stats(f, db.scans_for(f["id"], edition), db.responses_for(f["id"], edition))


# ---------- 방문객 API ----------
@app.post("/api/scan")
def post_scan(s: Scan):
    f = _festival(s.festival)
    if s.checkpoint not in {c["id"] for c in f["checkpoints"]}:
        raise HTTPException(400, "없는 거점입니다")
    db.add_scan({**s.model_dump(), "edition": f["edition"], "ts": now().isoformat()})
    return {"ok": True}


@app.post("/api/exit-reason")
def post_exit_reason(r: ExitReason):
    f = _festival(r.festival)
    db.add_response({**r.model_dump(), "edition": f["edition"], "ts": now().isoformat()})
    return {"ok": True}


@app.get("/api/festival/{fid}")
def get_festival(fid: str):
    return _festival(fid)


# ---------- 관리자 API ----------
@app.get("/api/festivals")
def list_festivals():
    return db.list_festivals()


@app.get("/api/stats/{fid}")
def get_stats(fid: str):
    f = _festival(fid)
    cur = _stats(f, f["edition"])
    prev = _stats(f, f["edition"] - 1) if f["edition"] > 1 else None
    if prev and prev["visitors"] == 0:
        prev = None
    return {"festival": f, "current": cur, "previous": prev, "comparison": stats.compare(prev, cur)}


@app.post("/api/report/{fid}")
def make_report(fid: str):
    d = get_stats(fid)
    return ai.write_report(d["festival"], d["current"], d["comparison"])


@app.post("/api/design/{fid}")
def make_design(fid: str):
    d = get_stats(fid)
    plan = design.propose(d["current"])
    return {"plan": plan, "explanation": ai.explain_design(plan)}


@app.get("/api/health")
def health():
    return {"ok": True, "store": db.kind, "llm": bool(os.getenv("ANTHROPIC_API_KEY"))}


# ---------- 시연용 예시 데이터 ----------
DEMO_ID = "demo"
DEMO_CPS = [
    {"id": "gate", "name": "입구 안내소", "x": 10, "y": 80},
    {"id": "market", "name": "먹거리 장터", "x": 30, "y": 55},
    {"id": "stage", "name": "메인 무대", "x": 55, "y": 70},
    {"id": "craft", "name": "체험 부스", "x": 75, "y": 35},
    {"id": "view", "name": "전망대", "x": 90, "y": 12},
]


def _seed_edition(edition, keep_prob, reasons, n=320, seed=0):
    rnd = random.Random(seed)
    day = datetime(2025 + edition - 1, 10, 11, 10, tzinfo=timezone.utc)
    for i in range(n):
        sess = f"demo{edition}-{i:04d}"
        t = day + timedelta(minutes=rnd.randint(0, 420))
        for j, cp in enumerate(DEMO_CPS):
            if j > 0 and rnd.random() > keep_prob[j - 1]:
                db.add_response({"festival": DEMO_ID, "checkpoint": DEMO_CPS[j - 1]["id"], "session": sess,
                                 "reason": rnd.choices(list(reasons), weights=list(reasons.values()))[0],
                                 "comment": "", "edition": edition, "ts": t.isoformat()})
                break
            db.add_scan({"festival": DEMO_ID, "checkpoint": cp["id"], "session": sess,
                         "edition": edition, "ts": t.isoformat()})
            t += timedelta(minutes=rnd.randint(8, 25))


@app.post("/api/demo/seed")
def seed_demo():
    """예시 데이터(실측 아님). 작년(1회차)과 올해(2회차)를 만든다."""
    db.upsert_festival({"id": DEMO_ID, "name": "예시 축제 (시연용 가상 데이터)", "edition": 2,
                        "demo": True, "checkpoints": DEMO_CPS})
    db.clear_festival(DEMO_ID)
    # 1회차: 메인 무대 → 체험 부스 구간 이탈이 큼 / 2회차: 개선 후 이탈 감소
    _seed_edition(1, [0.9, 0.85, 0.55, 0.8], {"화장실·편의시설 부족": 5, "대기 줄이 김": 2, "다음 장소가 멀다": 3}, seed=1)
    _seed_edition(2, [0.9, 0.87, 0.78, 0.82], {"대기 줄이 김": 4, "다음 장소가 멀다": 2, "화장실·편의시설 부족": 1}, seed=2)
    return {"ok": True, "festival": DEMO_ID}


# ---------- 화면 ----------
@app.get("/s/{fid}/{cid}")
def visitor_page(fid: str, cid: str):
    return FileResponse(os.path.join(STATIC, "visit.html"))


@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(STATIC, "admin.html"))


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
