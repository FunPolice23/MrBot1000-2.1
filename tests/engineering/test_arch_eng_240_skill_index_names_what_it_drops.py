"""ARCH-ENG-240 / AT-01 -- a prompt that hides its tools must NAME what it
hides.

The finding
-----------
`skill_index_prompt` sorts entries alphabetically (`discover_skills`) and
drops from the end of that sorted list when the char budget runs out -- so
the entries the model can never see are exactly the alphabetically LAST
skills. Measured in the depth pass: 17 of 25 entries shown, and the 8 hidden
ones were `pptx`, `skill-creator`, `slack-gif-creator`, `Social Discovery`,
`theme-factory`, `web-artifacts-builder`, `webapp-testing` and `xlsx` --
including the two an operator reaches for when a task mentions a deck or a
spreadsheet. The only notice was "- ...and 8 more; call list_skills() for
the full index", which did not identify them.

The framing-first bound stays: the untruncated IL2 preamble and the dropped
entries both still count against the budget. The fix is honesty, not volume:
the tail line now lists the dropped NAMES (the name list itself is trimmed
inside the same budget, and falls back to a plain count only when even one
name cannot fit).

Note the dialogue caller passes an ELASTIC budget (whatever remains of the
context limit), so this discipline matters precisely when the block is
smallest -- the same-day shapes where `xlsx` would vanish without a word.

Vacuity: against the pre-fix module the dropped names never appear in the
prompt, so the name-assertions fail; the environment-level test would note
truncation naming fewer than the true dropped count.
"""

import pathlib
import sys
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import agents.knowledge.skill_index as si


def _entry(name, desc_len=240):
    return si.SkillEntry(
        name=name,
        description="x" * desc_len,
        path=f"/fake/{name}.md",
        source="workshop",
    )


def _alphabet(n):
    return [f"skill_{chr(ord('a') + i)}" for i in range(n)]


def _install(entries):
    """Point the cached index at a synthetic list."""
    patcher = mock.patch.object(si, "get_skill_index", return_value=list(entries))
    return patcher


def _dropped_representation_contract(prompt, entries, dropped):
    """AT-01's honesty contract: every dropped entry is NAMED in the prompt,
    or sits under the tail's continuation marker (a trimmed name list that
    itself hit the budget edge -- never silently vanished)."""
    named = [e for e in dropped if
             e.name in prompt and f"(read with read_skill '{e.name}')" not in prompt]
    unnamed = [e for e in dropped if e not in named]
    if unnamed:
        # Continuation marker required when the name list was trimmed.
        assert ("…; call list_skills()" in prompt) or (",…" in prompt), (
            f"dropped entries were neither named nor marked: {unnamed}")
    return named


