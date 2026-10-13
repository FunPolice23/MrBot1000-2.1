"""ARCH-ENG-092 — financial-integrity regressions, cycle 092.

Two reproduced defects, both of which let real money disappear from (or appear
in) the books without any error being raised.

* 092a — `OpportunityLifecycleTracker._mark_paid` persisted the state file
        BEFORE writing `state.status` / `state.verification`. `_transition` ->
        `_append` -> `_persist` wrote the JSON snapshot one mutation too early,
        so disk held `current_stage='paid'` with `status='active'` and
        `verification=None`. A restart recovered exactly that,
        `_is_verified_evidence(None)` returned False, and a genuine $750
        externally-verified payout silently collapsed to
        `verified_revenue_usd() == 0.0` — while `unverified_payouts()` was
        empty too, so the money vanished from every report with no signal.

* 092b — `to_usd` valued ANY unrecognised currency at exactly 1.0 USD via
        `.get(currency, 1.0)`. A 250,000 JPY payout was booked as $250,000 of
        verified revenue (~250x), and an empty/absent currency (the
        `Evidence.currency` default is `""`) was booked at face value too.

Both were reproduced by execution against the real implementation before the
fix, then asserted resolved here.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.evidence.evidence import (
    Evidence,
    EvidenceStatus,
    VerificationLevel,
)
from agents.earning.economic_accounting import (
    EconomicAccounting,
    EconomicProfile,
    is_convertible,
    to_usd,
)
from agents.earning.opportunity_lifecycle import OpportunityLifecycleTracker


# ── Fixtures ─────────────────────────────────────────────────────────────────

class _EvidenceStoreStub:
    """Minimal EvidenceStore surface the lifecycle and accounting layers use."""

    def __init__(self, items=None):
        self.items = list(items or [])

    def record(self, ev):
        self.items.append(ev)
        return ev

    def get(self, evidence_id):
        for ev in self.items:
            if getattr(ev, "id", None) == evidence_id:
                return ev
        return None

    def for_subject(self, subject_type, subject_id):
        return [e for e in self.items
                if e.subject_type == subject_type and e.subject_id == subject_id]


def _evidence(subject_id, amount, evidence_type, currency="usd",
              method="authenticated_api",
              level=VerificationLevel.L3_EXTERNAL_SOURCE,
              status=EvidenceStatus.VERIFIED):
    return Evidence.create(
        source="system", evidence_type=evidence_type,
        subject_type="opportunity", subject_id=subject_id,
        external_id=f"ext-{subject_id}-{evidence_type}",
        amount=amount, currency=currency, verification_method=method,
        verification_level=level, status=status,
        provenance={"producer": "payment_provider"})


def _paid_tracker(tmpdir, amount=750.0, currency="usd", opp_id="opp1"):
    """A tracker on a real state file, with a verified L3 payout recorded.

    Walks the freelance route (researched -> queued -> applied -> in_progress ->
    submitted) and seeds the SUBMITTED->PAID evidence chain the policy gate
    requires (platform_submission + completion_confirmation + payment).
    """
    store = _EvidenceStoreStub([
        _evidence(opp_id, 0.0, "platform_submission"),
        _evidence(opp_id, 0.0, "completion_confirmation"),
    ])
    pay = _evidence(opp_id, amount, "payment_confirmation", currency=currency,
                    method="authenticated_api",
                    level=VerificationLevel.L3_EXTERNAL_SOURCE)
    state_path = os.path.join(tmpdir, "lifecycle_state.json")
    tracker = OpportunityLifecycleTracker(evidence_store=store, state_path=state_path)
    tracker.mark_researched(opp_id)
    tracker.mark_queued(opp_id, score=0.9)
    tracker.mark_applied(opp_id)
    tracker.mark_in_progress(opp_id)
    tracker.mark_submitted(opp_id)
    tracker.mark_paid_verified(opp_id, amount=amount, evidence=pay)
    return tracker, store, pay, state_path


# ── ARCH-ENG-092a: a paid lifecycle must survive a restart ───────────────────

class TestPaidSurvivesRestart(unittest.TestCase):
    """The JSON snapshot must be written AFTER the paid fields are set."""

    def test_disk_snapshot_carries_status_and_verification(self):
        """Before the fix the on-disk record held status='active', verification=None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _tracker, _store, pay, state_path = _paid_tracker(tmpdir)
            with open(state_path, "r", encoding="utf-8") as fh:
                disk = json.load(fh)
            rec = [r for r in disk if r.get("opportunity_id") == "opp1"][0]
            self.assertEqual(rec["current_stage"], "paid")
            self.assertEqual(
                rec["status"], "paid",
                "the persisted record must say paid, not active — a restart "
                "reads this and _is_verified_evidence(None) books $0 revenue")
            self.assertIsNotNone(
                rec["verification"],
                "verification must be persisted or verified revenue is lost on restart")
            self.assertEqual(rec["verification"]["evidence_id"] if
                             "evidence_id" in rec["verification"] else
                             rec["verification"].get("id"), pay.id)

    def test_verified_revenue_survives_a_second_tracker_on_same_path(self):
        """The exact regression: build a tracker, mark paid, re-open the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker, store, _pay, state_path = _paid_tracker(tmpdir, amount=750.0)

            # In-process sanity: the money IS booked before the restart.
            st = tracker.get_state("opp1")
            self.assertEqual(st["current_stage"], "paid")
            self.assertEqual(st["status"], "paid")
            self.assertAlmostEqual(tracker.verified_revenue_usd(), 750.0, places=2)

            # Simulate a restart: a brand-new tracker over the same state file.
            restarted = OpportunityLifecycleTracker(
                evidence_store=store, state_path=state_path)
            st2 = restarted.get_state("opp1")
            self.assertEqual(st2["current_stage"], "paid")
            self.assertEqual(
                st2["status"], "paid",
                "a restart must recover status='paid' — before the fix it "
                "recovered 'active' and the $750 became $0")
            self.assertIsNotNone(
                st2["verification"],
                "verification must survive the restart")
            self.assertAlmostEqual(
                restarted.verified_revenue_usd(), 750.0, places=2,
                msg="a verified $750 payout must still count as revenue after restart")
            self.assertEqual(
                restarted.unverified_payouts(), [],
                "an externally verified payout must not be reported as unverified")

    def test_paid_state_from_every_live_stage_survives_restart(self):
        """`_mark_paid` routes through intermediate stages; the final persist
        must reflect the terminal result regardless of the entry stage."""
        for start_stage, walk in (
            ("discovered", lambda t, o: None),
            ("researched", lambda t, o: t.mark_researched(o)),
            ("queued", lambda t, o: (t.mark_researched(o), t.mark_queued(o, 0.9))),
            ("applied", lambda t, o: (t.mark_researched(o), t.mark_queued(o, 0.9),
                                      t.mark_applied(o))),
            ("in_progress", lambda t, o: (t.mark_researched(o), t.mark_queued(o, 0.9),
                                          t.mark_applied(o), t.mark_in_progress(o))),
        ):
            with self.subTest(start_stage=start_stage):
                with tempfile.TemporaryDirectory() as tmpdir:
                    oid = f"live-{start_stage}"
                    store = _EvidenceStoreStub([
                        _evidence(oid, 0.0, "platform_submission"),
                        _evidence(oid, 0.0, "completion_confirmation"),
                        _evidence(oid, 750.0, "payment_confirmation"),
                    ])
                    state_path = os.path.join(tmpdir, "lifecycle_state.json")
                    tracker = OpportunityLifecycleTracker(
                        evidence_store=store, state_path=state_path)
                    walk(tracker, oid)
                    self.assertEqual(tracker.get_state(oid)["current_stage"], start_stage)
                    tracker.mark_paid_verified(
                        oid, amount=750.0,
                        evidence=_evidence(oid, 750.0, "payment_confirmation"))
                    restarted = OpportunityLifecycleTracker(
                        evidence_store=store, state_path=state_path)
                    self.assertEqual(
                        restarted.get_state(oid)["status"], "paid",
                        f"paid from {start_stage} must survive a restart")
                    self.assertAlmostEqual(
                        restarted.verified_revenue_usd(), 750.0, places=2,
                        msg=f"a $750 payout from {start_stage} must not vanish on restart")

    def test_a_refused_paid_transition_does_not_persist_paid(self):
        """Fail-safe direction: a terminal `failed` opportunity can never be
        routed to paid, so nothing may be written as paid either."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _EvidenceStoreStub([
                _evidence("bad", 0.0, "platform_submission"),
                _evidence("bad", 0.0, "completion_confirmation"),
            ])
            state_path = os.path.join(tmpdir, "lifecycle_state.json")
            tracker = OpportunityLifecycleTracker(evidence_store=store, state_path=state_path)
            tracker.mark_researched("bad")
            tracker.mark_queued("bad", 0.9)
            tracker.mark_applied("bad")
            tracker.mark_in_progress("bad")
            tracker.mark_submitted("bad")
            tracker.mark_failed("bad", "client cancelled")

            ok = tracker._mark_paid(
                tracker._ensure("bad"),
                "late payout attempt",
                amount=9999.0,
                verification={"status": "VERIFIED", "verification_level": 3})
            self.assertFalse(ok, "a failed opportunity must never reach paid")
            restarted = OpportunityLifecycleTracker(
                evidence_store=store, state_path=state_path)
            self.assertEqual(restarted.get_state("bad")["status"], "failed")
            self.assertAlmostEqual(restarted.verified_revenue_usd(), 0.0, places=2)


