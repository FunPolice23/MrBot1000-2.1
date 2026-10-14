"""Unattributed `$` figure is not a payout (ARCH-ENG-120).

`AirdropScanner._parse_entry` booked the FIRST `$` figure anywhere in the
headline+body as the airdrop's `estimated_value_usd`, with no check that the
figure described the payout. A BTC market price became a $95,000 airdrop:

  headline: "Bitcoin holds at $95,000 as airdrop season begins"
  _parse_entry      -> estimated_value_usd = 95000.0
  AirdropSource     -> advertised_amount=95000.0, estimated_net_value=95000.0
  opportunity_intelligence -> EV $3,446.52, verdict "attractive" (threshold 20.0)

Reachability was live: AirdropSource is in `all_builtin_sources()`, enabled
with MRBOT_ENABLE_AIRDROPS unset, reached via run_full_cycle -> discover();
the `feature_enabled("airdrop_claiming")` gate in app/earning_pipeline.py
only guards the legacy `_discover_source` path, which has no callers.

Per the golden rule, an amount a listing never stated for the payout is
unknown (0.0), never a guess. A figure is now only booked when the text ties
it to the airdrop/reward; a bare price quote yields 0.0. Genuinely stated
values ("airdrop worth $500", "valued at $1,200") still parse — the fix must
not over-reject.

No network: feed entries are constructed as plain dicts and passed straight
to `_parse_entry` / through a `_parse_feed` stub.

Scope note: the currency mislabel in AirdropSource._discover (a USD `$`
figure published as `currency="TOKEN"`) is a separate finding and is
deliberately untouched here, as is `_evaluate_opportunity`'s 50.0/10.0
defaults (no production caller).
"""
import ast
import os
import sys
import unittest

sys.path.insert(0, r"D:\MrBot1000_2.0")

SCANNER_PATH = os.path.join(
    r"D:\MrBot1000_2.0", "agents", "earning", "airdrop_scanner.py"
)

BTC_PRICE_HEADLINE = "Bitcoin holds at $95,000 as airdrop season begins"


def _parse(title, body=""):
    """Run `_parse_entry` directly with a constructed entry dict."""
    from agents.earning.airdrop_scanner import AirdropScanner

    scanner = AirdropScanner()
    combined = f"{title} {body}".strip()
    return scanner._parse_entry(
        {"title": title, "link": "https://example.test/airdrop/1"}, combined
    )


class TestUnattributedDollarIsUnknown(unittest.TestCase):
    """A `$` figure the listing never attributed to the payout is 0.0."""

    def test_market_price_is_not_a_payout(self):
        """The measured repro: BTC price became a $95,000 airdrop."""
        opp = _parse(BTC_PRICE_HEADLINE)
        self.assertIsNotNone(opp)
        self.assertEqual(
            opp.estimated_value_usd, 0.0,
            "a BTC price quote is market commentary, not a stated payout",
        )

    def test_other_price_phrasings_also_yield_unknown(self):
        for headline in (
            "ETH trades at $3,200 while airdrop season begins",
            "Bitcoin price of $95,000 dominates airdrop headlines",
            "SOL drops to $140 as the token distribution debate rages",
        ):
            with self.subTest(headline=headline):
                self.assertEqual(_parse(headline).estimated_value_usd, 0.0)

    def test_no_amount_stated_yields_unknown(self):
        opp = _parse("New retroactive airdrop announced for early users")
        self.assertEqual(opp.estimated_value_usd, 0.0)


