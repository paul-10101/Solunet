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

    reasons = Counter(r.get("reason", "기타") for r in responses)
    hours = Counter(s["ts"][11:13] for s in scans if isinstance(s.get("ts"), str))

    return {
        "visitors": visitors,
        "completed": completed,
        "completion_rate": round(completed / visitors * 100, 1) if visitors else 0.0,
        "scans": len(scans),
        "responses": len(responses),
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
    return {
        "visitors_prev": prev["visitors"], "visitors_cur": cur["visitors"],
        "completion_prev": prev["completion_rate"], "completion_cur": cur["completion_rate"],
        "checkpoints": rows,
    }
