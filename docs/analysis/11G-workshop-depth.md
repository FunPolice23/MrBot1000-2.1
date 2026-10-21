# 11G — `agents/knowledge/workshop.py` depth pass (997 lines, 52 methods)

> **AY-02 RESOLVED in v2.1.125 (ARCH-ENG-245).** The operator's rule for
> this item was: verify whether the subsystem is superseded, delete if so,
> wire if not. Verified: it was never one feature. `get_template` served
> four hardcoded skeleton strings from memory and NEVER read the
> `templates/` directory `save_template` wrote; `save_template` wrote files
> that nothing could read back (not get_template, not any tool, not any
> GUI). A saved template was unreadable by construction. And better code
> exists for the load-bearing use: proposal copy is served by the LIVE
> A/B intro mechanism (`agents/knowledge/proposal_templates.py`, wired at
> `agents/earning/proposal.py:25`), which learns which copy wins; the
> document skeletons are what an LLM persona generates natively.
> Therefore the subsystem is DELETED -- both methods, the section, and the
> `templates` PATHS entry that made every Workshop init create an empty
> directory on the operator's disk for no writer and no reader. The
> deletion is pinned executably
> (`tests/engineering/test_arch_eng_245_templates_removed.py`), per this
> doc's own AY-04 concern.
>
> **AY-01 RESOLVED in v2.1.125 (ARCH-ENG-248) — wired, not deleted.**
> Operator disposition: wire the FULL typed surface. The workshop could
> write structured documents through tools but not read one back through
> the same contract: twelve typed readers/status/removal methods were dead,
> and five typed writers (research, script, application, deliverable,
> note) had never been exposed. Twenty tools now cover the surface —
> thirteen read tools (proposal list/get, research read/list, script
> read/list, application list, account get/list, payment get/list,
> deliverable list, note list) and seven writes (proposal status, research,
> script, application, account remove, deliverable, note) — with schemas,
> handlers, dispatch and SafetyGate classification. The typed readers call
> the typed methods, keep ARCH-ENG-134's secret-path refusal and
> `redact_secrets`, and mask account passwords: the raw store is a refused
> secret file, so a typed reader that returned the dict verbatim would
> have re-opened the boundary. `workshop_account`/`workshop_payment` were
> dispatchable and gated but absent from the model-facing registry — that
> wiring gap is closed too. ARCH-ENG-214's anti-drift guard forced every
> new failure prefix into `_NOT_EXECUTED_MARKERS`.

Depth-pass #33 of 83. **23 dead of 52 — 44%, the highest dead proportion in the sweep.** The
quota and write path are among the best-engineered in the codebase. The dead surface is one
coherent shape, and its history is recorded in a test.

---

## Structure

```
L   30-58    _atomic_write_json (29)   — tmp + os.replace + cleanup on failure
L   63-74    WORKSHOP_ROOT, WORKSHOP_MAX_BYTES (ARCH-ENG-221)
L  114-136   WorkshopWriteError
L  139-923   Workshop (48 methods)
L 2244+      get_workshop, create_proposal (module level)
```

Docstring: *"Workshop workspace manager for MrBot1000 personas. Gives Edward Hurst and Jacob
Stanley a real workspace at `D:\ai_workshop` for: Proposals… Research… Scripts…
Applications…"*

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AY-01 | **med** | **23 dead of 52 — the Workshop is a write-mostly surface.** Seven write methods exist; **their twelve readers are dead**: `get_proposal` (`:423`), `list_proposals` (`:427`), `update_proposal_status` (`:431`), `get_account` (`:587`), `remove_account` (`:597`), `read_research` (`:472`), `list_research` (`:476`), `read_script` (`:512`), `list_scripts` (`:516`), `list_applications` (`:554`), `list_deliverables` (`:722`), `list_notes` (`:836`). A persona can write a proposal and then not list it, fetch it by id, or change its status. |
| AY-02 | **med** | **The template subsystem is entirely dead** — `get_template` (`:728`, **80 lines, the largest dead method in the depth pass**) and `save_template` (`:809`, 5 lines). Nothing writes a template and nothing reads one. |
| AY-03 | info | **Three small utilities dead:** `get_file_info` (`:362`, 16 lines), `list_dirs` (`:347`, 9), `file_exists` (`:357`, 4) — the `list_files` path at `:324` is live, so the directory-listing surface is half-present. |
| AY-04 | info | **The executable record is asymmetric.** `tests/engineering/test_arch_eng_206_207_removals_hold.py` exists specifically to make *deletions* checkable — *"A deletion with no executable check is a claim, not a change: the next person cannot tell deliberate removal from accidental loss."* Nothing makes the **retention** of these 23 methods checkable. They could be deleted tomorrow, no test would fail, and no record would show anyone chose to keep them. |

