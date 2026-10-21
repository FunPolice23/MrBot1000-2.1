"""ARCH-ENG-150 — a CHANGELOG entry cannot claim a fix that is not in the release.

v2.1.104 recorded ARCH-ENG-143 and ARCH-ENG-144 as released. They were not.
Verified against ``git show`` on the four commits that entry named: only
ARCH-ENG-145 (``6335ed4``, ``cost.py``) had landed — ``HEAD:app/earning_memory.py``
carried no ``platform_key`` and ``HEAD:agents/services/autonomous_loop.py`` no
``payment_evidence`` capture. The code existed only in the working tree, so the
documented release was a record of work a fresh clone would never contain.

That is a *documentation* defect with a *software* consequence: the operator
reads the changelog to learn what protections they have. An entry that names a
safety or accounting fix which is absent from HEAD tells the operator they are
protected by something that is not in the build they are running. ARCH-ENG-143
was a verified-payment discard and ARCH-ENG-144 a fail-open win-rate guard —
both financial-integrity controls. Claiming them falsely is worse than not
claiming them, because it suppresses the investigation that would find them
missing.

This suite closes the hole mechanically rather than by discipline.

ARCH-ENG-152 (the vacuity probe below) is part of this file: the probe tag
is constructed at runtime so the guard cannot match itself.

SCOPE (why only the top entry, and why that is not a weaker check): every
``ARCH-ENG-nnn`` named in a CHANGELOG entry must be findable in tracked code.
Seven historical ids (071, 076-080, 131) fail a whole-file grep **because their
code carries no tag comment at all** — the implementation is present and
correct, it simply was never annotated. A guard that scanned all 125 entries
would red-line on those seven forever and train the operator to ignore it, so
it would be a false-alarm machine rather than a control. The top entry is the
one entry whose claim is *load-bearing right now* — it is the release the
operator is running, and it is the entry a fix author writes before the code is
committed. That is exactly where v2.1.104 failed. So the top entry is asserted
hard; older entries are reported, not failed.

The second invariant: every id in the top entry must appear in a **test** file.
A recorded fix with no regression test is the same "recorded but not really
there" defect at one remove — ARCH-ENG-147 shipped green precisely because its
fakes encoded the caller's bug, so the entry's claim of a fix was never
exercised. Requiring the tag in a test does not prove the test is good, but it
proves the release did not ship a claim with no executable check behind it.

Hermeticity: REPO comes from the installed ``app`` package, never a hardcoded
path (ARCH-ENG-113/149 class — a literal ``D:\\MrBot1000_2.0`` made a fresh
clone probe the LIVE repo). The guard inspects ``HEAD`` via ``git grep``, so a
dirty working tree cannot make an absent fix look present — that is the exact
condition v2.1.104 got wrong. Where the tree is not a git checkout (an exported
tarball, a zip download) the suite SKIPS with a reason instead of erroring: the
subject it guards, "is this commit in the release", does not exist there. This
mirrors the ARCH-ENG-148 precedent for a suite whose subject was never shipped.
"""

import re
import subprocess
import unittest
from pathlib import Path

import app

REPO = Path(app.__file__).resolve().parents[1]
CHANGELOG = REPO / "CHANGELOG.md"
VERSION_FILE = REPO / "app" / "version.py"

ID_RE = re.compile(r"ARCH-ENG-(\d+)")


def _is_git_checkout() -> bool:
    r = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=REPO,
                       capture_output=True, text=True)
    return r.returncode == 0


def _authority_version() -> str:
    m = re.search(r'^__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']',
                  VERSION_FILE.read_text(encoding="utf-8"), re.MULTILINE)
    return m.group(1) if m else ""


def _top_entry(changelog_text: str) -> str:
    """The body of the first ``## [x.y.z]`` entry, heading line included."""
    parts = re.split(r"^## ", changelog_text, flags=re.MULTILINE)
    if len(parts) < 2:
        return ""
    body = "## " + parts[1]
    # Cut at the next entry heading so an id named in an OLD entry does not
    # count as evidence for the top one.
    nxt = re.search(r"^## ", body[len("## "):], flags=re.MULTILINE)
    return body[:len("## ") + nxt.start()] if nxt else body


