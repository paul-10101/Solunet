"""현장 운영 기록: 인력 출퇴근, 부스별 매출, 영수증 정산 분류, 자유 응답 요약, 산출내역 초안.
모두 규칙·산식으로 계산한다(AI 호출 없음). 단가와 분류 규칙은 가정값이며 담당자가 고친다."""
from datetime import datetime

KINDS = ("ops_staff", "ops_sales", "ops_receipt")

RECEIPT_RULES = [
    ("식비", ["식대", "도시락", "생수", "다과", "커피", "간식"]),
    ("인건비", ["인건비", "일당", "알바", "아르바이트", "스태프", "요원", "수당", "급여"]),
    ("외주비", ["무대", "음향", "조명", "출연", "섭외", "설치", "렌탈", "임차", "천막", "발전기"]),
    ("재료비", ["인쇄", "현수막", "배너", "경품", "기념품", "스탬프", "용지", "문구", "명찰"]),
    ("운송·교통", ["운송", "택배", "주유", "주차", "버스", "화물", "퀵"]),
    ("홍보비", ["광고", "홍보", "포스터", "촬영", "영상"]),
    ("보험·안전", ["보험", "구급", "안전", "경비", "소화기"]),
]

COMMENT_TOPICS = [
    ("대기·줄", ["줄", "대기", "기다"]),
    ("화장실·편의시설", ["화장실", "쉼터", "의자", "그늘", "쉴 곳", "편의"]),
    ("안내·표지", ["안내", "표지", "찾기", "헷갈", "지도"]),
    ("동선·거리", ["멀", "동선", "걷", "이동"]),
    ("먹거리", ["음식", "먹거리", "맛", "비싸", "가격"]),
    ("좋았던 점", ["좋았", "좋아", "재미", "재밌", "친절", "만족", "최고"]),
]


def classify_receipt(desc):
    """내역 문구에 든 낱말로 비목을 고른다. 맞는 낱말이 없으면 '미분류'로 남겨 담당자가 정한다."""
    for cat, words in RECEIPT_RULES:
        for w in words:
            if w in desc:
                return cat, w
    return "미분류", ""


def summarize_receipts(rows):
    cats = {}
    for r in rows:
        c = cats.setdefault(r["category"], {"category": r["category"], "count": 0, "amount": 0})
        c["count"] += 1
        c["amount"] += r["amount"]
    order = [c for c, _ in RECEIPT_RULES] + ["미분류"]
    return {"rows": sorted(rows, key=lambda r: r["ts"], reverse=True),
            "by_category": sorted(cats.values(), key=lambda c: order.index(c["category"])),
            "total": sum(r["amount"] for r in rows),
            "unclassified": sum(1 for r in rows if r["category"] == "미분류")}


def summarize_staff(rows):
    """이름별 첫 출근과 마지막 퇴근. 근무 시간은 둘 다 있을 때만 계산한다."""
    people = {}
    for r in sorted(rows, key=lambda r: r["ts"]):
        p = people.setdefault(r["name"], {"name": r["name"], "in": None, "out": None})
        if r["action"] == "in" and p["in"] is None:
            p["in"] = r["ts"]
        if r["action"] == "out":
            p["out"] = r["ts"]
    out = []
    for p in people.values():
        hours = None
        if p["in"] and p["out"] and p["out"] > p["in"]:
            hours = round((datetime.fromisoformat(p["out"]) - datetime.fromisoformat(p["in"])).total_seconds() / 3600, 1)
        out.append({**p, "hours": hours, "on_site": bool(p["in"]) and not (p["out"] and p["out"] > p["in"])})
    out.sort(key=lambda p: p["in"] or "")
    return {"people": out, "checked_in": sum(1 for p in out if p["in"]), "on_site": sum(1 for p in out if p["on_site"]),
            "hours": round(sum(p["hours"] or 0 for p in out), 1)}


