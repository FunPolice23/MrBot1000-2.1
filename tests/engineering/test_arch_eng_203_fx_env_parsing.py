"""ARCH-ENG-203 — four parsers for the same `MRBOT_FX_*` values, disagreeing.

## What was wrong

`MRBOT_FX_*` settings were parsed four different ways:

| site | code | empty string | `1` / `yes` / `on` |
|---|---|---|---|
| `app/effects.py` | `in ("1","true","yes","on")` | **False** | True |
| `tab_feature_builders.py` `_env_bool` | three-state | default | True |
| `tab_feature_builders.py` fx_compact | `.lower() == "true"` | **False** | **False** |
| `tab_feature_builders.py` fx_rounded | `.lower() != "false"` | **True** | **True** |

The last two sat **four lines apart in the same function**, seeding two
checkboxes four lines apart. They parsed the same `.env` format in opposite
directions: `== "true"` and `!= "false"` are complements, so any value outside
`{"true"} ∪ {"false"}` — including every empty string — was read as False by one
and True by the other.

An operator hand-editing `.env` to `MRBOT_FX_ANTIALIASING=1` got antialiasing
enabled in the renderer while a neighbouring checkbox showed unchecked. Nothing
errored. The screen simply disagreed with the behaviour, which is the failure
mode this project keeps finding: an observation presented as fact.

The `!= "false"` form was the worse of the pair, because it treats *any*
unrecognised value as True. A typo reads as ON rather than falling back to the
documented default.

## The fix

`app.effects.env_bool` is the single definition, and `app/effects.py` is its
home because that module already owns these settings (`EffectSettings.from_env`).
The local `_env_bool` closure survives as a one-line delegation, since call
sites in the same function reference it.

The three-state rule is the only one where an unrecognised value has a defined
answer:

* unset or empty → `default` (not False — the old behaviour let an empty value
  silently disable a feature that defaults to on)
* true token → True, false token → False
* **anything else → `default`**

That last rule matters: `MRBOT_FX_SHADOWS=ture` now resolves to the documented
default instead of to False, so a misspelt setting cannot quietly switch a
feature off. `main.py` persists `str(bool)` — `"True"`/`"False"` — which the
lower-casing handles.
"""

import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
EFFECTS = REPO / "app" / "effects.py"
BUILDER = REPO / "gui" / "builders" / "tab_feature_builders.py"


class TestTheCanonicalParser(unittest.TestCase):
    """ARCH-ENG-203 — `env_bool` behaviour, including the disagreement cases."""

    def _parse(self, raw, default=True):
        from app.effects import env_bool
        return env_bool("K", default, env={} if raw is None else {"K": raw})

    def test_true_tokens(self):
        for raw in ("1", "true", "True", "TRUE", " yes ", "on", "ON"):
            with self.subTest(raw=raw):
                self.assertTrue(self._parse(raw))

    def test_false_tokens(self):
        for raw in ("0", "false", "False", "FALSE", " no ", "off", "OFF"):
            with self.subTest(raw=raw):
                self.assertFalse(self._parse(raw, default=True))

    def test_the_three_values_the_old_parsers_disagreed_on(self):
        """`1`, `yes` and `on` were True for effects.py and False for the
        `== "true"` checkbox. That is the whole bug."""
        for raw in ("1", "yes", "on"):
            with self.subTest(raw=raw):
                self.assertTrue(
                    self._parse(raw),
                    f"{raw!r} was read as True by the renderer and False by "
                    f"the checkbox; it must now mean one thing")

    def test_empty_falls_back_to_the_default_not_false(self):
        """The old `in (...)` form made an empty value silently disable a
        feature that defaults to ON."""
        self.assertTrue(self._parse(""), "empty must take the default")
        self.assertFalse(self._parse("", default=False),
                         "empty must take whatever default was passed")
        self.assertTrue(self._parse("   "), "whitespace-only is still empty")
        self.assertTrue(self._parse(None), "unset must take the default")

    def test_an_unrecognised_value_takes_the_default(self):
        """A typo must not switch a feature off."""
        self.assertTrue(self._parse("ture"), "typo must not disable a default-on")
        self.assertFalse(self._parse("ture", default=False),
                         "typo must not enable a default-off")

    def test_defaults_are_respected_per_call(self):
        from app.effects import env_bool
        self.assertTrue(env_bool("MISSING", True))
        self.assertFalse(env_bool("MISSING", False))


