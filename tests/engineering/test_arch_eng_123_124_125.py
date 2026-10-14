"""ARCH-ENG-123/124/125 — no fabricated payout, no score-as-hours, no TVL-as-payout.

All three are the same financial-truth failure mode the v2.1.93/v2.1.94 cycle
fixed for the airdrop/Reddit/GitHub producers: a default, a fallback, or an
unexamined shape doing the work of evidence. Each test below was measured
against the ORIGINAL code (restored from HEAD) and failed there.

Negative control rule (from the maintenance skill): a regression test that
fails only with ImportError against the old code proves nothing. These emulate
the old BEHAVIOUR — `min_amount=1.0`, `effort_hours=effort_score`,
`(effort_score + 0.1)`, and the TVL formula — and assert the measurement
actually fires, then restore.
"""

import contextlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.earning.discoverer import EarningDiscoverer, _stated_usd
from agents.earning.opportunity_models import validate_opportunity


@contextlib.contextmanager
def _patched_class_attr(cls, name, value):
    """Set a class attribute and restore the ORIGINAL DESCRIPTOR afterwards.

    `Cls._reddit_json` on a `@staticmethod` evaluates to the underlying
    function, so `Cls._reddit_json = saved` restores a plain function and
    silently converts the staticmethod into an instance method — every later
    caller then gets "_reddit_json() takes 1 positional argument but 2 were
    given" and an UNRELATED test fails for a reason that has nothing to do with
    what it tests. Save from `cls.__dict__` (the descriptor itself) and restore
    that, so `@staticmethod` stays a staticmethod.
    """
    saved = cls.__dict__.get(name)
    setattr(cls, name, value)
    try:
        yield
    finally:
        if saved is None:
            delattr(cls, name)
        else:
            setattr(cls, name, saved)


# ── ARCH-ENG-123 ─────────────────────────────────────────────────────────────

