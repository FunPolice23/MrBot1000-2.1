# 10o — `agents/safety/`

> **N-01 RESOLVED in v2.1.125 (ARCH-ENG-292).** `agents/earning/router.py` no
> longer defines or exports a second `get_all_tools()`. The canonical
> `agents.safety.tools.get_all_tools` is the only public registry; the legacy
> task-scoped selector remains for `BigBrain`'s existing worker loop, but it is
> no longer advertised as a whole-registry alternative.

22 scripts, 5,920 lines. The approval queue, trust boundary, authorization
dispatcher, tool schemas, instruction quarantine, and the file-tool guards that
several earlier findings point at.

---

## Structure and reachability

**No dead modules.** Every one of the 22 has at least one production consumer.
The area is the most heavily wired in the repository:

| Module | Lines | Outside consumers |
|---|---:|---:|
| `approval.py` | 636 | 21 |
| `handlers.py` | 992 | 7 |
| `guard.py` | 782 | 8 |
| `legacy_tools.py` | 336 | 2 |
| `calling.py` | 237 | 4 |
| `provider_rate_limiter.py` | 207 | 5 |
| `instructions.py` | 214 | 3 |
| `authorization.py` | 154 | 1 |
| `cost.py` | 168 | 3 |
| `workspace.py` | 284 | 2 |
| `gate.py` | 168 | 3 |
| `gates.py` | 257 | 1 |
| `dispatch.py` | 133 | 1 |
| `circuit.py` | 112 | 1 |
| `filesystem.py` | 355 | 1 |
| `trust.py` | 89 | 2 |
| `response.py` | 289 | 1 |
| `sql.py` | 53 | 1 |
| `learning.py` | 21 | **0** |
| `policy.py` | 46 | 0 (intra only) |
| `tools.py` | 301 | 0 (intra only, but live — see below) |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| N-01 | med | **Two public tool-definition registries coexist, and the canonical one is not the only one advertised.** `agents/safety/tools.py` is titled *"Canonical tool schema registry"* — a single 293-line `get_all_tools` — and it **is** what the model-facing loop actually uses: `agents/safety/calling.py:111` imports it, re-exports it, and `agents/dialogue/chat_completion.py:9` consumes it from there. But `agents/earning/router.py:119-122` defines a **second** `get_all_tools`, exported publicly at `agents/earning/__init__.py:74`, which reads from a *different* source entirely: `from agents.safety.legacy_tools import TOOL_DEFS; return list(TOOL_DEFS)`. So the two public functions of the same name return different tool sets. The project has already documented this exact hazard in `legacy_tools.py:265-271`: the earning router *"advertised its `TOOL_DEFS` — including `write_file` and `run_command` — to model-facing callers. Any new importer would have inherited an unguarded path by accident."* That hazard was mitigated by requiring the `_DISPATCH_CAPABILITY` token (`legacy_tools.py:273-276`), so a new importer is now blocked rather than exploitable — but the duplication itself remains, and a caller using the earning router still gets a different tool list than the canonical registry. |
| N-02 | low | **`learning.py` (21 lines) is dead.** `LearningSafetyBoundary` — *"Safety boundary between learned preferences and actual execution"* — has four production references: its own `class` at `:6`, its `__all__` at `:21`, and the `agents/safety/__init__.py` facade at `:29` and `:79`. No consumer. Given the area's subject matter, this is worth a second look rather than deletion — a boundary between learned preferences and execution is a guardrail someone intended, and it currently guards nothing. |
| N-03 | low | **Executable debris sits inside the working tree and corrupts tree-wide analysis.** `tmp/` holds six untracked Python scripts — `probe_concurrency.py`, `probe_concurrency2.py`, `probe_concurrency3.py`, `probe_repeat.py`, `probe_review.py` (103 lines) and `ae151_sweep.py` — plus `dbl` and `subtest` as zero-byte files and four `suite_run*.txt` artifacts. `.mrbot_backups/arch_eng_167_root_debris/` holds `_dbg3.py` and `_dbg4.py`. **None are tracked by git** (`git ls-files` returns nothing for all of them), so they cannot reach the public mirror and this is not a disclosure risk. The concrete cost is analytical: this sweep's own reachability scan counted `_dbg3.py`/`_dbg4.py` as production consumers of `approval` and `probe_concurrency*.py` as consumers of `guard`, inflating both counts. Any future audit, code-map generator or coverage tool that globs `**/*.py` will hit the same problem. Recorded rather than removed, per the standing instruction — but it should be gitignored explicitly, since "untracked" is currently incidental rather than declared. |
| N-04 | info | **`policy.py` (46 lines) has no consumer outside `agents/safety/`.** Checked by module and import form but not by symbol, so this is recorded as intra-package-only rather than dead. |

---

## Verified as sound

**The authorization path is layered and consistently token-gated.** `handlers.py`
is reached through `composition_root`, `context` and `executor`;
`authorization.py` provides `AuthorizedActionDispatcher`; `dispatch.py` is the
boundary the main app calls. `legacy_tools.py:273-276` states the rule for mutating
tools plainly: *"Mutating tools now require the same `_DISPATCH_CAPABILITY` token
the hardened handlers require. Read-only tools keep working unchanged so the
ARCH-ENG-133 secret-redaction guarantees (which are tested here) still hold — they
never needed a gate, only the two layers applied below."* Separating read-only
from mutating, and applying the gate only where it is needed, is the right shape.

**ARCH-ENG-164 removed a dependency that never existed.** `legacy_tools.py:278-280`
records that a `web_search` branch did `from hermes_tools import web_search` where
`hermes_tools` *"has never been a dependency of this project (it appears in no
requirements file)"*. The fix documents the evidence rather than just the change.

**`approval.py` is the most-wired module in the repository** at 21 outside
consumers, consistent with its role as the human-approval choke point that
`registration.register_with_vault`, `platform_submitter`, `live_trading` and the
ARCH-ENG-043 win-rate gate all depend on.

**The instruction quarantine and SSRF guard live here** — `instructions.py`
(`QuarantinedInstruction`, `InstructionGate`, `_is_safe_fetch_url`), assessed in
`10j` and `10l`, and structurally sound.

---

## Assessment

This is the area the whole architecture is arranged around, and it shows: no dead
modules, 21-way wiring on the approval queue, and a dispatch boundary that
separates read-only from mutating tools rather than gating everything uniformly.

N-01 is the finding worth acting on, and its significance is that the codebase
already identified it. `legacy_tools.py:265-271` is a precise statement of why a
second tool advertisement is dangerous — *"Any new importer would have inherited an
unguarded path by accident, which is exactly how the second dispatcher came to
exist."* The hazard was closed at the token layer but the duplication that enabled
it was left in place. Today the two functions return different lists and only one
of them is canonical; a future caller reaching for `agents.earning.get_all_tools`
would get a different answer and no signal that anything is wrong.

N-02 is small but worth a deliberate look rather than deletion, on the same logic
as `goal_system.py` (G-02): a boundary between learned preferences and execution
sounds like a guardrail someone meant to install, and its absence may be an
oversight rather than a decision.

N-03 is bookkeeping, but it has already cost this sweep real accuracy twice in one
area, and the fix is one `.gitignore` line rather than a decision.