---

## AY-01 — the history is recorded, and it is a near-miss worth reading

`test_arch_eng_206_207_removals_hold.py:1-23` tells the whole story:

> *"**ARCH-ENG-206** removed genuinely dead code (`workflow_engine.py`, `cost_tracker.py`,
> `agents/polish/`, **seven `workshop.py` shims**, two unused event-logger callbacks)."
> …
> * `get_workshop` and `create_proposal` **stay** — **the audit that prompted their removal
>   said "8 shims", but those two have 11 and 1 callers respectively.**"*

So an audit counted 8 dead methods in this file, **7 were correctly removed, and 2 were
wrongly flagged** — `get_workshop` (11 callers, via nine sites in `agents/safety/handlers.py`
plus `dialogue_tab.py:3159`) and `create_proposal` (1 caller). Both were rescued by hand, and
the test now pins them so the next audit cannot repeat the error.

**This also corrects a note carried in the sweep's own history**, which recorded *"8 dead
`Workshop` methods had tests"* as an instance of the *"presence of tests implies a live
function"* heuristic failing. The accurate account is different in an instructive way: the
audit said **8**; **7 were real and removed**; the 2 it wrongly named were live. **The
heuristic did not fail here — the count was simply wrong, and the correction mechanism
worked.**

**But the survivors were never triaged.** 21 methods beyond the 7 removed remain, with no
recorded decision either way. They are not "shims" — the removed seven were thin wrappers,
whereas what remains is a **complete CRUD surface** whose create half is wired to tools and
whose read half is not:

| written (live) | read (dead) |
|---|---|
| `create_proposal` `:381` (41L) | `get_proposal`, `list_proposals`, `update_proposal_status` |
| `add_account` `:560` (26L) | `get_account`, `remove_account` |
| `add_research` `:442` (29L) | `read_research`, `list_research` |
| `create_script` `:482` (29L) | `read_script`, `list_scripts` |
| `create_application` `:522` (31L) | `list_applications` |
| `add_deliverable` `:702` (19L) | `list_deliverables` |
| `add_note` `:817` (18L) | `list_notes` |

**The write half is reachable through tools** — `agents/safety/handlers.py` calls
`get_workshop()` at nine sites (`:359`, `:383`, `:405`, `:420`, `:431`, `:441`, `:461`,
`:476`, `:491`) — and the *consequences* are visible: a persona that writes a proposal
through `workshop_write` cannot read it back through any workshop tool, because
`read_research`/`read_script`/`list_*` have no callers.

