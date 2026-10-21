# 11a — `main.py` depth pass (3,735 lines, 100 methods)

> **U-01 RESOLVED in v2.1.125 (ARCH-ENG-284).** The instruction-quarantine
> review surface is live as the Safety tab's fourth sub-tab (list, counts,
> Approve/Blacklist) and calls the same `InstructionGate` the adapters use. The
> dead-but-referenced `MainWindow._refresh_review_queue` / `_review_selected`
> methods are deleted, so there is one review path rather than a resurrected
> second one.
>
> **LOW TIER CLOSED in v2.1.125.** U-03 + U-04 (ARCH-ENG-250/251): the dead
> `_format_ago` formatter and the leftover `_run_http` are deleted. AF-03
> (ARCH-ENG-272): `force_research_rescan` now runs `worker.research_all()`
> instead of telling the operator to visit the Dialogue tab, and falls back to
> `load_latest_research_cache(folder)` when the scan fails. The hidden Ollama
> combo surface removed under AB-01 (ARCH-ENG-275) also lived here; the
> app-level model state is read from `.env` through `_active_ollama_models()`.
>

The largest file in the repository, and the top of the largest-first backlog.
Reviewed at method level. **`main.py` is 96% live — 4 dead of 100** — but one of
the four is a dead island around the system's central trust mechanism.

---

## Structure

```
L   57-90    def   _sanitize_sys_path
L  132-157   def   _ensure_qt_font_directory
L  264-289   def   validate_clipboard_json
L  295-316   class HttpWorker          (2 methods)
L  319-340   class PipelineWorker      (2 methods)
L  343-362   class ModelFetchWorker     (2 methods)
L  368-382   def   _log_html
L  388-400   def   _contrast
L  402-416   def   _log_shutdown_warning
L  419-3682  class MainWindow           (94 methods, 3,263 lines)
```

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| U-01 | **high** | **The instruction quarantine has no operator-facing review surface.** Three methods form a **dead island**, and the whole quarantine review path is unreachable. `_review_selected(approve)` (`:2182`) is the human approve/blacklist action for a quarantined `SKILL.md`; it is called by nothing. `_refresh_review_queue` (`:2163`) populates the review list and is called from exactly one place — `:2216`, inside `_review_selected`. And `self.review_list` is **never assigned**: its only three references are `:2174` and `:2177` (inside `_refresh_review_queue`) and `:2187` (inside `_review_selected`). Calling any of it would raise `AttributeError`. The decisive evidence: the only two `gate.pending(...)` reads in the entire codebase are at `:2175` and `:2199`, both inside those dead methods, and the only production call to `InstructionGate.review(...)` is `:2208`, also inside them. `self.instruction_gate` **is** constructed at `:483` (with a `None` fallback at `:485`), so the gate exists and accumulates pending items — there is simply no way to see, approve or blacklist them. **This is not a security hole** — the quarantine is fail-closed, so an unapproved instruction is never injected, which is exactly the guarantee `registration.py`'s docstring claims when it says *"An untrusted instruction can never satisfy this."* **It is a capability hole in the architecture the quarantine exists to serve**: the human review step is absent, so quarantined content is permanently unapprovable and `platform_skill_urls.py`'s verified `skill.md` fetches (moltbook, ugig) can never graduate from data to usable reference. |
| U-02 | med | **`_human_send` (`:1752`) is a documented no-op stub.** Its body is `pass` and its comment is honest about why: *"Legacy AgentsTab send-box callback (control removed). The Chat tab / N-device Dialogue is the chat authority."* Correctly retained as a compatibility shim and honestly labelled. Recorded so it is not mistaken for a defect — and as a positive example of the codebase marking deliberate dead code rather than leaving it ambiguous. |
| U-03 | low | **`_format_ago` (`:1978`, 12 lines) is dead** — a seconds-to-`"5h 3m ago"` formatter with zero tests. Trivial; the only genuinely dead code in the file that is neither part of a dead island nor a documented stub. |
| U-04 | low | **`_run_http` (`:2218`, 8 lines) is dead.** Immediately follows `_review_selected` and appears to belong to the same removed review-queue feature rather than to the `HttpWorker` class at `:295`. |

