# 11z — `agents/safety/legacy_tools.py` depth pass (336 lines, 7 module functions)

Depth-pass #26 of 83. **0 dead of 7 — no findings.** The second counter-example file after
`11t`, and the one where the sweep's recurring defect is documented *three times in one
file* — each time with the fix applied at both ends.

---

## Structure

```
L   1-38     module docstring — ARCH-ENG-133 in full
L   41-44    _redact          L   87-92    _list_dir
L   47-56    _is_secret_path  L   95-138   _run_command    (44)
L   59-68    _read_file       L  251-336   execute_tool    (86)
L   71-84    _write_file
```

Docstring: *"Tool definitions for Big Brain tool calling. Uses OpenAI-compatible
function/tool calling schema."*

---

## Findings

None. All seven functions are live, and the module is the best-documented in the depth pass:
**three separate ARCH-ENG fixes are narrated at the point of implementation**, and in each
case the narration names the exact mechanism that produced the defect.

---

## ARCH-ENG-133 — the alias problem, and why these handlers must self-defend

The module docstring (`:19-32`) is the clearest statement of a security architecture in the
whole sweep:

> *"ARCH-ENG-133: `read_file`/`write_file`/`run_command` here are reached through the Big
> Brain tool loop, where SafetyGate classifies `read_file` as an **ALIAS of `file_read`
> (READONLY => ALLOWED)** and dispatches to execute_tool — i.e. to the handlers in THIS
> module, not to the hardened `_tool_file_read` in handlers.py. The private readers below
> therefore have to re-apply the same two layers the hardened path applies, **using the
> SAME authority (`_is_secret_file`) so there is one blocklist, not two that can drift:**
>
> 1. SECRET FILES are refused outright (the value IS the whole file).
> 2. every other file's content passes through `redact_secrets`, so a secret pasted into a
>    readable file (README, notes) is scrubbed before it enters model context."*

**The subtle part is the aliasing.** The SafetyGate is not bypassed — it classifies
`read_file` as READONLY and therefore ALLOWED, and that classification is correct for the
*intent*. But READONLY ⇒ ALLOWED means **the gate provides no protection at all for reads**,
so an alias that looks innocuous to the gate routes around the hardened handler. Anyone
reading only the gate's policy would conclude reads are protected. They are not.

The fix is not to change the gate; it is to make the aliasing destination as safe as the
canonical one — and to do it by *importing the same predicate* rather than reimplementing
it. `_read_file:66` calls `_is_secret_file(p)`; `_write_file:76` calls it again;
`_is_secret_path:50,54` calls it twice; `execute_tool:321` calls it a fourth time. **One
blocklist, four call sites, zero copies.**

The test names record what was at stake (`tests/safety/test_arch_eng_133_legacy_tools_secrets.py:8-9`):

> *"`legacy_tools.execute_tool` — NOT to the hardened `handlers._tool_file_read`):
> `execute_tool('read_file', {'path': '.env'})` → 13,418 chars, 264 keys
> `execute_tool('read_file', {'path': 'wallet.key'})` → the raw Fernet key"*

---

## ARCH-ENG-211 — the hardened path was *more* permissive than the one it replaced

`_run_command:105-117` is the sharpest defect description in the sweep, because the
inversion is counter-intuitive:

> *"ARCH-ENG-211: this scan is no longer private to this function. It used to exist ONLY
> here, which meant the other dispatcher — the hardened one in
> `handlers._tool_run_command` — **never consulted it**. So `type .env` was **refused**
> through the Big Brain tool loop and **executed** through dispatch.
> **The hardened path was strictly more permissive than the path it replaced.**
>
> Both now call `refuse_secret_argv`, which uses the same `_is_secret_file` authority this
> module already imported — so ARCH-ENG-133's 'one blocklist, not two that can drift' is
> **finally true of the dispatchers, not just of the blocklist.**"*

Read that failure carefully, because it generalises past this codebase:

