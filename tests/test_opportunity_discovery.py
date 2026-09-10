"""tests/test_opportunity_discovery.py — Generalized paid-opportunity discovery.

Covers the structured Opportunity model, flexible taxonomy, pluggable source
interface, deduplication, registry failure-isolation, validation vs evaluation
separation, and the 13 required scenarios (categories, dup detection, malformed,
missing payment, USD/crypto/unknown currency, unknown category, source failures,
empty results, provenance, duplicate sources, LLM-not-trusted-as-verified).

Run: python -m tests --category discovery
"""

import os
import sys
import unittest
from dataclasses import dataclass
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.opportunity_models import (
    Opportunity, classify_category, TAXONOMY, KNOWN_CURRENCIES,
    validate_opportunity, ValidationResult,
    OpportunitySource, BaseOpportunitySource,
    OpportunityDeduplicator, OpportunityRegistry,
)
from agents.discovery_sources import (
    UpworkSource, FiverrSource, SocialSource, AirdropSource, DefiSource,
    MicrotaskSource, UgigSource, ContentSource, DynamicSource, all_builtin_sources,
)
from agents.discovery_engine import DiscoveryEngine, DiscoveryStats
from agents.web_discovery import WebDiscoverySource
from agents.opportunity_models import validate_opportunity


def _mk(url="https://x.com/1", src="s", **kw):
    return Opportunity(
        opportunity_id="i", source=src, platform="P", title="Same", description="d",
        category=kw.pop("category", "writing"), external_url=url,
        provenance=f"{src}::{url}", **kw,
    )


# ── T1: structured model + taxonomy ──────────────────────────────────────────

class TestOpportunityModel(unittest.TestCase):
    REQUIRED = [
        "opportunity_id", "source", "platform", "title", "description", "category",
        "subcategory", "task_type", "required_skills", "required_tools",
        "payment_type", "currency", "advertised_amount", "estimated_net_value",
        "estimated_effort", "estimated_duration", "deadline",
        "location_requirements", "eligibility_requirements", "automation_potential",
        "human_required", "risk_level", "scam_risk", "source_reliability",
        "discovered_at", "external_id", "external_url", "provenance",
    ]

    def test_required_fields_present(self):
        o = _mk()
        for f in self.REQUIRED:
            self.assertTrue(hasattr(o, f), f"missing field {f}")

    def test_unknown_category_preserved(self):
        o = _mk(category="novel_thing_i_made_up")
        self.assertEqual(o.category, "novel_thing_i_made_up")

    def test_multiple_categories_classify(self):
        self.assertEqual(classify_category("proofreading gig"), "writing")
        self.assertEqual(classify_category("label this dataset"), "data_labeling")
        self.assertEqual(classify_category("find bugs in our repo"), "bug_bounty")
        self.assertEqual(classify_category("random gibberish xyz"), "other")

    def test_taxonomy_is_not_closed(self):
        # The taxonomy is a set; unknown values must not crash and are kept.
        self.assertNotIn("future_category_999", TAXONOMY)
        o = _mk(category="future_category_999")
        self.assertEqual(o.category, "future_category_999")

    def test_identity_key_normalizes_for_dedup(self):
        a = _mk("https://x.com/job/1", "upwork")
        b = _mk("https://x.com/job/1", "reddit")  # same url, diff source
        self.assertEqual(a.identity_key(), b.identity_key())


# ── T2: pluggable source interface + dedup + registry ────────────────────────

