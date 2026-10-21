# 10p — `agents/services/`

> **O-01 RESOLVED in v2.1.125 (ARCH-ENG-304).** `CoderWorker` now has a live
> caller: the `propose_code_patch` tool accepts a defect without complete
> replacement content and asks CoderWorker to draft it. The worker's
> `_submit_edit` routes through the same `CodePatchService` approval/backup/
> verify/rollback gate as every other source edit; nothing is written at
> proposal time.
>
> **O-02 RESOLVED in v2.1.125 (ARCH-ENG-294).** `MainWindow._build_reviewer()`
> now constructs `AnalystWorker` and passes it to `ProposalReviewer`, so the
> pre-submission gate's quality scoring is live rather than structurally absent.
> The analyst's proposal analysis is deterministic and works without a model
> key; if it cannot be built, the reviewer falls back to the rule-based path.

15 scripts, 4,657 lines. The autonomous loop, self-audit, code-patch service,
the live-order reconstruction helper, the Coder/Analyst workers, and the CLIs.

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 1 | — |
| `task_executor.py` | 19 | `executor.py` (compat shim) |
| `application_services.py` | 54 | `main.py` |
| `workflow_planner.py` | 60 | `earning_pipeline.py` |
| `self_improvement_commands.py` | 137 | `main.py`, `tab_feature_builders.py` |
| `cli_interface.py` | 213 | **nothing** |
| `patch_sandbox.py` | 220 | `handlers.py` |
| `autonomous_run_store.py` | 263 | `composition_root.py` |
| `analyst_worker.py` | 338 | **nothing constructs it** |
| `coder.py` | 318 | **nothing constructs it** |
| `mrbot_cli.py` | 501 | **nothing imports it** |
| `code_patch_service.py` | 488 | `composition_root.py`, `handlers.py` |
| `live_order_execution.py` | 45 | `main.py` (approved live-order handler only; keeps the optional ccxt import out of the bootstrap) |
| `self_audit.py` | 691 | `earning_pipeline.py` |
| `autonomous_loop.py` | 1309 | `earning_pipeline.py`, `earning_tab.py` |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| O-01 | med | **`coder.py` (318 lines) is never instantiated — and ARCH-ENG-204 hardened it anyway.** `CoderWorker` has **zero** construction sites in production. The only match for `CoderWorker(` is its own `class` statement at `:23`; every other production reference is a comment or a docstring, including `handlers.py:229`. This matters because ARCH-ENG-204 rewired `CoderWorker._submit_edit` through `CodePatchService` specifically to close the *"single holdout"* it identified: *"CoderWorker was the single holdout — it called `safe_write_file()` directly, so an agent rewrite of the program's own source skipped approval, skipped verify, and had no rollback path."* That remediation is **correct and should be kept** — and its fail-closed refusal at `:82-89` is exemplary, returning `status: "blocked"` with the reason *"refusing to edit an existing file ungated (ARCH-ENG-204)"* rather than degrading to a direct write. But the component it protects has never run. **This is the ninth instance of the sweep's recurring pattern, and the second in my own remediation work** (after F-01's `DiscoveryScheduler`). The difference from F-01 is worth stating: there, the fix closed a half-loop and left a live consumer reading nothing; here, the fix closed a hole in code that is unreachable, so the hole was never live either. |
| O-02 | med | **`analyst_worker.py` (338 lines) is never instantiated, and a live gate depends on it.** `AnalystWorker` appears only in `proposal_reviewer.py`'s docstrings, comments and type hints, plus `runtime/services.py:76` where the *string* `"AnalystWorker"` is used as a logger source. `ProposalReviewer.__init__(self, analyst=None)` (`:135`) stores the analyst, and `proposal_reviewer.py:17` describes the design: *"the gate is model-optional. If an AnalystWorker is provided it uses it."* Nothing provides it. So the pre-submission gate's LLM-assisted quality scoring is **structurally absent**, leaving only the deterministic checks. This compounds J-05: that gate has zero tests *and* its optional model-backed half is not wired, so only the rule-based path is reachable — and it is the path that has never been demonstrated to behave correctly. |
| O-03 | low | **`mrbot_cli.py` (501 lines) documents an invocation path that does not exist.** Its docstring gives six usage examples, all of the form `python -m agents.mrbot_cli …`. The file lives at `agents/services/mrbot_cli.py`; neither `agents/mrbot_cli.py` nor `agents/mrbot_cli/` exists. Every documented command fails with `No module named agents.mrbot_cli`. The correct form is `python -m agents.services.mrbot_cli`. A read-only diagnostic CLI whose every documented command is wrong is worse than no CLI — and it is the module an operator would reach for when something else in this report has gone wrong. |
| O-04 | low | **`cli_interface.py` (213 lines) is dead.** `CLIState`, `load_state` and `save_state` all appear only within their own module. Not imported by `mrbot_cli.py` or anything else, so the two CLI-adjacent modules are independent and both unreachable. |

