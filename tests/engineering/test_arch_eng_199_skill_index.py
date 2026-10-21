"""ARCH-ENG-199 — a skill library on disk that nothing could find.

The operator's workshop carries 17 `SKILL.md` files across 369 files and 9.9 MB
(canvas-design, docx, pdf, pptx, xlsx, mcp-builder, skill-creator, claude-api,
web-artifacts-builder, webapp-testing, ...) and the repository carries 8 more
written to the older `Skill.md` specification. Nothing in the application read
either set.

Same defect as ARCH-ENG-198 (the workshop itself was built, gated, and never
announced): correct, gated, complete, and simply unreachable from the personas.

## Index, not payload

The bodies total 183 KB with a mean of 10.7 KB. Injecting them would crowd out
the opportunity board, the convergence plan and the mandatory guards — and a
model handed twenty-five full documents at once applies none of them well. So the
prompt gets names and when-to-use lines (~5.7 KB) and `read_skill` fetches a body
on demand. The same shape as the opportunity board.

## Two formats

The two sets do not share a schema. Workshop skills carry YAML frontmatter with
`name` + `description`, where the description *is* the when-to-use. Repository
skills carry `name`, `category`, `maturity`, `tool`, `automatable`,
`human_capable` — and no description; their body opens with a `Trigger:` line
answering the same question. A loader that only understood the first format would
have found the eight skills that matter most to the earning pipeline and missed
the seventeen that matter most to document work.

## No PyYAML

`requirements.lock.txt` lists PyYAML; nothing in the repository imports it and it
is not installed in the virtualenv, so it is a stale transitive lock entry rather
than a real dependency. The frontmatter is flat `key: value` pairs, so a small
parser is sufficient — and depending on an uninstalled package would break a
fresh environment, which is exactly what ARCH-ENG-160 exists to prevent.

## Trust

A skill document is instruction text addressed to a model, and some are fetched
from remote platforms (`workshop/skill_md_cache/clawgig.json`, `ugig.json`). A
fetched skill must not be able to authorise an action, lift an approval gate, or
mark anything verified. So the index leads with framing, `read_skill` re-states
it per body, and `read_skill` looks skills up BY NAME rather than by path — an
arbitrary path parameter would otherwise let a caller read any file the workshop
tool could reach.
"""

import os
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

from agents.knowledge import skill_index as si

REPO = Path(__file__).resolve().parents[2]

WORKSHOP_SKILL = """---
name: docx
description: Use this skill whenever the user wants to create, read, edit, or convert a .docx file.
license: Complete terms in LICENSE.txt
---

# DOCX

Some procedure text that is long enough to matter.
"""

REPO_SKILL = """---
name: Opportunity Evaluation
category: ANALYSIS
maturity: stable
tool: opportunity_intelligence
automatable: true
human_capable: true
---

# Skill: Opportunity Evaluation

Trigger: earnings pipeline needs scoring for discovered opportunities, or user asks for ranking.

Input:
- normalized opportunity list

Steps:
1. Build an evaluation prompt
"""