class TestSourceInterfaceAndDedup(unittest.TestCase):
    def test_dedup_same_url_diff_source(self):
        d = OpportunityDeduplicator()
        a = _mk("https://x.com/job/1")
        b = _mk("https://x.com/job/1", src="other")
        self.assertFalse(d.seen(a))
        d.add(a)
        self.assertTrue(d.seen(b))

    def test_dedup_allows_different(self):
        d = OpportunityDeduplicator()
        self.assertFalse(d.seen(_mk("https://x.com/1")))
        d.add(_mk("https://x.com/1"))
        self.assertFalse(d.seen(_mk("https://x.com/2")))

    def test_registry_runs_source_and_isolates_failure(self):
        reg = OpportunityRegistry()

        class Dummy(BaseOpportunitySource):
            name = "dummy"

            def _discover(self, query=None, categories=None):
                return [_mk("https://x.com/1")]

        class Bad(BaseOpportunitySource):
            name = "bad"

            def _discover(self, query=None, categories=None):
                return 1 / 0  # boom

        reg.register(Dummy())
        reg.register(Bad())
        results, errors = reg.run_all()
        self.assertEqual(len(results), 1)
        self.assertIn("bad", errors)
        self.assertEqual(len(errors), 1)

    def test_base_source_coerces_provenance(self):
        class S(BaseOpportunitySource):
            name = "mysrc"

            def _discover(self, query=None, categories=None):
                return [Opportunity(opportunity_id="1", source="mysrc", platform="P",
                                    title="T", description="d", category="writing",
                                    external_url="https://x.com/z")]

        opps = S().discover()
        self.assertEqual(opps[0].provenance, "mysrc::https://x.com/z")


class FakeGig:
    id = "g1"; title = "Python API"; description = "build it"; budget_usd = 120.0
    url = "https://up.work/j/g1"


class FakeUpworkClient:
    def __init__(self, *a, **k):
        pass
    def find_gigs(self, q, limit):
        return [FakeGig()]


class TestExistingIntegrationsAsSources(unittest.TestCase):
    def test_ugig_source_parses_public_hiring_listings(self):
        payload = {
            "gigs": [{
                "id": "gig-1", "title": "Build a Python API",
                "description": "Create an HTTP service.",
                "skills_required": ["Python", "API"],
                "budget_min": 100, "budget_max": 250,
                "payment_coin": "USDC",
            }]
        }
        response = mock.Mock(status_code=200)
        response.json.return_value = payload
        with mock.patch("requests.get", return_value=response) as get:
            opps = UgigSource().discover(query="python")

        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["params"], {
            "listing_type": "hiring", "search": "python",
        })
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].opportunity_id, "ugig_gig-1")
        self.assertEqual(opps[0].advertised_amount, 250.0)
        self.assertEqual(opps[0].currency, "USDC")
        self.assertEqual(opps[0].category, "api_data_task")
        self.assertEqual(opps[0].external_url, "https://ugig.net/gigs/gig-1")

    def test_upwork_source_sets_provenance_and_category(self):
        for k in ("UPWORK_CLIENT_ID", "UPWORK_CLIENT_SECRET",
                  "UPWORK_ACCESS_TOKEN", "UPWORK_REFRESH_TOKEN"):
            os.environ[k] = "x"
        # Patch the real Upwork client so no network/credentials are needed.
        with mock.patch("agents.upwork_client.UpworkClient", FakeUpworkClient):
            opps = UpworkSource().discover()
        self.assertEqual(len(opps), 1)
        self.assertTrue(opps[0].provenance.startswith("upwork::"))
        self.assertEqual(opps[0].category, "freelance")
        self.assertEqual(opps[0].advertised_amount, 120.0)

    def test_upwork_source_empty_without_credentials(self):
        for k in ("UPWORK_CLIENT_ID", "UPWORK_CLIENT_SECRET",
                  "UPWORK_ACCESS_TOKEN", "UPWORK_REFRESH_TOKEN"):
            os.environ.pop(k, None)
        self.assertEqual(UpworkSource().discover(), [])

    def test_content_source_is_deprecated_and_emits_nothing(self):
        # v2.0.36p: ContentSource no longer emits hardcoded $5 static gigs
        # (the "repeating hardcoded results" bug). It yields [] so it cannot
        # fabricate findings; real content work flows via WebDiscoverySource
        # (human-review-gated) or the legacy DynamicSource.
        opps = ContentSource().discover()
        self.assertEqual(opps, [])
        self.assertEqual(ContentSource.name, "content")

    def test_all_builtin_sources_are_registry_compatible(self):
        srcs = all_builtin_sources()
        self.assertEqual(len(srcs), 9)
        for s in srcs:
            self.assertIsInstance(s, BaseOpportunitySource)

    def test_source_failure_isolated_by_registry(self):
        reg = OpportunityRegistry()
        reg.register(UpworkSource())
        class Boom(BaseOpportunitySource):
            name = "boom"
            def _discover(self, query=None, categories=None):
                raise RuntimeError("network down")
        reg.register(Boom())
        results, errors = reg.run_all()
        # upwork returns [] (no creds) but still runs; boom is isolated
        self.assertIn("boom", errors)