class NamesTheDropped(unittest.TestCase):

    def _truncated_prompt(self, n_entries, budget):
        entries = [_entry(n) for n in _alphabet(n_entries)]
        with _install(entries) as _p:
            return si.skill_index_prompt(budget), entries

    def test_dropped_entries_are_named_or_marked(self):
        prompt, entries = self._truncated_prompt(n_entries=25, budget=2600)
        _, dropped = self._split_shown_dropped(prompt, entries)
        self.assertGreater(len(dropped), 0, "test must exercise the drop path")
        named = _dropped_representation_contract(prompt, entries, dropped)
        self.assertGreater(
            len(named), 0,
            "the tail line must name at least one hidden skill when the "
            "budget can hold a name")

    def test_every_name_fits_case_names_all(self):
        """A scan down the budgets must find AT LEAST ONE truncated prompt
        whose tail can hold every dropped name -- proving the naming is a
        real feature of the contract, not a lucky trim."""
        found = False
        for budget in range(1200, 7000, 20):
            prompt, entries = self._truncated_prompt(n_entries=25, budget=budget)
            _, dropped = self._split_shown_dropped(prompt, entries)
            self.assertLessEqual(len(prompt), budget)
            if not dropped:
                continue
            if all(e.name in prompt for e in dropped):
                found = True
                self.assertIn(f"…and {len(dropped)} more", prompt)
                break
            _dropped_representation_contract(prompt, entries, dropped)
        self.assertTrue(
            found,
            "no budget yields a truncated index that can name every "
            "dropped skill without trimming")

    def test_dropped_count_is_accurate(self):
        prompt, entries = self._truncated_prompt(n_entries=25, budget=2600)
        _, dropped = self._split_shown_dropped(prompt, entries)
        self.assertIn(f"…and {len(dropped)} more", prompt)

    def test_prompt_still_honors_the_budget(self):
        # NOTE: 400 is deliberately absent -- the preamble ALONE is ~396
        # chars, and even the pre-fix plain-count tail overflowed to ~450
        # (the ARCH-ENG-199 probe bound of 460 encodes exactly that floor).
        # These budgets are satisfiable; the naming tail must not loosen
        # them.
        for budget in (600, 2600, 6000):
            prompt, _ = self._truncated_prompt(n_entries=25, budget=budget)
            self.assertLessEqual(
                len(prompt), budget,
                f"the naming tail must not blow the bound (budget {budget})")

    def test_none_fits_case_degrades_to_plain_count(self):
        """Even one name cannot fit inside a tiny budget: a plain count is
        what remains -- never a padded prompt."""
        prompt, _ = self._truncated_prompt(n_entries=40, budget=560)
        self.assertIn("…and ", prompt)
        self.assertLessEqual(len(prompt), 560)

    @staticmethod
    def _split_shown_dropped(prompt, entries):
        shown = [e for e in entries if e.name in prompt and
                 f"(read with read_skill '{e.name}')" in prompt]
        dropped = [e for e in entries if e not in shown]
        return shown, dropped

    def test_every_entry_name_appears_with_a_generous_budget(self):
        penry = [_entry(n, desc_len=60) for n in _alphabet(10)]
        with _install(penry) as _p:
            prompt = si.skill_index_prompt(20000)
        for entry in penry:
            self.assertIn(entry.name, prompt)

    def test_empty_and_degenerate_budgets_unchanged(self):
        self.assertEqual(si.skill_index_prompt(0), "")
        self.assertEqual(si.skill_index_prompt(-10), "")


class TheRealIndexIsHonest(unittest.TestCase):
    """Drive the module against the operator's real skill dirs."""

    def _real_entries(self):
        try:
            si.reset_skill_index_cache()
            return si.get_skill_index()
        except Exception:
            return []

    def test_default_budget_never_drops_a_name_silently(self):
        entries = self._real_entries()
        if len(entries) <= 1:
            self.skipTest("no skills discovered on this machine")
        with _install(entries) as _p:
            prompt = si.skill_index_prompt()
        self.assertLessEqual(len(prompt), 6000)
        # Any entry NOT represented as an index line must be NAMED in the tail.
        unshown = []
        for entry in entries:
            if f"- **{entry.name}**" not in prompt:
                unshown.append(entry)
        for entry in unshown:
            self.assertIn(
                entry.name, prompt,
                f"{entry.name} is neither shown nor named in the default "
                f"prompt -- a silent drop (AT-01 unchanged)")

    def test_elastic_small_budget_names_what_it_drops(self):
        """The dialogue path's elastic case: a small budget still names what
        it drops (or marks the remainder -- never silence)."""
        entries = self._real_entries()
        if len(entries) <= 1:
            self.skipTest("no skills discovered on this machine")
        with _install(entries) as _p:
            prompt = si.skill_index_prompt(2400)
        self.assertLessEqual(len(prompt), 2400)
        unshown = [e for e in entries if f"- **{e.name}**" not in prompt]
        named = [e for e in unshown
                 if e.name in prompt
                 and f"(read with read_skill '{e.name}')" not in prompt]
        self.assertGreater(
            len(named), 0,
            "a small elastic budget should still name the tail it drops")
        _dropped_representation_contract(prompt, entries, unshown)


if __name__ == "__main__":
    unittest.main()
