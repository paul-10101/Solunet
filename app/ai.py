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


def _grounded(text, data):
    allowed = _numbers_in(data) | set(range(0, 11))  # 서수·개수 같은 작은 수 허용
    bad = _nums(text) - allowed
    if bad:
        print("LLM grounding rejected numbers:", sorted(bad)[:10])
    return not bad


GH_MODEL = os.getenv("GH_MODEL", "openai/gpt-4.1-mini")


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
        return r.json()["choices"][0]["message"]["content"]
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


REPORT_SYSTEM = (
    "너는 지역축제 평가보고서 작성 보조다. 입력 JSON의 숫자만 그대로 사용하고, 더하기·빼기·비율 계산으로 새 숫자를 만들지 마라. "
    "변화량이 필요하면 changes에 있는 값만 쓴다. "
    "한국어 보고서체로 '1. 개요 2. 방문·완주 현황 3. 거점별 이탈 분석 4. 이탈 사유·설문 5. 이전 회차 대비 6. 시사점' 순서로 쓴다. "
    "이전 회차 비교(comparison)가 없으면 5번은 '비교할 이전 회차 없음'으로 쓴다. 설문 만족도·재방문 의사가 있으면 4번에 쓴다."
)

DESIGN_SYSTEM = (
    "너는 축제 동선 설계 보조다. 입력의 changes 각각에 대해 '무엇을, 왜(근거 데이터)' 바꾸는지 "
    "한국어로 2문장 이내씩 설명하라. 입력에 없는 숫자는 쓰지 마라."
)


def _template_report(festival, stats, comparison):
    worst = max(stats["checkpoints"], key=lambda c: c["drop_rate"], default=None)
    lines = [
        f"1. 개요: {festival['name']} {festival.get('edition', '')}회차 QR 데이터 기반 평가.",
        f"2. 방문·완주: 참여 {stats['visitors']}명, 완주 {stats['completed']}명 (완주율 {stats['completion_rate']}%).",
    ]
    if worst:
        lines.append(f"3. 이탈: '{worst['name']}' 이후 이탈률 {worst['drop_rate']}%로 가장 높음.")
    sv = stats.get("survey", {})
    parts = []
    if stats["exit_reasons"]:
        parts.append(f"이탈 사유는 '{next(iter(stats['exit_reasons']))}' 응답이 가장 많음")
    if sv.get("count"):
        parts.append(f"설문 {sv['count']}건, 혼잡도 평균 {sv['crowd_avg']} / 5" +
                     (f", 만족도 평균 {sv['satisfaction_avg']} / 5" if sv.get("satisfaction_avg") else ""))
    if parts:
        lines.append("4. 이탈 사유·설문: " + ", ".join(parts) + ".")
    if comparison:
        line = (f"5. 이전 회차 대비: 참여 {comparison['visitors_prev']}명 → {comparison['visitors_cur']}명, "
                f"완주율 {comparison['completion_prev']}% → {comparison['completion_cur']}%")
        if comparison.get("satisfaction_prev") and comparison.get("satisfaction_cur"):
            line += f", 만족도 {comparison['satisfaction_prev']} → {comparison['satisfaction_cur']}"
        lines.append(line + ".")
    else:
        lines.append("5. 이전 회차 대비: 비교할 이전 회차 데이터 없음.")
    return "\n".join(lines)


def _template_design(design):
    return "\n".join(f"- {c['checkpoint']}: {c['action']} (근거: {c['evidence']})" for c in design["changes"])


def write_report(festival, stats, comparison=None):
    data = {"festival": festival["name"], "edition": festival.get("edition"), "stats": stats, "comparison": comparison}
    if comparison:  # 모델이 직접 빼기를 하지 않도록 차이를 미리 계산해 넘긴다
        diff = lambda a, b: round(b - a, 1) if a is not None and b is not None else None
        data["changes"] = {k: diff(comparison.get(k + "_prev"), comparison.get(k + "_cur"))
                           for k in ("visitors", "completion", "satisfaction", "revisit", "crowd")}
        data["changes"]["checkpoints"] = {c["name"]: c["change"] for c in comparison["checkpoints"]}
    try:
        text = _call_llm(REPORT_SYSTEM, data)
        if text and _grounded(text, data):
            return {"source": "llm", "text": text}
    except Exception as e:  # 시연 중 API 장애가 나도 화면은 유지
        print("LLM error:", e)
    return {"source": "template", "text": _template_report(festival, stats, comparison)}


def explain_design(design):
    try:
        text = _call_llm(DESIGN_SYSTEM, design)
        if text and _grounded(text, design):
            return {"source": "llm", "text": text}
    except Exception as e:
        print("LLM error:", e)
    return {"source": "template", "text": _template_design(design)}
