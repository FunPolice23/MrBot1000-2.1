"""ARCH-ENG-194 — the mixin contract, declared and checked instead of implied.

`DualBrainControl(ProviderLifecycleBackend, QWidget)` mixes a backend in as a
base class. Measured across the two files:

  * 64 methods on the backend, 104 on the widget, with only **two** shared names
    (`_log`, `cleanup`). Nothing is duplicated -- this is a clean horizontal split
    of provider control away from widget code, which is the right shape.
  * but the backend references **115 distinct** `self.<attr>`, and only **48**
    are its own. The other **67 live on the widget**: 12 widget *methods* and 55
    data attributes.

So `self` inside the backend means "the facade", and that was knowable only by
grepping both files and diffing the names. A rename or a deletion on the widget
side would raise `AttributeError` when the operator clicks Start — or, worse,
silently skip a line if it sat behind a broad `except`.

This suite pins the contract. The backend now names what it needs
(`HOST_METHODS`, `HOST_ATTRS`, and the `ProviderLifecycleHost` Protocol), and
these tests assert the facade actually provides it.

## Why composition was NOT done instead

Passing the widget as `self` is semantically identical to mixing it in, so
"converting" would be a rename rather than a refactor: ~180 `self.` sites inside
the backend to rewrite for zero architectural gain, against a test surface that
already subclasses `ProviderLifecycleBackend` and monkey-patches its methods onto
`BrainLaunchWorker`.

Real decoupling requires a view object exposing 32 attributes and 12 methods —
that is a rewrite, not a remediation, and it should not be attempted without a
dedicated pass over the Providers & GPU tab.

What this buys instead is that the 180-site question now has a measured answer
recorded next to the code, instead of being rediscovered.

## One contract member worth naming

`bb_ctx_spin`, `bb_gpu_layers_spin`, `bb_batch_spin`, `bb_threads_spin`,
`bb_split_combo`, `bb_kv_combo` and their `sb_*` counterparts are the
llama-server parameter controls. The backend reads them to build the llama
command line, which is why a persistence gap in them surfaces as *a server that
ignores the value the operator set* rather than as a visible error.
"""

import ast
import inspect
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _backend_module():
    from gui.workers import provider_lifecycle_backend as mod
    return mod


