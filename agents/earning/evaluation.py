"""Provider-facing semantic scoring for earning opportunities.

This service produces estimates only. It does not make lifecycle, safety, or
execution decisions; those remain owned by the pipeline's deterministic
intelligence and policy layers.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable


def evaluate_opportunity(
    opportunity: Any,
    *,
    memory: Any,
    log_fn: Callable[[str], None],
    normalize_keep_alive: Callable[[Any], Any],
) -> Any:
    """Apply model scores or a deterministic fallback to an opportunity."""
    import httpx

    def normalize_scores(raw_scores: dict) -> dict:
        def to_float(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return float(default)

        def to_unit(value: Any, default: float) -> float:
            """A 0..1 score, accepting the model answering on a 0..10 scale.

            ARCH-ENG-124: the prompt below asks for every axis on a 0-10 scale,
            but every consumer of `skill_match` and `effort` treats them as 0..1
            (`SemanticEstimate.skill_fit`/`difficulty`, `min(1.0, ...)` clamps,
            the `/(effort_score + 0.1)` ranking divisor, and the engine's
            `p_complete = 1 - 0.6*difficulty`). Measured before this
            normalization: a model answering honestly with skill_match=7.0
            saturated `p_acceptance` to 1.000 and effort=5.0 drove
            `p_completion` to its 0.01 floor, collapsing a $2,500 opportunity to
            `marginal` — the model's own scale was silently breaking the
            probability model in BOTH directions. Dividing by 10 when the value
            exceeds 1.0 makes a 0..10 answer mean what the code expects while
            leaving an already-0..1 answer untouched.

            `risk` is deliberately NOT normalized: its thresholds (>=7 high,
            >=4 medium) are written for the 0-10 scale the prompt asks for.
            """
            try:
                v = float(value)
            except (TypeError, ValueError):
                return float(default)
            if v > 1.0:
                v = v / 10.0
            return max(0.0, min(1.0, v))

        return {
            "profit": to_float(raw_scores.get("profit", 0.0), 0.0),
            "effort": to_unit(raw_scores.get("effort", 0.5), 0.5),
            "risk": to_float(raw_scores.get("risk", 5.0), 5.0),
            "urgency": to_float(raw_scores.get("urgency", 0.0), 0.0),
            "skill_match": to_unit(raw_scores.get("skill_match", 0.5), 0.5),
            "scam_prob": to_unit(raw_scores.get("scam_prob", 0.0), 0.0),
        }

    def extract_scores(content: str):
        body = (content or "").strip()
        if not body:
            return None
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return normalize_scores(parsed)
        except json.JSONDecodeError:
            pass
        for match in re.finditer(r"\{.*?\}", body, re.DOTALL):
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return normalize_scores(parsed)
        return None

    memory_state = memory.get_opportunity_history(opportunity.id)
    if memory_state and "past_decisions" in memory_state:
        opportunity.skill_match = memory_state.get(
            "skill_match", opportunity.skill_match
        )

    prompt = (
        f"Evaluate this earning opportunity:\n"
        f"Title: {opportunity.title}\n"
        f"Description: {opportunity.description[:300]}\n"
        f"Platform: {opportunity.platform}\n"
        f"Payment: {opportunity.payment_amount} {opportunity.payment_currency}\n"
        f"Min Amount: ${opportunity.min_amount}\n\n"
        f"Score each axis 0-10:\n"
        f"1. Profit potential\n2. Effort (lower is better)\n"
        f"3. Risk (scam likelihood)\n4. Urgency\n5. Skill match\n\n"
        f'Reply ONLY as JSON: {{"profit": N, "effort": N, '
        f'"risk": N, "urgency": N, "skill_match": N}}'
    )

    try:
        model = (
            os.getenv("OLLAMA_MAIN_MODEL", "").strip()
            or os.getenv("OLLAMA_MODEL", "llama3.2")
        )
        response = httpx.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert evaluator of earning "
                            "opportunities. Be honest. Flag scams."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "options": {"num_predict": 300},
                "keep_alive": normalize_keep_alive(
                    os.getenv("OLLAMA_KEEP_ALIVE", "300s")
                ),
            },
            timeout=30.0,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        scores = extract_scores(content)
        if not scores:
            raise ValueError("No valid score JSON found in model output")

        opportunity.skill_match = scores.get("skill_match", 0.5)
        opportunity.effort_score = scores.get("effort", 0.5)
        risk = scores.get("risk", 5)
        opportunity.risk_level = (
            "high" if risk >= 7 else ("medium" if risk >= 4 else "low")
        )
        opportunity.urgency = scores.get("urgency", 0.0)
        opportunity.status = "evaluated"
        # ARCH-ENG-126: the model's scam assessment was COMPUTED and then
        # DISCARDED. `normalize_scores` produced `scam_prob`, and the only use
        # of it was `if scam_prob > 0.7: risk_level = "high"` — a coarse 0.7
        # cliff that threw the number away. `opportunity.scam_prob` was never
        # assigned (verified: `hasattr(o, "scam_prob")` was False after a
        # successful evaluation), so `intelligence.evaluate_intelligence` —
        # which reads exactly that attribute — always saw 0.0 and reported
        # `reasons["scam_risk"] = "low"` for an opportunity the model had
        # scored 0.95. The engine's `scam >= 0.6 -> unsafe` gate was therefore
        # unreachable from the LLM path; only the risk_level cliff survived,
        # and it set "high" which the engine treats as unsafe for an unrelated
        # reason (`risk_levels_unsafe`), masking the missing signal.
        opportunity.scam_prob = scores.get("scam_prob", 0.0)
        if scores.get("scam_prob", 0.0) > 0.7:
            opportunity.risk_level = "high"
    except Exception as exc:
        log_fn(f"[Evaluate] LLM error for {opportunity.id}: {exc}")
        title_desc = (opportunity.title + " " + opportunity.description).lower()
        if opportunity.source == "content":
            base_skill = 0.5
        elif opportunity.source in ["referral", "airdrop"]:
            base_skill = 0.6
        else:
            base_skill = 0.2
        skills = [
            "python", "ai", "data", "write", "content",
            "code", "dev", "review", "test",
        ]
        matched = sum(1 for skill in skills if skill in title_desc)
        opportunity.skill_match = min(
            1.0, base_skill + (matched / len(skills)) * 0.5
        )
        opportunity.effort_score = 0.5
        opportunity.risk_level = (
            "low" if "airdrop" not in opportunity.type else "medium"
        )
        opportunity.urgency = 0.3
        opportunity.status = "evaluated"
    return opportunity


__all__ = ["evaluate_opportunity"]