# ── ARCH-ENG-092b: an unknown currency is not USD ────────────────────────────

class TestUnknownCurrencyIsNotFaceValueUSD(unittest.TestCase):
    """`to_usd` must never invent a 1.0 rate for a currency it does not know."""

    def test_known_currencies_still_convert(self):
        self.assertEqual(to_usd(100.0, "usd"), 100.0)
        self.assertEqual(to_usd(100.0, "usdc"), 100.0)
        self.assertEqual(to_usd(1.0, "eth"), 3500.0)
        self.assertEqual(to_usd(0.5, "btc"), 32500.0)
        self.assertEqual(to_usd(1.0, "ETH"), 3500.0, "lookup stays case-insensitive")
        self.assertEqual(to_usd(5.0, "foo", {"foo": 10.0}), 50.0,
                         "a caller-supplied rate table is still honoured")

    def test_unmapped_currency_is_not_valued_at_one(self):
        for cur in ("JPY", "GBP", "EUR", "TOKEN", "xxx"):
            with self.subTest(currency=cur):
                self.assertEqual(
                    to_usd(1000.0, cur), 0.0,
                    f"{cur} has no known USD rate; it must NOT be booked as $1000")

    def test_empty_or_blank_currency_is_not_valued_at_one(self):
        """`Evidence.currency` defaults to `""`; that is an unknown denomination."""
        for cur in ("", "   ", None):
            with self.subTest(currency=repr(cur)):
                self.assertEqual(
                    to_usd(1000.0, cur), 0.0,
                    "an absent currency must not be booked at face value as USD")

    def test_is_convertible_distinguishes_unknown_from_worthless(self):
        self.assertTrue(is_convertible("usd"))
        self.assertTrue(is_convertible("ETH"))
        self.assertFalse(is_convertible("JPY"))
        self.assertFalse(is_convertible(""))
        self.assertFalse(is_convertible(None))
        self.assertFalse(is_convertible("   "))

    def test_jpy_payout_is_not_booked_as_verified_revenue(self):
        """The reproduced defect: 250,000 JPY booked as $250,000 verified revenue."""
        store = _EvidenceStoreStub([
            _evidence("opp-jpy", 250000.0, "payment_confirmation", currency="JPY",
                      method="authenticated_api",
                      level=VerificationLevel.L3_EXTERNAL_SOURCE),
        ])
        profile = EconomicAccounting(store).get_profile("opp-jpy")
        self.assertAlmostEqual(
            profile.verified_revenue, 0.0, places=2,
            msg="an unconvertible currency must not enter verified revenue")
        self.assertAlmostEqual(profile.realized_gross, 0.0, places=2)
        self.assertAlmostEqual(profile.realized_net, 0.0, places=2)
        self.assertAlmostEqual(profile.actual_revenue, 0.0, places=2)
        # Fail-safe zeroing must be auditable, not a silent disappearance.
        self.assertEqual(profile.unconvertible_payment_amounts.get("JPY"), 250000.0)

    def test_unconvertible_amount_is_visible_for_operator_review(self):
        store = _EvidenceStoreStub([
            _evidence("opp-vis", 250000.0, "payment_confirmation", currency="JPY"),
            _evidence("opp-vis", 100.0, "payment_confirmation", currency="gbp"),
        ])
        profile = EconomicAccounting(store).get_profile("opp-vis")
        self.assertEqual(profile.unconvertible_payment_amounts["JPY"], 250000.0)
        self.assertEqual(profile.unconvertible_payment_amounts["GBP"], 100.0)
        self.assertAlmostEqual(profile.verified_revenue, 0.0, places=2)

    def test_empty_currency_evidence_is_not_booked_at_face_value(self):
        store = _EvidenceStoreStub([
            _evidence("opp-blank", 480.0, "payment_confirmation", currency="",
                      method="blockchain_balance_delta",
                      level=VerificationLevel.L5_CRYPTOGRAPHIC),
        ])
        profile = EconomicAccounting(store).get_profile("opp-blank")
        self.assertAlmostEqual(
            profile.verified_revenue, 0.0, places=2,
            msg="evidence with no currency must not be booked as $480 of USD revenue")
        self.assertAlmostEqual(profile.realized_net, 0.0, places=2)
        self.assertEqual(profile.unconvertible_payment_amounts.get("UNSPECIFIED"), 480.0)

    def test_convertible_currency_still_books_normally(self):
        """Fail-safe must not over-correct: known currencies are unaffected."""
        store = _EvidenceStoreStub([
            _evidence("opp-ok", 100.0, "payment_confirmation", currency="usd"),
            _evidence("opp-ok", 1.0, "payment_confirmation", currency="eth"),
        ])
        profile = EconomicAccounting(store).get_profile("opp-ok")
        self.assertAlmostEqual(profile.verified_revenue, 3600.0, places=2)
        self.assertAlmostEqual(profile.realized_net, 3600.0, places=2)
        self.assertEqual(profile.unconvertible_payment_amounts, {})

    def test_unconvertible_expense_does_not_distort_net(self):
        """An unconvertible fee must not be dropped into `other` at face value."""
        store = _EvidenceStoreStub([
            _evidence("opp-exp", 1000.0, "payment_confirmation", currency="usd"),
            _evidence("opp-exp", 30000.0, "platform_fee", currency="JPY"),
        ])
        profile = EconomicAccounting(store).get_profile("opp-exp")
        self.assertAlmostEqual(profile.verified_revenue, 1000.0, places=2)
        self.assertAlmostEqual(
            profile.realized_expense, 0.0, places=2,
            msg="a JPY fee must not be booked as $30,000 of USD expense")
        self.assertAlmostEqual(profile.realized_net, 1000.0, places=2)
        self.assertEqual(profile.unconvertible_expense_amounts.get("JPY"), 30000.0)

    def test_helper_accessors_fail_safe_too(self):
        store = _EvidenceStoreStub([
            _evidence("opp-acc", 250000.0, "payment_confirmation", currency="JPY"),
        ])
        acct = EconomicAccounting(store)
        self.assertAlmostEqual(acct.get_verified_revenue("opp-acc"), 0.0, places=2)
        store2 = _EvidenceStoreStub([
            _evidence("opp-exp2", 50000.0, "payment_fee", currency="GBP"),
        ])
        self.assertAlmostEqual(
            EconomicAccounting(store2).get_total_expenses("opp-exp2"), 0.0, places=2)

    def test_to_dict_exposes_unconvertible_amounts(self):
        profile = EconomicProfile(opportunity_id="opp-d")
        profile.unconvertible_payment_amounts["JPY"] = 250000.0
        d = profile.to_dict()
        self.assertEqual(d["unconvertible_payment_amounts"], {"JPY": 250000.0})
        self.assertEqual(d["unconvertible_expense_amounts"], {})

    def test_custom_rates_make_a_currency_convertible(self):
        """Adding a JPY rate is the supported remedy, and it books correctly."""
        rates = dict(_DEFAULT_RATES := {"usd": 1.0})
        rates["jpy"] = 0.0067
        self.assertEqual(to_usd(250000.0, "JPY", rates), 1675.0)
        self.assertTrue(is_convertible("JPY", rates))
        store = _EvidenceStoreStub([
            _evidence("opp-rated", 250000.0, "payment_confirmation", currency="JPY"),
        ])
        profile = EconomicAccounting(store, rates=rates).get_profile("opp-rated")
        self.assertAlmostEqual(profile.verified_revenue, 1675.0, places=2)
        self.assertEqual(profile.unconvertible_payment_amounts, {})


if __name__ == "__main__":
    unittest.main()
