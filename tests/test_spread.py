import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import spread  # noqa: E402

CPS = [{"id": c, "name": n} for c, n in [("a", "입구"), ("b", "장터"), ("c", "무대"), ("d", "체험"), ("e", "전망대")]]


def test_no_scans_means_no_guidance():
    m = spread.measure(CPS, {})
    assert not m["active"] and all(r["level"] == "ok" for r in m["rows"])


def test_crowd_turns_on_and_marks_cold():
    m = spread.measure(CPS, {"c": 36, "a": 1})
    lv = {r["id"]: r["level"] for r in m["rows"]}
    assert m["active"] and lv["c"] == "hot" and lv["b"] == "cold"


def test_small_sample_is_not_crowd():
    m = spread.measure(CPS, {"c": 5})  # 예상 1.0의 5배지만 8명 미만
    assert not m["active"]


def test_hysteresis_keeps_guidance_until_below_off_ratio():
    counts = {"a": 8, "b": 8, "c": 14, "d": 8, "e": 8}  # c는 평균 9.2의 1.52배→곧바로 켜짐
    assert spread.measure(CPS, counts)["active"]
    counts["c"] = 11  # 1.2배 이상이라 이미 켜져 있으면 유지, 꺼져 있었다면 켜지지 않음
    assert spread.measure(CPS, counts, was_active=True)["active"]
    assert not spread.measure(CPS, counts, was_active=False)["active"]


def test_recommend_skips_done_and_hot():
    m = spread.measure(CPS, {"c": 36})
    pick = spread.recommend(m["rows"], {"a", "b"})
    assert pick["id"] in ("d", "e")
    assert spread.recommend(m["rows"], {"a", "b", "d", "e"}) is None  # 남은 곳이 혼잡뿐이면 추천하지 않음


def test_staff_moves_and_korean_particle():
    m = spread.measure(CPS, {"c": 36})
    assert m["staff"][0]["to"] == "c" and m["staff"][0]["n"] == 2
    assert "'무대'로 보조 인력 2명" in spread.staff_text(m["staff"][0])
    assert spread._ro("정문") == "으로" and spread._ro("장터") == "로" and spread._ro("물") == "로"


def test_acceptance_counts_only_scans_after_recommendation():
    recs = [{"session": "s1", "to": "d", "ts": "2026-11-15T10:00:00"}, {"session": "s2", "to": "d", "ts": "2026-11-15T10:00:00"},
            {"session": "s3", "to": "e", "ts": "2026-11-15T10:00:00"}]
    scans = [{"session": "s1", "checkpoint": "d", "ts": "2026-11-15T10:05:00"},
             {"session": "s2", "checkpoint": "d", "ts": "2026-11-15T09:00:00"}]  # 추천 전에 찍은 것은 수락이 아님
    a = spread.acceptance(recs, scans)
    assert (a["issued"], a["accepted"], a["rate"]) == (3, 1, 33.3)
    assert spread.acceptance([], [])["rate"] is None