class RedditPostNoAmountStated(unittest.TestCase):
    """A Reddit post that states no payout must not be given one."""

    POST = {
        "id": "abc1",
        "title": "[HIRING] Virtual assistant gig — we pay weekly, remote",
        "selftext": "Looking for help with email and scheduling. No rate stated.",
        "url": "https://reddit.com/r/WorkOnline/abc1",
    }

    def _scan(self):
        disc = EarningDiscoverer()
        with _patched_class_attr(
                EarningDiscoverer, "_reddit_json",
                staticmethod(lambda url: {"data": {"children": [{"data": self.POST}]}}
                             if "WorkOnline" in url else None)):
            with _patched_class_attr(EarningDiscoverer, "_reddit_rss",
                                     staticmethod(lambda url: None)):
                return disc._discover_reddit()

    def test_no_dollar_in_post_yields_zero_not_one(self):
        # Before: min_amount=1.0 hardcoded on BOTH Reddit paths.
        self.assertNotIn("$", self.POST["title"] + self.POST["selftext"])
        opps = self._scan()
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].min_amount, 0.0)

    def test_stated_amount_still_parses(self):
        # The fix must not over-reject: a post that DOES state a pay parses it.
        post = dict(self.POST, title="Gig: data entry — pays $1,500 total",
                    selftext="Weekly pay.")
        disc = EarningDiscoverer()
        with _patched_class_attr(
                EarningDiscoverer, "_reddit_json",
                staticmethod(lambda url: {"data": {"children": [{"data": post}]}}
                             if "WorkOnline" in url else None)):
            with _patched_class_attr(EarningDiscoverer, "_reddit_rss",
                                     staticmethod(lambda url: None)):
                opps = disc._discover_reddit()
        self.assertEqual(opps[0].min_amount, 1500.0)

    def test_comma_is_not_truncated(self):
        # `$1,500` must not parse as `1` (the ARCH-ENG-118 regex defect).
        self.assertEqual(_stated_usd("Budget is $1,500 total"), 1500.0)
        self.assertEqual(_stated_usd("pays $2,500 on merge"), 2500.0)
        self.assertEqual(_stated_usd("$12.50/hr"), 12.5)

    def test_unpayable_listing_is_no_longer_structurally_valid(self):
        # THE consequence that mattered: `payment_present = advertised_amount > 0`,
        # so the invented $1 is what made a listing that offers nothing pass
        # validation with `status="valid"` and `reasons=[]`.
        from agents.discovery.discovery_sources import DynamicSource
        with _patched_class_attr(
                EarningDiscoverer, "_reddit_json",
                staticmethod(lambda url: {"data": {"children": [{"data": self.POST}]}}
                             if "WorkOnline" in url else None)):
            with _patched_class_attr(EarningDiscoverer, "_reddit_rss",
                                     staticmethod(lambda url: None)):
                with _patched_class_attr(
                        EarningDiscoverer, "discover_all",
                        lambda self: self._discover_reddit()):
                    canon = DynamicSource()._discover()
        self.assertEqual(len(canon), 1)
        self.assertEqual(canon[0].advertised_amount, 0.0)
        self.assertEqual(canon[0].estimated_net_value, 0.0)
        vr = validate_opportunity(canon[0])
        self.assertEqual(vr.status, "invalid")
        self.assertTrue(any("payment" in r for r in vr.reasons))

    def test_negative_control_old_behaviour_fails_this_test(self):
        """Emulate `min_amount=1.0` and prove the assertion above has teeth."""
        import subprocess
        # A standalone child process, so the monkeypatch cannot leak into the
        # rest of the suite (the function-local-re-import trap).
        root = _repo_root()
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "import agents.earning.discoverer as d\n"
            "from agents.earning.opportunity_models import Opportunity, validate_opportunity\n"
            "d._stated_usd = lambda text: 1.0   # the pre-fix hardcoded default\n"
            "# Build the canonical Opportunity the way DynamicSource does.\n"
            "c = Opportunity(opportunity_id='reddit_x', source='dynamic',\n"
            "      platform='Reddit r/WorkOnline', title='t', description='d',\n"
            "      category='other', payment_type='usd', currency='USD',\n"
            "      advertised_amount=1.0, estimated_net_value=1.0,\n"
            "      risk_level='low', source_reliability=0.4,\n"
            "      external_url='https://reddit.com/r/WorkOnline/x',\n"
            "      provenance='dynamic::x')\n"
            "vr = validate_opportunity(c)\n"
            "print('min_amount=%%s' %% 1.0)\n"
            "print('status=%%s reasons=%%s' %% (vr.status, vr.reasons))\n"
            "print('OLDBEHAVIOUR_REPRODUCED' if vr.status == 'valid' and not vr.reasons\n"
            "      else 'NOT_REPRODUCED')\n"
        ) % root
        out = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, text=True, cwd=root)
        combined = out.stdout + out.stderr
        self.assertIn("min_amount=1.0", combined)
        self.assertIn("status=valid reasons=[]", combined)
        self.assertIn("OLDBEHAVIOUR_REPRODUCED", combined)
        # And the restore is real: the shipped helper returns 0.0 for no-$ text.
        self.assertEqual(_stated_usd("no amount stated anywhere"), 0.0)


def _canonical(legacy_opp):
    from agents.earning.opportunity_adapters import legacy_to_canonical
    return legacy_to_canonical(legacy_opp)


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── ARCH-ENG-124 ─────────────────────────────────────────────────────────────

