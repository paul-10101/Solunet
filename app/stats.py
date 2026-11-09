"""집계는 전부 코드로 한다. AI는 여기서 나온 숫자만 받는다."""
from collections import Counter, defaultdict


def compute_stats(festival, scans, responses):
    cps = festival["checkpoints"]  # [{id, name, x, y}] 코스 순서대로
    order = [c["id"] for c in cps]
    by_session = defaultdict(set)
    for s in scans:
        by_session[s["session"]].add(s["checkpoint"])

    visitors = len(by_session)
    completed = sum(1 for v in by_session.values() if set(order) <= v)

    per_cp = []
    for i, cid in enumerate(order):
        reached = sum(1 for v in by_session.values() if cid in v)
        nxt = order[i + 1] if i + 1 < len(order) else None
        # 이 거점까지 오고 다음 거점은 안 간 사람 = 이 거점에서 이탈
        dropped = sum(1 for v in by_session.values() if cid in v and nxt and nxt not in v) if nxt else 0
        per_cp.append({
            "id": cid,
            "name": next(c["name"] for c in cps if c["id"] == cid),
            "visitors": reached,
            "dropped_after": dropped,
            "drop_rate": round(dropped / reached * 100, 1) if reached else 0.0,
        })

    exits = [r for r in responses if r.get("reason")]
    surveys = [r for r in responses if r.get("kind") == "survey"]
    reasons = Counter(r["reason"] for r in exits)
    avg = lambda k: round(sum(r[k] for r in surveys) / len(surveys), 2) if surveys else None
    sat = [r["satisfaction"] for r in surveys if r.get("satisfaction")]  # v2 이전 응답은 이 키가 없다
    revisit = Counter(r["revisit"] for r in surveys if r.get("revisit"))
    hours = Counter(s["ts"][11:13] for s in scans if isinstance(s.get("ts"), str))

    return {
        "visitors": visitors,
        "completed": completed,
        "completion_rate": round(completed / visitors * 100, 1) if visitors else 0.0,
        "scans": len(scans),
        "responses": len(exits),
        "survey": {"count": len(surveys), "crowd_avg": avg("crowd"), "route_avg": avg("route"),
                   "compare": dict(Counter(r.get("compare") or "무응답" for r in surveys)),
                   "satisfaction_count": len(sat),
                   "satisfaction_avg": round(sum(sat) / len(sat), 2) if sat else None,
                   "revisit": dict(revisit.most_common())},
        "checkpoints": per_cp,
        "exit_reasons": dict(reasons.most_common()),
        "scans_by_hour": dict(sorted(hours.items())),
    }


def compare(prev, cur):
    """작년(prev) 대비 올해(cur) 변화. 둘 다 compute_stats 결과."""
    if not prev:
        return None
    rows = []
    prev_cp = {c["id"]: c for c in prev["checkpoints"]}
    for c in cur["checkpoints"]:
        p = prev_cp.get(c["id"])
        if p:
            rows.append({"id": c["id"], "name": c["name"],
                         "drop_rate_prev": p["drop_rate"], "drop_rate_cur": c["drop_rate"],
                         "change": round(c["drop_rate"] - p["drop_rate"], 1)})
    revisit_share = lambda s: (round(s["survey"]["revisit"].get("오고 싶다", 0) / sum(s["survey"]["revisit"].values()) * 100, 1)
                               if s["survey"].get("revisit") else None)
    return {
        "visitors_prev": prev["visitors"], "visitors_cur": cur["visitors"],
        "completion_prev": prev["completion_rate"], "completion_cur": cur["completion_rate"],
        "survey_prev": prev["survey"]["count"], "survey_cur": cur["survey"]["count"],
        "satisfaction_prev": prev["survey"].get("satisfaction_avg"), "satisfaction_cur": cur["survey"].get("satisfaction_avg"),
        "crowd_prev": prev["survey"]["crowd_avg"], "crowd_cur": cur["survey"]["crowd_avg"],
        "revisit_prev": revisit_share(prev), "revisit_cur": revisit_share(cur),
        "checkpoints": rows,
    }