class TestHostContractIsComplete(unittest.TestCase):
    """ARCH-ENG-194 — the declared contract covers what the backend uses."""

    def test_the_contract_is_non_trivial(self):
        mod = _backend_module()
        self.assertGreaterEqual(len(mod.HOST_METHODS), 12)
        self.assertGreaterEqual(len(mod.HOST_ATTRS), 32)

    def test_every_unresolved_self_reference_is_declared(self):
        """The point of the exercise: nothing the backend reads is undeclared.

        Re-derives the backend's `self.<attr>` references and subtracts the ones
        it defines itself. Whatever remains is the host's responsibility, and
        every one of them must appear in the contract. This is the test that
        fails if someone adds a `self.something_new` to the backend without
        declaring it.
        """
        mod = _backend_module()
        cls = mod.ProviderLifecycleBackend
        # `vars(cls)` keys are the attribute NAMES. Iterating `.values()` and
        # reading `.name` off a plain function is the bug the first draft had.
        own = set(vars(cls))

        used, written = set(), set()
        for node in ast.walk(ast.parse(inspect.getsource(cls))):
            if not (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                continue
            (written.add(node.attr) if isinstance(node.ctx, ast.Store)
             else used.add(node.attr))

        # The host contract is what the backend READS but never WRITES. An
        # attribute it assigns itself (`_closing`, `_persist_dirty`,
        # `_small_launch_worker`, ...) is its own business, not the facade's --
        # and listing those in the contract would be noise. The first draft used
        # a class-level test instead and so reported 19 such names as undeclared.
        undeclared = {
            name for name in used
            if name not in own and name not in written
            and name not in mod.HOST_METHODS and name not in mod.HOST_ATTRS
        }
        self.assertEqual(
            undeclared, set(),
            f"the backend reads these off `self` but declares nothing about "
            f"them: {sorted(undeclared)}")

    def test_the_contract_has_no_duplicates(self):
        mod = _backend_module()
        combined = tuple(mod.HOST_METHODS) + tuple(mod.HOST_ATTRS)
        self.assertEqual(len(combined), len(set(combined)),
                         "a name is declared twice in the contract")

    def test_the_contract_has_no_internal_overlap(self):
        mod = _backend_module()
        overlap = set(mod.HOST_METHODS) & set(mod.HOST_ATTRS)
        self.assertEqual(overlap, set(),
                         f"declared as both a method and an attribute: {overlap}")

    def test_the_backend_does_not_define_what_it_demands(self):
        """A host member the backend also defines would be redundant."""
        mod = _backend_module()
        for name in mod.HOST_METHODS:
            self.assertNotIn(
                name, vars(mod.ProviderLifecycleBackend),
                f"{name} is in HOST_METHODS but the backend defines it too; "
                f"it is not a host responsibility")


class TestFacadeSatisfiesTheContract(unittest.TestCase):
    """ARCH-ENG-194 — the widget must actually provide every declared name."""

    def test_every_contract_method_exists_on_the_widget_class(self):
        from gui.widgets.dual_brain_control import DualBrainControl
        mod = _backend_module()
        missing = [n for n in mod.HOST_METHODS if not hasattr(DualBrainControl, n)]
        self.assertEqual(
            missing, [],
            f"DualBrainControl no longer provides {missing}; the backend calls "
            f"them, so this raises AttributeError when the operator clicks "
            f"Start rather than failing here")

    def test_the_llama_parameter_controls_are_declared(self):
        """These build the llama command line, so a gap is a silent no-op."""
        mod = _backend_module()
        expected = {
            "bb_ctx_spin", "bb_gpu_layers_spin", "bb_batch_spin",
            "bb_threads_spin", "bb_split_combo", "bb_kv_combo",
            "sb_ctx_spin", "sb_gpu_layers_spin", "sb_batch_spin",
            "sb_threads_spin", "sb_split_combo", "sb_kv_combo",
        }
        self.assertTrue(
            expected.issubset(set(mod.HOST_ATTRS)),
            f"the llama parameter controls must be in the contract; missing "
            f"{sorted(expected - set(mod.HOST_ATTRS))}")

    def test_the_mixin_relationship_is_intentional_not_inherited_by_accident(self):
        """Make the coupling explicit at the class definition."""
        from gui.widgets.dual_brain_control import DualBrainControl
        from gui.workers.provider_lifecycle_backend import ProviderLifecycleBackend
        self.assertIn(ProviderLifecycleBackend, DualBrainControl.__mro__,
                      "the backend is no longer mixed in; if that was "
                      "deliberate, update this test and the contract together")

    def test_the_contract_checker_works_on_a_live_instance(self):
        """`host_contract_satisfied` must be usable on a real, built widget.

        The 32 attributes are assigned while the UI is built, not declared on the
        class -- so a class-level check would report every one as missing.

        Some are conditional on DETECTED HARDWARE: the `bb_*` / `sb_*` llama
        controls only exist once brain rows are built, and `big_brain` /
        `small_brain` are supplied by the application. On a box with no detected
        GPU those legitimately do not exist, so this asserts the contract for
        whatever the environment actually produced rather than pretending every
        machine has the same devices. That is the honest property: no member is
        missing EXCEPT the hardware-conditional ones.
        """
        import agents.safety  # noqa: F401  (import-cycle order)
        from PySide6.QtWidgets import QApplication
        from gui.widgets.dual_brain_control import DualBrainControl
        from gui.workers.provider_lifecycle_backend import (
            HOST_ATTRS, HOST_METHODS, host_contract_satisfied,
        )
        app = QApplication.instance() or QApplication([])
        # Constructing the widget is itself part of the contract: ARCH-ENG-194
        # fixed a crash in __init__ that only appeared with no brain rows.
        widget = DualBrainControl()
        try:
            missing_methods = [n for n in HOST_METHODS if not hasattr(widget, n)]
            self.assertEqual(missing_methods, [],
                             f"host methods missing at runtime: {missing_methods}")

            rows_built = hasattr(widget, "bb_ctx_spin")
            if not rows_built:
                self.skipTest(
                    "no brain rows on this machine, so the hardware-conditional "
                    "contract members cannot be exercised here")

            missing_attrs = [n for n in HOST_ATTRS if not hasattr(widget, n)]
            # big_brain / small_brain are injected by the application, not the UI.
            runtime_supplied = {"big_brain", "small_brain"}
            self.assertEqual(
                sorted(set(missing_attrs) - runtime_supplied), [],
                f"declared in the contract but never created: "
                f"{sorted(set(missing_attrs) - runtime_supplied)}")
        finally:
            try:
                widget.cleanup()
            except Exception:
                pass
            del widget
            del app


class TestProtocolMatchesTheTuples(unittest.TestCase):
    """ARCH-ENG-194 — the Protocol and the checkable tuples must agree.

    Three parallel declarations of one contract is a way to create drift, so this
    asserts they describe the same set.
    """

    def test_protocol_annotations_cover_the_methods(self):
        mod = _backend_module()
        declared = set(mod.ProviderLifecycleHost.__annotations__)
        self.assertTrue(
            set(mod.HOST_METHODS).issubset(declared),
            f"HOST_METHODS not annotated on the Protocol: "
            f"{sorted(set(mod.HOST_METHODS) - declared)}")

    def test_protocol_annotations_cover_the_attributes(self):
        mod = _backend_module()
        declared = set(mod.ProviderLifecycleHost.__annotations__)
        # The three runtime-supplied names are annotated too, so this is total.
        self.assertTrue(
            set(mod.HOST_ATTRS).issubset(declared),
            f"HOST_ATTRS not annotated on the Protocol: "
            f"{sorted(set(mod.HOST_ATTRS) - declared)}")

    def test_the_protocol_declares_nothing_extra(self):
        mod = _backend_module()
        extra = set(mod.ProviderLifecycleHost.__annotations__) - (
            set(mod.HOST_METHODS) | set(mod.HOST_ATTRS))
        self.assertEqual(extra, set(),
                         f"annotated on the Protocol but not in the tuples: "
                         f"{sorted(extra)}")


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-194 — the detector must be able to fail."""

    def test_the_missing_name_detector_reports_a_real_gap(self):
        import types
        mod = _backend_module()
        empty = types.SimpleNamespace()
        missing = mod.host_contract_satisfied(empty)
        self.assertEqual(sorted(missing),
                         sorted(tuple(mod.HOST_METHODS) + tuple(mod.HOST_ATTRS)),
                         "an empty object should miss the whole contract; if it "
                         "did not, the check is vacuous")

    def test_a_declared_but_absent_method_is_detected(self):
        import types
        mod = _backend_module()
        partial = types.SimpleNamespace()
        for name in mod.HOST_METHODS:
            setattr(partial, name, lambda *a, **k: None)
        missing = mod.host_contract_satisfied(partial)
        self.assertEqual(sorted(missing), sorted(mod.HOST_ATTRS),
                         "with every method present, only attributes should be "
                         "reported missing")

    def test_the_backend_really_does_read_the_host_methods(self):
        """Anti-vacuity: the contract is not decorative."""
        from gui.workers import provider_lifecycle_backend as mod
        src = inspect.getsource(mod)
        for name in ("_set_loading", "_repopulate_model_combo", "_brain_port"):
            self.assertIn(f"self.{name}(", src,
                          f"the backend no longer calls self.{name}(); if that is "
                          f"intentional, drop it from HOST_METHODS too")