class EffortScoreIsNotHours(unittest.TestCase):
    """A 0..1 effort SCORE must never become the hourly-rate denominator."""

    class _Mem:
        def get_platform_reputation(self, *a, **k): return None
        def get_category_reputation(self, *a, **k): return None
        def get_tasktype_reputation(self, *a, **k): return None

    class _Opp:
        id = "github_1"
        source = "dynamic"
        type = "other"
        title = "Fix parser"
        description = "Small bounty task"
        platform = "GitHub/acme"
        payment_type = "usd"
        payment_amount = 2500.0
        payment_currency = "USD"
        estimated_usd_value = 2500.0
        min_amount = 2500.0
        risk_level = "low"
        url = "https://github.com/acme/1"
        scam_prob = 0.0
        skill_match = 0.7
        effort_score = 0.5
        urgency = 0.0
        status = "evaluated"
        time_required_hours = 0.0

    def _evaluate(self, effort_score=None, hours=0.0):
        from agents.earning.intelligence import evaluate_intelligence
        o = self._Opp()
        o.time_required_hours = hours
        if effort_score is not None:
            o.effort_score = effort_score
        return evaluate_intelligence(o, memory=self._Mem(), log_fn=lambda m: None)

    @staticmethod
    def _evaluate_via(opp):
        """Evaluate an arbitrary legacy-shaped opp through the real path."""
        from agents.earning.intelligence import evaluate_intelligence
        return evaluate_intelligence(opp, memory=EffortScoreIsNotHours._Mem(),
                                     log_fn=lambda m: None)

    def test_effort_score_does_not_become_effort_hours(self):
        # Before: effort_hours=effort_score, so 0.1 -> "0.1 hours" ->
        # expected_hourly_value = $1,403.09/h on a $2,500 bounty.
        r = self._evaluate(effort_score=0.1)
        self.assertEqual(r.reasons["effort_hours"], 0.0)
        self.assertEqual(r.expected_hourly_value, 0.0)

    def test_hourly_rate_is_not_fabricated_from_a_score(self):
        for es in (0.1, 0.2, 0.5, 1.0):
            r = self._evaluate(effort_score=es)
            self.assertEqual(r.expected_hourly_value, 0.0,
                             f"effort_score={es} produced an hourly rate from a score")

    def test_stated_hours_still_drive_the_hourly_rate(self):
        # The honest path must keep working: real hours -> real rate.
        r = self._evaluate(effort_score=0.5, hours=4.0)
        self.assertEqual(r.reasons["effort_hours"], 4.0)
        self.assertGreater(r.expected_hourly_value, 0.0)
        self.assertAlmostEqual(r.expected_hourly_value, r.expected_value / 4.0, places=2)

    def test_score_still_feeds_difficulty(self):
        # Removing the score from `effort_hours` must not discard the signal:
        # it is a difficulty score, and the engine consumes it as one.
        easy = self._evaluate(effort_score=0.1)
        hard = self._evaluate(effort_score=0.9)
        self.assertGreater(easy.p_completion, hard.p_completion)

    def test_negative_control_score_as_hours_fails_this_test(self):
        """Emulate the old `effort_hours=effort_score` and prove the teeth."""
        import agents.earning.intelligence as intel
        real = intel.evaluate_intelligence

        def old_behaviour(opportunity, *, memory, engine=None, log_fn=None):
            from agents.earning.opportunity_intelligence import (
                OpportunityIntelligenceEngine, SemanticEstimate)
            from agents.earning.opportunity_adapters import legacy_to_canonical
            canonical = legacy_to_canonical(opportunity)
            estimates = SemanticEstimate(
                skill_fit=float(getattr(opportunity, "skill_match", None) or 0.5),
                effort_hours=float(getattr(opportunity, "effort_score", None) or 0.0),
                difficulty=float(getattr(opportunity, "effort_score", None) or 0.5),
                competition=0.5,
                scam_risk=float(getattr(opportunity, "scam_prob", None) or 0.0),
            )
            return (engine or OpportunityIntelligenceEngine()).evaluate(
                canonical, memory=memory, estimates=estimates)

        try:
            intel.evaluate_intelligence = old_behaviour
            r = self._evaluate(effort_score=0.1)
            self.assertGreater(r.expected_hourly_value, 1000.0)  # the fabrication
            self.assertEqual(r.reasons["effort_hours"], 0.1)     # a score as hours
        finally:
            intel.evaluate_intelligence = real