class _S(BaseOpportunitySource):
    def __init__(self, name, opps):
        self.name = name
        self._opps = opps
    def _discover(self, query=None, categories=None):
        return self._opps


class TestDiscoveryEngine(unittest.TestCase):
    def _opp(self, url, src):
        return Opportunity(opportunity_id="1", source=src, platform="P", title="T",
                           description="d", category="writing", external_url=url,
                           provenance=f"{src}::{url}")

    def test_engine_dedups_across_sources(self):
        e = DiscoveryEngine(throttle=False)
        e.add_source(_S("a", [self._opp("https://x/1", "a")]))
        e.add_source(_S("b", [self._opp("https://x/1", "b")]))  # same url
        e.add_source(_S("c", [self._opp("https://x/2", "c")]))
        opps, errors, stats = e.discover_all()
        self.assertEqual(len(opps), 2, stats)
        self.assertEqual(stats.deduped, 2)
        self.assertEqual(stats.raw, 3)
        self.assertEqual(stats.sources, 3)

    def test_engine_isolates_source_failure(self):
        e = DiscoveryEngine(throttle=False)
        e.add_source(_S("a", [self._opp("https://x/1", "a")]))
        class Bad(BaseOpportunitySource):
            name = "bad"
            def _discover(self, query=None, categories=None):
                raise RuntimeError("boom")
        e.add_source(Bad())
        opps, errors, stats = e.discover_all()
        self.assertEqual(len(opps), 1)
        self.assertIn("bad", errors)
        self.assertEqual(stats.errors, 1)

    def test_engine_reports_by_category_stats(self):
        e = DiscoveryEngine(throttle=False)
        e.add_source(_S("a", [
            Opportunity(opportunity_id="1", source="a", platform="P", title="Write gig",
                        description="d", category="writing", external_url="https://x/w"),
            Opportunity(opportunity_id="2", source="a", platform="P", title="Label data",
                        description="d", category="data_labeling", external_url="https://x/d"),
        ]))
        opps, errors, stats = e.discover_all()
        self.assertEqual(stats.by_category.get("writing"), 1)
        self.assertEqual(stats.by_category.get("data_labeling"), 1)

    def test_engine_add_source_without_core_change(self):
        e = DiscoveryEngine(throttle=False)
        # A brand-new source type added purely via add_source (no pipeline edit).
        class NovelSource(BaseOpportunitySource):
            name = "novel"
            def _discover(self, query=None, categories=None):
                return [Opportunity(opportunity_id="n", source="novel", platform="X",
                                    title="Do a paid study", description="d",
                                    category="paid_study", external_url="https://x/study",
                                    provenance="novel::https://x/study")]
        e.add_source(NovelSource())
        opps, errors, stats = e.discover_all()
        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].category, "paid_study")


class TestPipelineWiring(unittest.TestCase):
    def test_discover_uses_discovery_engine_and_adapts(self):
        from earning_pipeline import EarningPipeline
        from agents.opportunity_models import Opportunity, BaseOpportunitySource

        class FakeSrc(BaseOpportunitySource):
            name = "upwork"
            def _discover(self, query=None, categories=None):
                return [Opportunity(opportunity_id="u1", source="upwork", platform="Upwork",
                                    title="Python gig", description="do python",
                                    category="freelance", payment_type="usd", currency="USD",
                                    advertised_amount=150.0, external_url="https://up.work/j/u1",
                                    provenance="upwork::https://up.work/j/u1")]

        import tempfile, os as _os
        import agents.discovery_sources as ds
        tmp = _os.path.join(tempfile.mkdtemp(), "pipe_test.db")
        with mock.patch.object(ds, "all_builtin_sources", return_value=[FakeSrc()]):
            pipe = EarningPipeline(db_path=tmp, memory_path=tmp.replace(".db", "_mem.db"),
                                   log_fn=lambda *a, **k: None)
            opps = pipe.discover(sources=["upwork"])
        self.assertEqual(len(opps), 1)
        # Adapted to the pipeline's legacy Opportunity model.
        self.assertEqual(opps[0].id, "u1")
        self.assertEqual(opps[0].payment_amount, 150.0)
        self.assertEqual(opps[0].type, "freelance")


