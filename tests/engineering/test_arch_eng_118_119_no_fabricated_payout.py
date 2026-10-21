"""No fabricated payout at discovery (ARCH-ENG-118/119).

Two producers invented revenue for listings that never stated an amount, and
both wrote the invented figure into the fields the rest of the system treats as
fact (`min_amount` / `estimated_value` -> canonical `advertised_amount` /
`estimated_net_value` -> `validate_opportunity`'s `payment_present` -> ranking,
scoring, and the autonomous loop's economics stage):

  * `SocialEarningPlatform._scan_reddit_jobs` defaulted to `50.0` when no `$`
    figure appeared, and its regex `\\$(\\d+)` truncated "$1,500" to "1".
  * `EarningDiscoverer._discover_github_bounties` defaulted to `10.0` both when
    no figure appeared and when the parsed figure was implausible — under a
    comment that explicitly said "treat ... as unknown rather than a real
    prize". The code asserted the opposite of its own stated intent.

Measured before the fix (Reddit listing "[HIRING] Virtual assistant / We pay
weekly. Remote." — no amount anywhere): emitted `min_amount=50.0`,
`estimated_value=50.0`; after mapping through `SocialSource._discover` that
became `advertised_amount=50.0`, and `validate_opportunity` returned
`status="valid"`, `payment_present=True`, `reasons=[]`. A post that offered no
money passed structural validation with no reasons at all.

Same class of defect as the LinkedIn/WeWorkRemotely fixes in v2.1.68 — those
were fixed, this pair was not.

No network: `feedparser` and the feed/API responses are mocked.
"""
import os
import sys
import types
import unittest
from unittest import mock

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _fake_feedparser(entries):
    """Install a feedparser stub returning `entries` from any parse() call."""

    class _Entry(dict):
        __getattr__ = dict.get

    mod = types.ModuleType("feedparser")

    def parse(_url):
        class _Feed:
            pass

        # The Reddit scan reads `entry.title` / `entry.link` as attributes;
        # _Entry exposes dict keys as attributes so a plain dict stub works.
        _Feed.entries = [_Entry(e) for e in entries]
        return _Feed()

    mod.parse = parse
    return mock.patch.dict(sys.modules, {"feedparser": mod})


class TestRedditScanNeverFabricates(unittest.TestCase):
    """ARCH-ENG-118 — Reddit social scan."""

    PLATFORM = "agents.earning.social_earning_platform"

    def test_listing_with_no_amount_emits_zero_not_fifty(self):
        from agents.earning.social_earning_platform import SocialEarningPlatform

        entry = {
            "title": "[HIRING] Virtual assistant",
            "link": "https://reddit.com/r/forhire/va1",
            "description": "We pay weekly. Remote work.",
        }
        with _fake_feedparser([entry]):
            opps = SocialEarningPlatform()._scan_reddit_jobs()

        # Two feeds are scanned, so the stub entry appears once per feed.
        self.assertTrue(opps)
        for o in opps:
            self.assertEqual(o.min_amount, 0.0,
                             "a listing stating no amount must not gain one")
            self.assertEqual(o.estimated_value, 0.0)

    def test_comma_amount_is_not_truncated(self):
        """`\\$(\\d+)` read "$1,500" as "1" — a 1500x understatement."""
        from agents.earning.social_earning_platform import SocialEarningPlatform

        entry = {
            "title": "[HIRING] Brand designer",
            "link": "https://reddit.com/r/forhire/d1",
            "description": "Budget is $1,500 total for the full project.",
        }
        with _fake_feedparser([entry]):
            opps = SocialEarningPlatform()._scan_reddit_jobs()

        self.assertTrue(opps)
        for o in opps:
            self.assertEqual(o.min_amount, 1500.0)

    def test_plain_amount_still_parsed(self):
        from agents.earning.social_earning_platform import SocialEarningPlatform

        entry = {
            "title": "[HIRING] Bug fix, $50 bounty",
            "link": "https://reddit.com/r/forhire/b1",
            "description": "Small patch, quick turnaround.",
        }
        with _fake_feedparser([entry]):
            opps = SocialEarningPlatform()._scan_reddit_jobs()

        self.assertTrue(opps)
        for o in opps:
            self.assertEqual(o.min_amount, 50.0)

    def test_unpayable_listing_no_longer_passes_validation(self):
        """The regression that mattered: fabricated 50.0 made it VALID."""
        from agents.earning.social_earning_platform import SocialEarningPlatform
        from agents.discovery.discovery_sources import SocialSource
        from agents.earning.opportunity_models import validate_opportunity

        entry = {
            "title": "[HIRING] Virtual assistant",
            "link": "https://reddit.com/r/forhire/va2",
            "description": "We pay weekly. Remote work.",
        }
        # Keep the stub installed through _discover(): SocialSource reads every
        # social source, and without it the others reach the real network.
        with _fake_feedparser([entry]):
            raw = SocialEarningPlatform()._scan_reddit_jobs()
            self.assertTrue(raw)
            canonical = SocialSource()._discover()

        self.assertTrue(canonical)
        for c in canonical:
            v = validate_opportunity(c)
            self.assertEqual(c.advertised_amount, 0.0)
            self.assertFalse(v.payment_present,
                             "no stated amount must not read as payment present")
            self.assertIn("missing payment information", " ".join(v.reasons))

    def test_no_hardcoded_fallback_literal_remains(self):
        """Structurally pin the fix: the `else 50.0` fallback is gone."""
        import ast

        path = os.path.join(str(Path(__file__).resolve().parents[2]), "agents", "earning",
                            "social_earning_platform.py")
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_scan_reddit_jobs":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.IfExp):
                        # `X if cond else <literal>`
                        if isinstance(sub.orelse, ast.Constant) and isinstance(
                                sub.orelse.value, float) and sub.orelse.value > 0:
                            found.append(sub.orelse.value)
        self.assertEqual(found, [],
                         "a positive float fallback in the Reddit scan is a "
                         "fabricated payout")


