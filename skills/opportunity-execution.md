# Skill: Opportunity Execution

Trigger: earnings pipeline enters execute phase, or user manually selects an opportunity to pursue.

Input:
- filtered opportunity
- execution policy: safe-only, low-risk, user-confirmed
- document/scanner output if available
- quality gate settings

Steps:
1. Verify the opportunity is still valid and not expired
2. Prepare required artifacts: application text, response template, or metadata
3. Run document scanner and quality controller if content is present
4. If quality gate fails, mark outcome as rejected_pre_submit and stop
5. If user confirmation is required, pause and request confirmation
6. Execute only safe, reversible actions; do not pay, transfer, or submit without explicit confirmation
7. Record outcome to memory tier 2 with status, time spent, result, revenue, scam flag

Guardrails:
- Do not spend money or transfer funds automatically
- Do not submit work that has not passed QA
- Do not reuse credentials or session tokens across platforms
- If execution is uncertain, mark as manual_action_required

Output:
- execution outcome record
- next action recommendation if applicable