class TestGenuineValueStillParses(unittest.TestCase):
    """The fix must not over-reject: stated payouts still parse."""

    def test_airdrop_worth_parses(self):
        opp = _parse("New protocol airdrop worth $500 for early users")
        self.assertEqual(opp.estimated_value_usd, 500.0)

    def test_valued_at_parses(self):
        opp = _parse("Retroactive rewards valued at $1,200 announced")
        self.assertEqual(opp.estimated_value_usd, 1200.0)

    def test_comma_amount_not_truncated(self):
        opp = _parse("Community reward: airdrop worth $2,500 for stakers")
        self.assertEqual(opp.estimated_value_usd, 2500.0)

    def test_decimal_amount_parses(self):
        opp = _parse("Testnet campaign distributes a reward of $12.50")
        self.assertEqual(opp.estimated_value_usd, 12.5)

    def test_value_after_price_quote_still_parses(self):
        """A real payout later in the text must not be masked by the price."""
        opp = _parse(
            "Bitcoin holds at $95,000 while the new airdrop is worth $500"
        )
        self.assertEqual(opp.estimated_value_usd, 500.0)

    def test_up_to_amount_parses(self):
        """"up to $X" is genuine payout language, not price language."""
        opp = _parse("Airdrop season begins, up to $300 per wallet claimed")
        self.assertEqual(opp.estimated_value_usd, 300.0)

    # --- Reviewer-found over-rejections (ARCH-ENG-120 review pass) ----------
    # The first version of this fix only looked BACKWARD from the figure for a
    # value cue, so real payouts whose cue FOLLOWS the amount were silently
    # dropped. Each case below failed against that first version.

    def test_cue_after_amount_parses(self):
        """"$2,500 reward for testnet participants" — the cue is AFTER the $."""
        opp = _parse("AirDrop: $2,500 reward for testnet participants")
        self.assertEqual(opp.estimated_value_usd, 2500.0)

    def test_appositive_subject_parses(self):
        """"Airdrop live now — $1,000" names the drop with no value verb."""
        opp = _parse("Airdrop live now — $1,000 for eligible wallets")
        self.assertEqual(opp.estimated_value_usd, 1000.0)

    def test_appositive_does_not_reopen_market_price(self):
        """A coin ticker next to a payout noun means the COIN is the subject.

        The appositive rule must not undo the original fix: "airdrop Bitcoin
        $95,000" is still a BTC price, not a payout.
        """
        for headline in (
            "airdrop Bitcoin $95,000",
            "Airdrop speculation — BTC $95,000",
            "The airdrop Bitcoin price $95,000 today",
            "Airdrop hunters, Solana at $210",
            "airdrop season begins bitcoin $95,000",
            # ARCH-ENG-120 review pass: 7 words sit in BOTH VALUE_INTENT_CUES and
            # PAYOUT_NOUNS, so the first market-subject guard ("no payout noun
            # anywhere before the figure") was disabled by any of them and all of
            # these booked a coin price as a payout. The guard now requires the
            # coin to be ADJACENT with no attribution verb between it and the $.
            "Airdrop allocation — Bitcoin $95,000 snapshot",
            "reward token Bitcoin $95,000 today",
            "Airdrop rewards: Bitcoin now $95,000",
            "Airdrop distribution as Bitcoin hits $95,000",
            "Airdrop giveaway news: Ethereum $4,200",
            "Staking rewards — BTC $95,000",
            "Airdrop payout update: SOL at $212",
            "airdrop prize announcement bitcoin $95,000",
            "Retroactive airdrop allocation, XRP $2.40",
            "airdrop news Bitcoin $95,000",
            "the drop Bitcoin price $95,000",
            "airdrop update: BTC now $95,000",
        ):
            with self.subTest(headline=headline):
                self.assertEqual(_parse(headline).estimated_value_usd, 0.0)

    def test_coin_adjacent_to_figure_is_a_price_not_a_payout(self):
        """The rule, stated directly: a ticker immediately before a bare figure.

        An attribution verb between the coin and the figure is what makes it a
        payout ("ETH stakers claim $500"); a coin sitting next to a bare figure
        is what makes it a quote ("...Bitcoin $95,000").
        """
        self.assertEqual(
            _parse("Protocol launches airdrop — Bitcoin $95,000").estimated_value_usd,
            0.0,
        )
        self.assertEqual(
            _parse("ETH stakers claim $500 airdrop").estimated_value_usd, 500.0,
        )

    def test_payment_demand_is_not_a_payout(self):
        """"pay $95,000 to claim" is a fee the victim owes, never revenue.

        Forward cues are restricted to nouns naming what is DISTRIBUTED, so a
        verb like "claim" after the figure cannot book a demand as a payout.
        """
        opp = _parse("WARNING: pay $95,000 to claim your airdrop")
        self.assertEqual(opp.estimated_value_usd, 0.0)

    def test_price_phrasings_still_rejected_with_payout_noun_present(self):
        """Price language must win even when an airdrop noun is nearby."""
        for headline in (
            "Airdrop news: Bitcoin holds at $95,000",
            "Airdrop rumours as ETH trades at $4,200",
        ):
            with self.subTest(headline=headline):
                self.assertEqual(_parse(headline).estimated_value_usd, 0.0)

    def test_known_over_rejections_are_recorded(self):
        """Headlines the reviewer found still drop to 0.0 — fail-SAFE, not silent.

        These are genuine payouts the cue tables do not yet recognise. Dropping
        them to 0.0 (unknown) is the correct direction per the golden rule — an
        unrecognised payout must never become a fabricated number — but they are
        pinned here so widening the cue tables is a conscious decision, and so a
        future change that makes them WORSE (booking a market price instead) is
        caught.
        """
        for headline in (
            "Eligible wallets receive $400 from the retroactive drop",
            "Users get $250 in the new airdrop",
            "Recipients will earn $120 from the drop",
            "Stakers earned $800 from the retroactive airdrop",
        ):
            with self.subTest(headline=headline):
                # 0.0 = "unknown", never a fabricated amount.
                self.assertEqual(_parse(headline).estimated_value_usd, 0.0)


