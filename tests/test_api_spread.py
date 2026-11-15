import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)


def test_spread_flow_recommend_accept_report_and_verify():
    assert c.post("/api/demo/seed").json()["ok"]
    assert c.get("/api/spread/demo").json()["active"] is False
    first = c.post("/api/scan", json={"festival": "demo", "token": "gate", "session": "demoT-0001"}).json()
    assert first["recommend"] is None  # 쏠림이 없으면 추천하지 않는다
    c.post("/api/demo/crowd?cp=stage&n=36")
    st = c.get("/api/spread/demo").json()
    assert st["active"] and st["activations"] == 1 and st["staff_text"]
    r = c.post("/api/scan", json={"festival": "demo", "token": "gate", "session": "demoT-0002"}).json()
    rec = r["recommend"]
    assert rec and rec["id"] != "stage"
    again = c.post("/api/scan", json={"festival": "demo", "token": "gate", "session": "demoT-0002"}).json()
    assert again["recommend"]["id"] == rec["id"]  # 새로고침해도 같은 추천, 기록은 한 번만
    assert c.get("/api/spread/demo").json()["acceptance"]["issued"] == 1
    assert c.get("/api/spread/demo").json()["acceptance"]["accepted"] == 0
    got = c.post("/api/scan", json={"festival": "demo", "token": rec["id"], "session": "demoT-0002"}).json()
    assert got["tickets"] == 1
    assert c.get("/api/spread/demo").json()["acceptance"]["accepted"] == 1
    text = c.post("/api/report/demo?mode=template").json()["text"]
    assert "분산 유도는 1회 작동" in text
    n = c.get("/api/stats/demo").json()["current"]["visitors"]
    ok = c.post("/api/verify/demo", json={"text": f"참여 인원은 {n}명임."}).json()
    assert ok["ok"] and ok["checked"] == 1
    bad = c.post("/api/verify/demo", json={"text": "참여 인원은 777명임."}).json()
    assert not bad["ok"] and 777.0 in bad["bad"]


def test_home2_page_served():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/home2")
    assert r.status_code == 200 and "예비 창업팀" in r.text
    assert c.get("/img/ops-hero.png").status_code == 200


def test_root_is_new_home():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert "예비 창업팀" in c.get("/").text
    assert c.get("/home-old").status_code == 200