1. The Big Brain loop was called "legacy" and was assumed to be the weaker path.
2. It was hardened first, privately — the secret-argv scan was written into `_run_command`
   and nowhere else.
3. The hardened dispatcher was built second, correctly, from a *different* set of checks
   that simply did not include the argv scan.
4. So the hardened path inherited **strictly fewer** protections, and nobody noticed because
   "hardened" was a property of the label.

**The fix is stated as a property of the pair, not of either function:** *"finally true of
the dispatchers, not just of the blocklist."* That is the sweep's recurring defect
recognised from the inside — the drift was between two correct mechanisms, so neither one
looked wrong on its own.

---

## ARCH-ENG-164 — a second, unguarded dispatcher, and a tool that never worked

`execute_tool:255-284` documents both halves:

> *"ARCH-ENG-164 — THIS DISPATCHER HAD NO AUTHORIZATION.*
>
> `agents/safety/dispatch.py:execute_tool` is the gated entry point… This function
> implemented a SECOND, parallel dispatcher that did none of that — it executed `write_file`
> and `run_command` directly, with only the secret-path and argv policy checks below
> standing between a model and the filesystem.
>
> **It was not an active exploit:** the only caller (`agents/brains/big_brain.py`) ran
> `safety_gate.check(...)` itself and only called this on ALLOWED. But the function itself
> was a public, unguarded API, and `agents/earning/router.py:get_tools_for_task` /
> `get_all_tools` advertised its `TOOL_DEFS` — including `write_file` and `run_command` — to
> model-facing callers. **Any new importer would have inherited an unguarded path by
> accident, which is exactly how the second dispatcher came to exist.**"*

Note the reasoning: **not an active exploit, but a public unguarded API with its tool
schemas advertised to model-facing callers.** The fix was judged necessary not because
something was currently exploitable but because the next importer would inherit it. That is
the correct threshold for a security API.

**The same docstring records a tool that has never worked on a stock install** (`:278-283`):