class TestTheTwoCheckboxesNoLongerOpposite(unittest.TestCase):
    """ARCH-ENG-203 — the specific pair that sat four lines apart."""

    # Values the parser does NOT recognise. These are the ones the old parsers
    # split: `== "true"` said False, `!= "false"` said True.
    #
    # `1`, `yes` and `on` are deliberately NOT here -- they are recognised
    # tokens, and both old parsers disagreed about them for a different reason
    # (effects.py accepted them, the `== "true"` checkbox did not). That case is
    # covered by test_the_three_values_the_old_parsers_disagreed_on.
    UNRECOGNISED = ("", "   ", "ture", "banana", "2", "enabled")

    def test_compact_density_and_rounded_corners_agree(self):
        """They read the same setting family and share one parser, so for any
        input the answer can only be the recognised-token answer or the default.

        Before the fix these were complements -- `== "true"` and `!= "false"` --
        so every unrecognised value split them, with no defined winner.
        """
        from app.effects import env_bool

        for raw in self.UNRECOGNISED:
            with self.subTest(raw=raw):
                # An unrecognised value must behave exactly like an unset one,
                # for BOTH defaults.
                for default in (False, True):
                    got = env_bool("K", default, env={"K": raw})
                    unset = env_bool("K", default, env={"K": None})
                    self.assertEqual(
                        got, unset,
                        f"{raw!r} (default={default}) resolved to {got} but an "
                        f"unset value resolves to {unset}; the parser is "
                        f"inventing an answer for unrecognised input")

    def test_a_recognised_token_ignores_the_default(self):
        """The counterpart: `1` must mean True even where the default is False,
        which is what `== "true"` got wrong."""
        from app.effects import env_bool

        for raw in ("1", "yes", "on"):
            with self.subTest(raw=raw):
                self.assertTrue(env_bool("K", False, env={"K": raw}))
        for raw in ("0", "no", "off"):
            with self.subTest(raw=raw):
                self.assertFalse(env_bool("K", True, env={"K": raw}))


class TestOnlyOneParserRemains(unittest.TestCase):
    """ARCH-ENG-203 — structural, so the copies cannot come back."""

    def test_effects_defines_env_bool_once(self):
        tree = ast.parse(EFFECTS.read_text(encoding="utf-8"))
        fns = [n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "env_bool"]
        self.assertEqual(len(fns), 1)

    def test_the_old_ad_hoc_parsers_are_gone_from_the_builder(self):
        src = BUILDER.read_text(encoding="utf-8")
        # Scoped to MRBOT_FX lines only, and comments are stripped first.
        #
        # Two scoping mistakes are baked into the first draft of this guard, both
        # of which made it fail against correct code:
        #   * the whole file was searched, but the builder legitimately contains
        #     `.lower() == "true"` for OTHER settings -- AUTO_RESEARCH,
        #     PIPELINE_ENABLED, PIPELINE_ALLOW_WRITE, PIPELINE_ALLOW_SELF_IMPROVE;
        #   * the ARCH-ENG-203 explanatory comments quote the old expressions
        #     verbatim, so even a scoped search matches the documentation of the
        #     bug.
        code_lines = []
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            code_lines.append(line)
        fx_only = "\n".join(l for l in code_lines if "MRBOT_FX_" in l)

        self.assertNotRegex(
            fx_only, r'\.lower\(\)\s*==\s*"true"',
            'an `.lower() == "true"` MRBOT_FX parse is back; it reads 1/yes/on '
            'as False while the renderer reads them as True')
        self.assertNotRegex(
            fx_only, r'\.lower\(\)\s*!=\s*"false"',
            'an `.lower() != "false"` MRBOT_FX parse is back; it treats any '
            'unrecognised value as True, including typos')
        self.assertNotRegex(
            fx_only, r'\.lower\(\)',
            "a MRBOT_FX_ setting is still parsed with a bare .lower() chain "
            "instead of the canonical env_bool")

    def test_both_fx_checkboxes_use_the_canonical_parser(self):
        src = BUILDER.read_text(encoding="utf-8")
        for name in ("MRBOT_FX_COMPACT_DENSITY", "MRBOT_FX_ROUNDED_CORNERS"):
            with self.subTest(setting=name):
                self.assertRegex(
                    src, rf'_env_bool\(\s*"{name}"',
                    f"{name} must be seeded through the canonical parser")

    def test_the_local_env_bool_is_only_a_delegation(self):
        """It survives as a name because call sites use it, but it must not
        re-implement the logic."""
        src = BUILDER.read_text(encoding="utf-8")
        self.assertRegex(
            src, r"from app\.effects import env_bool as _env_bool",
            "the GUI must delegate to app.effects.env_bool")
        # No `def _env_bool` body left doing its own parsing.
        self.assertNotRegex(
            src, r"def _env_bool\(name,\s*default=False\):",
            "_env_bool was re-implemented locally; that is the duplication "
            "this ticket removed")


