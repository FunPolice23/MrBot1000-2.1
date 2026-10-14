# ARCH-ENG-129/130/131 — an approval authorizes ONE action, not a capability

**Status:** **RESOLVED in v2.1.97**

Found by the Security Engineer during the continuous engineering cycle of
2026-10-14, then independently reproduced by the Architect by **executing the
real handlers** before any code was written. Nothing here is inferred from
reading.

## The three defects

`record_payment` and `social_post` are the project's two HIGH-TRUST mutating
tools. Both accepted an `approval_id` and checked exactly one property of the
item it named: `status == ApprovalStatus.APPROVED`. The item's `kind`,
`details` and `payload` were never read. Every argument that reaches the
machine — `amount`, `content` — was therefore a raw agent tool argument sitting
next to a gate that did not know what the human had reviewed.

| ID | Defect | Measured before the fix |
|---|---|---|
| 129 | The approved AMOUNT was not the amount booked | approved **$5.00** → booked **$1,000,000.00** verified revenue |
| 130 | Any APPROVED item authorized any mutating tool | approved **file_write**(`scratch.txt`) → authorized **record_payment** $777 |
| 131 | `social_post` published content other than approved | approved `'Hello team'` → published `'BUY THIS NOW http://x'` |

Reachability for ARCH-ENG-130 was not theoretical: approval ids are
model-visible. `agents/safety/dispatch.py`, `agents/dialogue/chat_completion.py`
(both the text-call and function-call paths) and `agents/brains/big_brain.py`
all return `request_id=<id>` into the transcript, so a model can harvest ONE
approved id and spend it against any mutating tool.

## The fix

One predicate, `agents.safety.approval.assert_approval_covers(item, tool,
arguments)`, called by both HIGH-TRUST tools before they mutate:

- the approval must name **this tool** (`details["tool"]` or `payload["tool"]`);
- where the producer recorded the arguments the human reviewed, those
  arguments must **match** — a different amount, path, network or content is a
  DIFFERENT action needing its own approval;
- an item recording **no** tool scope authorizes **nothing** (fail closed).

Supporting changes, each required to keep the honest path working:

1. **`enqueue_payment` records scope.** The approved amount now travels in
   `details["arguments"]` alongside `tool: "record_payment"`. The legacy
   `details["amount"]`/`["currency"]` keys are preserved for existing
   consumers, and a caller-supplied `payload` is kept verbatim.
2. **`main._execute_approved_action` stamps the approved id into the call.**
   The model cannot know an approval id before the item exists, so the queued
   arguments carry no `approval_id` — and the tools would then refuse a call a
   human genuinely approved. The stamp happens on a copy, immediately before
   dispatch. Without this the fix would have been an approval-loop regression
   wearing a security badge.
3. **`approval_id` is excluded from the argument comparison** — it is the
   handle by which the caller refers to the approval, and (2) legitimately
   rewrites it.
4. **The Social Activity tab's Moltbook post captures the draft.** The button
   previously enqueued an approval with no content, so there was nothing for a
   scope binding to check. It now has a submolt field and a post body, both
   recorded in the approval item, and refuses an empty draft.
5. **Both tool descriptions** in `agents/safety/tools.py` state the binding, so
   the model stops reusing an approval id across requests.

## Discrimination

`tests/engineering/test_arch_eng_129_approval_scope_binding.py` (29 tests) was
run against the pre-fix handler with the scope helper still present:
**9 failed**, and they are exactly the amount-scope, tool-scope and
content-scope cases. The other 20 cover the predicate's own semantics
(payload-over-details precedence, nested values, bool-vs-number, unrecorded
keys not policed, status checked before scope) and the stamp site.

## Also fixed in the same pass

Two existing test fixtures (`tests/safety/test_record_payment_gate.py`,
`tests/safety/test_social_post_gate.py`) enqueued **unscoped** approvals and
asserted the tools ran behind them — they encoded the defect. Both now enqueue
scoped approvals and add cases for a different amount, a different content, an
approval for another tool, and an unscoped approval. The ARCH-ENG-121 fixture
gained an `amount=` parameter for the same reason.

**Version authority gotcha (worth remembering):** `app/version.py` is the
single authority and `main.py` carries a last-resort fallback literal in its
window title. `tests/engineering/test_arch_eng_117_version_authority.py` parses
`main.py` and fails if the literal disagrees. Bumping the version without the
fallback is a one-test suite failure — the full run caught it
(`1 failed, 1890 passed`) and both were bumped together.

## Not defects (verified sound, no change made)

- `HumanApprovalQueue.find_by_id` refuses decisions restored from a prior
  process, so a restart cannot turn a stale approval into a live one.
- `_execute_approved_action`'s consumed-once ledger bounds an approval to one
  execution per process.
- The L3 evidence floor (ARCH-ENG-121) still runs after the scope check: an
  approval authorizes an action, not a verification.
- `social_post` still refuses when no confirmed writer is wired.
- The instruction-provenance gate blacklists before any network call and
  fails closed on unresolvable hosts.

## Open findings from the same audit (not fixed this cycle)

- **MEDIUM/HIGH — `file_read` returns `.env` and the vault to the model with no
  approval.** `file_read` is classified READONLY and auto-allowed, and
  `resolve_project_path` confines to `PROJECT_ROOT`, which *contains* the
  secrets. Executed: `execute_tool('file_read', {'path':'.env'})` returned
  13,418 chars and 27 credential keys into model context with zero approval.
  `data/platform_vault.json` and `wallet.key` are also inside the root. The
  vault's "never returned to a model" rule is defeated by a tool that never
  touches the vault. Fix: a secret-name blocklist in `_tool_file_read`, or move
  the secret stores outside `PROJECT_ROOT`.
- **MEDIUM — `.env` is in git history** (~9 commits, `git show d7d36bc:.env`).
  Historical values were placeholders, so no live secret leaked — but the
  current `.env` holds real-length keys, and `.gitignore` was added after the
  commits. Rotate any key ever committed; `git filter-repo` if the public
  mirror `FunPolice23/MrBot1000-2.1` ever pulled those refs.
- **LOW — `RealCryptoOperator.confirm_and_send` takes a `private_key` as a plain
  argument** (`real_crypto_operator.py:86`). Unreachable in the wired path
  (`CryptoPayments` is built with `human_approval_required=True` and
  `try_real_payment` hard-returns `{"ok": False}`; only `propose_payment` is
  called from the GUI). Also `RealCryptoOperator.__init__(safety_guard=None)`
  makes `propose_payment` silently return `status:"simulated"`.
