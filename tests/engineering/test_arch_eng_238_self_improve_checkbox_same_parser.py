"""ARCH-ENG-238 / AW-02 -- the self-improvement checkbox must parse the gate
variable with the SAME parser as the enforcement point.

The finding
-----------
`create_settings_tab` read `PIPELINE_ALLOW_SELF_IMPROVE` with the inline
`.lower() == "true"` while `app/action_pipeline.py:384` reads the SAME variable
through `app.effects.env_bool` (ARCH-ENG-203's one canonical parser,
accepting `1`/`yes`/`on`/`True`). For the perfectly reasonable hand-edited
`PIPELINE_ALLOW_SELF_IMPROVE=1`, the checkbox rendered **unchecked** while the
agent was **permitted** to modify its own code. The screen agreed with the
operator and disagreed with the enforcement point -- the same shape as
`11v`'s AO-03, and the last standing member of the ARCH-ENG-203 parser family.

Fix: the checkbox reads through `env_bool` too. The write side
(stateChanged -> "true"/"false") is unchanged and readable by every parser.
`PIPELINE_ALLOW_WRITE` at :2530 keeps its inline parse deliberately: no other
module parses that variable, so there is no counterparty to disagree with.

Tests are AST-based over the settings builders. ARCH-ENG-278 (AW-03) split
`create_settings_tab` into section methods, so the scan now covers the whole
builder module: the checkbox lives in `_build_pipeline_group`, and a test that
kept looking only at the orchestrator would pass with the defect restored.

Vacuity: against the pre-fix source, the ad-hoc `os.getenv(...)
.lower() == "true"` reader is present and the assertions fail.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
BUILDER = REPO / "gui" / "builders" / "tab_feature_builders.py"
PIPELINE = REPO / "app" / "action_pipeline.py"

SELF_IMPROVE_VAR = "PIPELINE_ALLOW_SELF_IMPROVE"


def _settings_tree():
    """The whole builder module (ARCH-ENG-278 split the one function)."""
    return ast.parse(BUILDER.read_text(encoding="utf-8"))


class TestTheCheckboxReadsTheCanonicalParser(unittest.TestCase):

    def test_self_improve_gate_is_read_through_env_bool(self):
        """The setChecked() argument for the self-improvement gate must be an
        env_bool() call."""
        func = _settings_tree()
        found = []
        for node in ast.walk(func):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "env_bool"
                    and node.args):
                arg = node.args[0]
                if (isinstance(arg, ast.Constant)
                        and arg.value == SELF_IMPROVE_VAR):
                    found.append(node)
        self.assertEqual(
            len(found), 1,
            f"the settings builders must read {SELF_IMPROVE_VAR} via env_bool(); "
            f"env_bool call(s) with that variable: {len(found)}")

    def test_no_ad_hoc_reader_remains_for_the_variable(self):
        """The subclass of defect this file twice proved dangerous: the same
        variable read with a private parser."""
        src = BUILDER.read_text(encoding="utf-8")
        func = _settings_tree()
        for node in ast.walk(func):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "getenv"):
                arg = node.args[0] if node.args else None
                if (isinstance(arg, ast.Constant)
                        and arg.value == SELF_IMPROVE_VAR):
                    self.fail(
                        "an os.getenv reader for the self-improvement gate "
                        "still exists in the settings builders -- a second "
                        "parser on the same variable is exactly the AW-02/AO-03 "
                        "shape")

    def test_enforcement_point_still_uses_the_same_parser(self):
        """Pair the two readers of the SAME variable in one contract test, so
        that fixing one side again can never pass without noticing."""
        line = next(n for n in ast.walk(ast.parse(
            PIPELINE.read_text(encoding="utf-8")))
            if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "env_bool"
                and n.args
                and isinstance(n.args[0], ast.Constant)
                and n.args[0].value == SELF_IMPROVE_VAR))
        self.assertTrue(
            line, "action_pipeline's env_bool reader must stay paired with the "
            "checkbox's")


if __name__ == "__main__":
    unittest.main()
