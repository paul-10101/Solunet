

def test_home2_page_served():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/home2")
    assert r.status_code == 200 and "예비 창업팀" in r.text
    assert c.get("/img/ops-hero.png").status_code == 200
