"""ARCH-ENG-202 — the blocklist setting was display-only, and editing it could
have silently un-blocked ten protected filenames.

## What was wrong

`FILENAME_BLOCKLIST` and `BLOCKED_MIME_TYPES` appear in the Settings screen and
are persisted to `.env`. Before this ticket **nothing read them**. The runtime
used a hardcoded 14-entry set in `worker_safety`, while the GUI defaulted the
text box to a hardcoded **4**-entry list:

    runtime enforced : 14 filenames, 4 MIME types
    screen displayed :  4 filenames, 2 MIME types

Ten protected filenames — `passwd`, `shadow`, `sudoers`, `id_dsa`, `hosts`,
`.bashrc`, `.zshrc`, `.gitconfig`, `secure`, `config.yml` — and two MIME types
were invisible. An operator reading the screen had no way to know they were
blocked.

## Why it was not merely cosmetic

ARCH-ENG-195 made these two keys persist. That is what turned the display-only
divergence into a latent hazard: `.env` line 141 now read

    FILENAME_BLOCKLIST=config.yaml,.env,credentials.json,id_rsa

— four entries, written by the GUI's own short default. It was inert only
because nothing read it. Had the setting been wired up naively, the very first
Save All would have narrowed enforcement from 14 to 4, and every worker would
have been able to read `passwd`, `shadow` and `sudoers`.

The line was not hypothetical. It was sitting in the repository.

## The fix: a floor, not a setting

`FILENAME_BLOCKLIST_FLOOR` is the hardcoded baseline and is **always** enforced.
The operator's `.env` value is an additive extension:

    effective = FLOOR | parse(os.environ["FILENAME_BLOCKLIST"])

Subtraction is structurally impossible. Blocking more is always allowed;
blocking less is not reachable through configuration at all. That is the right
shape for a safety control — the posture must not depend on a comma-separated
string being edited correctly.

The floor is also fail-secure: if `.env` is missing or loads late, the floor
still applies. The worst case is that additions are not picked up until
`refresh_from_env()` runs, which is over-blocking, never under-blocking.

## The drift bug this ticket also caught

The first version of `refresh_from_env()` rebound the module global.
`base_worker` does `from ...worker_safety import FILENAME_BLOCKLIST`, which
binds by value — so enforcement (reading the module global at call time) would
update while every importer kept a stale set. The name a caller sees and the
set actually enforced would silently disagree: the exact failure mode
ARCH-ENG-201 was filed for, reintroduced through a different door.

`refresh_from_env()` therefore mutates in place, keeping one object.
`test_refresh_does_not_desynchronise_importers` pins that.
"""

import os
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

CRITICAL_FILENAMES = (
    "passwd", "shadow", "sudoers", "id_rsa", "id_dsa", "hosts",
    ".bashrc", ".zshrc", ".gitconfig", "credentials.json", ".env",
    "config.yaml", "config.yml", "secure",
)


class _EnvGuard:
    """Context manager restoring the blocklist env vars exactly."""

    def __init__(self, **values):
        self._values = values
        self._saved = {}

    def __enter__(self):
        from agents.brains import worker_safety

        for key, val in self._values.items():
            self._saved[key] = os.environ.get(key)
            os.environ[key] = val
        worker_safety.refresh_from_env()
        return worker_safety

    def __exit__(self, *exc):
        from agents.brains import worker_safety

        for key, old in self._saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        worker_safety.refresh_from_env()
        return False


class TestFloorSurvivesANarrowingAttempt(unittest.TestCase):
    """ARCH-ENG-202 — the core property."""

    def test_a_four_entry_env_cannot_shrink_the_floor(self):
        """The exact value that was sitting in `.env`."""
        with _EnvGuard(
            FILENAME_BLOCKLIST="config.yaml,.env,credentials.json,id_rsa",
            BLOCKED_MIME_TYPES="application/x-executable,application/x-sharedlib",
        ) as ws:
            self.assertEqual(len(ws.FILENAME_BLOCKLIST), 14)
            self.assertEqual(len(ws.BLOCKED_MIME_TYPES), 4)
            lost = ws.FILENAME_BLOCKLIST_FLOOR - ws.FILENAME_BLOCKLIST
            self.assertEqual(
                lost, set(),
                f"the floor lost entries to configuration: {sorted(lost)}")

    def test_every_critical_filename_stays_refused(self):
        with _EnvGuard(FILENAME_BLOCKLIST="passwd") as ws:
            # Asking for ONLY `passwd` must not un-block the other thirteen.
            for name in CRITICAL_FILENAMES:
                with self.subTest(name=name):
                    self.assertFalse(
                        ws.is_safe_filename(name),
                        f"{name} became readable -- configuration was able to "
                        f"remove it from the enforced set")

    def test_an_empty_value_cannot_empty_the_list(self):
        with _EnvGuard(FILENAME_BLOCKLIST="", BLOCKED_MIME_TYPES="") as ws:
            self.assertEqual(len(ws.FILENAME_BLOCKLIST), 14)
            self.assertEqual(len(ws.BLOCKED_MIME_TYPES), 4)
            self.assertFalse(ws.is_safe_filename("shadow"))

    def test_a_missing_value_cannot_empty_the_list(self):
        with _EnvGuard(FILENAME_BLOCKLIST="", BLOCKED_MIME_TYPES="") as ws:
            saved = {k: os.environ.pop(k) for k in
                     ("FILENAME_BLOCKLIST", "BLOCKED_MIME_TYPES")}
            ws.refresh_from_env()
            try:
                self.assertEqual(len(ws.FILENAME_BLOCKLIST), 14,
                                 "with no .env value at all the floor must "
                                 "still apply -- fail-secure, not fail-open")
            finally:
                os.environ.update({k: v for k, v in saved.items() if v is not None})
                ws.refresh_from_env()


