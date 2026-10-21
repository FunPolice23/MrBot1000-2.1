# 10d — `agents/core/`

> **D-02 RESOLVED in v2.1.125 (ARCH-ENG-302).** `recovery.py` and
> `account_profile.py` had no production caller and are deleted with their
> test. `architecture_boundaries.py` was useful only as a test authority, so it
> moved to `tests/support/architecture_boundaries.py`; the existing boundary
> test still runs against it. No live import remains.
>
> **D-01 RESOLVED in v2.1.125 (ARCH-ENG-281).** `crypto_operations` now gates
> the live crypto boundary: `RealCryptoOperator.propose_payment()` and
> `confirm_and_send()` fail closed before creating a request, enqueueing an
> approval, or touching the chain. The refusal names the canonical
> `MRBOT_ENABLE_CRYPTO` variable; content-validation refusals keep their own
> statuses. D-03 (the `live_trading` flag gated only tab visibility) is also
> fixed under G-05/ARCH-ENG-283.

14 scripts, 3,109 lines. Composition root, service wiring, event bus, gating.

---

## Structure

| File | Lines | Role | Reached from |
|---|---:|---|---|
| `__init__.py` | 1 | marker | — |
| `recovery.py` | 41 | measurable recovery progress | **tests only** |
| `account_profile.py` | 86 | safe account-profile readiness | **nothing** |
| `architecture_boundaries.py` | 81 | static boundary checks | **tests only** |
| `feature_flags.py` | 87 | explicit feature boundaries | 8 modules |
| `configuration.py` | 101 | typed provider settings | 4 modules |
| `comms_log.py` | 168 | durable in-flight message log | 3 modules |
| `composition_root.py` | 180 | unified composition | `application_services` |
| `state_reconciliation.py` | 188 | read-only cross-store reconciliation | `tab_feature_builders` |
| `persistence_contract.py` | 279 | canonical SQLite ownership | `handlers` |
| `personas`-adjacent `notifications` | 213 | Windows toasts | `main`, `approval` |
| `alerting.py` | 494 | alert rules engine | `main` |
| `comms.py` | 623 | message/event bus | 7 modules |
| `event_logger.py` | 567 | structured event log | `main`, `tab_feature_builders` |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| D-01 | **high** | **The "Enable crypto operations" setting controls nothing.** `crypto_operations` is the only one of the seven feature flags that gates **no behaviour at all** — verified by exhaustive search of every production occurrence. Its whole footprint is: the two entries in `feature_flags.py`'s own tables (`:11`, `:21`), the Settings-screen label at `tab_feature_builders.py:2464`, and one test. The operator can toggle it, it persists to `.env` via `save_settings` → `feature_env_key`, it is picked up by `_settings_snapshot` (`:3210`) so **changing it triggers a restart prompt** — and then it gates nothing. A safety-shaped toggle in the Settings screen that changes no behaviour and costs a restart is worse than no toggle, because it reads as protection. |
| D-02 | med | **Three modules exist only for their own tests — 208 lines.** `recovery.py` (41 lines, `RecoveryTracker`) is imported only by `tests/runtime/test_recovery.py`. `architecture_boundaries.py` (81 lines, `BoundaryViolation`/`UsageLedger`) only by `tests/runtime/test_architecture_boundaries.py`. `account_profile.py` (86 lines, `AccountProfile`) is referenced **nowhere at all**, not even a test — only its own module body. Each is a coherent, documented, working unit; none is reachable from the running application. |
| D-03 | low | **`live_trading` and `autonomous_learning` gate only tab visibility, no behaviour.** Both are consumed solely through the `optional_tabs` dict at `main.py:1540–1546`, whose values are passed to `feature_enabled` at `:1551` to decide whether a tab is built at all. Neither appears in any conditional in an agent, task or service. Turning `MRBOT_ENABLE_LIVE_TRADING` on gives the operator the Live Portfolio and Strategy Simulator tabs; it does not enable trading, which is gated elsewhere (or nowhere — worth confirming when `agents/earning/live_trading.py` is analysed). |
| D-04 | info | Five of the fourteen docstrings still name pre-refactor paths (`alerting.py` claims `agents/alerting.py`, `comms.py` claims `comms.py`, `comms_log.py`, `notifications.py`, `event_logger.py` likewise). Same partial-refactor drift as C-03 in `agents/cognition/`, but here it is the majority of the directory rather than a minority — suggesting `agents/core/` was assembled by moving files in two passes. |

---

## Verified as sound

- **The four flags that matter do gate behaviour.** Verified per flag, counting
  `feature_enabled()` call sites in production:
  `self_improvement` (6), `airdrop_claiming` (2), `defi_scanning` (2),
  `social_automation` (1). These are real gates on real code paths.
- **`feature_enabled` fails closed and is honest about it.** An unknown feature
  name returns `False` rather than raising (`gate.py:65`), and an unset, empty or
  unrecognised value all leave the feature disabled. `_truthy` delegates to the
  single canonical parser `app.effects.env_bool` (ARCH-ENG-203), with the
  docstring recording the concrete disagreement that motivated it —
  `PIPELINE_ALLOW_SELF_IMPROVE=1` previously yielded `True` from
  `feature_enabled("self_improvement")` and `False` from
  `ActionPipeline.allow_self_improve`, with neither raising. That is a
  well-documented fix.
- **`_LEGACY_ENV` is accepted only when the new key is absent** (`:67`), so an
  operator can migrate without a flag silently flipping. Correct ordering.

---

## Assessment

`agents/core/` is the plumbing layer and it is mostly well-connected: `comms`,
`event_logger`, `feature_flags`, `configuration` and `composition_root` all have
multiple live consumers. The composition root being reachable from exactly one
place (`application_services`) is correct by design — it is an entry point, not a
library.

**D-01 is the finding worth acting on.** It is the only one where the
application *presents* a control and the control does nothing. The fix is not
obvious in either direction: either wire `crypto_operations` to the crypto paths
it appears to name, or remove the toggle and the flag. Which is right depends on
whether crypto operations are meant to be gated at all — `agents/earning/` has
airdrop and DeFi gated by their own flags, so the asymmetry looks like an
oversight rather than a decision, but that is a question for the operator rather
than one to infer.

D-02 is a straightforward dead-code decision: 208 well-built lines either get
wired or retired. `architecture_boundaries.py` is the interesting one — static
boundary checking would be a natural CI gate, and it is currently only reachable
from a test, so it is never enforced against the real tree.