class TestRuntimeStillAgreesWithTheScreen(unittest.TestCase):
    """ARCH-ENG-203 — the property the divergence broke."""

    def test_settings_and_checkboxes_read_the_same_value(self):
        """Whatever `EffectSettings` decides, the seeded checkbox must match."""
        from app.effects import EffectSettings, env_bool

        for raw, default in (("1", False), ("yes", False), ("on", False),
                             ("0", True), ("no", True), ("off", True),
                             ("true", False), ("false", True)):
            with self.subTest(raw=raw):
                env = {"MRBOT_FX_COMPACT_DENSITY": raw}
                settings_says = EffectSettings.from_env(env).compact_density
                checkbox_says = env_bool(
                    "MRBOT_FX_COMPACT_DENSITY", default, env=env)
                self.assertEqual(
                    settings_says, checkbox_says,
                    f"renderer says {settings_says}, the checkbox would show "
                    f"{checkbox_says} -- the screen disagrees with behaviour")

    def test_effect_settings_still_reads_the_real_environment(self):
        from app.effects import EffectSettings
        env = {"MRBOT_FX_COMPACT_DENSITY": "True",
               "MRBOT_FX_ROUNDED_CORNERS": "False",
               "MRBOT_FX_ANTIALIASING": "False"}
        s = EffectSettings.from_env(env)
        self.assertTrue(s.compact_density)
        self.assertFalse(s.rounded_corners)
        self.assertFalse(s.antialiasing)

    def test_str_bool_round_trips(self):
        """`main.py` persists `str(bool)`. That must survive."""
        from app.effects import env_bool
        self.assertTrue(env_bool("K", False, env={"K": str(True)}))
        self.assertFalse(env_bool("K", True, env={"K": str(False)}))


