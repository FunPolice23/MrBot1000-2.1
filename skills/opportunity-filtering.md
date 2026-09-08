# Skill: Opportunity Filtering

Trigger: earnings pipeline enters filter phase, or user applies risk/value/skill constraints.

Input:
- scored opportunities
- max_risk: low/medium/high
- min_skill_match: 0..1
- min_usd_value: float
- payment_types: list
- optional memory-derived priorities

Steps:
1. Remove opportunities that do not match allowed payment types
2. Remove opportunities above the max_risk threshold
3. Remove opportunities below min_skill_match
4. Remove opportunities below min_usd_value
5. Apply memory boost/suppress adjustments where available
6. Sort by expected value adjusted by confidence and risk
7. Return filtered list with filter statistics

Guardrails:
- Do not execute filtered opportunities in this skill
- Do not hide rejected opportunities; log rejection reasons
- If filtering is too strict and returns empty, report that plainly

Output:
- filtered opportunity list
- filtered_out counts by reason