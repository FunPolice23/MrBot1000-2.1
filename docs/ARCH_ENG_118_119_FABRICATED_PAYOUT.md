# ARCH-ENG-118/119 — fabricated payout at discovery

**Status:** **RESOLVED in v2.1.93**
**Resolved:** 2026-10-13, v2.1.93 continuous-engineering cycle

Theme: **a default value doing the work of evidence.** Same family as v2.1.68
(LinkedIn / WeWorkRemotely) and v2.1.92 (hardware asserted as fact) — a number
the system never verified, presented as something it had.

---

## ARCH-ENG-118 — `_scan_reddit_jobs` invented `$50`, and truncated `$1,500` to `$1`

**Where.** `agents/earning/social_earning_platform.py::_scan_reddit_jobs`.

**Before.**

```python
dollar_match = re.search(r'\$(\d+)', title + desc)
pay_amount = float(dollar_match.group(1)) if dollar_match else 50.0
```

**Two defects on one line.**

1. `else 50.0` — a listing that stated no amount at all was emitted with
   `min_amount=50.0` / `estimated_value=50.0`.
2. `\$(\d+)` has no comma handling — `"$1,500"` matched the digits after the
   `$` up to the first non-digit, i.e. `1`. A $1,500 project was emitted as a
   $1 project (1500× understatement, the opposite direction of the first bug).

**Measured (stubbed feedparser, no network).**

| Listing text | before | after |
|---|---|---|
| `"[HIRING] Virtual assistant" / "We pay weekly. Remote."` | `min_amount=50.0` | `0.0` |
| `"Budget is $1,500 total for the full project."` | `min_amount=1.0` | `1500.0` |
| `"[HIRING] Bug fix, $50 bounty"` | `50.0` | `50.0` |

**Why the invented 50.0 mattered more than being numerically wrong.**
`SocialSource._discover` maps `min_amount` → canonical `advertised_amount` and
`estimated_value` → `estimated_net_value`. `validate_opportunity` then sets

```python
payment_present = o.advertised_amount > 0 or o.estimated_net_value > 0
```

so a post offering nothing validated `status="valid"` with `reasons=[]`, and
flowed into ranking, the opportunity-intelligence score, and the autonomous
loop's `check_economics` / `check_risk` / `request_approval` stages. The
fabricated default was what made an unpayable listing structurally sound. With
the fix the same listing is `advertised_amount=0.0`, `payment_present=False`,
`reasons=["missing payment information (amount=0)"]` — it is still discovered
(that is real), it is simply no longer described as paid (that was not).

**Reachability.** Reddit is the only social source that returns entries in
practice — LinkedIn's public jobs feed returns zero, and the forum and Twitter
scanners fail closed (`return []`). This was the live path, not a dormant
branch.

**Fix.** Comma-aware parse identical to the v2.1.68 scanners,
`\$\s*([\d,]+)(?:\.\d{2})?`, with `0.0` for no match / unparseable.

---

## ARCH-ENG-119 — `_discover_github_bounties` invented `$10`, contradicting its own comment

**Where.** `agents/earning/discoverer.py::_discover_github_bounties`.

**Before.**

```python
match = re.search(r'\$(\d+(?:\.\d+)?)', body + title)
bounty = float(match.group(1)) if match else 10.0
# Guard against absurd parses ("$239398281948585883* bounty"):
# treat an implausible figure as unknown rather than a real prize.
if not (1.0 <= bounty <= self.MAX_BOUNTY_USD):
    bounty = 10.0
```

The guard existed specifically to stop garbage figures becoming prizes. Both of
its outcomes wrote a hardcoded `$10`, and the no-match fallback did the same —
three code paths, all asserting a prize the issue never offered, one of them
directly under a comment saying "unknown rather than a real prize". The
comment describes the intent; the code does the opposite. The same regex bug as
118 applied: `"$2,500 on merge"` parsed as `25`.

**Measured.**

| Issue body | before | after |
|---|---|---|
| `"Paid issue, contact us for details."` (no amount) | `min_amount=10.0` | `0.0` |
| `"$239398281948585883* bounty available."` (implausible) | `10.0` | `0.0` |
| `"A $25 reward is available."` | `25.0` | `25.0` |
| `"We will pay $2,500 on merge."` | `25.0` | `2500.0` |

**Fix.** Same comma-aware parse; `0.0` for no-match, unparseable, and
implausible. The `MAX_BOUNTY_USD` ceiling and the `1.0` floor are unchanged —
they now reject into `0.0` instead of inventing.

---

## Not changed — recorded finding

`AirdropScanner._evaluate_opportunity` (`agents/earning/airdrop_scanner.py`)
carries the identical pattern: `value = 50.0  # Conservative estimate` for a
Reddit token hit, `value = 10.0` as the final `else`.

**It has no production caller.** Both wired callers —
`agents/discovery/discovery_sources.py:168` (`AirdropSource._discover`) and
`app/earning_pipeline.py:572` (`_discover_airdrops`) — call `scan_feeds()`,
which routes through `_parse_entry` and already yields `0.0` when no amount is
stated. `_evaluate_opportunity` is reached only from the legacy `scan()` entry
point, which nothing in `agents/`, `app/`, `gui/`, or `main.py` calls.

Deliberately left alone: editing unreached code cannot be verified by
execution, so a "fix" there would be unverifiable rather than safe. Recorded so
that when `scan()` is either wired or retired, the fabrication goes with it.

---

## Verification

- `tests/engineering/test_arch_eng_118_119_no_fabricated_payout.py` (10 tests).
- **Discrimination: 8 of 10 failed with the fix stashed, 10 pass applied.** The
  2 that pass under both are the "real amount still parses" cases — correct
  before and after, present to prove the fix did not break the happy path.
- Each producer is additionally pinned **structurally by AST**: the test parses
  the module and fails if any positive float fallback (118) or any hardcoded
  `10.0` (119) reappears inside the scanner function — so this cannot be
  silently reintroduced.
- No network: `feedparser` and the GitHub search response are mocked.
- Full suite (global Python 3.14, default fd capture): **1773 passed,
  5 skipped, 106 subtests**, zero failures (1763 before + 10 new).
- Full suite re-run with `-s`: identical.
- `.env` byte-identical before and after every run.
