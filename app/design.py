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
