"""분산 유도: 거점별 '예상 대비 실제' 인원을 보고, 쏠림이 있으면 한산한 거점을 추천한다.
안전 통제가 아니라 안내다. 효과는 증명되지 않았고, 첫 행사에서 추천 수락률을 측정한다.
계산은 전부 코드가 하고 AI는 쓰지 않는다. 기준값은 가정이며 상수로 분리해 두었다."""

RATIO_ON = 1.5    # 실제가 예상의 1.5배 이상이면 '혼잡'(빨강)
RATIO_OFF = 1.2   # 한 번 켜진 뒤에는 1.2배 아래로 내려와야 꺼진다 (깜빡임 방지)
MIN_N = 8         # 최근 구간 방문자가 이 수 미만이면 혼잡으로 보지 않는다 (표본이 너무 작을 때)
CALM_RATIO = 0.7  # 예상의 0.7배 이하면 '한산'(파랑), 추천 후보
BIG_RATIO = 2.5   # 이 이상이면 인력 재배치 제안을 2명, 아니면 1명 (가정 규칙)


def measure(cps, recent, was_active=False):
    """cps: [{id, name}] 코스 순서. recent: {거점 id: 최근 구간에 찍은 방문자 수}.
    예상 = 최근 구간 전체 스캔 수를 거점 수로 균등 배분 (모든 참가자가 모든 거점을 돌도록 설계된 코스라는 가정)."""
    counts = {c["id"]: int(recent.get(c["id"], 0)) for c in cps}
    total = sum(counts.values())
    expected = total / len(cps) if cps else 0.0
    on_at = RATIO_OFF if was_active else RATIO_ON
    rows = []
    for c in cps:
        n = counts[c["id"]]
        ratio = round(n / expected, 2) if expected else None
        if ratio is not None and n >= MIN_N and ratio >= on_at:
            level = "hot"
        elif ratio is not None and ratio <= CALM_RATIO:
            level = "cold"
        else:
            level = "ok"
        rows.append({"id": c["id"], "name": c["name"], "actual": n, "expected": round(expected, 1),
                     "ratio": ratio, "level": level})
    active = any(r["level"] == "hot" for r in rows)
    return {"rows": rows, "active": active, "staff": staff_moves(rows) if active else []}


def staff_moves(rows):
    """같은 신호로 보조 인력 재배치를 제안한다. 법정 배치 인력은 건드리지 않는다는 전제의 '제안'일 뿐 자동 실행이 아니다."""
    cold = sorted((r for r in rows if r["level"] == "cold"), key=lambda r: r["ratio"])
    out = []
    for r in sorted((r for r in rows if r["level"] == "hot"), key=lambda r: -r["ratio"]):
        if not cold:
            break
        src = cold[len(out) % len(cold)]
        n = 2 if r["ratio"] >= BIG_RATIO else 1
        out.append({"to": r["id"], "to_name": r["name"], "from": src["id"], "from_name": src["name"], "n": n})
    return out


def recommend(rows, done):
    """방금 찍은 사람에게 줄 다음 거점: 아직 안 찍은 한산한 거점 중 비율이 가장 낮은 곳 (같으면 코스 순서)."""
    best = None
    for r in rows:
        if r["level"] == "cold" and r["id"] not in done:
            if best is None or r["ratio"] < best["ratio"]:
                best = r
    return best


def acceptance(recs, scans):
    """추천(rec)을 받은 뒤 같은 사람이 추천 거점을 실제로 찍었으면 수락. 둘 다 기록에서만 센다."""
    by_sess = {}
    for s in scans:
        by_sess.setdefault(s["session"], []).append(s)
    accepted = 0
    per = {}
    for r in recs:
        ok = any(s["checkpoint"] == r["to"] and s["ts"] >= r["ts"] for s in by_sess.get(r["session"], []))
        accepted += ok
        p = per.setdefault(r["to"], [0, 0])
        p[0] += 1
        p[1] += ok
    issued = len(recs)
    return {"issued": issued, "accepted": accepted,
            "rate": round(accepted / issued * 100, 1) if issued else None,
            "per_checkpoint": {k: {"issued": v[0], "accepted": v[1]} for k, v in per.items()}}


def summarize(logs, recs, scans):
    """결과보고서에 들어갈 숫자: 발동 횟수와 수락률."""
    return {"activations": sum(1 for x in logs if x.get("on")), **acceptance(recs, scans)}


def _ro(name):
    """받침이 없거나 ㄹ 받침이면 '로', 아니면 '으로'."""
    ch = name[-1] if name else ""
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        return "로" if jong in (0, 8) else "으로"
    return "(으)로"


def staff_text(m):
    return f"'{m['to_name']}'{_ro(m['to_name'])} 보조 인력 {m['n']}명 이동 제안 ('{m['from_name']}' 쪽에서)"