---

## Verified as sound

**`CoderWorker._submit_edit` is the best fail-closed code in the sweep**, and its
docstring explains why the failure is the *safe* one:

> *"The fallback matters: with no patch service available this returns a refusal
> rather than writing. Silently degrading to a direct write would reintroduce
> exactly the hole this wiring closes, and it would do so quietly — the caller
> would see `success` and no backup would exist."*

That last clause is the point. A refactor that made this fallback permissive would
not fail loudly; it would report success while writing an unbacked, unapproved,
unverified change to the program's own source. The code refuses instead. The
new-file branch at `:90-95` makes the same distinction — creation has no prior
content to lose, so `safe_write_file` is "not a gate but is not a hazard."

**`mrbot_cli.py` is built with secrets safety as an explicit design property**,
stated in its docstring: *"Never prints full credential values. Endpoint URLs are
public localhost addresses and may be printed. All .env reads are whitelisted by key
prefix."* The module being unreachable (O-03) means this property is currently
unexercised, but the constraint is documented where it will be read.

**`code_patch_service.py` is genuinely wired at both ends.** It is built by
`composition_root` and consumed by `handlers.py`, with `patch_sandbox.py`
(`handlers.py`) providing the rehearsal path from ARCH-ENG-227. This is the
component that CoderWorker was correctly prevented from bypassing.

**`autonomous_loop.py` (1,309 lines) is live** from `earning_pipeline.py` and
`earning_tab.py`, and is a real writer to the evidence store (`:855`, `:958`,
`:1065`) — which is why `agents/evidence/` could be assessed as genuinely wired.

---

## Assessment

`agents/services/` contains the most consequential remediation work in the
repository and also the clearest evidence of the sweep's recurring pattern landing
in this project's own history.

O-01 and O-02 together are **656 lines** of fully-built worker agents that no
production code instantiates. `CoderWorker` and `AnalystWorker` are the two halves
of the autonomous self-improvement story — one proposes code changes through an
approval gate, the other scores proposal quality through a model. Neither runs.
The machinery around them (`CodePatchService`, the approval queue, the sandbox,
`self_improvement_commands`) is all live and correctly wired; the two workers that
would use it are not connected.

That is worth saying plainly rather than as a dead-code line count, because it
changes what the surrounding features *mean*. The self-improvement pipeline can
propose, approve, rehearse, apply, back up and roll back a patch — but nothing
currently *generates* those patches through the agent path. `self_improvement_commands`
must be supplying them some other way, or the pipeline is exercised only by tests.

The distinction between O-01 and O-02 matters for priority. **O-01 is safe**: dead
code cannot bypass the gate that was built to stop it. **O-02 is a silent
capability gap**: `ProposalReviewer` accepts an analyst it never receives, so the
gate reports its deterministic-only verdict with nothing indicating the model-backed
half was expected. A caller reading `ReviewResult` cannot tell which path produced
it.

O-03 deserves fixing regardless of everything else — it is a one-line docstring
correction, and it is the diagnostic tool an operator would reach for next.