> *"ARCH-ENG-164 also removed a dead import: the `web_search` branch did `from
> hermes_tools import web_search`, and `hermes_tools` has never been a dependency of this
> project (it appears in no requirements file), so that branch **raised ImportError on every
> stock install** and the blanket `except Exception` turned it into a `[Tool error: ...]`
> string."*

So `web_search` was advertised to the model, failed on every install, and reported itself as
a generic tool error. **The blanket `except Exception` at `:335-336` is what concealed it** —
and that handler is also what makes the module correct for its actual purpose, since a tool
that raises gives the model nothing it can reason about. The fix was not to remove the
blanket except; it was to find the branch that *always* failed and point it at the real
implementation (`agents.safety.calling._tool_web_search`).

---

## Verified as sound — wired at both ends, with an unforgeable token

The `_DISPATCH_CAPABILITY` check at `:298` is `authorization is not _DISPATCH_CAPABILITY`,
and the sentinel is `object()` (`agents/safety/calling.py:53`). **Identity comparison
against a module-private object is unforgeable** — a caller cannot pass it without importing
it, and importing it is a visible act in the source.

Both mutating paths obtain it legitimately:

| path | line |
|---|---|
| Big Brain tool loop | `agents/brains/big_brain.py:304-307` — `execute_tool(fn_name, arguments, authorization=_DISPATCH_CAPABILITY)`, with a comment at `:300` explaining why |
| hardened dispatcher | `agents/safety/dispatch.py:127` — `handler(arguments, authorization=runtime._DISPATCH_CAPABILITY)` |

**The negative case is tested at integration level** —
`tests/runtime/test_end_to_end_recovery.py:18` calls
`execute_tool("run_command", {"command": "echo must-not-run"})` with no token, asserting the
command does not run. That is the test that would catch a regression on ARCH-ENG-164.

**Read-only tools deliberately keep working without a gate** (`:273-276`): *"Read-only tools
keep working unchanged so the ARCH-ENG-133 secret-redaction guarantees (which are tested
here) still hold — they never needed a gate, only the two layers applied below."* That is a
correct scoping decision: gating reads would add ceremony without adding protection, since
the protection is content redaction, not authorisation.

**The alias check is defensive in the right direction** (`:286-297`). `MUTATING_TOOLS` holds
canonical names (`file_write`), this module dispatches on its own (`write_file`), and
canonicalizing would rewrite `read_file` → `file_read` and fall through to `[Unknown tool]`.
So it checks **both spellings** rather than translating — and falls back to a literal set if
the import fails. The comment states the reason rather than leaving the duplication to be
discovered.

**`_run_command`'s subprocess call is well-formed** (`:120-129`): `shell=False`,
`command_argv(cmd)` (parsed, not a shell string), `timeout=30`, `CREATE_NO_WINDOW`,
**`encoding="utf-8", errors="replace"`** — the last being the fix `11q` found missing from
`run_lead_routine.py:678`. Refusals and errors return strings, never raise (`:99`).

**`analyze_document` refuses before reading** (`:316-322`), rather than relying on
`_read_file`'s own refusal — because the analysis block would otherwise have a copy of the
content in hand before any check ran.

**`query_database` routes through `execute_readonly_query`** (`agents/safety/sql.py`), so the
model's SQL cannot write.

**`tests/safety/test_safety_gate_registry_alignment.py` guards the drift class directly** —
its docstring is *"Add a new tool to `execute_tool` (or to the schema) without classifying
it in…"*. A test whose stated purpose is to prevent a tool existing in one registry and not
the other is the structural answer to ARCH-ENG-133's "two blocklists that can drift."

---

## Re-verification

**`10p` confirmed and closed.** `10p` recorded `legacy_tools.py:265` — *"the only caller
(`agents/brains/big_brain.py`) ran `safety_gate.check(...)`"*. That is now a historical note
inside the ARCH-ENG-164 docstring, and `big_brain.py:304-307` shows the finished state: the
loop imports the token and passes it.

**`11g` consistent.** `11g` verified `handlers.py`'s `_SECRET_FILE_NAMES` and
`_tool_propose_code_patch`. This file imports `_is_secret_file` and `refuse_secret_argv`
*from* that module (`:14`) — so the authority named in both docstrings is the same object.

**`11t` extended.** The approval queue remains the only producer of authority, and this
file's mutating tools reach it through `dispatch.py`. The queue is intact and both
consumers are wired.

**`11q` contrasted usefully.** `run_lead_routine.py:678` (`text=True`, no `encoding=`) versus
`_run_command:128` (`encoding="utf-8", errors="replace"`) — the same call shape, one hardened
and one not. The difference is that `_run_command`'s call was written after ARCH-ENG-211 and
the other predates it.

**ARCH-ENG-165 unaffected.** This module's gate is the token, checked *before* dispatch
(`:298`), which is stricter than the verified/unverified distinction in
`authorization.py:78-87`. There is no "caller-asserted" path here at all — the token is
binary.

---

## Assessment

Zero dead of seven, no findings, and no caveats.

This file is worth a document for the same reason `11t` was: it is the **positive control**
for the sweep's central finding, at the highest stakes in the codebase. `11t` showed the
approval queue wired at both ends; this shows the *tool-execution surface* wired at both
ends, with the token unforgeable, the negative case tested at integration level, and a
registry-alignment test guarding the drift class structurally.

The three docstrings are also the best available answer to a question the sweep keeps asking:
**what does a well-handled instance of the recurring defect look like?** Each one names the
mechanism rather than the symptom — "the scan existed only here, so the other dispatcher
never consulted it"; "the gate classifies the alias as READONLY, so it dispatches here
instead of the hardened handler"; "any new importer would have inherited an unguarded path
by accident." A finding that says *"this could be exploited"* teaches a reader nothing; a
finding that says *how the second path came to exist* tells them how the next one will too.

If one thing were to be changed here, it would be a note in `handlers.py` pointing at
`_run_command:105-117` — because ARCH-ENG-211's lesson is that the *hardened* path is the
one that silently lost a protection, and that is the assumption every future reader will
bring to this file.
