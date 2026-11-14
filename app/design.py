"""다음 회차 설계안: 규칙 기반으로 '무엇을 바꿀지'를 정하고, 근거 데이터를 붙인다.
AI는 이 결과를 설명하는 문장만 쓴다 (ai.py)."""

DROP_ALERT = 20.0  # 이 거점 이후 이탈률(%)이 이보다 높으면 개선 대상 (가정값, 실증으로 조정)


def propose(stats):
    changes = []
    reasons = stats.get("exit_reasons", {})
    top_reason = next(iter(reasons), None)

    for c in stats["checkpoints"]:
        if c["drop_rate"] >= DROP_ALERT:
            action = "다음 거점까지 동선 단축 또는 중간 휴게·안내 지점 추가"
            if top_reason and "화장실" in top_reason:
                action = "이 거점 인근에 화장실·편의시설 배치"
            elif top_reason and ("대기" in top_reason or "줄" in top_reason):
                action = "이 거점 부스 분산 + 줄 관리 인력 배치"
            elif top_reason and ("멀" in top_reason or "거리" in top_reason):
                action = "다음 거점을 더 가까운 위치로 이동"
            changes.append({
                "checkpoint": c["name"],
                "action": action,
                "evidence": f"방문 {c['visitors']}명 중 {c['dropped_after']}명이 이 거점 이후 이탈 ({c['drop_rate']}%)",
            })

    if not changes:
        changes.append({"checkpoint": "전체", "action": "현 동선 유지, 완주 보상 강화 검토",
                        "evidence": f"모든 거점 이탈률이 {DROP_ALERT}% 미만"})
    return {"threshold": DROP_ALERT, "top_exit_reason": top_reason, "changes": changes}


def proposal_basis(festival, cur, comparison, req):
    """제안서 초안에 들어갈 숫자를 전부 여기서 정한다. AI는 이 값으로 문장만 쓴다.
    목표치 규칙: 완주율은 실측 +5%p(최대 100), 만족도는 실측 +0.2(최대 5), 설문 응답률은 실측값 유지 이상."""
    cps = cur["checkpoints"]
    worst = max((c for c in cps if c["dropped_after"] > 0), key=lambda c: c["drop_rate"], default=None)
    sv = cur["survey"]
    sat = round(sv["satisfaction_avg"], 1) if sv.get("satisfaction_avg") else None
    resp_rate = round(sv["count"] / cur["completed"] * 100, 1) if cur["completed"] else None
    b = {
        "title": (req.get("title") or "").strip() or f"{festival['name']} 다음 회차",
        "based_on": {"festival": festival["name"], "edition": festival.get("edition", 1)},
        "expected_visitors": req.get("expected_visitors"), "days": req.get("days"),
        "checkpoint_count": len(cps), "checkpoint_names": [c["name"] for c in cps],
        "measured": {"visitors": cur["visitors"], "completed": cur["completed"], "completion_rate": cur["completion_rate"],
                     "survey_count": sv["count"], "survey_response_rate": resp_rate, "satisfaction_avg": sat,
                     "crowd_avg": sv.get("crowd_avg")},
        "bottleneck": {"name": worst["name"], "drop_rate": worst["drop_rate"]} if worst else None,
        "top_exit_reason": next(iter(cur["exit_reasons"]), None),
        "targets": {"completion_rate": round(min(cur["completion_rate"] + 5, 100), 1),
                    "satisfaction_avg": round(min(sat + 0.2, 5), 1) if sat else None},
        "target_rule": "완주율 = 실측 + 5%p, 만족도 = 실측 + 0.2 (담당자가 조정)",
    }
    if comparison:
        b["trend"] = {"completion_prev": comparison["completion_prev"], "completion_cur": comparison["completion_cur"],
                      "satisfaction_prev": comparison.get("satisfaction_prev"), "satisfaction_cur": comparison.get("satisfaction_cur")}
    return b
