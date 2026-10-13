# ARCH-ENG-111 — Pre-existing test-order pollution in test_webcontroller_escalation

**Status:** **RESOLVED in v2.1.91 (ARCH-ENG-112)**
**Discovered:** 2026-10-13, v2.1.90 cycle
**Resolved:** 2026-10-13, v2.1.91 cycle
**Severity:** Medium (test-suite reliability, not product behaviour)

## Resolution — root cause found and fixed (ARCH-ENG-112)

The cause was **NOT** any of the four hypotheses below. It was a split
`requests` module identity:

`tests/earning/test_social_writer_factory.py` ended its patched window with

```python
tearDown:   sys.modules.pop("requests", None)
```

Popping the key removes the REAL `requests` from `sys.modules`, so the next
`import requests` executes the real module again and builds a **new module
object**. `agents.integrations.browser` had already bound the ORIGINAL object
at its own import time, so it kept calling `requests.get` on the original —
while `mock.patch("requests.get", ...)` resolves `"requests"` through
`sys.modules` and patched the NEW object. The mock therefore applied to
nothing: `g.called` was measured **False**, production hit the real network,
and `read_page` returned `ok=False`.

Verified directly, not inferred:

```
>>> browser.requests is (re-imported) requests   ->  False
>>> g.called  (mock on "requests.get")           ->  False
```

**Fix:** `setUp` now uses `mock.patch.dict(sys.modules, {"requests": fake})`
with `addCleanup(patcher.stop)`, which restores the exact prior entry and
keeps one `requests` identity for the session.

**Regression test:** `tests/engineering/test_arch_eng_112_requests_identity.py`
(7 tests). The key test drives the REAL `TestFactoryWithKey` through
`setUp()` → `tearDown()` → `doCleanups()` and asserts both that
`sys.modules["requests"]` is still the object `browser` holds and that a
subsequent `mock.patch("requests.get")` actually reaches `read_page`.
Proven to discriminate: **2 failed on pre-fix source, 7 passed after the fix.**

## Why it matters

A suite that passes alone but fails together hides real regressions: a
contributor running the full suite sees red noise and may dismiss a genuine
failure as "just the flaky webcontroller tests". It also means the ARCH-ENG-110
verification had to prove innocence by comparison rather than by a clean run.

## Lesson (durable)

**A bare `sys.modules[name] = fake` plus `sys.modules.pop(name)` in teardown is
never safe.** `pop` does not restore the previous object — it removes the entry,
so the next import mints a *new* module object. Anything that already imported
the module keeps the old one, and `mock.patch("mod.attr")` targets the new one.
Use `mock.patch.dict(sys.modules, {...})` (or save-and-restore the exact prior
object) so the identity is preserved.

Note also that `addCleanup` callbacks fire from `run()`/`doCleanups()`, **not**
from `tearDown()` — a regression test driving another TestCase must call
`doCleanups()` explicitly or it will observe the patch still installed.

---

## Original analysis (kept for the record)

## Observation (verified, not inferred)

`tests/integrations/test_webcontroller_escalation.py` — 8 tests.

- Run **alone**: 8 passed.
- Run **paired** with the new ARCH-ENG-110 test file: 14 passed.
- Run in the **full suite** (`python -m pytest -q`): **4 failed**.

The 4 failures are identical on a clean checkout of v2.1.89 (`git stash -u`
then full run: `4 failed, 1717 passed`) and with the ARCH-ENG-110 change
applied (`4 failed, 1723 passed`). So they are **pre-existing** and unrelated
to ARCH-ENG-110.

```
FAILED test_non_200_browser_also_fails_marks_human_open
FAILED test_rich_page_no_escalation
FAILED test_robots_allow_proceeds
FAILED test_thin_and_playwright_unavailable_falls_back_to_stub
```

Failure mode: `self.assertTrue(out["ok"])` is False — `WebController.read_page`
returns `ok=False` for a page that should succeed.

## Ruled out (hypotheses from the v2.1.90 cycle — all four were WRONG)

1. `WebController` singleton carrying a robots/escalation flag — **ruled out**:
   every test constructs a fresh `WebController()`.
2. Cached HTTP session/adapter left on `requests` — **ruled out**: `requests.get`
   was never called at all; the mock never fired (identity split, not staleness).
3. Memoised Playwright availability bypassing `_read_with_playwright` — **ruled
   out**: every escalation test patches that method directly on the instance.
4. Leaking `mock.patch` from an earlier module — **ruled out**: the leak was in
   `sys.modules` bookkeeping, not a live patcher.

The `_fake_response`/`mock.patch("requests.get", ...)` construction pointed at
(1) or (2) — the truth was a fourth mechanism: the patch target resolved to a
different module object than the one production code called.

## Second polluted module (same class, found in the v2.1.90 cycle)

**Status: RESOLVED in v2.1.91 (second fix, same cycle).**

`tests/safety/test_query_db_multidb.py::TestQueryDbTool::test_write_still_refused`
(assertion at line 53) showed the **same signature**:

- Passes alone (7 passed) and paired with the ARCH-ENG-110 file.
- Fails when run as part of `tests/dialogue tests/safety` together — but only
  from a **fresh clone**; in the main repo checkout the same combined run is
  green (420 passed). Reproducible on the parent commit `HEAD~1` (v2.1.89) too,
  so it is pre-existing and unrelated to ARCH-ENG-110.

**Root cause (verified, not the earlier cwd guess):** every `*.db` is gitignored
runtime state, so a fresh clone has **no `earning.db`**. `_tool_query_db`
checks `os.path.exists(db_path)` **before** the SQL read-only validator:

```python
db_path = _resolve_db_path(...)
if not os.path.exists(db_path):
    return f"[Database not found: {basename}]"   # <-- returns here in a clone
return execute_readonly_query(...)               # the gate never runs
```

So in a clone the test got `"[Database not found: earning.db]"` instead of
`"read-only"`. It passed in-tree only because the operator's live `earning.db`
happened to exist — meaning **the read-only gate the test exists to prove was
never exercised in a clone**.

**Fix:** the tests now build their own store DBs in a temp dir and patch
`agents.safety.handlers.PROJECT_ROOT` (a `Path` — a bare `str` breaks the `/`
operator in `_resolve_db_path`) at it. A companion test asserts an absent store
is still reported cleanly rather than crashing.

**Discrimination proven:** with the read-only gate disabled the new test fails;
with the gate enabled it passes. In a fresh clone `tests/dialogue tests/safety`
now reports **421 passed** (was 1 failed / 419 passed).

The repo-vs-clone difference did point at **filesystem state** rather than pure
module ordering, but it was the gitignored DB's existence, not a cwd-relative
allowlist path.

**Net for ARCH-ENG-110:** both polluted failures were proven present on clean
code by stash/bisect comparison, so the +7 new passing tests are the only
delta attributable to that cycle.

## Next action (updated)

Both ARCH-ENG-111 pollution cases are closed and the full suite is green
(**1736 passed, 5 skipped**, up from a 4-failed baseline). Note the one
remaining clone-only failure class, already documented in the changelog
discipline skill: `tools/github_publish/` is gitignored, so its 9 tests error
in any fresh clone while passing in-tree. Verified pre-existing and unrelated —
worth a separate decision (ship the tool or drop its tests) rather than a fix.

