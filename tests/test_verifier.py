import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import ai  # noqa: E402

DATA = {"participants": 320, "completed": 240, "rate": 75.0, "name": "예시축제 2회차"}


def test_grounded_sentence_passes():
    assert ai._bad_numbers("참여 320명 중 240명이 완주함. 완주율 75%임.", DATA) == []


def test_invented_number_rejected():
    assert ai._bad_numbers("완주율은 82%임.", DATA) == [82.0]


def test_derived_number_rejected():
    assert 80.0 in ai._bad_numbers("80명이 이탈함.", DATA)


def test_formatting_variants_equal():
    assert ai._bad_numbers("참여 320.0명, 1,000이 아님", {"a": 320, "b": 1000}) == []


def test_small_ordinals_allowed():
    assert ai._bad_numbers("1. 행사 개요 2. 집계 3개 항목", {}) == []


def test_draft_falls_back_without_llm(monkeypatch=None):
    for k in ("GITHUB_MODELS_TOKEN", "ANTHROPIC_API_KEY"):
        os.environ.pop(k, None)
    r = ai._draft("s", DATA, lambda: "틀 문장")
    assert r["source"] == "template" and r["reason"] == "no_llm"


def test_verify_trial_shape():
    t = ai.verify_trial()
    assert [c["ok"] for c in t["cases"]] == [True, False, False]
