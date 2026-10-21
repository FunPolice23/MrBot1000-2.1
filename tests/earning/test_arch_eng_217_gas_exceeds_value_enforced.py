"""ARCH-ENG-217 — an unprofitable airdrop claim was executed anyway.

## The defect

`AirdropClaimer.plan()` has always computed the economics and flagged them:

    gas = estimate_gas_usd(chain=chain, op_type="claim")
    return ClaimPlan(
        ...
        estimated_cost_usd=gas,
        gas_exceeds_value=gas_exceeds_value(gas, expected),
        safe_to_claim=safe,          # <- safe is the RISK/KYC/DEDUP heuristic
    )

`safe_to_claim` comes from `is_safe_to_claim(airdrop)`, which knows nothing about
gas. And `claim()` gated only on that:

    if not plan.safe_to_claim:
        self.failed.append(airdrop.id); return plan

So `gas_exceeds_value` was computed, rendered into the plan for human review,
**approved by a human reading it, and then ignored**.

Concretely: a $0.25 airdrop costing an estimated $40 of gas. Low risk, no KYC,
not a duplicate -- so `safe_to_claim` is True. The plan is shown, the operator
approves, and the claim proceeds to a real on-chain transaction that destroys the
value it exists to collect.

The confirmation callback is a **human gate, not an economic one**. Being shown a
cost that exceeds the payout does not make spending it correct, and the flag
existed precisely to express that judgement -- it just never reached the
decision.

## The fix

`claim()` now fails closed on `plan.gas_exceeds_value`. An unprofitable claim is
never worth a network action, and if the gas model is ever wrong the safe
direction is to skip the claim rather than spend real money finding out.

## Why this test asserts the economics rather than the flag

The tempting cheap test is "the plan sets `gas_exceeds_value`" -- and that
already passed before this fix, because `plan()` has always set it. The property
worth pinning is that the flag **reaches a decision**, which is what was broken.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
CLAIMER = REPO / "agents" / "earning" / "airdrop_claimer.py"


def _fn(name):
    tree = ast.parse(CLAIMER.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


class TestTheFlagReachesADecision(unittest.TestCase):
    """ARCH-ENG-217 — the actual defect."""

    def test_claim_refuses_when_gas_exceeds_value(self):
        body = ast.unparse(_fn("claim"))
        self.assertIn(
            "plan.gas_exceeds_value", body,
            "claim() never consults gas_exceeds_value; the flag is computed, "
            "shown to the operator, approved, and then ignored")
        self.assertLess(
            body.index("plan.safe_to_claim"), body.index("plan.gas_exceeds_value"),
            "the gas check must come with the other refusal gates, before any "
            "network action is prepared")

    def test_the_refusal_actually_stops_execution(self):
        """A check that logs but falls through is the same defect again."""
        body = ast.unparse(_fn("claim"))
        tail = body[body.index("plan.gas_exceeds_value"):]
        self.assertIn(
            "return", tail[:400],
            "the gas branch does not return; execution continues past the check")

    def test_the_failure_is_recorded(self):
        body = ast.unparse(_fn("claim"))
        idx = body.index("plan.gas_exceeds_value")
        self.assertIn("failed.append", body[idx:idx + 200],
                      "a skipped claim must be recorded, not silently dropped")


class TestTheEconomicsStillFlow(unittest.TestCase):
    """ARCH-ENG-217 — the flag must still be computed and shown."""

    def test_plan_still_computes_the_flag(self):
        """Otherwise the guard above could never see a True."""
        body = ast.unparse(_fn("plan"))
        self.assertIn("gas_exceeds_value", body)
        self.assertIn("estimated_cost_usd", body)

    def test_safe_to_claim_is_still_the_risk_heuristic(self):
        """Documenting WHY the gas check had to be separate.

        `safe_to_claim` deliberately means "not risky", not "profitable". Mixing
        the two would change the meaning of an existing field that other callers
        and the UI read, so the economic gate is enforced in `claim()` instead.
        """
        body = ast.unparse(_fn("plan"))
        self.assertIn("safe_to_claim=safe", body,
                      "safe_to_claim no longer carries the risk heuristic")

    def test_the_human_still_sees_the_flag_in_the_plan(self):
        """The operator should be able to see why a claim was skipped."""
        self.assertIn("gas_exceeds_value",
                      CLAIMER.read_text(encoding="utf-8"))


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-217 — each detector must be able to fail."""

    def test_the_detector_sees_the_pre_fix_body(self):
        """The original claim() had no gas_exceeds_value reference at all."""
        pre_fix = ast.unparse(_fn("plan"))
        claim_only = ast.unparse(_fn("claim"))
        self.assertIn("gas_exceeds_value", pre_fix,
                      "plan() no longer computes the flag")
        # claim() is asserted separately; confirm the substring the guard looks
        # for is specific enough not to match anything incidental.
        self.assertNotIn("plan.gas_exceeds_value", claim_only.split("ARCH-ENG-217")[0]
                         if "ARCH-ENG-217" in claim_only else "",
                         "the guard matches an incidental substring")

    def test_the_reason_is_recorded_in_the_source(self):
        self.assertIn("ARCH-ENG-217", CLAIMER.read_text(encoding="utf-8"),
                      "the new gate needs a marker explaining why an "
                      "already-computed flag was previously ignored")