def summarize_sales(rows, booths=None, target=None, visitors=0, cp_visits=None, cp_names=None):
    """부스·일자별 매출과 성과 지표. 같은 부스·같은 날을 다시 입력하면 마지막 값으로 바꾼다.
    booths: 등록 부스 [{name, zone}] (있으면 미제출 부스와 구역별 지표를 낸다). target: 과업의 매출 목표.
    cp_visits: {거점 id: 방문 인원}. 구역 매출을 그 구역 거점의 QR 방문 인원으로 나눠 '방문 1명당 매출'을 낸다."""
    cell = {}
    for r in sorted(rows, key=lambda r: r["ts"]):
        cell[(r["booth"], r["day"])] = r["amount"]
    days = sorted({d for _, d in cell})
    reg = {b["name"]: b.get("zone") for b in (booths or [])}
    names = list(reg) + sorted({b for b, _ in cell} - set(reg))
    table = [{"booth": b, "zone": (cp_names or {}).get(reg.get(b)), "days": [cell.get((b, d)) for d in days],
              "total": sum(cell.get((b, d)) or 0 for d in days)} for b in names]
    table.sort(key=lambda r: r["total"], reverse=True)
    day_totals = [sum(cell.get((b, d)) or 0 for b in names) for d in days]
    total = sum(cell.values())
    out = {"days": days, "booths": table, "day_totals": day_totals, "total": total,
           "registered": len(reg) or None, "target": target,
           "achievement": round(total / target * 100, 1) if target else None,
           "per_visitor": round(total / visitors) if visitors and total else None, "visitors": visitors,
           "day_change": round((day_totals[-1] - day_totals[-2]) / day_totals[-2] * 100, 1) if len(days) >= 2 and day_totals[-2] else None,
           "missing": [{"day": d, "booths": [b for b in reg if (b, d) not in cell]} for d in days if reg],
           "zones": []}
    if reg and cp_visits:
        z = {}
        for b in names:
            if reg.get(b):
                z[reg[b]] = z.get(reg[b], 0) + sum(cell.get((b, d)) or 0 for d in days)
        out["zones"] = sorted(({"zone": (cp_names or {}).get(k, k), "sales": v, "visits": cp_visits.get(k, 0),
                                "per_visit": round(v / cp_visits[k]) if cp_visits.get(k) else None} for k, v in z.items()),
                              key=lambda r: r["per_visit"] or 0, reverse=True)
    return out


def summarize_comments(comments):
    """자유 응답을 낱말 규칙으로 주제별로 센다. 요약 문장을 지어내지 않고 건수와 원문 예시만 보여 준다."""
    texts = [c.strip() for c in comments if c and c.strip()]
    topics, unmatched = [], 0
    hit = [False] * len(texts)
    for name, words in COMMENT_TOPICS:
        idx = [i for i, t in enumerate(texts) if any(w in t for w in words)]
        for i in idx:
            hit[i] = True
        if idx:
            topics.append({"topic": name, "count": len(idx), "examples": list(dict.fromkeys(texts[i] for i in idx))[:2]})
    unmatched = hit.count(False)
    topics.sort(key=lambda t: t["count"], reverse=True)
    return {"total": len(texts), "topics": topics, "unmatched": unmatched}


# 산출내역 초안의 단가 (가정값). 화면에 '가정'으로 표시하고 담당자가 고친다.
UNIT = {"qr_board": 15000, "staff_day": 82560, "prize": 3000, "solunet": 900000, "overhead": 0.06, "profit": 0.05}


def estimate(n_checkpoints, visitors, days, completion_rate, staff=None, prizes=None):
    """QR 참여형 프로그램의 산출내역 초안. 수량은 기초 설계(거점 수·안내 인력·경품 수량)에서, 단가는 가정값에서 온다."""
    staff = staff or n_checkpoints
    done = prizes if prizes is not None else round(visitors * completion_rate / 100)
    rows = [
        {"item": "QR 안내판 제작", "group": "재료비", "formula": f"거점 {n_checkpoints}곳 × {UNIT['qr_board']:,}원",
         "amount": n_checkpoints * UNIT["qr_board"]},
        {"item": "거점 안내 요원", "group": "인건비",
         "formula": f"{staff}명 × {days}일 × {UNIT['staff_day']:,}원 (2026년 최저임금 8시간)",
         "amount": staff * days * UNIT["staff_day"]},
        {"item": "완주 경품", "group": "재료비",
         "formula": f"참가 {visitors:,}명 × 목표 완주율 {completion_rate}% = {done:,}개 × {UNIT['prize']:,}원",
         "amount": done * UNIT["prize"]},
        {"item": "QR 집계·보고 시스템 이용료", "group": "외주비", "formula": "스탠다드 1건 (부가세 포함)",
         "amount": UNIT["solunet"]},
    ]
    direct = sum(r["amount"] for r in rows)
    over = round(direct * UNIT["overhead"])
    profit = round((direct + over) * UNIT["profit"])
    rows += [{"item": "일반관리비", "group": "판관비", "formula": f"직접비 {direct:,}원 × 6%", "amount": over},
             {"item": "이윤", "group": "이윤", "formula": "(직접비 + 일반관리비) × 5%", "amount": profit}]
    return {"rows": rows, "direct": direct, "total": direct + over + profit,
            "basis": {"checkpoints": n_checkpoints, "visitors": visitors, "days": days, "completion_rate": completion_rate,
                      "staff": staff, "prizes": done}}
