# 11x — `app/action_pipeline.py` depth pass (649 lines, 23 methods)

> **AQ-02 RESOLVED in v2.1.125 (ARCH-ENG-276).** `_exec_modify_file` wrote a
> `<target>.bak` sidecar it never used and then wrote the target in place. It now
> follows ARCH-ENG-227's contract: byte-exact backup under
> `.mrbot_backups/action_pipeline/` (no mutation if the backup fails), temp file
> plus `os.replace`, `py_compile` verification for `.py`, and restore of the
> original bytes on any failure.
>

Depth-pass #24 of 83. **1 dead of 23.** This file contains the sweep's most consequential
absence so far, and the finding is not "something is broken" — it is **"the absence of a
caller is currently the thing keeping a file-write path from bypassing ARCH-ENG-165."**

---

## Structure

```
L   47-60    ProposedAction      L  275-315   ImportValidator
L   64-80    ValidationResult    L  318-340   SecurityValidator
L   84-89    ExecutionResult     L  347-649   ActionPipeline (15 methods)
L   96-138   SyntaxValidator     +  6 dataclasses / validators
L  141-192   ApiUsageValidator
L  195-227   NullSafetyValidator
L  230-272   SpellingValidator
```

Docstring: *"Every proposed action (file creation, code modification, self-improvement)
passes through this pipeline before execution: 1. PROPOSE 2. VALIDATE — syntax check, API
usage scan, null/error pattern check, spelling check (via Summarizer), import validation
3. APPROVE 4. EXECUTE 5. NOTIFY."*

Largest: `_execute` (51), `SyntaxValidator.validate` (39), `process` (35), `__init__` (32),
`NullSafetyValidator.validate` (27), `_run_validators` (27).

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AQ-01 | **med** | **`ActionPipeline.process()` has no production caller — and wiring it would reintroduce ARCH-ENG-165.** The pipeline is constructed at `main.py:447` with all three callbacks wired (`:452-454`), but **`ProposedAction` is never constructed anywhere in production** (only `tests/safety/test_safe_mode_pipeline.py` builds one). The sole production consumer of `self.pipeline` is `quick_check()` at `main.py:3328` — the clipboard validator, which does not execute. `_execute:470-474` calls `authorize(tool_name, …, approved=bool(action.metadata.get("approved")))` and **passes no `approval_id`**, and `metadata["approved"]` is never set in production. Per `agents/safety/authorization.py:78-87`, that exact shape returns `ALLOWED` with the reason *"Explicit approval supplied by the caller (UNVERIFIED: no approval_id was passed, so no tool scope or argument scope was checked)."* |
| AQ-02 | low | **A second, weaker implementation of code modification exists beside ARCH-ENG-227's.** `_exec_modify_file:563-566` writes the backup **at apply time** — `path.with_suffix(suffix + ".bak")` — whereas ARCH-ENG-227 step 1 requires backup **at propose time**, and `handlers.py:_tool_propose_code_patch:241-245` explains exactly why: *"If the target exists, it is copied into the backup directory now — at PROPOSE time, not at apply time. That way a revert path exists **from the moment the human is asked to approve**, so a patch that goes wrong later has something to go back to even if the backup step at apply time never gets that far."* This module has **no `ai_workshop` rehearsal and no `revert`** anywhere (both terms absent). |
| AQ-03 | info | **The Summarizer integration is entirely vestigial and the docstring overstates it.** `set_summarizer` (`:396-398`, 3 lines) is dead; `self._summarizer_worker` is written at `:377` (`None`) and `:398` and **never read**. Yet the module docstring `:9` advertises the VALIDATE stage as including *"spelling check (via Summarizer)"*. The real spelling check is `SpellingValidator` (`:230-272`), a static 21-line validator with no LLM involvement. |

---

## AQ-01 — why the missing caller is load-bearing

`11t` documented ARCH-ENG-165's fix in `authorization.py:38-60`:

> *"When the gate returned NEEDS_APPROVAL, a truthy `approved` upgraded the decision
> straight to ALLOWED… Nothing consulted `HumanApprovalQueue` and nothing called
> `assert_approval_covers`, so **the caller's assertion was the whole authorization.** The
> HIGH-TRUST handlers … were never exposed — **but a mutating tool with no internal check
> (`file_write`, `run_command`, `workshop_payment`) executed on a bare boolean.**"*