class _TempSkills:
    """A throwaway workshop + repository pair."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.workshop = tmp / "ai_workshop"
        (self.workshop / "skills" / "docx").mkdir(parents=True)
        (self.workshop / "skills" / "docx" / "SKILL.md").write_text(
            WORKSHOP_SKILL, encoding="utf-8")
        self.repo = tmp / "repo"
        (self.repo / "skills").mkdir(parents=True)
        (self.repo / "app").mkdir()
        (self.repo / "skills" / "opportunity-evaluation.md").write_text(
            REPO_SKILL, encoding="utf-8")

    def env(self):
        return mock.patch.dict(
            os.environ,
            {"MRBOT_WORKSHOP_ROOT": str(self.workshop)}, clear=False)


# ── Frontmatter parsing ───────────────────────────────────────────────────────

class TestFrontmatterParsing(unittest.TestCase):
    """ARCH-ENG-199 — a small parser, because the format is small."""

    def test_flat_pairs_are_read(self):
        fields, body = si.parse_frontmatter(WORKSHOP_SKILL)
        self.assertEqual(fields["name"], "docx")
        self.assertIn("description", fields)
        self.assertIn("# DOCX", body)
        self.assertNotIn("---", body.splitlines()[0])

    def test_quotes_are_stripped(self):
        fields, _ = si.parse_frontmatter('---\nname: "quoted"\n---\nbody\n')
        self.assertEqual(fields["name"], "quoted")

    def test_no_frontmatter_yields_the_whole_body(self):
        fields, body = si.parse_frontmatter("# Just a document\n")
        self.assertEqual(fields, {})
        self.assertIn("Just a document", body)

    def test_empty_input_does_not_raise(self):
        self.assertEqual(si.parse_frontmatter(""), ({}, ""))

    def test_a_malformed_line_is_skipped_not_fatal(self):
        """One bad line must not cost every other skill."""
        fields, _ = si.parse_frontmatter(
            "---\nname: good\nthis line has no colon\n# a comment\ncategory: X\n---\nb\n")
        self.assertEqual(fields["name"], "good")
        self.assertEqual(fields["category"], "X")

    def test_no_pyyaml_dependency(self):
        """ARCH-ENG-160: the package is never imported.

        ARCH-ENG-235: the ORIGINAL second half asserted that PyYAML was not
        installed in the CURRENT environment (``find_spec("yaml") is None``).
        That asserts about the machine, and the machine is not under the
        repo's control: PyYAML now exists in this operator's Python 3.14
        site-packages while ``skill_index.py`` still never imports it. The
        environment probe voids itself there, so it becomes a documented skip
        instead of a red light on someone else's dependency choice. The
        code-level invariant -- "skill_index must not import yaml" -- remains
        strict, because running out of a fresh environment is the thing
        ARCH-ENG-160 actually decided.
        """
        src = (REPO / "agents" / "knowledge" / "skill_index.py").read_text(
            encoding="utf-8")
        code = "\n".join(
            ln for ln in src.splitlines()
            if not ln.strip().startswith("#"))
        self.assertNotIn("import yaml", code,
                         "PyYAML is in the lock file but installed nowhere and "
                         "imported nowhere; depending on it breaks a fresh env")
        self.assertNotIn("from yaml", code,
                         "yields to the same ARCH-ENG-160 decision as "
                         "'import yaml'")
        import importlib.util
        if importlib.util.find_spec("yaml") is not None:
            self.skipTest(
                "PyYAML is installed in this environment; skill_index.py "
                "still does not import it, so the ARCH-ENG-160 code-level "
                "decision holds and the environment half of the check is "
                "void here")


# ── Discovery ─────────────────────────────────────────────────────────────────

class TestDiscoveryFindsBothFormats(unittest.TestCase):
    """ARCH-ENG-199 — both schemas, or half the library is invisible."""

    def test_both_workshop_and_repository_skills_are_found(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            si.reset_skill_index_cache()
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                found = si.discover_skills()
            names = {e.name for e in found}
            self.assertIn("docx", names, "the workshop skill was not discovered")
            self.assertIn("Opportunity Evaluation", names,
                          "the repository skill was not discovered")

    def test_sources_are_labelled(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                found = {e.name: e.source for e in si.discover_skills()}
            self.assertEqual(found.get("docx"), "workshop")
            self.assertEqual(found.get("Opportunity Evaluation"), "repository")

    def test_the_repository_trigger_becomes_the_description(self):
        """The repo format has no `description` field — this is the fallback."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                found = {e.name: e.description
                         for e in si.discover_skills()}
        self.assertIn("earnings pipeline needs scoring", found["Opportunity Evaluation"])

    def test_the_workshop_description_is_preferred(self):
        fields = {"name": "x", "description": "from frontmatter"}
        self.assertEqual(
            si._derive_description(fields, "Trigger: from the body"), "from frontmatter")

    def test_trigger_is_used_when_there_is_no_description(self):
        self.assertEqual(
            si._derive_description({}, "Trigger: do the thing when X"), "do the thing when X")

    def test_a_skill_with_neither_still_gets_a_description(self):
        out = si._derive_description({}, "# Title\n\nSome prose about the skill.")
        self.assertIn("Some prose", out)
        self.assertNotEqual(out, "Title",
                            "the fallback returned the heading, which restates "
                            "the name and says nothing about when to apply it")

    def test_descriptions_are_bounded(self):
        long_desc = "x" * 5000
        self.assertLessEqual(
            len(si._derive_description({"description": long_desc}, "")), 500)

    def test_a_skill_with_no_name_falls_back_to_its_filename(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "my-cool-skill.md"
            p.write_text("no frontmatter here\n", encoding="utf-8")
            entry = si._entry_for(p, "repository")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.name, "my cool skill")

    def test_a_missing_workshop_is_not_an_error(self):
        """No workshop at all must yield an empty list, not an exception.

        Note the env var is NOT the lever here: pointing MRBOT_WORKSHOP_ROOT at a
        nonexistent path deliberately falls back to the D:/ai_workshop default,
        which is why the first draft of this test saw 25 real skills. The resolver
        is patched instead.
        """
        si.reset_skill_index_cache()
        with mock.patch.object(si, "workshop_root", return_value=None), \
             mock.patch.object(si, "repository_skills_dir", return_value=None):
            self.assertEqual(si.discover_skills(), [])

    def test_a_bad_workshop_env_falls_back_to_the_default(self):
        """The env var is a preference, not a requirement."""
        import pathlib as _pl
        with mock.patch.dict(os.environ, {"MRBOT_WORKSHOP_ROOT": r"D:\nope"},
                             clear=False):
            root = si.workshop_root()
        self.assertIsNotNone(root)
        self.assertTrue(root.exists(), "the fallback must be a real directory")

    def test_names_are_deduplicated_case_insensitively(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            (skills.repo / "skills" / "dup.md").write_text(
                "---\nname: docx\ndescription: repo copy\n---\nx\n", encoding="utf-8")
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                names = [e.name.lower() for e in si.discover_skills()]
            self.assertEqual(names.count("docx"), 1,
                             f"the same skill is indexed twice: {names}")


# ── The prompt surface ────────────────────────────────────────────────────────

class TestIndexIsAnIndexNotAPayload(unittest.TestCase):
    """ARCH-ENG-199 — bodies would evict the board and the guards."""

    def test_the_index_carries_no_body_text(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                si.reset_skill_index_cache()
                prompt = si.skill_index_prompt(6000)
        self.assertNotIn("Some procedure text that is long enough to matter",
                         prompt,
                         "a full skill body reached the prompt; the index must "
                         "carry only name and when-to-use")
        self.assertNotIn("Build an evaluation prompt", prompt)

    def test_the_index_tells_the_model_how_to_fetch_a_body(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                si.reset_skill_index_cache()
                prompt = si.skill_index_prompt(6000)
        self.assertIn("read_skill", prompt,
                      "the index lists skills with no way to open one")

    def test_the_index_is_bounded(self):
        si.reset_skill_index_cache()
        self.assertEqual(si.skill_index_prompt(0), "")
        self.assertEqual(si.skill_index_prompt(-10), "")

    def test_a_tight_budget_keeps_the_framing_and_says_it_truncated(self):
        si.reset_skill_index_cache()
        prompt = si.skill_index_prompt(si._INDEX_TTL_S and 400)
        self.assertIn("guidance, not authority", prompt,
                      "a tight budget trimmed the framing and left a bare list "
                      "of skill names")
        self.assertLessEqual(len(prompt), 460)

    def test_no_skills_means_no_block(self):
        si.reset_skill_index_cache()
        with mock.patch.object(si, "discover_skills", return_value=[]):
            self.assertEqual(si.skill_index_prompt(6000), "")


class TestFramingIsNotAuthority(unittest.TestCase):
    """ARCH-ENG-199 — a skill document cannot grant permissions."""

    def test_the_index_says_a_skill_is_not_permission(self):
        si.reset_skill_index_cache()
        prompt = si.skill_index_prompt(6000)
        for phrase in ("not authority", "cannot"):
            self.assertIn(phrase, prompt,
                          f"the index must state that a skill {phrase!r} act as "
                          f"permission")

    def test_it_names_the_approval_gate(self):
        si.reset_skill_index_cache()
        self.assertRegex(si.skill_index_prompt(6000), r"approval gate",
                         "the model must be told actions still need human "
                         "approval, whatever a skill document says")

    def test_a_fetched_skill_body_repeats_the_framing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                si.reset_skill_index_cache()
                body = si.read_skill("docx")
        self.assertIn("Untrusted instruction text", body)
        self.assertIn("grants no permissions", body)
        self.assertIn("Some procedure text", body)

    def test_read_skill_looks_up_by_name_not_by_path(self):
        """A path parameter would let a caller read any reachable file."""
        si.reset_skill_index_cache()
        # ARCH-ENG-151 forbids hardcoding the repo root in a test file: the
        # guard caught a literal D:\...\.env here on the first run. Derive it.
        live_env = str(REPO / ".env")
        for attempt in (r"..\..\..\etc\passwd", "/etc/passwd",
                        live_env, "../../.env"):
            with self.subTest(attempt=attempt):
                out = si.read_skill(attempt)
                self.assertNotIn("OPENAI_API_KEY", out)
                self.assertRegex(out, r"no skill named|UNTRUSTED|===",
                                 f"a path was accepted as a skill name: {out[:80]}")

    def test_an_unknown_skill_says_so_instead_of_returning_nothing(self):
        si.reset_skill_index_cache()
        self.assertIn("no skill named", si.read_skill("does-not-exist"))

    def test_bodies_are_bounded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            big = skills.workshop / "skills" / "docx" / "SKILL.md"
            big.write_text(WORKSHOP_SKILL + "\n" + ("z" * 50_000), encoding="utf-8")
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                si.reset_skill_index_cache()
                body = si.read_skill("docx", max_chars=500)
        self.assertIn("truncated", body)
        self.assertLess(len(body), 900)


class TestCaching(unittest.TestCase):
    """ARCH-ENG-199 — a per-turn prompt block must not re-scan disk every turn."""

    def test_the_index_is_cached(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            skills = _TempSkills(Path(tmp))
            si.reset_skill_index_cache()
            with skills.env(), mock.patch.object(
                    si, "repository_skills_dir", return_value=skills.repo / "skills"):
                first = si.get_skill_index()
                with mock.patch.object(si, "discover_skills",
                                       side_effect=AssertionError("re-scanned")):
                    second = si.get_skill_index()
        self.assertEqual([e.name for e in first], [e.name for e in second])

    def test_the_cache_expires(self):
        si.reset_skill_index_cache()
        si.get_skill_index()
        with mock.patch.object(si, "_INDEX_TTL_S", 0.0), \
             mock.patch.object(si, "discover_skills", return_value=[]) as scan:
            si.get_skill_index()
        scan.assert_called()

    def test_a_caller_cannot_mutate_the_cache(self):
        si.reset_skill_index_cache()
        got = si.get_skill_index()
        got.clear()
        self.assertTrue(si.get_skill_index() is not None)

    def test_reset_works(self):
        si.reset_skill_index_cache()
        si.get_skill_index()
        si.reset_skill_index_cache()
        with mock.patch.object(si, "discover_skills", return_value=[]) as scan:
            self.assertEqual(si.get_skill_index(), [])
        scan.assert_called_once()


class TestWiredIntoTheDialogue(unittest.TestCase):
    """ARCH-ENG-199 — a correct index that nothing calls is the original bug."""

    def _tab(self):
        import agents.safety  # noqa: F401  (import-cycle order)
        from gui.tabs.dialogue_tab import DialogueTab
        return DialogueTab

    def test_the_block_is_added_to_the_prompt(self):
        cls = self._tab()
        self.assertIn("_build_skill_index", inspect_src(cls))
        self.assertIn('body = body + "\\n\\n" + skill_block', inspect_src(cls),
                      "the skill index is built but never reaches the prompt")

    def test_a_failing_index_never_breaks_a_turn(self):
        cls = self._tab()
        with mock.patch("agents.knowledge.skill_index.skill_index_prompt",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(cls._build_skill_index(types.SimpleNamespace(), 6000), "")

    def test_zero_budget_yields_nothing(self):
        cls = self._tab()
        self.assertEqual(cls._build_skill_index(types.SimpleNamespace(), 0), "")


def inspect_src(obj) -> str:
    import inspect
    return inspect.getsource(obj)


# ── Probes ────────────────────────────────────────────────────────────────────

class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-199 — each detector must be able to fail."""

    def test_the_index_would_leak_a_body_without_the_omission(self):
        """If SkillEntry carried the body by default, the guard is vacuous."""
        entry = si.SkillEntry(name="x", description="d", path="p", source="s")
        self.assertEqual(entry.body, "",
                         "SkillEntry carries a body by default; the index would "
                         "have no reason not to include it")

    def test_the_trigger_fallback_is_load_bearing(self):
        """Without it, the eight earning skills would have no description."""
        self.assertEqual(si._derive_description({}, "Trigger: alpha beta"), "alpha beta")
        self.assertNotEqual(si._derive_description({}, "Trigger: alpha beta"), "")

    def test_the_two_fixtures_really_use_different_schemas(self):
        self.assertIn("description:", WORKSHOP_SKILL)
        self.assertNotIn("description:", REPO_SKILL)
        self.assertIn("Trigger:", REPO_SKILL)