def _ids_named(entry: str):
    return sorted({f"ARCH-ENG-{n}" for n in ID_RE.findall(entry)},
                  key=lambda t: int(t.rsplit("-", 1)[1]))


def _ids_present_in_head(ids) -> list:
    """Which of ``ids`` are findable in TRACKED code at HEAD (excluding the
    changelog itself — the changelog naming its own claim is not evidence).

    ``git grep ... HEAD`` reads the committed tree, so uncommitted work cannot
    satisfy this. That is the whole point: it is what v2.1.104 got wrong.
    """
    missing = []
    for tag in ids:
        r = subprocess.run(
            ["git", "grep", "-l", "--", tag, "HEAD", "--",
             ":!CHANGELOG.md"],
            cwd=REPO, capture_output=True, text=True)
        if not r.stdout.strip():
            missing.append(tag)
    return missing


def _ids_with_test(ids) -> list:
    """Which of ``ids`` appear in a tracked TEST file at HEAD."""
    missing = []
    for tag in ids:
        r = subprocess.run(
            ["git", "grep", "-l", "--", tag, "HEAD", "--", "tests/"],
            cwd=REPO, capture_output=True, text=True)
        if not r.stdout.strip():
            missing.append(tag)
    return missing


@unittest.skipUnless(_is_git_checkout(),
                     "not a git checkout — 'is this fix in the release' is "
                     "not a question this tree can answer")
class TestRecordedFixIsInTheRelease(unittest.TestCase):
    """The top CHANGELOG entry's claims must be present in HEAD."""

    @classmethod
    def setUpClass(cls):
        cls.text = CHANGELOG.read_text(encoding="utf-8")
        cls.entry = _top_entry(cls.text)
        cls.ids = _ids_named(cls.entry)

    def test_top_entry_exists_and_names_the_authority(self):
        authority = _authority_version()
        self.assertTrue(authority, "could not read app/version.py")
        m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", self.entry, re.MULTILINE)
        self.assertTrue(m, "CHANGELOG.md has no version heading")
        self.assertEqual(
            m.group(1), authority,
            f"top CHANGELOG entry is {m.group(1)} but app/version.py is "
            f"{authority} — the guard cannot know which release is live")

    def test_top_entry_names_at_least_one_fix(self):
        """A vacuous entry would make every claim below pass trivially."""
        self.assertTrue(
            self.ids,
            "the top CHANGELOG entry names no ARCH-ENG-nnn id; either it is "
            "not a fix entry or the ids are written in an unrecognised form")

    def test_every_named_fix_is_present_in_head(self):
        """THE guard. v2.1.104 failed exactly here: ids named, code absent."""
        missing = _ids_present_in_head(self.ids)
        self.assertEqual(
            missing, [],
            "the top CHANGELOG entry records fix(es) "
            f"{missing} that are NOT in HEAD's tracked code. Either the code "
            "was never committed (the v2.1.104 defect: the operator is told "
            "they are protected by something absent from the build), or the "
            "fix landed without its ARCH-ENG-nnn tag — annotate the code.")

    def test_every_named_fix_has_a_regression_test_in_head(self):
        missing = _ids_with_test(self.ids)
        self.assertEqual(
            missing, [],
            "the top CHANGELOG entry records fix(es) "
            f"{missing} with no test in HEAD carrying that id. A recorded fix "
            "with no executable check is the ARCH-ENG-147 failure mode: the "
            "claim was never exercised, so it shipped green.")

    def test_an_id_that_is_not_in_head_is_detected(self):
        """Anti-vacuity: prove the checker can actually fail.

        Without this, a change to the grep pattern or a silent subprocess
        failure could make every assertion above pass on an empty result set
        and the guard would report CLEAR while checking nothing.

        The probe tag is CONSTRUCTED AT RUNTIME, never written as a literal
        (the all-nines id this test used to hardcode): once this suite is
        committed, that literal lives in tracked code, so
        ``_ids_present_in_head`` finds it in this very file and the probe
        reports "present" for a tag that is certainly absent — the guard then
        fails while healthy (observed: 26a0d1e shipped this test red for
        exactly that reason). Building the string keeps the literal out of
        every file, so the only way the grep can match is a real regression.
        """
        bogus = "ARCH-ENG-" + "9" * 8
        self.assertNotIn(
            bogus, Path(__file__).read_text(encoding="utf-8"),
            "the probe tag is written as a literal in this file — the grep "
            "below would match the test itself; construct it at runtime")
        missing = _ids_present_in_head([bogus])
        self.assertEqual(
            missing, [bogus],
            "the checker did NOT flag a tag that is certainly absent — the "
            "guard is vacuous and is not verifying anything")


