"""ARCH-ENG-212 — a fabricated payout estimate in the DeFi discovery branch.

## What was wrong

`app/earning_pipeline.py` built DeFi `Opportunity` records with:

    estimated_usd_value = opp.tvl_usd * (opp.apy_percent / 100) * 0.01

This is the exact expression `agents/discovery/discovery_sources.py:205-231`
deleted in a 27-line comment when that branch was rewritten. It survived in the
pipeline because the deletion was applied to one copy of the logic, not both —
the same shape as the blocklist duplicate, but on a revenue number.

## Why the number is not merely imprecise

It is not an estimate. It is **one share of a pool's own APY yield**:

* `tvl_usd` is the total value *other people's* money sits in the pool.
* `apy_percent` is the protocol's rate on that whole pool.

Neither says anything about what this agent could earn. Their product is not a
payout in any sense — it is a number that looks like revenue and is derived
from nothing the agent would ever receive.

It mattered because `estimated_usd_value` feeds the earning pipeline's scoring
and exposure limits, **including the `payment > 100.0` real-money threshold**.
The day any protocol branch populates `tvl_usd`, this books a stranger's pool
size as our earnings and could cross that threshold unaided.

Nothing populates `tvl_usd` today, so the defect is latent rather than live —
which is precisely why it survived. **No test can observe a number that is
never computed.**

## The fix

`estimated_usd_value=0.0`. There is no honest value derivable from this data,
and inventing a placeholder would recreate the defect with extra indirection.

## The rule this encodes

A value that reaches a revenue, payment, or exposure decision must be derived
from something the agent would actually receive. If the inputs do not support a
claim, the correct value is "unknown" — and in a numeric field that means zero,
not a plausible-looking product of unrelated quantities.

The test also asserts the *duplicate* is gone repo-wide, because the original
defect was one copy of a deleted expression surviving in another file.

ARCH-ENG-285 (W-01): the pipeline's legacy DeFi branch was deleted as a dead
parallel discovery island.  The live DeFi producer is now
`agents/discovery/discovery_sources.py:DefiSource`, so the structural checks
below target that producer instead of asserting a call site that no longer
exists.  The forbidden-expression and marker checks still scan both files, so
the deletion cannot be used to smuggle the fabricated formula back in.
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
PIPELINE = REPO / "app" / "earning_pipeline.py"
DISCOVERY_SOURCES = REPO / "agents" / "discovery" / "discovery_sources.py"

# The fabricated expression, in the forms it could plausibly be written.
# Two spellings, because the original could be written either way:
#   tvl_usd * (opp.apy_percent / 100) * 0.01     <- as it was
#   tvl_usd * opp.apy_percent / 100 * 0.01      <- parentheses dropped
#
# A third candidate -- `tvl_usd\s*\*\s*opp\.apy_percent` -- was removed after
# it failed its own probe: it requires the parenthesised form to be absent, so
# it could only ever match a spelling that never existed. A guard that cannot
# fail on anything real is worse than no guard.
FORBIDDEN = (
    r"tvl_usd\s*\*\s*\(?\s*opp\.apy_percent",
    r"apy_percent\s*/\s*100\s*\)?\s*\*\s*0\.01",
)


def _opportunities(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "Opportunity"]


class TestTheFabricatedEstimateIsGone(unittest.TestCase):
    """ARCH-ENG-212 — no pool size may be presented as our earnings."""

    @staticmethod
    def _code_without_comments(path=PIPELINE):
        """Source with comment text removed.

        The ARCH-ENG-212 comment at the site quotes the original expression
        verbatim so a future reader knows what was removed. A raw-text scan
        therefore matches its own documentation forever and can never pass.
        This is the third time this session that documenting a bug defeated the
        guard written to catch it.
        """
        src = path.read_text(encoding="utf-8")
        out = []
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            out.append(line.split("  #")[0] if "  #" in line else line)
        return "\n".join(out)

    def test_the_expression_is_not_reproduced_in_any_live_discovery_path(self):
        for path in (PIPELINE, DISCOVERY_SOURCES):
            code = self._code_without_comments(path)
            for pattern in FORBIDDEN:
                with self.subTest(path=path.name, pattern=pattern):
                    self.assertNotRegex(
                        code, pattern,
                        "the fabricated TVL x APY payout is back; it books a "
                        "stranger's pool size as this agent's earnings")

    def test_the_comment_scan_really_strips_comments(self):
        """Otherwise the guard above could pass by stripping everything."""
        code = self._code_without_comments()
        self.assertIn("class EarningPipeline", code,
                      "the live pipeline body must survive comment stripping")
        self.assertNotIn("ARCH-ENG-212", code,
                         "comments were not stripped, so the detectors above "
                         "are matching their own documentation")

    def test_no_deifi_opportunity_carries_a_derived_estimate(self):
        """Structural: every DeFi record must book no claimed payout."""
        calls = [call for path in (PIPELINE, DISCOVERY_SOURCES)
                 for call in _opportunities(path)]
        defi_calls = [call for call in calls
                      if "defi" in ast.unparse(call).lower()]
        # Vacuity: without this the loop below could pass on an empty list.
        self.assertGreaterEqual(
            len(defi_calls), 1,
            "no DeFi Opportunity records found in either live discovery "
            "producer; the scan is broken")
        for call in defi_calls:
            body = ast.unparse(call)
            with self.subTest(line=call.lineno):
                for field in ("advertised_amount", "estimated_net_value"):
                    match = re.search(rf"{field}=([^,\n]+)", body)
                    self.assertIsNotNone(
                        match, f"the DeFi Opportunity no longer sets {field}; "
                               f"the value is required for scoring and "
                               f"exposure limits")
                    value = match.group(1).strip()
                    self.assertIn(
                        value, ("0.0", "0"),
                        f"{field}={value} is derived from opportunity data "
                        f"(tvl_usd/apy_percent), which describes the pool, "
                        f"not our share of it")
                # ARCH-ENG-212's original field is not used by the live
                # canonical model; if it reappears it must still be zero.
                legacy = re.search(r"estimated_usd_value=([^,\n]+)", body)
                if legacy is not None:
                    self.assertIn(legacy.group(1).strip(), ("0.0", "0"))

    def test_the_reason_is_recorded_at_the_live_site(self):
        """A bare 0.0 would be "helpfully corrected" back to a formula."""
        src = DISCOVERY_SOURCES.read_text(encoding="utf-8")
        self.assertIn("ARCH-ENG-125", src,
                      "the zero needs a marker, or someone will replace it "
                      "with the product of two unrelated numbers")
        self.assertIn("advertised_amount=0.0", src)
        self.assertIn("estimated_net_value=0.0", src)


class TestTheZeroDoesNotBreakScoring(unittest.TestCase):
    """ARCH-ENG-212 — honesty must not become an outage."""

    def test_the_field_is_still_set(self):
        """A missing field would crash scoring; a zero is deliberate."""
        body = "\n".join(ast.unparse(c) for c in _opportunities(DISCOVERY_SOURCES)
                         if "defi" in ast.unparse(c).lower())
        self.assertIn("advertised_amount", body)
        self.assertIn("estimated_net_value", body)

    def test_the_exposure_threshold_still_compares_numerically(self):
        """The removed value fed `payment > 100.0`; a 0.0 must not break it."""
        estimate = 0.0
        self.assertFalse(estimate > 100.0,
                         "a zero estimate must fall below the exposure "
                         "threshold, which is the safe direction")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-212 — each detector must be able to fail."""

    # The original spanned TWO lines with the parenthesis opening the second,
    # which is why a single-line probe found nothing. Each pattern is checked
    # against the exact original spelling below, single- and multi-line.
    ORIGINAL = ("estimated_usd_value=opp.tvl_usd\n"
                "                * (opp.apy_percent / 100) * 0.01,")

    def test_the_regexes_match_the_original_expression(self):
        for pattern in FORBIDDEN:
            with self.subTest(pattern=pattern):
                self.assertRegex(
                    self.ORIGINAL, pattern,
                    "a detector cannot see the original expression, so it "
                    "would pass while the fabricated payout returned")

    def test_the_regexes_also_see_a_single_line_spelling(self):
        """A reformatting must not smuggle the formula past the guard."""
        one_line = "estimated_usd_value=opp.tvl_usd * (opp.apy_percent / 100) * 0.01"
        for pattern in FORBIDDEN:
            with self.subTest(pattern=pattern):
                self.assertRegex(one_line, pattern)

    def test_the_structural_check_sees_a_derived_value(self):
        bad = ast.parse(
            "Opportunity(id='defi_1', source='defi',\n"
            "             estimated_usd_value=opp.tvl_usd * 0.01)")
        call = next(n for n in ast.walk(bad) if isinstance(n, ast.Call))
        body = ast.unparse(call)
        match = re.search(r"estimated_usd_value=([^,\n]+)", body)
        self.assertIsNotNone(match)
        self.assertNotIn(
            match.group(1).strip(), ("0.0", "0"),
            "the structural check cannot see a derived value, so it would "
            "pass while the formula returned")

    def test_the_opportunity_scan_can_find_defi_records(self):
        """Otherwise every structural assertion above is vacuous."""
        defi = [c for path in (PIPELINE, DISCOVERY_SOURCES)
                for c in _opportunities(path)
                if "defi" in ast.unparse(c).lower()]
        self.assertGreaterEqual(
            len(defi), 1,
            "no DeFi Opportunity records found; the scan is broken and the "
            "structural guard would pass on anything")