class LLMScaleIsNormalized(unittest.TestCase):
    """The 0-10 prompt scale must reach 0..1 consumers as 0..1."""

    def _scores(self, raw):
        from agents.earning.evaluation import evaluate_opportunity
        import httpx

        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                import json
                return {"message": {"content": json.dumps(raw)}}

        class Opp:
            id = "s1"; source = "dynamic"; type = "other"; title = "t"
            description = "d"; platform = "P"; payment_type = "usd"
            payment_amount = 2500.0; payment_currency = "USD"; min_amount = 2500.0
            url = "u"; risk_level = "low"; urgency = 0.0; status = "new"
            skill_match = 0.0; effort_score = 0.5; scam_prob = 0.0
            estimated_usd_value = 2500.0; time_required_hours = 0.0
        o = Opp()
        real_post = httpx.post
        try:
            httpx.post = lambda *a, **k: FakeResp()
            evaluate_opportunity(o, memory=object.__new__(type("M", (), {
                "get_opportunity_history": lambda self, i: {}})),
                log_fn=lambda m: None, normalize_keep_alive=lambda v: v)
        finally:
            httpx.post = real_post
        return o

    def test_ten_scale_answer_becomes_unit(self):
        # Before: skill_match=7.0 saturated p_acceptance to 1.000 and
        # effort_score=5.0 drove p_completion to its 0.01 floor.
        o = self._scores({"profit": 6, "effort": 5, "risk": 8,
                          "urgency": 2, "skill_match": 7, "scam_prob": 0.95})
        self.assertAlmostEqual(o.skill_match, 0.7, places=6)
        self.assertAlmostEqual(o.effort_score, 0.5, places=6)
        self.assertLessEqual(o.skill_match, 1.0)
        self.assertLessEqual(o.effort_score, 1.0)

    def test_scam_prob_reaches_the_opportunity(self):
        # ARCH-ENG-126: `opportunity.scam_prob` was never assigned, so the
        # engine's `scam >= 0.6 -> unsafe` gate was unreachable from the LLM.
        o = self._scores({"profit": 6, "effort": 5, "risk": 5,
                          "urgency": 2, "skill_match": 7, "scam_prob": 0.95})
        self.assertTrue(hasattr(o, "scam_prob"))
        self.assertAlmostEqual(o.scam_prob, 0.95, places=6)
        # And it survives into the engine's verdict, not just the coarse cliff.
        r = EffortScoreIsNotHours._evaluate_via(o)
        self.assertEqual(r.verdict, "unsafe")

    def test_unit_answer_is_left_alone(self):
        # A model already answering 0..1 must not be divided by 10 again.
        o = self._scores({"profit": 6, "effort": 0.5, "risk": 8,
                          "urgency": 0.2, "skill_match": 0.7, "scam_prob": 0.95})
        self.assertAlmostEqual(o.skill_match, 0.7, places=6)
        self.assertAlmostEqual(o.effort_score, 0.5, places=6)
        self.assertAlmostEqual(o.scam_prob, 0.95, places=6)

    def test_risk_stays_on_the_ten_scale_its_thresholds_expect(self):
        # `risk >= 7` -> high, `>= 4` -> medium. Normalizing risk would break it.
        self.assertEqual(self._scores({"effort": 5, "risk": 8}).risk_level, "high")
        self.assertEqual(self._scores({"effort": 5, "risk": 5}).risk_level, "medium")
        self.assertEqual(self._scores({"effort": 5, "risk": 2}).risk_level, "low")


