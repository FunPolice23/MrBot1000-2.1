"""Regression tests for ARCH-ENG-307 and ARCH-ENG-308.

ARCH-ENG-307 -- the VRAM default-clamp note (``[small] context ... tier
allows ...``) was pure startup noise as emitted:

* ``SMALL_BRAIN_CONTEXT`` was set explicitly in ``.env``, and the ARCH-ENG-222
  contract says an explicit value wins untouched -- yet build_config still ran
  the clamp on the default and logged "tier allows 16384 ... not 32768" while
  the brain actually ran 32768. The note described a clamp that never landed.
* build_config runs several times per startup and each run re-logged the same
  note, so the operator saw five identical INFO lines.

The fix: an explicit CONTEXT override skips the clamp entirely (nothing
computed, nothing logged); without an override, each distinct note is logged
once per process; and the tier-table fallback now says WHY it ran (the model
was not measurable), which is what the operator needs to judge the number.

ARCH-ENG-308 -- the numeric evidence check flagged ``$0`` as an unsupported
monetary value when the model wrote it as shorthand for an unpaid listing.
Zero cannot be fabricated earnings; it can only understate them, so it is
exempt. Every nonzero value is checked exactly as before.
"""

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents.evidence.numeric_evidence import unsupported_values  # noqa: E402


# ── ARCH-ENG-307: the clamp note describes reality, and is logged once ─────


class TestExplicitContextSkipsTheClamp(unittest.TestCase):
    """An explicit CONTEXT override wins untouched, and says nothing."""

    def test_explicit_context_wins_and_no_clamp_no_note(self):
        import agents.runtime.dual_brain as db

        env = {
            "SMALL_BRAIN_PROVIDER": "llamacpp",
            "SMALL_BRAIN_CONTEXT": "16384",
            "SMALL_BRAIN_KV_CACHE": "q8_0",
        }
        with patch.object(db, "_vram_safe_context") as clamp, \
                patch.object(db.logger, "info") as info:
            cfg = db.build_config(db.BrainRole.SMALL, env=env)
        self.assertEqual(cfg.context, 16384)
        clamp.assert_not_called()
        info.assert_not_called()

    def test_default_context_still_gets_the_clamp(self):
        """Vacuity probe: without the override the clamp must still run."""
        import agents.runtime.dual_brain as db

        env = {"SMALL_BRAIN_PROVIDER": "llamacpp"}
        with patch.object(db, "_vram_safe_context",
                          return_value=(16384, "tier note")):
            cfg = db.build_config(db.BrainRole.SMALL, env=env)
        self.assertEqual(cfg.context, 16384)


class TestTheClampNoteIsLoggedOnce(unittest.TestCase):
    def test_identical_reson_logged_once(self):
        import agents.runtime.dual_brain as db

        env = {"SMALL_BRAIN_PROVIDER": "llamacpp"}
        with patch.object(db, "_CONTEXT_NOTES_LOGGED", set()), \
                patch.object(db, "_vram_safe_context",
                             return_value=(16384, "tier note")), \
                patch.object(db.logger, "info") as info:
            db.build_config(db.BrainRole.SMALL, env=dict(env))
            db.build_config(db.BrainRole.SMALL, env=dict(env))
        self.assertEqual(info.call_count, 1)

    def test_a_different_reason_is_still_logged(self):
        import agents.runtime.dual_brain as db

        env = {"SMALL_BRAIN_PROVIDER": "llamacpp"}
        with patch.object(db, "_CONTEXT_NOTES_LOGGED", set()), \
                patch.object(db, "_vram_safe_context",
                             side_effect=[(16384, "tier note"),
                                          (4096, "cpu note")]), \
                patch.object(db.logger, "info") as info:
            db.build_config(db.BrainRole.SMALL, env=dict(env))
            db.build_config(db.BrainRole.SMALL, env=dict(env))
        self.assertEqual(info.call_count, 2)


class TestTheFallbackNoteSaysWhy(unittest.TestCase):
    def _on_6gb(self):
        return SimpleNamespace(is_gpu=True, index=0, memory_gb=6.0)

    def test_note_names_the_unmeasurable_model(self):
        import agents.runtime.dual_brain as db

        with patch("agents.runtime.device_registry.detect_devices",
                   return_value=[self._on_6gb()]):
            _, reason = db._vram_safe_context(
                32768, db.BrainRole.SMALL, 0, None,
                model_path="C:/models/small.gguf", kv_type_bytes=1)
        self.assertIn("model at C:/models/small.gguf was not measurable", reason)
        self.assertIn("allows 16384", reason)

    def test_note_names_the_missing_path(self):
        import agents.runtime.dual_brain as db

        with patch("agents.runtime.device_registry.detect_devices",
                   return_value=[self._on_6gb()]):
            _, reason = db._vram_safe_context(
                32768, db.BrainRole.SMALL, 0, None,
                model_path=None, kv_type_bytes=1)
        self.assertIn("no local model file to measure", reason)


# ── ARCH-ENG-308: zero needs no context evidence ───────────────────────────


class TestZeroIsExemptFromTheEvidenceCheck(unittest.TestCase):
    def test_zero_unpaid_listing_is_never_a_gap(self):
        # Jacob's transcript turn, verbatim shape: the board showed no
        # dollar figure at all and the model wrote "$0" as shorthand.
        self.assertEqual(
            unsupported_values(
                "All listed opportunities have $0 expected USD value or are "
                "unpaid.", "The workshops: three listings, all unpaid."),
            [])

    def test_mixed_turn_reports_only_the_nonzero_value(self):
        self.assertEqual(
            unsupported_values("The posting is $0; the payout is $7,000.",
                               "posted: unpaid listings only."),
            ["$7,000"])

    def test_nonzero_values_still_require_context(self):
        """Vacuity probe: the zero exemption must not disable the check."""
        self.assertEqual(
            unsupported_values("I earn $4,500 here.", "nothing about money"),
            ["$4,500"])

    def test_zero_still_matches_when_it_is_in_the_context(self):
        self.assertEqual(
            unsupported_values("It pays $0.00.", "Payout: $0.00"), [])


if __name__ == "__main__":
    unittest.main()
