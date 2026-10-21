# 11g — `agents/safety/handlers.py` depth pass (992 lines, 30 functions)

> **AA-01 PINNED in v2.1.125 (ARCH-ENG-268).** `_tool_propose_code_patch` is the
> one mutating handler that does not declare the dispatch `authorization` kwarg
> -- correctly, because it routes through `CodePatchService`, which owns its
> approval. That exception is now a structural test rather than a comment:
> every other `MUTATING_TOOL_NAMES` handler must declare the keyword-only
> capability and call `_require_mutation_capability`, and no `READONLY_TOOL_NAMES`
> handler may. No production change -- the convention already held.
>

Depth-pass #7 of 83. **Zero dead functions.** The security-critical file is the
most completely wired in the repository — and re-verifying it produced the most
important correction of the depth pass.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AA-01 | low | **`_tool_propose_code_patch` (`:224`) is the one handler that does not declare the dispatch `authorization` kwarg — correctly.** All 19 other handlers match the correct pattern: read-only tools take a single positional `args` and receive no capability, while the mutating ones declare `authorization` and enforce it. `propose_code_patch` neither mutates nor needs the capability: it *"Rehearses a patch on a copy, then queues it for human approval"* and the actual write happens later in `CodePatchService.apply_approved` after approval. It is not in `HIGH_TRUST_ACTIONS` (`trust.py:21-22`). Recorded because the capability convention is enforced by *declaration*, so a future handler that mutates without declaring `authorization` would silently fall into the read-only branch — see AA-02. |
| AA-02 | info | **The capability convention's failure mode is safe but silent.** `dispatch.py:_accepts_authorization` uses `inspect.signature` to decide whether to pass `_DISPATCH_CAPABILITY`. A mutating handler that forgot to declare the kwarg would receive **no** capability — and would then be refused by the handlers that check it, so it fails closed. That is the correct direction, but the refusal would present as a runtime error rather than a registration mistake. Nothing currently tests that a mutating handler declares the kwarg. |

---

## Re-verification — a correction to O-01

**O-01 is over-scoped and must be amended.** In `10p` I recorded that `coder.py`
(318 lines) is never instantiated, that ARCH-ENG-204 hardened a component that has
never run, and framed the self-improvement chain as unusable.

`handlers.py:229-236` documents the same problem from inside the codebase — and says
it was **already fixed**:

> *"`CoderWorker` -- the only class that could ever call
> `self_improvement_commands.propose_code_patch` -- had zero callers anywhere in the
> codebase. So the Self-Improvement tab's whole chain (propose → approve → apply →
> verify → rollback → post-apply monitor) was fully built, fully gated, and could
> never be entered… **The loop was closed and empty.**"*

and at `:227`, on the function itself: *"ARCH-ENG-227. **This is the propose hop
that was missing.**"*

Verified that the fix is complete and live:

| Layer | Site |
|---|---|
| Canonical tool schema | `agents/safety/tools.py:59` — `"name": "propose_code_patch"` |
| Gate classification | `agents/safety/gate.py:52` |
| Dispatch table | `agents/safety/dispatch.py:108` |
| Re-export | `agents/safety/calling.py:161` |
| Implementation | `agents/safety/handlers.py:224` |

**So the model can call `propose_code_patch`, and it routes through
`execute_tool` → the authorization gate → `self_improvement_commands`.** The
self-improvement loop is enterable. My finding stands for `CoderWorker` itself — it
is dead, and ARCH-ENG-204 hardened a component that has never run — but I attributed
to that fact a consequence the codebase had already addressed, and the tool entry
point exists.

The residual is narrower and more precise than O-01 stated: **there are now two
propose paths** (a dead worker and a live tool), which is a de-duplication question
rather than a broken-loop question.

---

## Verified as sound — the best security engineering of any file in the project

**`dispatch.execute_tool` is the single authorization and routing entry point**, and
all 20 handlers are in its table (`:95-116`). Every failure path returns an
operator-readable string rather than raising: `[Unknown tool: …]`, `[BLOCKED] …`,
`[PENDING APPROVAL] … {name} was not executed`, `[Tool error: …]`.

**ARCH-ENG-165's approval binding is explicit** (`:44-49`): with an `approval_id`
the approval is *"VERIFIED against the shared queue via `assert_approval_covers`,
so it must name THIS tool and these exact arguments — an approval for one amount or
path cannot execute another."* Without an id the upgrade is *"caller-asserted and
unverified"* and the docstring says so.

**An alias bug is documented with its reproduction** (`:55-63`): aliases were
resolved by `is_known_tool` and the gate but not by the handler table, so
`execute_tool("write_file", …, approved=True)` returned `[Unknown tool: write_file]`
*"even though the identical file_write call succeeded. The operator approved an
action that could never run."* That is a defect class I searched for elsewhere in
this codebase and did not find — a gate that classified something the dispatcher
could not route.

**`_accepts_authorization` documents why it exists** (`:16-19`): passing
`authorization=` to a handler that does not declare it *"raises TypeError, which
would take out every read-only tool — exactly the ones the gate auto-allows."*
The capability is handed over at `:126-127` with the matching explanation.

**Both secret blocklists are intact and layered** — `_SECRET_FILE_NAMES` (`:516`,
covering `.env`, `wallet.key`, `platform_vault.key`, `platform_vault.json`,
`wallets.json`, `credentials.json`, `secrets.json`, `.netrc`, `.npmrc` plus the
`.key`/`.pem`/`.pfx`/`.p12`/`.keystore`/`.env` suffixes) and the workshop-specific
`_WORKSHOP_SECRET_FILE_NAMES` (`:564`, covering `accounts.json`, `payments.json`,
`payment_methods.json`), with `_is_workshop_secret_path` (`:571`) walking every path
segment and delegating to `_is_secret_file` for the rest. This matches `10j` and
`10l` exactly, and confirms the ARCH-ENG-134 near-miss recorded there is still
resolved.

**The SSRF guard is applied at the tool entry** (`_tool_web_read`), which is precisely
the boundary I-01 identified as correctly guarded while noting the browsing layer
below it is not.

---

## Assessment

Zero dead of 30 in the file that implements every file tool, the SSRF guard, the two
secret blocklists and the code-patch propose hop. Combined with `11b`'s
`provider_lifecycle_backend.py` (61 of 63) this is the strongest wiring evidence in
the sweep for the safety boundary specifically.

AA-01/AA-02 are minor. The capability convention works, fails closed, and its only
latent risk — a mutating handler that forgets to declare `authorization` — would
present as a runtime refusal rather than silently succeeding. Worth a test, not a
fix.

The AA-01 correction to O-01 matters more than anything else in this pass. It is the
third time the depth pass has produced a correction, and the pattern in all three is
the same: **a finding that was directionally right and materially over-scoped about
consequences.** W-02 (three feature gates in dead code), the `10i` amendment
(`CONFLICTED` modellable but not resolvable), and now O-01 (the loop is enterable via
a tool) all share a shape — the mechanism was correctly identified, and the
reachability claim was checked one hop short of where the real entry point was.