class TestAirdropSourceEndToEnd(unittest.TestCase):
    """The canonical path: AirdropSource._discover -> Opportunity."""

    def test_price_headline_yields_zero_advertised_amount(self):
        from unittest import mock

        from agents.earning.airdrop_scanner import AirdropScanner
        from agents.discovery.discovery_sources import AirdropSource

        entries = [{
            "title": BTC_PRICE_HEADLINE,
            "description": "Market commentary on the airdrop season.",
            "url": "https://example.test/airdrop/btc",
        }]

        # `scan_feeds` calls `_parse_feed(feed_url)` per configured feed;
        # stub it so the same entry is seen on every feed with no network.
        with mock.patch.object(AirdropScanner, "_parse_feed",
                               return_value=entries):
            opportunities = AirdropSource()._discover()

        self.assertTrue(opportunities, "the entry should survive the filters")
        for opp in opportunities:
            self.assertEqual(
                opp.advertised_amount, 0.0,
                "a market price must not reach advertised_amount",
            )
            self.assertEqual(opp.estimated_net_value, 0.0)

    def test_genuine_airdrop_still_reaches_advertised_amount(self):
        from unittest import mock

        from agents.earning.airdrop_scanner import AirdropScanner
        from agents.discovery.discovery_sources import AirdropSource

        entries = [{
            "title": "New protocol airdrop worth $500 for early users",
            "description": "Claim window open now.",
            "url": "https://example.test/airdrop/genuine",
        }]

        with mock.patch.object(AirdropScanner, "_parse_feed",
                               return_value=entries):
            opportunities = AirdropSource()._discover()

        self.assertTrue(opportunities)
        for opp in opportunities:
            self.assertEqual(opp.advertised_amount, 500.0)


class TestStructuralPin(unittest.TestCase):
    """Pin the shape of the fix so the bare first-`$`-match cannot return."""

    def _source(self):
        with open(SCANNER_PATH, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_value_comes_from_attribution_helper(self):
        """`estimated_value_usd` is no longer fed by a bare `value_match`."""
        tree = ast.parse(self._source())

        parse_entry = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_parse_entry":
                parse_entry = node
        self.assertIsNotNone(parse_entry)

        # No `re.search(r"\$([\d,]+...")` anywhere inside _parse_entry: the
        # value must be decided by the attribution helper, not a first match.
        for node in ast.walk(parse_entry):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "search" and node.args:
                    arg = node.args[0]
                    if (isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)
                            and r"\$([\d" in arg.value):
                        self.fail(
                            "_parse_entry still takes the first $ figure: "
                            + arg.value
                        )

        # estimated_value_usd=... is a call to the attribution helper.
        assigned_from = []
        for node in ast.walk(parse_entry):
            if isinstance(node, ast.keyword) and node.arg == "estimated_value_usd":
                value = node.value
                self.assertIsInstance(value, ast.Call)
                assigned_from.append(
                    getattr(value.func, "attr", getattr(value.func, "id", ""))
                )
        self.assertTrue(assigned_from, "estimated_value_usd not assigned")
        for name in assigned_from:
            self.assertIn("value", name,
                          "estimated_value_usd must come from the attribution "
                          "helper, not a raw regex match")

    def test_helper_exists_and_returns_zero_default(self):
        tree = ast.parse(self._source())
        helper = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and \
                    node.name == "_extract_stated_value_usd":
                helper = node
        self.assertIsNotNone(
            helper, "_extract_stated_value_usd is the attribution rule"
        )
        zero_returns = [
            node.value.value
            for node in ast.walk(helper)
            if isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and node.value.value == 0.0
        ]
        self.assertTrue(
            zero_returns,
            "the unknown default must be 0.0, never a guessed payout",
        )

    def test_helper_behaviour_on_the_repro(self):
        from agents.earning.airdrop_scanner import AirdropScanner

        self.assertEqual(
            AirdropScanner._extract_stated_value_usd(BTC_PRICE_HEADLINE), 0.0
        )
        self.assertEqual(
            AirdropScanner._extract_stated_value_usd(
                "New protocol airdrop worth $500 for early users"
            ),
            500.0,
        )


if __name__ == "__main__":
    unittest.main()