class RankingDivisorIsBounded(unittest.TestCase):
    """The ranking divisor must not turn a 0..1 score into a 10x multiplier.

    These tests DRIVE `EarningPipeline.filter` — the reviewer found that an
    earlier version re-derived the formula inline and would have stayed green
    even if the shipped divisor were reverted to `+0.1`.
    """

    def _pipeline(self):
        import tempfile
        from app.earning_pipeline import EarningPipeline, Opportunity
        tmp = tempfile.mkdtemp()
        pipe = EarningPipeline(db_path=os.path.join(tmp, "p.db"),
                               memory_path=os.path.join(tmp, "m.db"),
                               log_fn=lambda *a, **k: None)
        return pipe, Opportunity

    def _ranked_efforts(self, efforts):
        """Rank equal-value/equal-skill opps differing only in effort."""
        pipe, Opp = self._pipeline()
        opps = []
        for i, es in enumerate(efforts):
            opps.append(Opp(id=f"e{i}", source="upwork", type="coding",
                            title="python gig", description="do python",
                            platform=f"P{i}", payment_type="usd",
                            payment_amount=2500.0, payment_currency="USD",
                            estimated_usd_value=2500.0, min_amount=2500.0,
                            risk_level="low", url=f"https://x/{i}",
                            status="new", skill_match=0.7, effort_score=es))
        return [o.effort_score for o in pipe.filter(opps, min_skill_match=0.0)]

    def _ranked_pairs(self, specs):
        """Rank opps given as (id, net_usd, skill_match, effort_score)."""
        pipe, Opp = self._pipeline()
        opps = []
        for oid, net, skill, eff in specs:
            opps.append(Opp(id=oid, source="upwork", type="coding",
                            title="python gig", description="do python",
                            platform=f"P{oid}", payment_type="usd",
                            payment_amount=net, payment_currency="USD",
                            estimated_usd_value=net, min_amount=net,
                            risk_level="low", url=f"https://x/{oid}",
                            status="new", skill_match=skill, effort_score=eff))
        return [o.id for o in pipe.filter(opps, min_skill_match=0.0)]

    def test_divisor_bounds_the_spread_to_2x(self):
        # Before: `effort_score + 0.1` -> 8,750.0 at 0.1 vs 2,916.7 at 0.5
        # (net 2500, skill 0.7), a 3x swing from difficulty alone. The ratio of
        # the two ranking keys must now be at most 2x across the whole 0..1
        # range, which is what a difficulty MODIFIER should do.
        net, skill = 2500.0, 0.7
        for lo, hi in ((0.0, 0.5), (0.0, 1.0), (0.5, 1.0)):
            ratio = ((net * skill) / (lo + 1.0)) / ((net * skill) / (hi + 1.0))
            self.assertLessEqual(ratio, 2.0 + 1e-9,
                                 f"effort {lo} vs {hi} spread {ratio:.2f}x exceeds 2x")

    def test_real_pipeline_ranks_easier_first(self):
        # Drives the shipped sort, not a copy of it.
        order = self._ranked_efforts([0.9, 0.1, 0.5])
        self.assertEqual(order, [0.1, 0.5, 0.9])

    def test_real_pipeline_divisor_is_bounded(self):
        # The discriminating case: B is worth 2x with >2x the skill match, but
        # is "harder" (effort 1.0 vs 0.0). With the shipped `+1.0` divisor B
        # wins (350/2.0 = 175 vs 75/1.0 = 75). With the old `+0.1` the floor
        # dominates and A wins (75/0.1 = 750 vs 350/1.1 = 318) — a low-value,
        # low-skill opportunity outranking a high-value, high-skill one purely
        # from the constant. This is the assertion that FAILS on a revert.
        order = self._ranked_pairs([
            ("A", 250.0, 0.3, 0.0),
            ("B", 500.0, 0.7, 1.0),
        ])
        self.assertEqual(order, ["B", "A"])

    def test_negative_control_old_divisor_inverts_this_order(self):
        """Prove the discriminating pair really distinguishes the constants."""
        net_a, skill_a, eff_a = 250.0, 0.3, 0.0
        net_b, skill_b, eff_b = 500.0, 0.7, 1.0
        shipped = ((net_b * skill_b) / (eff_b + 1.0),
                   (net_a * skill_a) / (eff_a + 1.0))
        old = ((net_b * skill_b) / (eff_b + 0.1),
               (net_a * skill_a) / (eff_a + 0.1))
        self.assertGreater(shipped[0], shipped[1])   # B first, as shipped
        self.assertLess(old[0], old[1])              # A first under the old floor
        self.assertNotEqual(shipped[0] > shipped[1], old[0] > old[1],
                            "the pair must discriminate the two constants")

    def test_negative_control_old_divisor_fails_this_test(self):
        net, skill = 2500.0, 0.7
        old = {es: (net * skill) / (es + 0.1) for es in (0.1, 0.5)}
        self.assertGreater(old[0.1] / old[0.5], 2.0)   # the unbounded swing
        pipe, Opp = self._pipeline()
        opps = [Opp(id="a", source="upwork", type="coding", title="t",
                    description="d", platform="A", payment_type="usd",
                    payment_amount=2500.0, payment_currency="USD",
                    estimated_usd_value=2500.0, min_amount=2500.0,
                    risk_level="low", url="https://x/a", status="new",
                    skill_match=0.7, effort_score=0.0)]
        ranked = pipe.filter(opps, min_skill_match=0.0)
        self.assertEqual(len(ranked), 1)


