# MrBot1000 release checklist

## Scope and review

- [ ] Separate safety, evidence/accounting, GUI, orchestration, and provider
  changes into focused commits or clearly labeled review sections.
- [ ] Review database schema and migration compatibility.
- [ ] Confirm no secrets, databases, logs, virtual environments, or wallet
  material are tracked.
- [ ] Confirm the worktree contains only intentional release changes.

## Validation

- [ ] Run the focused tests for every changed subsystem.
- [ ] Run `python -m tests --category safety`.
- [ ] Run `python -m tests --category recovery`.
- [ ] Run the complete pytest suite with a CI timeout.
- [ ] Run compilation and `git diff --check`.
- [ ] Verify safe-mode startup and provider diagnostics.

## Operational safety

- [ ] Safe mode remains the default for new or uncertain deployments.
- [ ] Mutating tools require approval and cannot be called directly.
- [ ] Unknown evidence transitions fail closed.
- [ ] Validator failures fail closed.
- [ ] Live financial features remain disabled unless explicitly configured.
- [ ] Recovery and emergency-stop procedures are tested.
