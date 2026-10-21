# 10b — `agents/brains/`

> **B-01/B-02 RESOLVED in v2.1.125 (ARCH-ENG-288).** `PROTECTED_SOURCE_FILES`
> now names the trust boundary itself (`gate.py`, `approval.py`,
> `authorization.py`, `dispatch.py`, `handlers.py`, `calling.py`, `tools.py`,
> `instructions.py`, `filesystem.py`, `worker_safety.py`,
> `code_patch_service.py`, `composition_root.py`), and
> `CodePatchService._assert_patchable()` refuses both that set and
> `FILENAME_BLOCKLIST` by basename. The service is no longer the one source-write
> path that can edit the approval gate.

14 scripts, 3,494 lines. `WorkerAgent` plus the Big/Small Brain model adapters and
the "legacy worker" mixin layer.

---

## Structure

| File | Lines | Role |
|---|---:|---|
| `__init__.py` | 1 | package marker |
| `worker_provider.py` | 20 | keep-alive normalisation |
| `worker_thinking.py` | 78 | thinking-response helpers |
| `worker_budget.py` | 48 | context-window lookup |
| `worker_workspace.py` | 46 | workspace inspection |
| `worker_provider_calls.py` | 143 | provider-call compat mixin |
| `worker_safety.py` | 170 | **filesystem + content safety** |
| `worker_llm_mixin.py` | 241 | LLM retry/fallback |
| `base_worker.py` | 345 | `WorkerAgent` + `PROTECTED_SOURCE_FILES` |
| `worker_provider_mixin.py` | 353 | provider registry/selection |
| `shared_context.py` | 354 | cross-model communication |
| `brain_got.py` | 383 | graph-of-thought records |
| `small_brain.py` | 605 | fast chat model adapter |
| `big_brain.py` | 707 | main reasoning model adapter |

`WorkerAgent` is a pure composition root — it declares only three methods and
inherits `WorkerProviderMixin`, `WorkerLLMMixin`, `WorkerProviderCallsMixin`,
`WorkerFilesystemMixin`.

**Reachability — checked, all live.** The mixin layer looked like the usual
"legacy compatibility" smell, so each was traced: every one is imported by
`base_worker.py`, which has 13 production importers outside this directory. Only
`worker_thinking` and `worker_safety` are imported directly from elsewhere
(`gui/tabs/dialogue_tab.py:3653`, `gui/builders/tab_feature_builders.py:2430`).
No orphans in this area.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| B-01 | med | **`CodePatchService` does not consult `PROTECTED_SOURCE_FILES`.** There are three paths that write app source, and only two respect the protection. `agents/safety/filesystem.py:35` (the `file_write` tool) and `agents/services/coder.py:140` both refuse a basename in `PROTECTED_SOURCE_FILES`. `CodePatchService._assert_patchable` (`:279–311`) checks four things — non-empty target, lexical containment, realpath/symlink containment, and extension in `PATCHABLE_EXTENSIONS` — and nothing else. It never imports `PROTECTED_SOURCE_FILES` or `FILENAME_BLOCKLIST`. So the self-improvement path introduced by **ARCH-ENG-227** can propose and, on approval, apply an edit to any `.py` file in the repo, including the ones the other two paths refuse. |
| B-02 | med | **Consequence of B-01: the trust-boundary modules are writable through the patch service.** `PROTECTED_SOURCE_FILES` (30 entries) contains `main.py`, `base_worker.py`, `coder.py`, `database.py`, `earning_pipeline.py` — but **not** `agents/safety/gate.py` (the classification that decides which tools need human approval), `approval.py`, `authorization.py`, `dispatch.py`, `handlers.py`, `tools.py`, `calling.py`, `code_patch_service.py` (the patch approval service itself), or `composition_root.py`. Editing `gate.py` would remove every MUTATING classification; editing `approval.py` would touch the human approval queue. Mitigations that do hold: the tool is MUTATING-classified, a human must click Approve, the change is rehearsed on a copy, and backup/verify/rollback are applied on write. So this is **not an exploit** — but the defence-in-depth that protects `main.py` from accidental truncation does not extend to the files that define the trust boundary. Recorded as an asymmetry to close rather than a live vulnerability. |
| B-03 | low | **`is_safe_filename` matches on substrings, so it over-blocks.** `worker_safety.py:138–141` is `any(bad in lower or lower.endswith(bad) for bad in FILENAME_BLOCKLIST)`. Verified: `hosts_analysis.py` and `secure_backup.py` are **refused** because they contain `hosts` / `secure`, while `security.md` and `ghost.py` pass. **Fail-secure, not a hole** — every floor entry is still caught (`.env`, `.ENV`, `id_rsa`, `config.yaml`, `sudoers` all block). The cost is operator confusion: a legitimate script name is refused with "filename is on blocklist" and no indication of which entry matched. |
| B-04 | info | The Big/Small Brain adapters are the per-request cost centre this sweep has already been through — ARCH-ENG-221 cached `read_metadata` (3,672 ms → 0.213 ms per turn), `detect_devices` (192 ms → 0.005 ms), and `_hardware_line`'s `nvidia-smi` spawn; ARCH-ENG-222 made `_hardware_line`'s config build VRAM-aware. Not re-litigated here; recorded so this area's doc is self-contained. |

---

## Verified as sound

- **`worker_safety.py`'s floor design is correct and well argued.** `FILENAME_BLOCKLIST_FLOOR` cannot be subtracted from — `_apply_floor` is `set(floor) | additions`, so configuration can only *add* protection. The comment records the concrete incident that motivated it (`.env` line 141 held four entries; ten protected filenames including `passwd`, `shadow` and `sudoers` were absent), which is exactly the kind of evidence this codebase's fixes usually carry.
- **`refresh_from_env` mutates in place rather than rebinding the module global.** This is subtle and correct: `base_worker` does `from ... import FILENAME_BLOCKLIST`, which binds the *object*. Rebinding the global would update enforcement while leaving every importer pointing at the stale set — "the name a caller sees and the set actually enforced would silently disagree", which is precisely the ARCH-ENG-201 failure mode. The docstring says so explicitly.
- **`ARCH-ENG-201`'s duplicate blocklist is genuinely gone** — the comment at `base_worker.py:124–137` documents the trap and `worker_safety` is the single definition, re-exported for existing importers.
- **`PROTECTED_SOURCE_FILES` is matched by basename** (`filesystem.py:34`), so absolute paths and nested copies are also refused — the right choice given the list is basenames.

---

## Assessment

The area is in good shape and its safety documentation is the strongest in the
codebase — the floor argument, the in-place mutation, and the note on basename
matching are all non-obvious decisions recorded with their reasoning.

**B-01/B-02 are the actionable pair.** They describe an asymmetry rather than a
breach: the newest write path is the only one of three that skips the shared
protection list, and the list itself was assembled for a different purpose
(preventing accidental LLM truncation of import-critical files, per its comment)
rather than for protecting the trust boundary.

The fix is small and consistent with existing policy — `_assert_patchable` should
refuse a basename in `PROTECTED_SOURCE_FILES` exactly as `filesystem.py:35`
does — but it needs a decision on whether the list should also *grow* to cover
`agents/safety/*`, because that changes what the operator can patch at all. That
belongs in the fix phase, not here.

B-03 is cosmetic-but-confusing and worth a log line naming the offending entry.