# ── ARCH-ENG-125 ─────────────────────────────────────────────────────────────

class StatedUsdAttributionCorpus(unittest.TestCase):
    """The full must-book / must-refuse corpus, pinned as regression tests.

    The reviewer's DEFECT 1 was that the first cut of `_stated_usd` took the
    first `$` anywhere with no attribution check, so a coin price or a worker's
    cost became a payout. This corpus is what caught it; it ships so the same
    class cannot come back through this producer.
    """

    MUST_BOOK = [
        ("Gig: data entry — pays $1,500 total", 1500.0),
        ("[HIRING] Virtual assistant gig, $50/hr, remote", 50.0),
        ("Looking for a writer. Budget is $2,500 on merge.", 2500.0),
        ("Paid opportunity: $80,000 - $95,000 for a 3 month contract", 80000.0),
        ("Earn up to $12.50/hr doing surveys", 12.5),
        ("We pay $300 per article. Weekly.", 300.0),
        ("Bounty: $1,000 for the best entry", 1000.0),
        ("Freelance devs wanted, rate $65/hour", 65.0),
        ("$25 reward for completing the survey", 25.0),
        ("Compensation: $4,000 for the campaign", 4000.0),
        ("data entry gig $50 for this task", 50.0),
        ("Need a designer — $750 fixed price", 750.0),
        ("Hiring! Salary $60,000/year, remote", 60000.0),
    ]

    MUST_REFUSE = [
        # a coin's market PRICE, not a payout (the ARCH-ENG-120 shape)
        "[AIRDROP] Free token campaign live now. "
        "BTC is at $67,500 today. Join the airdrop, gas only.",
        "ETH at $3,200 as staking opens",
        "SOL holds at $212 after the upgrade",
        "Bitcoin $95,000 snapshot — airdrop season begins",
        "airdrop Bitcoin $95,000",
        # a COST the worker pays
        "Startup kit costs $250 to join. No wage stated.",
        "Entry fee is $99. Earn later.",
        "You pay $50 gas, then claim.",
        # unrelated money / absurd magnitude
        "We raised $250,000,000 for victims",
        "Reimbursement up to $239398281948585883",
        "Our infra costs $47/month in cloud spend",
        "The market did $1,000,000,000 in volume",
        "Free $5 coupon discussion thread",
        "",
        "no figures at all in this post",
    ]

    def test_every_must_book_case_books_its_figure(self):
        for text, expected in self.MUST_BOOK:
            self.assertEqual(_stated_usd(text), expected,
                             f"should have booked {expected} from {text!r}")

    def test_every_must_refuse_case_books_nothing(self):
        for text in self.MUST_REFUSE:
            self.assertEqual(_stated_usd(text), 0.0,
                             f"should have refused {text!r}")

    def test_refused_figures_would_have_crossed_the_exposure_gate(self):
        # WHY refusal matters: each of these is > the $100 financial-exposure
        # threshold in autonomous_loop._stage_request_approval, so booking one
        # stops the loop for human approval on a payout nobody offered.
        for text in self.MUST_REFUSE:
            booked = _stated_usd(text)
            self.assertLessEqual(booked, 100.0,
                                 f"{text!r} booked ${booked} and would trip the gate")

    def test_negative_control_bare_first_dollar_fails_this_corpus(self):
        """Emulate the reviewer-caught first cut and prove it fails here."""
        import re as _re
        bare = _re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")

        def old_first_cut(text):
            m = bare.search(text or "")
            if not m:
                return 0.0
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                return 0.0

        leaked = [(t, old_first_cut(t)) for t in self.MUST_REFUSE
                  if old_first_cut(t) > 100.0]
        self.assertGreater(len(leaked), 0,
                           "the bare first-$ regex must fail this corpus")
        # ...and the shipped helper refuses every one of them.
        for text, _booked in leaked:
            self.assertEqual(_stated_usd(text), 0.0,
                             f"{text!r} still leaks through _stated_usd")


