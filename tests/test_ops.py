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
    assert d["staff"]["checked_in"] == 5 and d["sales"]["total"] == 4460000 and d["comments"]["total"] > 0
    assert c.post("/api/staff/check", json={"festival": "demo", "name": "운영요원 F", "action": "in"}).json()["ok"]
    c.post("/api/sales", json={"festival": "demo", "booth": "기념품", "day": 2, "amount": 100})
    c.post("/api/sales", json={"festival": "demo", "booth": "기념품", "day": 2, "amount": 610000})
    assert c.post("/api/receipts", json={"festival": "demo", "desc": "무대 조명 추가 임차", "amount": 350000}).json()["category"] == "외주비"
    d = c.get("/api/ops/demo").json()
    assert d["staff"]["checked_in"] == 6
    assert d["sales"]["total"] == 4460000 + 610000  # 같은 부스·같은 날은 마지막 값
    assert d["receipts"]["rows"][0]["desc"] == "무대 조명 추가 임차"
    after = c.get("/api/stats/demo").json()["current"]
    assert (before["visitors"], before["completion_rate"], before["survey"]["count"]) == (after["visitors"], after["completion_rate"], after["survey"]["count"])


def test_pages_and_estimate_api():
    for u in ("/demo", "/demo-prev", "/staff"):
        assert c.get(u).status_code == 200
    assert "행사 전 · 준비" in c.get("/demo").text
    assert c.get("/api/estimate/demo?visitors=400&days=2").json()["basis"]["checkpoints"] == 5
