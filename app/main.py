import hashlib
import os
import random
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
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
DUP_WINDOW_SEC = 60  # 같은 방문자가 같은 거점을 60초 안에 다시 열면 새로고침으로 보고 기록하지 않음


# ---------- 모델 ----------
class Scan(BaseModel):
    festival: str = Field(max_length=40)
    token: str = Field(max_length=40)  # QR에 들어간 거점 토큰 (데모 축제는 거점 ID도 허용)
    session: str = Field(min_length=6, max_length=64)  # 익명 방문 ID (개인정보 없음)
    event: str = Field(default="visit", pattern="^(visit|enter|queue|start|done)$")


class ExitReason(BaseModel):
    festival: str = Field(max_length=40)
    token: str = Field(max_length=40)
    session: str = Field(min_length=6, max_length=64)
    reason: str = Field(max_length=40)
    comment: str = Field(default="", max_length=300)


class Survey(BaseModel):
    festival: str = Field(max_length=40)
    session: str = Field(min_length=6, max_length=64)
    crowd: int = Field(ge=1, le=5)  # 혼잡도: 1 매우 한산 ~ 5 매우 혼잡
    route: int = Field(ge=1, le=5)  # 동선 편의: 1 매우 불편 ~ 5 매우 편함
    compare: str = Field(default="", max_length=20)  # 이전 행사와 비교: 더 나음 / 비슷 / 더 나쁨 / 처음
    satisfaction: int | None = Field(default=None, ge=1, le=5)  # 전반 만족도 (v2, 선택): 1 매우 불만족 ~ 5 매우 만족
    revisit: str = Field(default="", max_length=20)  # 재방문 의사 (v2, 선택): 있다 / 모르겠다 / 없다
    comment: str = Field(default="", max_length=300)


class Inquiry(BaseModel):
    org: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=40)
    contact: str = Field(min_length=3, max_length=80)
    festival: str = Field(default="", max_length=80)
    scale: str = Field(default="", max_length=40)
    when: str = Field(default="", max_length=40)
    message: str = Field(default="", max_length=1000)


class Trial(BaseModel):
    org: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=40)
    contact: str = Field(min_length=3, max_length=80)
    event_name: str = Field(min_length=1, max_length=60)
    date: str = Field(default="", max_length=20)
    checkpoints: list[str] = Field(min_length=1, max_length=20)
    agree: bool = False