That is AY-01's practical shape: **the tool surface can deposit into the workspace but not
retrieve from it.** Given ARCH-ENG-198/199's work on making the workshop legible
(`11A`'s skill index is the other half of that), a write-only workspace is a gap in the same
story — the operator's personas can litter the workshop and neither they nor the operator can
enumerate what is in it.

---

## Verified as sound — the quota is the best engineering in this file

**ARCH-ENG-221's quota is enforced against two independent limits** (`_can_write:228-237`):

```python
delta = max(0, content_size - current_size)
stats = self.storage_stats()
return delta <= stats["remaining_bytes"] and delta <= stats["free_disk_bytes"]
```

**Quota *and* physical free disk**, with the `and` — a write is refused if it would breach
*either*. And `delta` is computed against the existing file size, so **rewriting a file does
not double-count it**; a 1 MiB file rewritten as 1 MiB costs zero against the quota.

**`_invalidate_usage:213-215` (ARCH-ENG-221) drops the cached total after every mutation**, so
the quota cannot be enforced against a stale figure — and the docstring says why it exists
rather than leaving the cache looking like an optimisation.

**The reasoning behind the 2 GiB default is stated in terms of this machine** (`:65-71`):

> *"ARCH-ENG-221: WAS 10 GiB. The target machine has 32 GB of RAM, and a 10 GB workshop quota
> lets the workspace consume a third of the machine's entire memory budget as disk, starving
> the page cache and swap headroom that a locally-hosted 8-10 GB GGUF model depends on. The
> quota is still overridable via `MRBOT_WORKSHOP_MAX_BYTES` for an operator who wants the old
> headroom."*

That is the CPU/RAM-accounting discipline `11j` recorded, applied to disk: the quota was
lowered **because** a local GGUF model needs the page cache, and the old value is still
reachable by env var rather than hardcoded away.

**ARCH-ENG-221 also capped the single-file read** (`:76-82`), and the comment traces where the
unbounded value would have gone: *"`read_file` did an uncapped `f.read()`, and its result
flows to `redact_secrets(...)` in `agents/safety/handlers.py:247` and then into a tool result
— i.e. into RAM **and into the model's context window**. With a 2 GiB quota, one call could
try to pull 2 GiB into a prompt. **The truncation is explicit rather than silent**, so the
model can see that it is looking at a…"*

**Every write funnels through one method.** `_write_or_raise` (`:269`) is the sole exit for
all seven write paths (`:421`, `:470`, `:510`, `:552`, `:720`, `:813`, `:834`), each naming
what it is writing so `WorkshopWriteError` can say which operation failed — which is what
`test_arch_eng_215_workshop_write_honesty.py` asserts.

**`_atomic_write_json` (`:30-58`) is a textbook atomic write** — temp file, `os.replace`, and
`os.unlink(tmp)` in an `except OSError: pass` before re-raising, so a failed replace does not
leave debris.

**Reads are secret-guarded at the tool layer**, not here: `test_arch_eng_134_workshop_read_secrets.py:41`
notes the patch point is *"once `agents.knowledge.workshop` has been imported"*, i.e.
`handlers.py`'s `_WORKSHOP_SECRET_FILE_NAMES` (`11g`) is the authority. This module's own
`_safe_path` handles traversal; the secret blocklist is the caller's — the same
"one blocklist, not two that can drift" arrangement `11z` documented for `_read_file`.

---

## Re-verification

**`11g` confirmed.** `_WORKSHOP_SECRET_FILE_NAMES` (`handlers.py:564`) is the secret authority
for this workspace, and the nine `get_workshop()` call sites in that file are what make
`create_proposal`, `add_account` and `storage_stats` live.

**`11A` consistent.** `skill_index.py`'s `workshop_root()` defaults to `D:/ai_workshop`; this
module's `WORKSHOP_ROOT` (`:63-64`) reads the same two env vars (`MRBOT_WORKSHOP_ROOT`,
`AI_WORKSHOP_ROOT`) with the same fallback. `agents/services/patch_sandbox.py:47` carries a
third copy with the comment *"Same default as `agents.knowledge.workshop`, kept [in sync]"* —
**three copies of one path constant, one of which acknowledges it.** Worth folding into one
helper when the fix list is assembled; it is the mildest version of the pattern `11v`'s AO-02
found harmful, since here all three currently agree.

**`11z` / ARCH-ENG-211 pattern, inverted.** `legacy_tools` had a protection that existed in
one dispatcher and not another. Here the protection exists in the caller (`handlers.py`) and
not in the callee — which is correct for a blocklist that must not drift, and is why the
`Workshop` methods carry no secret checks of their own.

**ARCH-ENG-198/199 confirmed as a pair.** ARCH-ENG-198 made the workshop *visible* to the
personas; ARCH-ENG-199 made its skills *legible*. This pass finds the third piece — the
workspace's own contents — still write-only.

---

## Assessment

Forty-four percent of this module is dead, and the shape is unusually legible: **a CRUD surface
whose create half is wired to tools and whose read half is not.**

That is worth separating from the usual sweep finding, because the usual finding is *"a
mechanism is not called."* Here it is closer to *"a mechanism is called, and calling it is
incomplete"* — the tool surface deposits proposals, research notes, scripts, applications,
deliverables and notes into `D:\ai_workshop`, and no path exists to enumerate or retrieve
them. An operator auditing what the agent has written to their disk has to open Explorer.

**AY-01 and AY-02 are one decision, not two.** The 21 untriaged survivors plus the 85-line
dead template subsystem are the same question: *is the workshop a workspace the personas can
work in, or a sink they write into?* The docstring answers "a real workspace… Proposals:
create, store, manage" — and **"manage" is exactly the dead half.** `update_proposal_status`,
`get_proposal` and `list_proposals` are the "manage" the module's own description promises.

That makes the fix unusually clean to state: either wire the read half to the existing tool
surface (nine call sites already exist in `handlers.py` to model on), or delete it and amend
the docstring. What should not happen is a third option — leaving 23 methods in place with no
record of why, which is what AY-04 describes and what ARCH-ENG-206 nearly made permanent when
it miscounted.

**The scan's own record is worth keeping alongside this.** ARCH-ENG-206 removed 7 methods
from this file and misidentified 2 more; the test that resulted now prevents that specific
error from recurring. That is the codebase doing the right thing about a deletion — and the
23 survivors are the residue of the audit that never finished, rather than a fresh discovery.
