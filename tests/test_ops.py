from fastapi.testclient import TestClient

from app import ops
from app.main import app

c = TestClient(app)


def test_receipt_rules():
    assert ops.classify_receipt("현수막 인쇄")[0] == "재료비"
    assert ops.classify_receipt("음향 장비 렌탈")[0] == "외주비"
    assert ops.classify_receipt("스태프 도시락")[0] == "식비"
    assert ops.classify_receipt("현장 잡비") == ("미분류", "")


def test_comment_topics_count_only_given_text():
    d = ops.summarize_comments(["줄이 길어요", "", "화장실 부족", "줄 서다 지침", "그냥 그랬어요"])
    assert d["total"] == 4 and d["unmatched"] == 1
    assert d["topics"][0] == {"topic": "대기·줄", "count": 2, "examples": ["줄이 길어요", "줄 서다 지침"]}


def test_estimate_adds_up():
    d = ops.estimate(5, 400, 2, 50.0)
    assert d["rows"][2]["amount"] == 200 * 3000
    assert d["total"] == sum(r["amount"] for r in d["rows"])


def test_ops_flow_and_stats_unchanged():
    c.post("/api/demo/seed")
    before = c.get("/api/stats/demo").json()["current"]
    d = c.get("/api/ops/demo").json()
    assert d["staff"]["checked_in"] == 5 and d["sales"]["total"] == 5850000 and d["comments"]["total"] > 0
    assert c.post("/api/staff/check", json={"festival": "demo", "name": "운영요원 F", "action": "in"}).json()["ok"]
    c.post("/api/sales", json={"festival": "demo", "booth": "기념품 가게", "day": 2, "amount": 100})
    c.post("/api/sales", json={"festival": "demo", "booth": "기념품 가게", "day": 2, "amount": 610000})
    assert c.post("/api/receipts", json={"festival": "demo", "desc": "무대 조명 추가 임차", "amount": 350000}).json()["category"] == "외주비"
    d = c.get("/api/ops/demo").json()
    assert d["staff"]["checked_in"] == 6
    assert d["sales"]["total"] == 5850000 + 610000  # 같은 부스·같은 날은 마지막 값
    assert d["sales"]["achievement"] == 64.6 and d["sales"]["per_visitor"] == round(6460000 / before["visitors"])
    assert [m["booths"] for m in d["sales"]["missing"]][1] == ["먹거리 1호", "먹거리 2호", "분식 코너", "체험 공방", "전망대 카페"]
    assert d["sales"]["zones"][0]["zone"] == "먹거리 장터"
    assert d["receipts"]["rows"][0]["desc"] == "무대 조명 추가 임차"
    after = c.get("/api/stats/demo").json()["current"]
    assert (before["visitors"], before["completion_rate"], before["survey"]["count"]) == (after["visitors"], after["completion_rate"], after["survey"]["count"])


def test_pages_and_estimate_api():
    for u in ("/demo", "/demo-prev", "/staff"):
        assert c.get(u).status_code == 200
    assert "행사 전 · 준비" in c.get("/demo").text
    assert c.get("/api/estimate/demo?visitors=400&days=2").json()["basis"]["checkpoints"] == 5


def test_plan_numbers_come_from_last_edition():
    c.post("/api/demo/seed")
    cur = c.get("/api/stats/demo").json()["current"]
    d = c.get("/api/plan/demo?visitors=400&days=2&mode=template").json()
    p = d["plan"]
    assert p["checkpoints"][0]["expected"] == round(400 * cur["checkpoints"][0]["visitors"] / cur["visitors"])
    assert p["prizes"] == round(400 * p["target_completion"] / 100)
    assert d["estimate"]["basis"]["staff"] == p["staff_total"] and d["explanation"]["source"] == "template"


def test_demo_crowd_is_realistic_and_keeps_stats():
    c.post("/api/demo/seed")
    before = c.get("/api/stats/demo").json()["current"]
    c.post("/api/demo/live")
    sp = c.get("/api/spread/demo").json()
    assert not sp["active"] and min(r["actual"] for r in sp["rows"]) >= 14
    c.post("/api/demo/crowd")
    sp = c.get("/api/spread/demo").json()
    stage = next(r for r in sp["rows"] if r["id"] == "stage")
    assert sp["active"] and stage["actual"] == 96 and sp["acceptance"]["issued"] == 38 and sp["acceptance"]["accepted"] == 13
    after = c.get("/api/stats/demo").json()["current"]
    assert (before["visitors"], before["completed"]) == (after["visitors"], after["completed"])


def test_report_has_ops_section():
    c.post("/api/demo/seed")
    d = c.post("/api/report/demo?mode=template").json()
    assert len(d["sections"]) == 6 and "6. 현장 운영 및 상권 성과" in d["text"] and "5,850,000원" in d["text"]


def test_call_flow_keeps_stats():
    c.post("/api/demo/seed")
    before = c.get("/api/stats/demo").json()["current"]
    n0 = c.get("/api/ops/demo").json()["calls"]["total"]
    assert n0 == 7
    cid = c.post("/api/call", json={"festival": "demo", "token": "craft", "reason": "경품 문의"}).json()["id"]
    assert any(x["id"] == cid and x["status"] == "대기" for x in c.get("/api/calls/demo").json()["calls"])
    assert c.post("/api/call/act", json={"festival": "demo", "id": "nope0000", "name": "A", "action": "accept"}).status_code == 404
    assert c.post("/api/call/act", json={"festival": "demo", "id": cid, "name": "운영요원 B", "action": "accept"}).status_code == 200
    calls = c.get("/api/ops/demo").json()["calls"]
    row = next(x for x in calls["rows"] if x["id"] == cid)
    assert calls["total"] == n0 + 1 and row["status"] == "이동 중" and row["by"] == "운영요원 B" and row["wait_sec"] is not None
    after = c.get("/api/stats/demo").json()["current"]
    assert (before["visitors"], before["completion_rate"]) == (after["visitors"], after["completion_rate"])