class NewFestival(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    date: str = Field(default="", max_length=20)
    checkpoints: list[str] = Field(min_length=1, max_length=40)


# ---------- 공통 ----------
def require_admin(x_admin_key: str = Header(default="")):
    # 시연 기간용 고정 키. 바꾸려면 Render 환경변수 SOLUNET_ADMIN_KEY를 넣으면 그 값이 우선한다.
    key = os.getenv("SOLUNET_ADMIN_KEY") or "1111"
    if not secrets.compare_digest(x_admin_key, key):
        raise HTTPException(401, "관리자 키가 필요합니다")


def _hash(k):
    return hashlib.sha256(k.encode()).hexdigest()


def _is_admin(x_admin_key):
    key = os.getenv("SOLUNET_ADMIN_KEY") or "1111"
    return bool(x_admin_key) and secrets.compare_digest(x_admin_key, key)


def _can_manage(f, x_admin_key="", x_event_key=""):
    """관리자 키 또는 그 행사를 만든 대행사의 행사 키."""
    if _is_admin(x_admin_key):
        return True
    h = f.get("owner_key_hash")
    return bool(h and x_event_key) and secrets.compare_digest(_hash(x_event_key), h)


def _require_manage(f, x_admin_key, x_event_key):
    if not _can_manage(f, x_admin_key, x_event_key):
        raise HTTPException(401, "이 행사의 관리 링크(또는 관리자 키)가 필요합니다")


def _private(f):
    return {k: v for k, v in f.items() if k != "owner_key_hash"}


def _festival(fid):
    f = db.get_festival(fid)
    if not f:
        raise HTTPException(404, "행사를 찾을 수 없습니다")
    return f


def _public(f):
    """방문객에게 보여 줄 정보. 토큰은 절대 내보내지 않는다."""
    return {"id": f["id"], "name": f["name"], "date": f.get("date", ""), "demo": f.get("demo", False),
            "edition": f.get("edition", 1),
            "checkpoints": [{"id": c["id"], "name": c["name"]} for c in f["checkpoints"]]}


def _checkpoint_by_token(f, token):
    for c in f["checkpoints"]:
        if c.get("token") == token or (f.get("demo") and c["id"] == token):
            return c
    raise HTTPException(404, "등록되지 않은 QR입니다")


def _guard(f, x_admin_key, x_event_key=""):
    """예시(데모) 행사는 공개, 실제 행사 데이터는 관리자 또는 행사를 만든 대행사만."""
    if not f.get("demo"):
        _require_manage(f, x_admin_key, x_event_key)


def _real(rows):
    return [r for r in rows if not str(r.get("session", "")).startswith("test")]  # 운영진 테스트 스캔 제외


def _stats(f, edition):
    return stats.compute_stats(f, _real(db.scans_for(f["id"], edition)), _real(db.responses_for(f["id"], edition)))


def _session_done(f, session):
    return sorted({s["checkpoint"] for s in db.scans_for(f["id"], f["edition"]) if s["session"] == session})


# ---------- 방문객 API ----------
@app.get("/api/festival/{fid}")
def get_festival(fid: str):
    return _public(_festival(fid))


@app.post("/api/scan")
def post_scan(s: Scan):
    f = _festival(s.festival)
    cp = _checkpoint_by_token(f, s.token)
    t = now()
    mine = [x for x in db.scans_for(f["id"], f["edition"]) if x["session"] == s.session]
    recent = any(x["checkpoint"] == cp["id"] and
                 (t - datetime.fromisoformat(x["ts"])).total_seconds() < DUP_WINDOW_SEC for x in mine)
    if not recent:
        db.add_scan({"festival": f["id"], "checkpoint": cp["id"], "session": s.session, "event": s.event,
                     "edition": f["edition"], "ts": t.isoformat()})
    done = sorted({x["checkpoint"] for x in mine} | {cp["id"]})
    return {"ok": True, "duplicate": recent, "checkpoint": {"id": cp["id"], "name": cp["name"]},
            "done": done, "total": len(f["checkpoints"])}


@app.post("/api/exit-reason")
def post_exit_reason(r: ExitReason):
    f = _festival(r.festival)
    cp = _checkpoint_by_token(f, r.token)
    db.add_response({"kind": "exit", "festival": f["id"], "checkpoint": cp["id"], "session": r.session,
                     "reason": r.reason, "comment": r.comment, "edition": f["edition"], "ts": now().isoformat()})
    return {"ok": True}


@app.post("/api/survey")
def post_survey(v: Survey):
    f = _festival(v.festival)
    db.add_response({"kind": "survey", **v.model_dump(), "festival": f["id"], "edition": f["edition"],
                     "ts": now().isoformat()})
    return {"ok": True}


# ---------- 도입 문의 ----------
@app.post("/api/inquiry")
def post_inquiry(q: Inquiry):
    db.add_inquiry({**q.model_dump(), "ts": now().isoformat()})
    return {"ok": True}


_trial_hits = defaultdict(deque)
TRIAL_PER_HOUR = 5


def _client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


@app.post("/api/trial")
def post_trial(q: Trial, request: Request):
    """대행사가 직접 무료 체험 행사를 만든다. 관리 키는 이 응답에서 한 번만 보여 주고 서버에는 해시만 남긴다."""
    if not q.agree:
        raise HTTPException(400, "이용 안내에 동의해 주세요")
    ip, t0 = _client_ip(request), time.time()
    hits = _trial_hits[ip]
    while hits and t0 - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= TRIAL_PER_HOUR:
        raise HTTPException(429, "한 시간에 만들 수 있는 체험 행사 수를 넘었습니다. 잠시 후 다시 시도하세요")
    names = [x.strip()[:40] for x in q.checkpoints if x.strip()]
    if not names:
        raise HTTPException(400, "거점 이름을 하나 이상 입력하세요")
    hits.append(t0)
    key = secrets.token_urlsafe(18)
    fid = "t" + secrets.token_hex(4)
    f = {"id": fid, "name": q.event_name.strip(), "date": q.date, "edition": 1, "demo": False, "trial": True,
         "org": q.org.strip(), "created": now().isoformat(), "owner_key_hash": _hash(key),
         "checkpoints": [{"id": f"c{i + 1}", "name": nm, "token": secrets.token_urlsafe(6)} for i, nm in enumerate(names)]}
    db.upsert_festival(f)
    db.add_inquiry({"org": q.org, "name": q.name, "contact": q.contact, "festival": q.event_name, "scale": f"거점 {len(names)}곳",
                    "when": q.date, "message": "무료 체험 행사 생성", "trial_id": fid, "ts": now().isoformat()})
    return {"id": fid, "key": key, "name": f["name"], "checkpoints": len(names)}


@app.get("/api/inquiries", dependencies=[Depends(require_admin)])
def list_inquiries():
    return db.list_inquiries()


# ---------- 관리자 API (행사 운영) ----------
@app.get("/api/admin/check", dependencies=[Depends(require_admin)])
def admin_check():
    return {"ok": True}


@app.post("/api/admin/festivals", dependencies=[Depends(require_admin)])
def create_festival(n: NewFestival):
    names = [x.strip() for x in n.checkpoints if x.strip()]
    if not names:
        raise HTTPException(400, "거점 이름을 하나 이상 입력하세요")
    fid = "f" + secrets.token_hex(3)
    f = {"id": fid, "name": n.name.strip(), "date": n.date, "edition": 1, "demo": False, "created": now().isoformat(),
         "checkpoints": [{"id": f"c{i + 1}", "name": nm[:40], "token": secrets.token_urlsafe(6)}
                         for i, nm in enumerate(names)]}
    db.upsert_festival(f)
    return f


@app.get("/api/admin/festivals", dependencies=[Depends(require_admin)])
def admin_festivals():
    fs = [f for f in db.list_festivals() if not f.get("demo")]
    return [_private(f) for f in sorted(fs, key=lambda f: f.get("created", ""), reverse=True)]


@app.get("/api/admin/festival/{fid}")
def admin_festival(fid: str, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    f = _festival(fid)
    _require_manage(f, x_admin_key, x_event_key)
    return _private(f)


@app.post("/api/admin/festival/{fid}/next-edition")
def next_edition(fid: str, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    """같은 거점·같은 QR로 다음 회차를 시작한다. 이전 회차 데이터는 그대로 남아 회차 비교에 쓰인다."""
    f = _festival(fid)
    _require_manage(f, x_admin_key, x_event_key)
    if f.get("demo"):
        raise HTTPException(400, "예시 행사는 회차를 바꿀 수 없습니다")
    if not _real(db.scans_for(fid, f["edition"])):
        raise HTTPException(400, "현재 회차에 기록된 스캔이 없습니다. 데이터가 쌓인 뒤 다음 회차를 시작하세요")
    f["edition"] = f.get("edition", 1) + 1
    db.upsert_festival(f)
    return {"ok": True, "edition": f["edition"]}


@app.get("/api/admin/logs/{fid}")
def admin_logs(fid: str, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    f = _festival(fid)
    _require_manage(f, x_admin_key, x_event_key)
    names = {c["id"]: c["name"] for c in f["checkpoints"]}
    scans = sorted(db.scans_for(fid, f["edition"]), key=lambda s: s["ts"], reverse=True)
    resp = sorted(db.responses_for(fid, f["edition"]), key=lambda r: r["ts"], reverse=True)
    for x in scans + resp:
        if "checkpoint" in x:
            x["checkpoint_name"] = names.get(x["checkpoint"], x["checkpoint"])
    return {"festival": _public(f), "scans": scans, "responses": resp}


# ---------- 분석 API ----------
@app.get("/api/festivals")
def list_festivals():
    return [_public(f) for f in db.list_festivals() if f.get("demo")]


@app.get("/api/stats/{fid}")
def get_stats(fid: str, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    f = _festival(fid)
    _guard(f, x_admin_key, x_event_key)
    cur = _stats(f, f["edition"])
    prev = _stats(f, f["edition"] - 1) if f["edition"] > 1 else None
    if prev and prev["visitors"] == 0:
        prev = None
    return {"festival": _public(f), "current": cur, "previous": prev, "comparison": stats.compare(prev, cur)}


@app.post("/api/report/{fid}")
def make_report(fid: str, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    d = get_stats(fid, x_admin_key, x_event_key)
    return ai.write_report(d["festival"], d["current"], d["comparison"])


@app.post("/api/design/{fid}")
def make_design(fid: str, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    d = get_stats(fid, x_admin_key, x_event_key)
    plan = design.propose(d["current"])
    return {"plan": plan, "explanation": ai.explain_design(plan)}


# ---------- 배치(격자 편집기 ↔ Unity 공통 JSON) ----------
@app.put("/api/layout/{fid}")
def put_layout(fid: str, layout: dict, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    f = _festival(fid)
    _guard(f, x_admin_key, x_event_key)
    if not isinstance(layout.get("checkpoints"), list):
        raise HTTPException(400, "checkpoints 배열이 필요합니다")
    f["layout"] = layout
    db.upsert_festival(f)
    return {"ok": True}


@app.get("/api/layout/{fid}")
def get_layout(fid: str, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    f = _festival(fid)
    _guard(f, x_admin_key, x_event_key)
    layout = f.get("layout")
    if not layout:
        raise HTTPException(404, "저장된 배치가 없습니다")
    cur = _stats(f, f["edition"])
    return {**layout, "drop_prob": {c["id"]: round(c["drop_rate"] / 100, 3) for c in cur["checkpoints"]}}


@app.get("/api/intervals/{fid}")
def get_intervals(fid: str, x_admin_key: str = Header(default=""), x_event_key: str = Header(default="")):
    """스캔 로그로 거점 사이 실측 이동시간을 구한다. 줄 선 시간이 섞이므로 하위 25% 값을 쓴다."""
    f = _festival(fid)
    _guard(f, x_admin_key, x_event_key)
    by_sess = {}
    for s in _real(db.scans_for(f["id"], f["edition"])):
        by_sess.setdefault(s["session"], []).append(s)
    pairs = {}
    for rows in by_sess.values():
        rows.sort(key=lambda s: s["ts"])
        for a, b in zip(rows, rows[1:]):
            if a["checkpoint"] == b["checkpoint"]:
                continue
            dt = (datetime.fromisoformat(b["ts"]) - datetime.fromisoformat(a["ts"])).total_seconds()
            if 0 < dt < 3 * 3600:
                pairs.setdefault(f'{a["checkpoint"]}>{b["checkpoint"]}', []).append(dt)
    out = {}
    for k, v in pairs.items():
        v.sort()
        out[k] = {"n": len(v), "p25_sec": round(v[max(0, int(len(v) * 0.25) - 1)] if len(v) >= 4 else v[0], 1)}
    return out


@app.get("/api/health")
def health():
    return {"ok": True, "store": db.kind, "llm": ai.llm_provider()}


# ---------- 시연용 예시 데이터 ----------
DEMO_ID = "demo"
DEMO_CPS = [
    {"id": "gate", "name": "입구 안내소", "x": 10, "y": 80},
    {"id": "market", "name": "먹거리 장터", "x": 30, "y": 55},
    {"id": "stage", "name": "메인 무대", "x": 55, "y": 70},
    {"id": "craft", "name": "체험 부스", "x": 75, "y": 35},
    {"id": "view", "name": "전망대", "x": 90, "y": 12},
]

# 격자 1칸 = 1m. capacity·service_sec는 운영자 추정값(실측 전)
DEMO_LAYOUT = {
    "id": "demo-plan-a", "grid": {"w": 100, "h": 100, "cell_m": 1},
    "entrance": "gate",
    "checkpoints": [
        {"id": "gate", "name": "입구 안내소", "x": 10, "y": 80, "type": "info", "capacity": 20, "service_sec": 30},
        {"id": "market", "name": "먹거리 장터", "x": 30, "y": 55, "type": "booth", "capacity": 40, "service_sec": 300},
        {"id": "stage", "name": "메인 무대", "x": 55, "y": 70, "type": "stage", "capacity": 150, "service_sec": 900},
        {"id": "craft", "name": "체험 부스", "x": 75, "y": 35, "type": "booth", "capacity": 15, "service_sec": 420},
        {"id": "view", "name": "전망대", "x": 90, "y": 12, "type": "spot", "capacity": 30, "service_sec": 180},
    ],
    "route": ["gate", "market", "stage", "craft", "view"],
    "blocked": [],
    "estimated": True,
}


def _seed_edition(edition, keep_prob, reasons, survey, n=320, seed=0):
    """survey: (응답 비율, 혼잡도 분포, 동선 분포, 만족도 분포, 재방문 분포) — 가중치 목록"""
    rnd = random.Random(seed)
    day = datetime(2025 + edition - 1, 10, 11, 10, tzinfo=timezone.utc)
    for i in range(n):
        sess = f"demo{edition}-{i:04d}"
        t = day + timedelta(minutes=rnd.randint(0, 420))
        for j, cp in enumerate(DEMO_CPS):
            if j > 0 and rnd.random() > keep_prob[j - 1]:
                db.add_response({"kind": "exit", "festival": DEMO_ID, "checkpoint": DEMO_CPS[j - 1]["id"],
                                 "session": sess, "reason": rnd.choices(list(reasons), weights=list(reasons.values()))[0],
                                 "comment": "", "edition": edition, "ts": t.isoformat()})
                break
            db.add_scan({"festival": DEMO_ID, "checkpoint": cp["id"], "session": sess, "event": "visit",
                         "edition": edition, "ts": t.isoformat()})
            t += timedelta(minutes=rnd.randint(3, 15))  # 이동 + 부스 이용 시간이 섞인 간격
        else:  # 완주한 방문객 중 일부가 설문에 답한다
            rate, crowd_w, route_w, sat_w, rev_w = survey
            if rnd.random() < rate:
                pick = lambda w: rnd.choices([1, 2, 3, 4, 5], weights=w)[0]
                db.add_response({"kind": "survey", "festival": DEMO_ID, "session": sess, "crowd": pick(crowd_w),
                                 "route": pick(route_w), "compare": "", "satisfaction": pick(sat_w),
                                 "revisit": rnd.choices(["오고 싶다", "모르겠다", "아니다"], weights=rev_w)[0],
                                 "comment": "", "edition": edition, "ts": t.isoformat()})


@app.post("/api/demo/seed")
def seed_demo():
    """예시 데이터(실측 아님). 작년(1회차)과 올해(2회차)를 만든다."""
    db.upsert_festival({"id": DEMO_ID, "name": "예시 축제 (시연용 가상 데이터)", "edition": 2,
                        "demo": True, "checkpoints": DEMO_CPS, "layout": DEMO_LAYOUT})
    db.clear_festival(DEMO_ID)
    _seed_edition(1, [0.9, 0.85, 0.55, 0.8], {"화장실·편의시설 부족": 5, "대기 줄이 김": 2, "다음 장소가 멀다": 3},
                  (0.6, [1, 2, 3, 4, 3], [2, 4, 4, 3, 1], [1, 2, 4, 4, 2], [5, 4, 2]), seed=1)
    _seed_edition(2, [0.9, 0.87, 0.78, 0.82], {"대기 줄이 김": 4, "다음 장소가 멀다": 2, "화장실·편의시설 부족": 1},
                  (0.6, [1, 3, 4, 3, 1], [1, 2, 4, 4, 3], [1, 1, 3, 5, 4], [7, 3, 1]), seed=2)
    return {"ok": True, "festival": DEMO_ID}


# ---------- 화면 ----------
def _page(name):
    return FileResponse(os.path.join(STATIC, name))


@app.get("/s/{fid}/{token}")
def visitor_page(fid: str, token: str):
    return _page("visit.html")


@app.get("/my")
def my_page():
    return _page("my.html")


@app.get("/sim")
def sim_page():
    return _page("sim.html")


@app.get("/editor")
def editor_page():
    return _page("editor.html")


@app.get("/admin")
def admin_page():
    return _page("admin.html")


@app.get("/admin/events")
def events_page():
    return _page("events.html")


@app.get("/admin/qr")
def qr_page():
    return _page("qr.html")


@app.get("/admin/logs")
def logs_page():
    return _page("logs.html")


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
