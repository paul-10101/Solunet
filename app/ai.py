"""AI는 코드가 계산한 숫자로 '문장'만 쓴다.
- 문장 속 숫자가 입력 데이터에 없으면 AI 결과를 버리고 템플릿 문장을 쓴다.
- ANTHROPIC_API_KEY가 없으면 템플릿 문장만 쓴다 (시연용 안전장치)."""
import json
import os
import re

import httpx

MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5")


def _nums(s):
    # 50 과 50.0, 1,437 과 1437 을 같은 값으로 본다
    return {round(float(n.replace(",", "")), 2) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


def _numbers_in(obj):
    return _nums(json.dumps(obj, ensure_ascii=False))


def _bad_numbers(text, data):
    allowed = _numbers_in(data) | set(range(0, 11))  # 서수·개수 같은 작은 수 허용
    bad = sorted(_nums(text) - allowed)
    if bad:
        print("LLM grounding rejected numbers:", bad[:10], flush=True)
    return bad


def _grounded(text, data):
    return not _bad_numbers(text, data)


def _draft(system, data, template, use_llm=True):
    """AI 문장을 쓰고 숫자를 대조한다. 결과와 함께 '왜 이 문장이 나왔는지'를 돌려준다.
    reason: None(AI 문장 통과) / no_llm(AI 미연결) / skipped(예비 경로) / rejected(숫자 불일치로 폐기) / error(AI 장애)"""
    reason, rejected = None, []
    if not use_llm:
        reason = "skipped"
    elif not llm_provider():
        reason = "no_llm"
    else:
        try:
            text = _call_llm(system, data)
            rejected = _bad_numbers(text, data) if text else []
            if text and not rejected:
                return {"source": "llm", "text": text, "reason": None, "rejected": []}
            reason = "rejected" if text else "error"
        except Exception as e:  # 시연 중 API 장애가 나도 화면은 유지
            print("LLM error:", _describe(e), flush=True)
            reason = "error"
    return {"source": "template", "text": template(), "reason": reason, "rejected": rejected[:10]}


GH_MODEL = os.getenv("GH_MODEL", "openai/gpt-4.1-mini")


VERIFY_DATA = {"participants": 320, "completed": 240, "completion_rate": 75.0, "top_dropoff": "먹거리 장터", "satisfaction": 4.2}


def verify_text(text):
    """사용자가 입력한 문장을 시험용 집계값과 대조한다 (AI 호출 없음)."""
    text = (text or "")[:400]
    bad = _bad_numbers(text, VERIFY_DATA)
    return {"text": text, "ok": bool(text.strip()) and not bad, "bad": bad, "checked": len(_nums(text)), "empty": not text.strip()}


def verify_trial():
    """AI 없이 숫자 검증기만 시험한다. 문장은 우리가 만든 예시이고, 판정은 실제 검증기가 한다."""
    data = VERIFY_DATA
    cases = [
        ("집계값을 그대로 인용", "참여 320명 중 240명이 완주하여 완주율은 75.0%임. 이탈이 가장 많은 거점은 먹거리 장터임."),
        ("없는 숫자를 지어냄", "참여 320명 중 240명이 완주하여 완주율은 82%임. 만족도는 4.8점으로 매우 높음."),
        ("직접 계산한 값을 씀", "참여 320명 중 240명이 완주하여 80명이 이탈함. 전년 대비 15% 증가함."),
    ]
    out = []
    for label, text in cases:
        bad = _bad_numbers(text, data)
        out.append({"label": label, "text": text, "ok": not bad, "bad": bad, "checked": len(_nums(text))})
    return {"data": data, "cases": out}


def _describe(e):
    """오류를 로그·확인용으로 짧게 요약한다. 토큰 값은 절대 넣지 않는다."""
    if isinstance(e, httpx.HTTPStatusError):
        body = (e.response.text or "")[:300].replace("\n", " ")
        return f"HTTP {e.response.status_code}: {body}"
    return f"{type(e).__name__}: {str(e)[:300]}"


def llm_check():
    """아주 짧은 요청 하나로 AI 연결을 시험한다."""
    p = llm_provider()
    if not p:
        return {"provider": None, "ok": False, "detail": "토큰 없음 (GITHUB_MODELS_TOKEN 또는 ANTHROPIC_API_KEY)"}
    try:
        text = _call_llm("한 단어로만 답하라.", {"q": "안녕"})
        return {"provider": p, "model": GH_MODEL if p == "github" else MODEL, "ok": bool(text), "detail": (text or "")[:40]}
    except Exception as e:
        return {"provider": p, "model": GH_MODEL if p == "github" else MODEL, "ok": False, "detail": _describe(e)}


def llm_provider():
    if os.getenv("GITHUB_MODELS_TOKEN"):
        return "github"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def _call_llm(system, payload):
    provider = llm_provider()
    if provider == "github":  # GitHub 계정만으로 쓰는 무료 추론 API (추가 가입 없음)
        r = httpx.post(
            "https://models.github.ai/inference/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('GITHUB_MODELS_TOKEN')}", "Content-Type": "application/json"},
            json={"model": GH_MODEL, "temperature": 0.3,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
            timeout=60,
        )
        r.raise_for_status()
        try:
            return r.json()["choices"][0]["message"]["content"]
        except Exception:
            ct = r.headers.get("content-type", "")
            raise RuntimeError(f"HTTP {r.status_code} 응답이 JSON 아님 ({ct}, {len(r.content)}바이트): {(r.text or '')[:200]!r}")
    if provider != "anthropic":
        return None
    key = os.getenv("ANTHROPIC_API_KEY")
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 1200, "system": system,
              "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


# 결과보고서 목차: 공공 행사 대행 용역의 결과보고 요구(행사 개요, 관람객 집계, 만족도 조사, 전년 대비, 개선 방안)를 따른다.
# 정산 내역·사진·홍보 실적처럼 QR 기록에 없는 항목은 화면에서 '담당자 작성' 칸으로 남긴다.
REPORT_SECTIONS = ["행사 개요", "방문객 집계 결과", "만족도 조사 결과", "전 회차 대비 성과", "문제점 및 개선 방안"]
REPORT_SYSTEM = (
    "너는 공공 행사 대행 용역의 결과보고서 작성 보조다. 입력 JSON의 숫자만 그대로 사용하고, 더하기·빼기·비율 계산으로 새 숫자를 만들지 마라. "
    "변화량이 필요하면 changes에 있는 값만 쓴다. 금액·예산은 쓰지 마라. "
    "한국어 공문서체(~함, ~임)로 아래 다섯 항목을 번호와 제목 그대로, 항목마다 2~3문장으로 쓴다. 표·기호·마크다운은 쓰지 않는다.\n"
    "1. 행사 개요: 행사명과 회차, QR 기반으로 참가를 확인·집계했다는 점.\n"
    "2. 방문객 집계 결과: 참여, 완주, 완주율, 이탈률이 가장 높은 거점.\n"
    "3. 만족도 조사 결과: 설문 응답 수, 만족도·혼잡도·동선 편의 평균, 재방문 의사. 설문이 없으면 '조사 결과 없음'.\n"
    "4. 전 회차 대비 성과: comparison과 changes의 값. comparison이 없으면 '비교할 이전 회차 없음'.\n"
    "5. 문제점 및 개선 방안: improvements의 각 항목(거점, 조치, 근거)을 문장으로."
)

DESIGN_SYSTEM = (
    "너는 축제 동선 설계 보조다. 입력의 changes 각각에 대해 '무엇을, 왜(근거 데이터)' 바꾸는지 "
    "한국어로 2문장 이내씩 설명하라. 입력에 없는 숫자는 쓰지 마라."
)


def _template_report(festival, stats, comparison, improvements=None):
    worst = max((c for c in stats["checkpoints"] if c["dropped_after"] > 0), key=lambda c: c["drop_rate"], default=None)
    sv = stats.get("survey", {})
    lines = [
        f"1. 행사 개요: 본 보고서는 「{festival['name']}」 {festival.get('edition', 1)}회차의 운영 결과를 정리한 것임. "
        f"참가 확인과 관람객 집계는 거점 {len(stats['checkpoints'])}곳에 설치한 QR로 수행하였으며, 수집한 스캔 기록은 {stats['scans']}건임.",
        f"2. 방문객 집계 결과: 참여 인원은 {stats['visitors']}명, 전 거점 완주 인원은 {stats['completed']}명(완주율 {stats['completion_rate']}%)임."
        + (f" 거점별로는 '{worst['name']}' 이후 이탈률이 {worst['drop_rate']}%로 가장 높게 나타남." if worst else ""),
    ]
    if sv.get("count"):
        t = f"3. 만족도 조사 결과: 완주자 대상 모바일 설문에 {sv['count']}건이 응답함."
        parts = [f"전반 만족도 평균 {sv['satisfaction_avg']}점" if sv.get("satisfaction_avg") else "",
                 f"혼잡도 평균 {sv['crowd_avg']}점" if sv.get("crowd_avg") else "", f"동선 편의 평균 {sv['route_avg']}점" if sv.get("route_avg") else ""]
        parts = [x for x in parts if x]
        if parts:
            t += " " + ", ".join(parts) + "(5점 척도)임."
        rv = sv.get("revisit") or {}
        if rv:
            k = next(iter(rv))
            t += f" 재방문 의사는 '{k}' 응답이 {rv[k]}건으로 가장 많음."
        lines.append(t)
    else:
        lines.append("3. 만족도 조사 결과: 조사 결과 없음.")
    if comparison:
        t = (f"4. 전 회차 대비 성과: 참여 인원은 {comparison['visitors_prev']}명에서 {comparison['visitors_cur']}명으로, "
             f"완주율은 {comparison['completion_prev']}%에서 {comparison['completion_cur']}%로 변동함.")
        if comparison.get("satisfaction_prev") and comparison.get("satisfaction_cur"):
            t += f" 만족도 평균은 {comparison['satisfaction_prev']}점에서 {comparison['satisfaction_cur']}점으로 변동함."
        lines.append(t)
    else:
        lines.append("4. 전 회차 대비 성과: 비교할 이전 회차 없음.")
    imp = improvements or []
    if stats["exit_reasons"]:
        k = next(iter(stats["exit_reasons"]))
        head = f"중도 이탈 사유는 '{k}' 응답이 {stats['exit_reasons'][k]}건으로 가장 많음. "
    else:
        head = ""
    lines.append("5. 문제점 및 개선 방안: " + head + " ".join(f"[{c['checkpoint']}] {c['evidence']}. 개선 방안: {c['action']}." for c in imp))
    return "\n".join(lines)


def _template_design(design):
    return "\n".join(f"- {c['checkpoint']}: {c['action']} (근거: {c['evidence']})" for c in design["changes"])


def write_report(festival, stats, comparison=None, use_llm=True, improvements=None):
    data = {"festival": festival["name"], "edition": festival.get("edition"), "stats": stats, "comparison": comparison,
            "improvements": improvements or []}
    if comparison:  # 모델이 직접 빼기를 하지 않도록 차이를 미리 계산해 넘긴다
        diff = lambda a, b: round(b - a, 1) if a is not None and b is not None else None
        data["changes"] = {k: diff(comparison.get(k + "_prev"), comparison.get(k + "_cur"))
                           for k in ("visitors", "completion", "satisfaction", "revisit", "crowd")}
        data["changes"]["checkpoints"] = {c["name"]: c["change"] for c in comparison["checkpoints"]}
    return _draft(REPORT_SYSTEM, data, lambda: _template_report(festival, stats, comparison, improvements), use_llm)


def explain_design(design):
    try:
        text = _call_llm(DESIGN_SYSTEM, design)
        if text and _grounded(text, design):
            return {"source": "llm", "text": text}
    except Exception as e:
        print("LLM error:", _describe(e), flush=True)
    return {"source": "template", "text": _template_design(design)}


# 제안서 목차: 협상에 의한 계약의 기술 제안서 가운데 기록으로 쓸 수 있는 부분만 쓴다.
# 제안업체 일반 현황, 세부 프로그램·홍보 계획, 추진 일정, 가격 제안서는 화면에서 '담당자 작성' 칸으로 남긴다.
PROPOSAL_SECTIONS = ["제안 개요", "행사 운영 계획", "인력 및 안전관리 계획", "성과 지표 및 목표", "결과 보고 및 사후 관리 계획"]
PROPOSAL_SYSTEM = (
    "너는 행사 대행사의 입찰 제안서(기술 부문) 작성 보조다. 입력 JSON(basis)의 숫자만 그대로 쓰고 새 숫자를 계산하거나 지어내지 마라. "
    "금액·예산·인건비는 쓰지 마라. 한국어 제안서체(~하겠음, ~임)로 아래 다섯 항목을 번호와 제목 그대로, 항목마다 2~3문장으로 쓴다. 표·기호·마크다운은 쓰지 않는다.\n"
    "1. 제안 개요: 제안 배경과 과업 이해. 지난 회차 기록을 근거로 한다는 점.\n"
    "2. 행사 운영 계획: 거점 구성과 QR 참가 확인, 실시간 집계.\n"
    "3. 인력 및 안전관리 계획: bottleneck 거점의 인력·안내 보강, crowd의 혼잡 경고 기준.\n"
    "4. 성과 지표 및 목표: measured(지난 회차 기록)와 targets(목표)를 나란히.\n"
    "5. 결과 보고 및 사후 관리 계획: 결과보고서, 회차 비교, 원자료 제출."
)


def _template_proposal(b):
    m, t = b["measured"], b["targets"]
    src = f"「{b['based_on']['festival']}」 {b['based_on']['edition']}회차"
    scale = "".join([f"예상 참가 {b['expected_visitors']}명, " if b.get("expected_visitors") else "",
                     f"행사 기간 {b['days']}일, " if b.get("days") else ""])
    cr = b.get("crowd") or {}
    lines = [
        f"1. 제안 개요: 본 제안은 「{b['title']}」의 참가 확인, 관람객 집계, 만족도 조사, 결과 보고를 QR 기반으로 수행하는 방안임. "
        f"{scale}거점 {b['checkpoint_count']}곳 운영을 기준으로 하며, {src}의 QR 기록을 근거로 계획을 수립하였음.",
        f"2. 행사 운영 계획: 거점({', '.join(b['checkpoint_names'])})마다 QR을 설치하고, 참가자는 앱 설치나 가입 없이 휴대폰 카메라로 참여하도록 하겠음. "
        "거점별 방문 인원은 운영자 화면에서 실시간으로 집계하며, 완주자에게는 모바일 설문과 경품 교환권을 제공하겠음.",
        "3. 인력 및 안전관리 계획: "
        + (f"지난 회차에 '{b['bottleneck']['name']}' 이후 이탈률이 {b['bottleneck']['drop_rate']}%로 가장 높았으므로, 이 구간에 안내 인력과 이동 안내를 보강하겠음. "
           if b.get("bottleneck") else "거점별 방문 현황에 따라 안내 인력을 배치하겠음. ")
        + (f"한 거점에서 최근 {cr['window_min']}분 동안 {cr['threshold']}명 이상이 확인되면 혼잡 경고를 띄워 인력을 재배치하겠음."
           if cr else "거점별 혼잡 경고 기준을 정해 인력을 재배치하겠음."),
        f"4. 성과 지표 및 목표: 지난 회차 기록은 참여 {m['visitors']}명, 완주 {m['completed']}명(완주율 {m['completion_rate']}%)"
        + (f", 만족도 평균 {m['satisfaction_avg']}점" if m.get("satisfaction_avg") else "")
        + (f", 설문 응답 {m['survey_count']}건" if m.get("survey_count") else "")
        + f"임. 이번 행사의 목표는 완주율 {t['completion_rate']}%"
        + (f", 만족도 평균 {t['satisfaction_avg']}점" if t.get("satisfaction_avg") else "") + "으로 설정함.",
        "5. 결과 보고 및 사후 관리 계획: 행사 종료 후 참여·완주·거점별 이탈·설문 결과를 같은 집계 기준으로 정리한 결과보고서를 제출하고, "
        "지난 회차와 같은 지표로 비교한 표와 원자료(CSV)를 함께 제출하겠음.",
    ]
    return "\n".join(lines)


def write_proposal(basis, use_llm=True):
    return _draft(PROPOSAL_SYSTEM, {"basis": basis}, lambda: _template_proposal(basis), use_llm)