class TestWebDiscoverySource(unittest.TestCase):
    def test_web_source_disabled_by_default(self):
        # No env flag -> disabled (safe default).
        import os
        os.environ.pop("ALLOW_WEB_DISCOVERY", None)
        self.assertFalse(WebDiscoverySource().is_enabled())

    def test_web_source_mock_returns_opps_with_provenance(self):
        s = WebDiscoverySource(mock=True)
        opps = s.discover()
        self.assertTrue(opps)
        self.assertTrue(all(o.provenance.startswith("web::") for o in opps))
        # Multiple categories represented (data_labeling, airdrop, paid_study).
        cats = {o.category for o in opps}
        self.assertIn("data_labeling", cats)

    def test_web_source_real_mode_without_flag_is_empty(self):
        # Real (non-mock) mode and not enabled -> empty, never invents listings.
        s = WebDiscoverySource(mock=False, allow=False)
        self.assertFalse(s.is_enabled())
        self.assertEqual(s.discover(), [])

    def test_web_source_can_be_enabled_explicitly(self):
        # Human-reviewed opt-in via explicit allow=True (or ALLOW_WEB_DISCOVERY).
        s = WebDiscoverySource(mock=True, allow=True)
        self.assertTrue(s.is_enabled())
        self.assertTrue(s.discover())


class TestValidationVsEvaluation(unittest.TestCase):
    """DISCOVERY != VALIDATION != EVALUATION. Validation is deterministic structure
    checks; it must NEVER treat an LLM-positive classification as 'verified'."""

    def _opp(self, **kw):
        base = dict(opportunity_id="1", source="s", platform="P", title="T",
                    description="d", category="writing")
        base.update(kw)
        return Opportunity(**base)

    def test_usd_payment_is_valid(self):
        r = validate_opportunity(self._opp(payment_type="usd", currency="USD",
                                           advertised_amount=50.0))
        self.assertEqual(r.status, "valid")
        self.assertTrue(r.currency_known)
        self.assertTrue(r.payment_present)

    def test_crypto_payment_known_currency_is_valid(self):
        r = validate_opportunity(self._opp(payment_type="crypto", currency="ETH",
                                           advertised_amount=0.5))
        self.assertEqual(r.status, "valid")
        self.assertTrue(r.currency_known)

    def test_missing_payment_info_invalid(self):
        r = validate_opportunity(self._opp(advertised_amount=0.0))
        self.assertEqual(r.status, "invalid")
        self.assertFalse(r.payment_present)
        self.assertTrue(any("payment" in reason.lower() for reason in r.reasons))

    def test_unknown_currency_flagged(self):
        r = validate_opportunity(self._opp(payment_type="crypto", currency="ZZZ",
                                           advertised_amount=5.0))
        self.assertFalse(r.currency_known)
        # Unknown currency cannot be validated -> invalid, with a flagged reason.
        self.assertEqual(r.status, "invalid")
        self.assertTrue(any("currency" in reason.lower() for reason in r.reasons))

    def test_malformed_listing_no_title_invalid(self):
        r = validate_opportunity(self._opp(title="", description=""))
        self.assertEqual(r.status, "invalid")

    def test_validation_never_returns_verified(self):
        # Validation can only be valid/invalid — there is no "verified" outcome,
        # so a discovered+validated listing is never mistaken for a verified fact.
        for amt in (50.0, 0.0):
            r = validate_opportunity(self._opp(advertised_amount=amt))
            self.assertNotEqual(r.status, "verified")

    def test_llm_positive_classification_does_not_verify(self):
        # Simulate an evaluator that uses the LLM to enrich (skills/category).
        # It must not flip validation_status to verified — that requires real
        # external evidence (see Evidence subsystem), not an LLM opinion.
        o = self._opp(advertised_amount=50.0)
        o.required_skills = ["python"]           # LLM-enriched
        o.category = classify_category("python coding gig")  # LLM-classified
        self.assertEqual(o.validation_status, "unvalidated")  # unchanged by eval
        r = validate_opportunity(o)
        self.assertEqual(r.status, "valid")  # structure OK...
        self.assertNotEqual(r.status, "verified")  # ...but NOT verified