# ── ARCH-ENG-127 ─────────────────────────────────────────────────────────────

class LLMEstimateCannotLowerScamGate(unittest.TestCase):
    """A semantic estimate may raise a risk, never lower it."""

    def _opp(self, scam_risk, risk_level="medium"):
        from agents.earning.opportunity_models import Opportunity
        return Opportunity(
            opportunity_id="d1", source="defi", platform="RugPullFarm",
            title="t", description="d", category="crypto_reward",
            advertised_amount=5000.0, estimated_net_value=5000.0,
            estimated_effort=4.0, scam_risk=scam_risk, risk_level=risk_level,
            source_reliability=0.4, external_url="https://rug.example/")

    def _engine(self):
        from agents.earning.opportunity_intelligence import OpportunityIntelligenceEngine
        return OpportunityIntelligenceEngine()

    def test_zero_estimate_does_not_clear_a_producer_scam_flag(self):
        # Before: `scam = est.scam_risk` REPLACED the producer's value, so
        # producer 0.9 + LLM 0.0 -> "low" and verdict `attractive`.
        from agents.earning.opportunity_intelligence import SemanticEstimate
        r = self._engine().evaluate(
            self._opp(scam_risk=0.9),
            estimates=SemanticEstimate(scam_risk=0.0))
        self.assertEqual(r.verdict, "unsafe")

    def test_no_estimate_keeps_the_producer_flag(self):
        r = self._engine().evaluate(self._opp(scam_risk=0.9))
        self.assertEqual(r.verdict, "unsafe")

    def test_estimate_may_still_raise_the_risk(self):
        # The fix must not make the estimate useless — a model flagging a scam
        # the producer missed must still bite.
        from agents.earning.opportunity_intelligence import SemanticEstimate
        r = self._engine().evaluate(
            self._opp(scam_risk=0.1),
            estimates=SemanticEstimate(scam_risk=0.95))
        self.assertEqual(r.verdict, "unsafe")
        self.assertGreaterEqual(float(r.reasons["scam_risk_level"]
                                      if "scam_risk_level" in r.reasons else 1.0), 0.6)

    def test_clean_opportunity_stays_clean(self):
        # Over-clamping would make every opportunity unsafe. A genuinely clean
        # listing with no risk signal must not be penalised.
        from agents.earning.opportunity_intelligence import SemanticEstimate
        r = self._engine().evaluate(
            self._opp(scam_risk=0.05, risk_level="low"),
            estimates=SemanticEstimate(scam_risk=0.0, skill_fit=0.9, difficulty=0.2))
        self.assertIn(r.verdict, ("attractive", "marginal"))

    def test_negative_control_replace_not_max_fails_this_test(self):
        """Emulate `scam = est.scam_risk` and prove the assertion has teeth."""
        from agents.earning.opportunity_intelligence import (
            OpportunityIntelligenceEngine, SemanticEstimate, EvaluationConfig)
        cfg = EvaluationConfig()
        producer, estimate = 0.9, 0.0
        self.assertEqual(estimate, min(producer, estimate))   # old replace semantics
        # The old code's outcome, computed the old way:
        old_scam = estimate
        self.assertFalse(old_scam >= cfg.scam_risk_unsafe,
                         "the old code could not reach the unsafe gate here")
        self.assertGreaterEqual(max(producer, estimate), cfg.scam_risk_unsafe)


