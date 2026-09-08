# Skill: Document QA

Trigger: user submits text for review, earnings pipeline needs pre-submit validation, or document scanning is requested.

Input:
- document text or file path
- task type: submission, application, review, proofread, qa
- minimum quality thresholds

Steps:
1. Extract content from PDF or plain text if path is provided
2. Check grammar, clarity, completeness, and task fit
3. Detect risky content: secrets, credentials, unsafe promises, scam-like language
4. Score quality dimensions: clarity, correctness, completeness, safety
5. If score is below threshold, return specific fixes
6. If document passes, return approved state with summary

Guardrails:
- Do not store extracted secrets; redact and warn instead
- Do not auto-submit documents
- If scanner cannot read the file, return needs_human_review

Output:
- approval status: approved, needs_changes, rejected, needs_human_review
- issue list with severity
- suggested fixes when applicable