The fix added a verified path (`approval_id` → `assert_approval_covers`, so an approval for
`$10` cannot execute a `$10,000` payment) and left the unverified path for compatibility,
documenting it honestly at `authorization.py:60-63`:

> *"`approval_id` ABSENT — UNVERIFIED, caller-asserted. Behaviour is unchanged for
> compatibility, but the reason now says plainly that no scope was checked, so it cannot be
> mistaken for the verified path. Production callers should always pass the id; `main.py`
> does."*

**`ActionPipeline` is a production caller that cannot pass the id, and does not.**
`_execute:466-474` is the whole authorization call:

```python
authorization = self._action_dispatcher.authorize(
    tool_name,                                    # "file_write"
    {"action_type": …, "target_path": …},
    approved=bool(action.metadata.get("approved")),
)
```

There is no `approval_id` parameter on `ProposedAction`, no field for one, and nothing in
`_execute` that could supply one. **The pipeline is structurally incapable of taking the
verified path.**

So the two halves of this finding have to be read together:

- `metadata["approved"]` is never set in production **and** `process()` is never called, so
  the unverified path is unreachable today.
- The moment someone wires `process()` up — which the object at `main.py:447` is
  positioned to invite — a `file_write` would be authorized on a caller-supplied boolean,
  with no queue record, no tool scope, and no argument scope.

**This inverts the sweep's standing advice.** For `AJ-01` the fix was "wire up
`run_audit`"; for `AA-01` it was "wire up the guard." Here, wiring the entry point is the
*unsafe* direction. The correct sequence is: plumb an `approval_id` through
`ProposedAction` → `authorize()` → `_authorize_verified` **first**, and only then give
`process()` a caller. The comment at `authorization.py:63` already asserts the invariant
(*"Production callers should always pass the id"*) — this caller silently violates it, and
the reason string it would produce is the one place the violation becomes visible.

---

## AQ-02 — two code-modification paths, different disciplines

| | ARCH-ENG-227 (`handlers.py` → `code_patch_service`) | this module (`ActionPipeline`) |
|---|---|---|
| backup | at **propose** time, into a backup dir | at **apply** time, `.bak` sibling |
| rehearsal | `ai_workshop` practice copy, `verify` before proposing | none (`ai_workshop` absent) |
| validation | `py_compile` on the copy | six validators, score ≥ 0.85 for `self_improve` |
| rollback | yes (`revert` absent here) | none (`revert` absent here) |
| approval | `HumanApprovalQueue` + `assert_approval_covers` | caller-supplied boolean |
| entry point | live (`tools.py:59`) | no production caller |

`11g` verified the left column is live and correctly ordered. The right column is better at
*static analysis* — six validators against one `py_compile` — and worse at every safety
step that depends on a human. That combination is worth stating plainly: **more validation,
less verification.** Neither path is the designated supersession of the other, which makes
this the ambiguous case rather than the clean `11p` layered pair.

The `_safe_path` guard (`:516-529`) is genuinely good and deserves credit: it resolves the
relative path, then verifies `is_relative_to(self.root)`, with a `str.startswith(root + os.sep)`
fallback for older Pythons — and rejects `full == self.root` explicitly, closing the
directory-escape case where the resolved path *is* the root.

---

## AQ-03 — docstring promises a check that cannot run

`:9` lists the VALIDATE stage as *"spelling check (via Summarizer)"*. `set_summarizer`
(`:396-398`) is dead, and `_summarizer_worker` — initialised at `:377` with the comment
*"Summarizer reference for language correction"* — is written twice and read never. There is
no Summarizer path. `SpellingValidator` (`:230-272`) does the work statically.

Minor, but it is the same class as `AK-01` (`11s`), where a docstring's promised contract
(`"Returns [] on any failure"`) did not match the code. Both are cheap to fix by correcting
the docstring rather than the code — the Summarizer integration has no caller to revive.

---

## Verified as sound

**ARCH-ENG-203's fix is present and documented at the site** (`:380-384`):

```python
# ARCH-ENG-203: was `.lower() == "true"`. `feature_enabled()` reads the
# SAME variable through `app.effects.env_bool`, which accepts 1/yes/on.
# This narrower form disagreed with it: for `PIPELINE_ALLOW_SELF_IMPROVE=1`
# the gate read closed here and open there. One parser, one answer.
self.allow_self_improve = env_bool("PIPELINE_ALLOW_SELF_IMPROVE", False)
```