class TestRequiredScenarios(unittest.TestCase):
    """The 13 required audit scenarios, enumerated explicitly."""

    def _opp(self, **kw):
        base = dict(opportunity_id="1", source="s", platform="P", title="T",
                    description="d", category="writing")
        base.update(kw)
        return Opportunity(**base)

    def test_1_multiple_opportunity_categories(self):
        cats = {"writing", "data_labeling", "bug_bounty", "airdrop", "paid_study",
                "coding", "transcription", "virtual_assistance", "design", "referral"}
        for c in cats:
            o = self._opp(category=c)
            self.assertEqual(o.category, c)

    def test_2_duplicate_detection(self):
        d = OpportunityDeduplicator()
        a = self._opp(external_url="https://x/1"); b = self._opp(external_url="https://x/1")
        d.add(a)
        self.assertTrue(d.seen(b))

    def test_3_malformed_listings(self):
        r = validate_opportunity(self._opp(title="", description=""))
        self.assertEqual(r.status, "invalid")

    def test_4_missing_payment_information(self):
        r = validate_opportunity(self._opp(advertised_amount=0.0))
        self.assertEqual(r.status, "invalid")

    def test_5_usd_payments(self):
        r = validate_opportunity(self._opp(payment_type="usd", currency="USD",
                                           advertised_amount=10.0))
        self.assertEqual(r.status, "valid")

    def test_6_crypto_payments(self):
        r = validate_opportunity(self._opp(payment_type="crypto", currency="ETH",
                                           advertised_amount=1.0))
        self.assertEqual(r.status, "valid")

    def test_7_unknown_currencies(self):
        r = validate_opportunity(self._opp(payment_type="crypto", currency="ZZZ",
                                           advertised_amount=1.0))
        self.assertFalse(r.currency_known)

    def test_8_unknown_categories(self):
        o = self._opp(category="some_future_category")
        self.assertEqual(o.category, "some_future_category")  # preserved, not forced

    def test_9_source_failures(self):
        reg = OpportunityRegistry()
        class Bad(BaseOpportunitySource):
            name = "bad"
            def _discover(self, query=None, categories=None): raise RuntimeError("down")
        reg.register(Bad())
        results, errors = reg.run_all()
        self.assertEqual(results, [])
        self.assertIn("bad", errors)

    def test_10_empty_source_results(self):
        reg = OpportunityRegistry()
        class Empty(BaseOpportunitySource):
            name = "empty"
            def _discover(self, query=None, categories=None): return []
        reg.register(Empty())
        results, errors = reg.run_all()
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 0)

    def test_11_source_provenance(self):
        o = self._opp(source="reddit", external_url="https://reddit.com/p/9",
                      provenance="reddit::https://reddit.com/p/9")
        self.assertTrue(o.provenance.startswith("reddit::"))
        self.assertIn("https://reddit.com/p/9", o.provenance)

    def test_12_duplicate_sources_same_opportunity(self):
        e = DiscoveryEngine(throttle=False)
        e.add_source(_S("reddit", [self._opp(external_url="https://x/job/1", source="reddit")]))
        e.add_source(_S("twitter", [self._opp(external_url="https://x/job/1", source="twitter")]))
        opps, errors, stats = e.discover_all()
        self.assertEqual(len(opps), 1)  # deduped across the two sources

    def test_13_llm_not_trusted_as_verified(self):
        o = self._opp(advertised_amount=50.0)
        o.category = classify_category("amazing python job")  # LLM-style classify
        self.assertEqual(o.validation_status, "unvalidated")
        r = validate_opportunity(o)
        self.assertNotEqual(r.status, "verified")


if __name__ == "__main__":
    unittest.main()