---

## Re-verification of earlier findings

Per the depth-pass decision to re-check settled claims that touch the swept code,
**R-02 re-confirmed exactly**: `save_settings` (`main.py:2697-3163`) is 467 lines
with 16 `except Exception`, of which **10 swallow** (`pass` ×9, `continue` ×1) and
**zero** are bare `except:`.

Also re-confirmed in this file:

- **D-01** — `_settings_snapshot` (`:3207`) includes `"MRBOT_ENABLE_CRYPTO"` in
  its restart-diff key list at `:3210`, so toggling the inert crypto checkbox
  still triggers a restart prompt while gating nothing.
- **D-03** — `optional_tabs` (`:1540-1546`) gates `live_trading` and
  `autonomous_learning` by tab visibility only, via `feature_enabled` at `:1551`.
- **ARCH-ENG-043** — `_verify_and_mark_paid` (`:1765-1846`) verified sound exactly
  as recorded in `10h`: three independent fail-closed checks before any secret is
  read, and `is_affirmative_verification` gating the ramp credit at `:1833`.
- **R-01** — `tab_specs` (`:1515-1538`) lists 24 tabs, confirming Collaboration
  and Diagnostics are absent.
- **P-01** — `startup_validation.validate_startup_environment` is absent from
  `main.py`'s startup path, confirming the 93-line validator is never called.

---

## Verified as sound

**`MainWindow` is well-wired at 94 methods.** 90 of 94 are live, and the four dead
ones do not include anything on a safety or payment path.

**The four worker classes are separated cleanly** — `HttpWorker` (`:295`),
`PipelineWorker` (`:319`) and `ModelFetchWorker` (`:343`) each keep network or
subprocess work off the GUI thread, which is the pattern behind ARCH-ENG-223's
tab-specific worker work and `main.py:321`'s note that *"a synchronous
`run_full_cycle()` would freeze the UI"*.

**`_sanitize_sys_path` (`:57`) runs first**, before any import that could resolve
against the wrong tree — the ordering that makes the ARCH-ENG-156 DB-isolation and
fresh-clone guarantees meaningful.

**`validate_clipboard_json` (`:264`) exists at all**, which is the check that keeps
arbitrary pasted JSON from becoming an operator action.

---

## Assessment

`main.py` is in better shape than its size suggests: 96% of its methods are live,
and the failures are localised rather than systemic.

U-01 is the most significant finding of the depth pass, and it is significant
precisely because everything *around* it is excellent. The instruction quarantine
is one of the best-designed trust mechanisms in the codebase — ARCH-ENG-213's
`_is_safe_fetch_url` in front of the fetch, `trusted=False` on return, an explicit
`related` string persisted so a blacklisted document is always ignored, and a
`platform_skill_urls.py` that refuses to list a URL it has not verified
(*"a guessed URL must NEVER be added"*). Every layer of it is present. The one
layer that is missing is the human at the end of it.

That produces an outcome that is safe and useless: quarantined instructions can
never be approved, so `moltbook` and `ugig` playbooks remain permanently
un-referenceable, and the operator has no indication that a queue is growing behind
them. This is the same shape as H-01 (`QualityController`, demo-only) and R-01
(diagnostics computed, never shown) — **a mechanism complete except for the last
hop**, which is now the twelfth instance of the sweep's core pattern.

The fix is small in code and non-trivial in judgement: the three methods are already
written, but `self.review_list` was never created, so this needs a widget as well as
a connection. It is also a good candidate to pair with R-01's Diagnostics tab — both
are "the data is already being computed" situations.

U-02 deserves noting as a positive. The codebase distinguishes *documented
deliberate dead code* (`_human_send`, with a comment explaining the removal) from
*accidental dead code* (U-01, U-03, U-04, with none). That distinction is not
maintained everywhere — `learning.py` (N-02) and `startup_validation.py` (P-01) both
lack such a note — but where it exists it is clear.