**This confirms `11v`'s AO-03 precisely**: the canonical parser is `app.effects.env_bool`,
`action_pipeline.py` was migrated to it, and `tab_feature_builders.py:2535` was not. The
fix landed at one of the two sites, exactly as that finding said.

**`safe_mode` short-circuits before any authorization or write** (`:481-492`), returning
`skipped=True` and logging *"SAFE MODE: skipped execution"*. `main.py:106` records that
`MRBOT_SAFE_MODE` is forced on for the entire test session so *"every ActionPipeline built"*
during tests is inert — the same class of structural guarantee as
`approval.py`'s `if "pytest" in sys.modules` guard (`11t`).

**Delete requires an explicit confirmation flag** (`:577-579`): `if not
action.metadata.get("confirmed"): return ExecutionResult(False, "Delete requires
metadata['confirmed']=True")`. Deletion is the one irreversible operation and it has its
own independent gate.

**`self_improve` has both an env gate and a quality threshold** — `allow_self_improve`
(`:501`) *and* `vr.score < 0.85` (`:595`), with the score and summary in the refusal
message. Two independent conditions, both stated to the operator on failure.

**`self._log` is injectable and `main.py:450` routes it into the live log** —
`log_fn=lambda msg: self.log_signal.emit(msg)`. That is the pattern `AP-01` (`11w`) found
missing in `discoverer.py`, done correctly here: `_execute`'s MODIFIED/DELETED messages
reach the operator's Live Log.

---

## Re-verification

**`11g` confirmed and materially extended.** `_tool_propose_code_patch`
(`handlers.py:224-261`) is live, advertised in `tools.py:59`, and its five-step ordering is
documented at the point of implementation. This pass confirms the *other* code-modification
path exists, is weaker on every human-dependent step, and — critically — **is positioned to
be wired up** by an object that is already constructed and callback-wired at `main.py:447`.

**`11v` / AO-03 confirmed at both sites.** `action_pipeline.py:384` uses `env_bool`;
`tab_feature_builders.py:2535` does not. The feature_flags.py docstring's claim that
`ActionPipeline.allow_self_improve` disagreed with `feature_enabled()` describes the *fixed*
state, and this pass confirms the fix is in place here.

**`11t` / ARCH-ENG-165 extended.** The approval queue is the most completely wired safety
component in the repository; `ActionPipeline` is a consumer that cannot reach it. That is
consistent with `11t`'s verdict on the queue itself — the queue is fine, one caller is not.

**`11a` / U-01 unaffected.** `main.py`'s dead `_review_selected` island is a different
surface (instruction quarantine review); this file's entry point is simply never called.

---

## Assessment

One dead method, three findings, and the most important one is an argument about **what not
to do**.

AQ-01 is the seventeenth instance of *"mechanism correct, wired at one end only"*, and it is
the first where the missing end is the **entry point of a mechanism that would be unsafe if
entered**. `ActionPipeline` is well-built — six validators, a path-escape guard, a
safe-mode short-circuit, a delete confirmation flag, a self-improvement score floor, and an
authorization call that is *reached*. What it lacks is the one thing ARCH-ENG-165 was
written to guarantee: the ability to say *"a human approved this specific write of this
specific file"*. It can only say *"some caller set a flag"*.

The temptation is obvious and wrong. The object is constructed in `main.py`, three callbacks
are wired, and a validator is reachable from the clipboard — so `process()` looks like a
missing feature rather than a dangerous one. Wiring it would produce a working
propose→validate→execute pipeline whose authorization step is exactly the defect
ARCH-ENG-165 closed. **The absence of the caller is currently doing the work the
authorization layer cannot do.**

That is the third time in the depth pass a "fix" has turned out to be the wrong move —
after `AJ-02` (`11r`, where wiring `run_audit` would have produced a healthy-looking report
on empty data) and `AN-03` (`11u`, where wiring `max_loop_depth` would have added a weaker
guard beside a stronger one). The pattern is consistent enough to state as a rule for the
fix list: **for a dead entry point, the first question is not "should this be wired?" but
"what would be true downstream the moment it was?"** Here the honest answer is "a file
would be written on a boolean," and that has to be answered before the wiring, not after.

AQ-02 and AQ-03 are cleanup, and both are fixed by editing text rather than code.