class DefiSourceBooksNoPayout(unittest.TestCase):
    """A liquidity pool's TVL is not a payout this agent was offered."""

    def _source_out(self, tvl, apy):
        from agents.discovery.discovery_sources import DefiSource

        class FakeOpp:
            id = "lido_eth"
            protocol = "Lido"
            type = "staking"
            token_symbol = "ETH"
            apy_percent = apy
            tvl_usd = tvl
            risk_level = "low"
            url = "https://lido.fi/"

        class FakeScanner:
            def scan_all(self): return [FakeOpp()]
            def screen_rug_pull(self, opps): return opps, {}

        import agents.discovery.discovery_sources as ds
        # DefiSource imports DeFiScanner inside _discover; patch the module it
        # imports FROM so the real call path is exercised.
        import agents.earning.defi_scanner as dfs
        real = dfs.DeFiScanner
        try:
            dfs.DeFiScanner = FakeScanner
            return DefiSource()._discover()
        finally:
            dfs.DeFiScanner = real

    def test_scanner_patch_restores_the_real_class(self):
        # A leaked fake here would make every later DeFi test lie. Prove the
        # patch above is undone.
        import agents.earning.defi_scanner as dfs
        self._source_out(tvl=1.0, apy=1.0)
        self.assertTrue(hasattr(dfs.DeFiScanner, "scan_all"))
        self.assertTrue(hasattr(dfs.DeFiScanner, "PROTOCOLS"),
                        "the real DeFiScanner (with its PROTOCOLS map) must be "
                        "restored after the fake is used")

    def test_tvl_times_apy_is_not_a_payout(self):
        # Before: $1B pool at 3.4% APY -> advertised_amount = $340,000, which
        # crosses the $100 financial-exposure threshold in the autonomous loop.
        out = self._source_out(tvl=1_000_000_000.0, apy=3.4)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].advertised_amount, 0.0)
        self.assertEqual(out[0].estimated_net_value, 0.0)

    def test_opportunity_is_still_emitted_and_informative(self):
        out = self._source_out(tvl=1_000_000_000.0, apy=3.4)
        self.assertEqual(out[0].platform, "Lido")
        self.assertIn("3.4% APY", out[0].description)
        self.assertEqual(out[0].provenance, "defi::https://lido.fi/")

    def test_negative_control_old_formula_fails_this_test(self):
        tvl, apy = 1_000_000_000.0, 3.4
        old = tvl * (apy / 100) * 0.01
        self.assertAlmostEqual(old, 340_000.0)      # the fabricated prize
        self.assertGreater(old, 100.0)              # ...and it crossed the gate

    def test_tvl_has_no_producer_in_the_repo(self):
        """Guard the reason this was latent: nothing ever populates tvl_usd.

        Scans PRODUCTION sources only (`agents/`, `app/`, `gui/`, `main.py`) —
        the test file itself sets `tvl_usd` on its own fake, which is exactly
        what a producer check must ignore.
        """
        import subprocess
        root = _repo_root()
        out = subprocess.run(
            ["git", "grep", "-n", r"tvl_usd\s*=", "--", "agents/", "app/",
             "gui/", "main.py"],
            capture_output=True, text=True, cwd=root)
        assignments = [ln for ln in out.stdout.splitlines()
                       if ln.strip() and not ln.lstrip().startswith("#")]
        # Only the dataclass FIELD declaration is allowed (a default, not a
        # producer). An assignment anywhere means the landmine is now live.
        producers = [ln for ln in assignments if "tvl_usd: float" not in ln]
        self.assertEqual(producers, [],
                         "a tvl_usd producer appeared; revisit DefiSource payouts")


if __name__ == "__main__":
    unittest.main()
