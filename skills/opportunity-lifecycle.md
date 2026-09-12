---
name: Opportunity Lifecycle
category: ADMINISTRATIVE
maturity: stable
tool: opportunity_lifecycle
automatable: true
human_capable: true
---

# Skill: Opportunity Lifecycle

Trigger: user asks about opportunity progress, earnings pipeline advances an opportunity to a new stage, or the system needs to report lifecycle status.

Input:
- opportunity id or record
- current stage: discovered, researched, applied, in_progress, submitted, paid, failed
- optional note and payment amount
- optional previous history/context

Steps:
1. Identify the opportunity and its current known stage.
2. Update the lifecycle state using the approved stage transition.
3. Persist the state update in the shared context and/or memory so chat and UI can read it.
4. Summarize the latest status change in plain language for the user.
5. If a payout is recorded, include the amount and confirmation context.

Guardrails:
- Do not invent missing payment or submission evidence.
- Do not change the stage without a valid transition or observed evidence.
- Do not expose secrets or private credentials in lifecycle reports.
- If the status is uncertain, report it as unknown or needs_review.

Output:
- updated lifecycle state
- concise status summary
- optional next recommended action