@unittest.skipUnless(_is_git_checkout(), "not a git checkout")
class TestHistoricalEntriesAreReported(unittest.TestCase):
    """Older entries are MEASURED, not failed — with the reason stated.

    Seven ids (071, 076-080, 131) are absent from a code grep because their
    implementations were never annotated. Their code IS present in HEAD; this
    suite pins that fact so the set of legacy un-annotated ids cannot quietly
    grow. If an eighth appears, this test fails and the operator learns which
    fix lost its tag.
    """

    # Verified present in HEAD on 2026-10-15 by locating each implementation:
    #   071 gui/workers/brain_launch_worker.py:_system_ram_contention_warn
    #   076 agents/integrations/browser.py RobotsChecker + playwright escalation
    #   077 agents/dialogue/chat_completion.py:_seed_executed_calls_from_history
    #   078 agents/earning/social_earning_platform.py:_scan_linkedin_jobs
    #   079 agents/platforms/registration.py RegistrationService
    #   080 agents/platforms/credential_vault.py + gui/panels/registration_panel.py
    #   131 agents/safety/approval.py:assert_approval_covers
    LEGACY_UNANNOTATED = {
        "ARCH-ENG-071", "ARCH-ENG-076", "ARCH-ENG-077", "ARCH-ENG-078",
        "ARCH-ENG-079", "ARCH-ENG-080", "ARCH-ENG-131",
    }

    def test_legacy_unannotated_set_does_not_grow(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        all_ids = sorted({f"ARCH-ENG-{n}" for n in ID_RE.findall(text)},
                         key=lambda t: int(t.rsplit("-", 1)[1]))
        newly_absent = [
            t for t in _ids_present_in_head(all_ids)
            if t not in self.LEGACY_UNANNOTATED
        ]
        self.assertEqual(
            newly_absent, [],
            "CHANGELOG entries name fix(es) "
            f"{newly_absent} that are not findable in HEAD's tracked code and "
            "are not in the reviewed LEGACY_UNANNOTATED set. Determine which: "
            "either the fix was never committed (a v2.1.104-class false "
            "release record) or the code lost its tag — annotate it, then "
            "extend LEGACY_UNANNOTATED with the evidence.")

    def test_legacy_ids_really_are_implemented(self):
        """The allowlist must not become a licence to claim absent work.

        Each legacy id is checked against the symbol its changelog entry
        describes. If one of those symbols is ever deleted, this fails and the
        id must leave the allowlist (it would then be a false record).
        """
        required = {
            "ARCH-ENG-071": ("gui/workers/brain_launch_worker.py",
                             "_system_ram_contention_warn"),
            "ARCH-ENG-076": ("agents/integrations/browser.py",
                             "RobotsChecker"),
            "ARCH-ENG-077": ("agents/dialogue/chat_completion.py",
                             "_seed_executed_calls_from_history"),
            "ARCH-ENG-078": ("agents/earning/social_earning_platform.py",
                             "_scan_linkedin_jobs"),
            "ARCH-ENG-079": ("agents/platforms/registration.py",
                             "RegistrationService"),
            "ARCH-ENG-080": ("agents/platforms/credential_vault.py",
                             "class CredentialVault"),
            "ARCH-ENG-131": ("agents/safety/approval.py",
                             "assert_approval_covers"),
        }
        for tag, (rel, symbol) in required.items():
            path = REPO / rel
            self.assertTrue(path.exists(),
                            f"{tag}: {rel} is gone — its changelog record is "
                            f"now false and {tag} must leave the allowlist")
            r = subprocess.run(
                ["git", "grep", "-q", "--", symbol, "HEAD", "--", rel],
                cwd=REPO, capture_output=True, text=True)
            self.assertEqual(
                r.returncode, 0,
                f"{tag}: {rel} no longer defines {symbol!r} in HEAD — the "
                f"changelog record for {tag} is false")


if __name__ == "__main__":
    unittest.main()