class TestTheSelfImprovementGateHasOneAnswer(unittest.TestCase):
    """ARCH-ENG-203 ? the same class of bug, on a SAFETY gate.

    `agents.core.feature_flags._LEGACY_ENV` maps `self_improvement` to
    `PIPELINE_ALLOW_SELF_IMPROVE`, and `app/action_pipeline.py` reads that same
    variable. Before this ticket they used different parsers, so for
    `PIPELINE_ALLOW_SELF_IMPROVE=1`:

        feature_enabled("self_improvement")  ->  True
        ActionPipeline.allow_self_improve    ->  False

    The gate was open on one path and closed on the other. Neither raised. This
    is the same screen-vs-behaviour divergence as the FX toggles, except the
    subject is whether the program is permitted to modify itself.
    """

    GATE = "PIPELINE_ALLOW_SELF_IMPROVE"

    def test_both_readers_agree_on_every_input(self):
        from agents.core.feature_flags import feature_enabled
        from app.effects import env_bool

        for raw in ("1", "true", "True", "yes", "on", "0", "false", "no",
                    "off", "", "   ", "ture", None):
            with self.subTest(raw=raw):
                env = {} if raw is None else {self.GATE: raw}
                gate = feature_enabled("self_improvement", env)
                pipeline = env_bool(self.GATE, False, env=env)
                self.assertEqual(
                    gate, pipeline,
                    f"{raw!r}: feature_enabled says {gate}, action_pipeline "
                    f"says {pipeline} -- the self-improvement gate has two "
                    f"answers")

    def test_the_gate_still_fails_closed(self):
        """Convergence must not weaken the default."""
        from agents.core.feature_flags import feature_enabled

        for env in ({}, {self.GATE: ""}, {self.GATE: "ture"},
                    {self.GATE: "2"}, {"UNKNOWN_FEATURE": "1"}):
            with self.subTest(env=env):
                self.assertFalse(
                    feature_enabled("self_improvement", env),
                    "self-improvement became reachable without an explicit "
                    "true token -- the fail-closed contract is broken")

    def test_the_new_variable_still_takes_precedence(self):
        """The convergence must not disturb the migration path."""
        from agents.core.feature_flags import feature_enabled

        self.assertFalse(feature_enabled("self_improvement", {
            "MRBOT_ENABLE_SELF_IMPROVEMENT": "false", self.GATE: "true"}),
            "the legacy alias is overriding the new feature variable")
        self.assertTrue(feature_enabled("self_improvement", {
            "MRBOT_ENABLE_SELF_IMPROVEMENT": "true"}))

    def test_feature_flags_no_longer_parses_its_own(self):
        src = (REPO / "agents" / "core" / "feature_flags.py").read_text(
            encoding="utf-8")
        self.assertNotRegex(
            src, r'in \{"1",\s*"true",\s*"yes",\s*"on"\}',
            "feature_flags has re-implemented its own truthy parser; it must "
            "delegate to app.effects.env_bool")
        self.assertRegex(src, r"from app\.effects import env_bool")

    def test_action_pipeline_uses_the_canonical_parser(self):
        src = (REPO / "app" / "action_pipeline.py").read_text(encoding="utf-8")
        self.assertRegex(
            src, r'env_bool\(\s*"PIPELINE_ALLOW_SELF_IMPROVE"',
            "action_pipeline must read the gate through env_bool")
        self.assertNotRegex(
            src, r'PIPELINE_ALLOW_SELF_IMPROVE.*\.lower\(\)',
            "the narrow `.lower() == \"true\"` form is back on the gate")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-203 — each detector must be able to fail."""

    def test_the_old_parser_still_disagrees(self):
        """Calibration: the detectors below must flag the old behaviour."""
        for raw in ("1", "yes", "on"):
            with self.subTest(raw=raw):
                old = raw.strip().lower() == "true"
                self.assertFalse(old, f"{raw!r} no longer splits the parsers, "
                                      f"so these guards are no longer meaningful")

    def test_the_regex_detectors_see_the_old_source(self):
        old = 'os.getenv("MRBOT_FX_COMPACT_DENSITY", "false").lower() == "true"'
        self.assertRegex(old, r'\.lower\(\)\s*==\s*"true"')
        old2 = 'os.getenv("MRBOT_FX_ROUNDED_CORNERS", "true").lower() != "false"'
        self.assertRegex(old2, r'\.lower\(\)\s*!=\s*"false"')

    def test_the_token_lists_are_disjoint(self):
        """If a token were in both lists, the parser would be order-dependent."""
        from app.effects import _FALSE_TOKENS, _TRUE_TOKENS
        overlap = _TRUE_TOKENS & _FALSE_TOKENS
        self.assertEqual(overlap, frozenset(),
                         f"tokens in both lists: {sorted(overlap)}")