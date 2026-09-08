# Skill: Opportunity Evaluation

Trigger: earnings pipeline needs scoring for discovered opportunities, or user asks for ranking/recommendation.

Input:
- normalized opportunity list
- provider/model selection from settings
- optional memory hints: prior outcomes, platform reputation, skill patterns

Steps:
1. For each opportunity, build an evaluation prompt covering profit potential, effort, risk, urgency, and skill match
2. Call the active LLM provider in priority order: OpenAI → Anthropic → Ollama
3. If LLM is unavailable, use heuristic fallback based on keyword matches and source priors
4. Normalize scores into skill_match, effort_score, risk_level, urgency, estimated_usd_value
5. Apply memory-based boost or penalty from platform reputation and pattern memory
6. Return scored opportunities with evaluation metadata

Guardrails:
- Do not execute or submit during evaluation
- Flag likely scams explicitly and do not hide risk
- Do not leak prompt text containing credentials into logs

Output:
- scored opportunities with confidence and provider used
- evaluation errors per opportunity, if any