class TestOperatorAdditionsStillWork(unittest.TestCase):
    """ARCH-ENG-202 — a floor that cannot be extended is useless."""

    def test_an_added_filename_is_blocked(self):
        with _EnvGuard(FILENAME_BLOCKLIST="my_private_notes.md") as ws:
            self.assertFalse(ws.is_safe_filename("my_private_notes.md"))
            self.assertEqual(len(ws.FILENAME_BLOCKLIST), 15)

    def test_adding_does_not_disturb_the_floor(self):
        with _EnvGuard(
                FILENAME_BLOCKLIST="a.md,b.md,passwd",
                BLOCKED_MIME_TYPES="application/pdf") as ws:
            self.assertEqual(len(ws.FILENAME_BLOCKLIST), 16)
            self.assertFalse(ws.is_safe_filename("shadow"))
            self.assertTrue(ws.FILENAME_BLOCKLIST_FLOOR <= ws.FILENAME_BLOCKLIST)
            self.assertIn("application/pdf", ws.BLOCKED_MIME_TYPES)
            self.assertTrue(ws.BLOCKED_MIME_TYPES_FLOOR <= ws.BLOCKED_MIME_TYPES)

    def test_parsing_normalises_case_and_whitespace(self):
        with _EnvGuard(FILENAME_BLOCKLIST="  Secret.TXT , , ID_RSA  ") as ws:
            self.assertIn("secret.txt", ws.FILENAME_BLOCKLIST)
            self.assertIn("id_rsa", ws.FILENAME_BLOCKLIST)


class TestRefreshDoesNotDesynchroniseImporters(unittest.TestCase):
    """ARCH-ENG-202 — the bug the first draft of `refresh_from_env` introduced."""

    def test_refresh_does_not_desynchronise_importers(self):
        from agents.brains import base_worker, worker_safety

        with _EnvGuard(FILENAME_BLOCKLIST="brand_new_secret.md") as ws:
            self.assertIs(
                ws.FILENAME_BLOCKLIST, base_worker.FILENAME_BLOCKLIST,
                "base_worker holds a different object from worker_safety after "
                "refresh; the name a caller sees would no longer be the set "
                "actually enforced")
            self.assertIs(
                ws.BLOCKED_MIME_TYPES, base_worker.BLOCKED_MIME_TYPES,
                "same desynchronisation for the MIME set")

    def test_the_identity_asserted_by_201_still_holds_after_refresh(self):
        from agents.brains import base_worker, worker_safety

        with _EnvGuard(FILENAME_BLOCKLIST="x.md"):
            self.assertIs(base_worker.FILENAME_BLOCKLIST,
                          worker_safety.FILENAME_BLOCKLIST)


class TestTheScreenShowsWhatIsEnforced(unittest.TestCase):
    """ARCH-ENG-202 — display and enforcement must not diverge again."""

    def test_the_helper_returns_the_effective_set(self):
        from agents.brains import worker_safety

        with _EnvGuard(FILENAME_BLOCKLIST="shown.md"):
            shown = worker_safety.effective_blocklist_text().split(",")
            self.assertEqual(sorted(shown), sorted(worker_safety.FILENAME_BLOCKLIST))
            self.assertGreaterEqual(len(shown), 14,
                                    "the Settings screen would again show "
                                    "fewer entries than are enforced")

    def test_every_floor_entry_appears_in_the_displayed_text(self):
        from agents.brains import worker_safety

        with _EnvGuard(FILENAME_BLOCKLIST="config.yaml"):
            shown = set(worker_safety.effective_blocklist_text().split(","))
            for name in CRITICAL_FILENAMES:
                with self.subTest(name=name):
                    self.assertIn(name, shown)

    def test_the_gui_no_longer_hardcodes_its_own_default(self):
        """The 4-entry literal was the source of the divergence."""
        src = (REPO / "gui" / "builders" / "tab_feature_builders.py").read_text(
            encoding="utf-8")
        self.assertNotIn(
            '"config.yaml,.env,credentials.json,id_rsa"', src,
            "the GUI's short hardcoded default is back; the screen would "
            "understate the enforced set again")
        self.assertRegex(
            src, r"effective_blocklist_text\(\)",
            "the Settings screen must read the runtime's effective set")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-202 — each detector must be able to fail."""

    def test_the_floor_check_detects_an_actual_loss(self):
        """If the floor check cannot fail, it proves nothing."""
        floor = frozenset({"passwd", "shadow"})
        shrunk = {"passwd"}
        self.assertNotEqual(
            floor - shrunk, set(),
            "the floor comparison never reports a loss, so it would pass "
            "while protection was being removed")

    def test_the_critical_list_is_not_vacuous(self):
        self.assertGreaterEqual(len(CRITICAL_FILENAMES), 14)
        for name in ("passwd", "shadow", "sudoers"):
            self.assertIn(name, CRITICAL_FILENAMES)

    def test_is_safe_filename_actually_refuses_things(self):
        """If `is_safe_filename` returned True for everything, every
        'stays blocked' assertion above would be vacuously false-but-passing."""
        from agents.brains import worker_safety

        self.assertTrue(worker_safety.is_safe_filename("ordinary_notes.md"),
                        "the blocklist rejects everything, so these tests "
                        "cannot detect an over-block either")
        self.assertFalse(worker_safety.is_safe_filename("passwd"))