class TestGithubBountyNeverFabricates(unittest.TestCase):
    """ARCH-ENG-119 — GitHub bounty scan."""

    def _response(self, items):
        return mock.Mock(status_code=200, json=lambda: {"items": items})

    def _issue(self, title, body, num=1):
        return {
            "id": num,
            "title": title,
            "body": body,
            "html_url": f"https://github.com/example/project/issues/{num}",
            "repository_url": "https://api.github.com/repos/example/project",
            "labels": [{"name": "bounty"}],
        }

    def test_issue_with_no_amount_emits_zero_not_ten(self):
        from agents.earning.discoverer import EarningDiscoverer

        resp = self._response([
            self._issue("Bounty: improve parser",
                        "Paid issue, contact us for details.", num=1),
        ])
        with mock.patch("agents.earning.discoverer.requests.get", return_value=resp):
            opps = EarningDiscoverer()._discover_github_bounties()

        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].min_amount, 0.0)
        self.assertEqual(opps[0].estimated_usd_value, 0.0)

    def test_implausible_amount_becomes_unknown_not_ten(self):
        """The absurd-parse guard previously wrote 10.0, not 0."""
        from agents.earning.discoverer import EarningDiscoverer

        resp = self._response([
            self._issue("Bounty: huge number",
                        "$239398281948585883* bounty available.", num=2),
        ])
        with mock.patch("agents.earning.discoverer.requests.get", return_value=resp):
            opps = EarningDiscoverer()._discover_github_bounties()

        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].min_amount, 0.0)

    def test_real_amount_still_parsed(self):
        from agents.earning.discoverer import EarningDiscoverer

        resp = self._response([
            self._issue("Paid bounty: improve parser",
                        "A $25 reward is available.", num=3),
        ])
        with mock.patch("agents.earning.discoverer.requests.get", return_value=resp):
            opps = EarningDiscoverer()._discover_github_bounties()

        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].min_amount, 25.0)

    def test_comma_amount_is_not_truncated(self):
        from agents.earning.discoverer import EarningDiscoverer

        resp = self._response([
            self._issue("Bounty: big feature",
                        "We will pay $2,500 on merge.", num=4),
        ])
        with mock.patch("agents.earning.discoverer.requests.get", return_value=resp):
            opps = EarningDiscoverer()._discover_github_bounties()

        self.assertEqual(len(opps), 1)
        self.assertEqual(opps[0].min_amount, 2500.0)

    def test_no_hardcoded_fallback_literal_remains(self):
        """Structurally pin the fix: both `10.0` fallbacks are gone."""
        import ast

        path = os.path.join(str(Path(__file__).resolve().parents[2]), "agents", "earning", "discoverer.py")
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and \
                    node.name == "_discover_github_bounties":
                for sub in ast.walk(node):
                    # `X if cond else 10.0`
                    if isinstance(sub, ast.IfExp) and isinstance(
                            sub.orelse, ast.Constant) and sub.orelse.value == 10.0:
                        found.append("ifexp")
                    # `bounty = 10.0`
                    if isinstance(sub, ast.Assign) and isinstance(
                            sub.value, ast.Constant) and sub.value.value == 10.0:
                        found.append("assign")
        self.assertEqual(found, [],
                         "a hardcoded 10.0 in the bounty scan is a fabricated payout")


if __name__ == "__main__":
    unittest.main()
