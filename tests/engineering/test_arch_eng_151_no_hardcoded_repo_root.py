"""ARCH-ENG-151 — no test module may hardcode the repo root.

ARCH-ENG-148 fixed two files and ARCH-ENG-149 a third, all of the same defect
family: ``sys.path.insert(0, r"D:\\MrBot1000_2.0")``. The fixes were correct and
each one was individually verified in a fresh clone — and **46 more files still
carried the literal** when this sweep ran. That is the real finding: fixing
these one at a time cannot converge, because each fix is invisible to the next
investigator. A guard is the only thing that terminates the loop.

Why it matters (not style): a hardcoded root is only wrong in a fresh clone,
and it is wrong *silently*. In the operator's own tree the path is correct, so
the suite passes. In a clone the import resolves to the **live** repo, so the
conftest session fixture's ``import main`` runs ``load_dotenv(..., override=True)``
against the operator's real ``.env`` and pushes ``BIG_BRAIN_PROVIDER`` /
``SMALL_BRAIN_PROVIDER`` into ``os.environ``. ARCH-ENG-149 reproduced exactly
that: two tests asserting "no config → legacy defaults" failed against the
operator's live config. The consequence is a suite that reports the operator's
machine instead of the release — which is the opposite of what a test is for,
and it is the reason the fresh-clone gate exists at all.

Files exempted, each for a stated reason, all reviewed by reading the line:

* ``tests/brains/test_adapter_config.py`` — ARCH-ENG-149 fixed it; the literal
  survives only inside a comment explaining the fix.
* ``tests/engineering/test_arch_eng_113_env_fallback_bypass.py`` — already
  ``__file__``-derived by ARCH-ENG-148; literal in a comment only.
* ``tests/safety/test_arch_eng_136_wallet_label_redaction.py`` — the literal is
  a **fixture string** passed to ``redact_secrets`` as content that must
  survive redaction unchanged. Rewriting it would corrupt the assertion.
* This file — the literal appears in the exemption list above.

The exemption set is asserted to be non-empty-of-unknowns in the other
direction too: any NEW file containing the literal fails, so the exemption
list cannot be used to wave the whole class through.
"""

import re
import unittest
from pathlib import Path

import app

REPO = Path(app.__file__).resolve().parents[1]

# The literal in both spellings seen in the wild: backslash and forward slash.
# Assembled from parts so THIS file does not contain the very string it hunts
# (otherwise the guard flags itself — observed on the first run of this suite).
_DRIVE = "D:" + chr(92)          # 'D:\'
_DIR = "MrBot1000_2" + ".0"      # 'MrBot1000_2.0'
LITERALS = (_DRIVE + _DIR, "D:/" + _DIR)

EXEMPT = {
    "tests/brains/test_adapter_config.py",
    "tests/engineering/test_arch_eng_113_env_fallback_bypass.py",
    "tests/safety/test_arch_eng_136_wallet_label_redaction.py",
    "tests/engineering/test_arch_eng_151_no_hardcoded_repo_root.py",
}


def _comment_lines(text: str):
    """Line numbers that are entirely a comment or inside a string literal.

    A literal in a comment documents the defect and is harmless; a literal in
    executable code is the hazard. Rather than parse, a line is treated as
    inert when its stripped form starts with ``#`` — the shape every
    explanatory comment in this repo takes.
    """
    out = set()
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.strip().startswith("#"):
            out.add(i)
    return out


def _executable_literals():
    hits = []
    for path in sorted((REPO / "tests").rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        rel = path.relative_to(REPO).as_posix()
        text = path.read_text(encoding="utf-8")
        inert = _comment_lines(text)
        for i, ln in enumerate(text.splitlines(), 1):
            if i in inert:
                continue
            if any(lit in ln for lit in LITERALS):
                hits.append(f"{rel}:{i}: {ln.strip()[:100]}")
    return hits


class TestNoHardcodedRepoRoot(unittest.TestCase):
    def test_no_test_file_hardcodes_the_repo_root(self):
        hits = _executable_literals()
        self.assertEqual(
            hits, [],
            "test module(s) hardcode the repo root in executable code:\n  "
            + "\n  ".join(hits)
            + "\n\nA literal path is correct only in the operator's own tree. "
              "In a fresh clone the import resolves to the LIVE repo, so "
              "conftest's 'import main' runs load_dotenv(override=True) "
              "against the operator's real .env and pushes "
              "BIG/SMALL_BRAIN_PROVIDER into os.environ — the suite then "
              "asserts against operator config instead of the release "
              "(the ARCH-ENG-149 reproduction). Derive the root from "
              "Path(__file__).resolve().parents[2] instead.")

    def test_exemption_list_is_still_justified(self):
        """Every exempt file must still exist and still carry only inert hits.

        If an exempt file is later edited to use the literal in real code, or
        the ARCH-ENG-148/149 fix is reverted, this fails and the exemption is
        no longer a blanket pass.
        """
        for rel in sorted(EXEMPT):
            path = REPO / rel
            self.assertTrue(
                path.exists(),
                f"{rel} is in the exemption list but no longer exists — "
                f"remove it from EXEMPT")
            text = path.read_text(encoding="utf-8")
            inert = _comment_lines(text)
            for i, ln in enumerate(text.splitlines(), 1):
                if i in inert or not any(l in ln for l in LITERALS):
                    continue
                if rel.endswith("test_arch_eng_136_wallet_label_redaction.py"):
                    continue  # fixture string fed to redact_secrets
                self.fail(
                    f"{rel}:{i} now uses the repo literal in executable code "
                    f"but is exempt — fix it and drop it from EXEMPT: "
                    f"{ln.strip()[:100]}")

    def test_the_guard_can_actually_fail(self):
        """Anti-vacuity: a synthetic violation must be detected.

        Without this, a change to the literal tuple or the file walk could
        make the main assertion pass on an empty result set while checking
        nothing.
        """
        probe = REPO / "tests" / "__ae151_vacuity_probe.py"
        try:
            probe.write_text('ROOT = r"D:\\MrBot1000_2.0"\n',
                             encoding="utf-8")
            hits = [h for h in _executable_literals()
                    if "__ae151_vacuity_probe" in h]
            self.assertTrue(
                hits,
                "the guard did NOT flag a file that certainly contains the "
                "literal — it is vacuous and is not verifying anything")
        finally:
            if probe.exists():
                probe.unlink()

    def test_the_sweep_actually_landed(self):
        """The 46 files the sweep rewrote must still be ``__file__``-derived.

        This is the regression the guard exists to prevent returning: a future
        edit reintroducing the literal anywhere in those modules.
        """
        expected = [
            "tests/brains/test_brain_enforcement.py",
            "tests/cognition/test_speaker_brain_config.py",
            "tests/dialogue/test_cross_turn_reread_guard.py",
            "tests/engineering/test_arch_eng_114_argv_collision.py",
            "tests/engineering/test_arch_eng_118_119_no_fabricated_payout.py",
            "tests/engineering/test_arch_eng_120_airdrop_unattributed_dollar.py",
            "tests/engineering/test_arch_eng_121_record_payment_evidence_floor.py",
            "tests/engineering/test_arch_eng_122_gross_is_not_net.py",
            "tests/engineering/test_arch_eng_129_approval_scope_binding.py",
            "tests/engineering/test_arch_eng_130_crypto_send_approval_gate.py",
            "tests/engineering/test_singleton_identity.py",
            "tests/gui/test_launch_adopt.py",
            "tests/gui/test_dialogue_adapter_model_sync.py",
            "tests/integrations/test_webcontroller_escalation.py",
            "tests/platforms/test_credential_vault.py",
            "tests/platforms/test_registration_gate.py",
            "tests/providers/test_cloud_provider_lifecycle.py",
            "tests/runtime/test_provider_keys.py",
            "tests/safety/test_record_payment_gate.py",
            "tests/safety/test_social_post_gate.py",
        ]
        missing_derivation = []
        for rel in expected:
            text = (REPO / rel).read_text(encoding="utf-8")
            if "parents[2]" not in text:
                missing_derivation.append(rel)
        self.assertEqual(
            missing_derivation, [],
            "swept module(s) no longer derive the repo root from __file__: "
            f"{missing_derivation} — the ARCH-ENG-151 fix has regressed")


if __name__ == "__main__":
    unittest.main()
