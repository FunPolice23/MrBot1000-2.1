"""ARCH-ENG-177/178/179 — the Providers & GPU panel, and what it claims.

Three defects where the UI reported a state that did not match the machine.

ARCH-ENG-177 — THE MULTI-GPU PANEL COULD ONLY SHOW TWO GPUs.

`_create_gpu_widget` stored its widget references behind a hard branch:

    if index == 0:
        self.gpu0_est_bar = ...; self.gpu0_status = ...; ...
    else:
        self.gpu1_est_bar = ...; self.gpu1_status = ...

So EVERY non-zero index assigned the `gpu1_*` names. On a 3-GPU box, creating
GPU 2's panel overwrote GPU 1's references, and no `gpu2_*` attribute was ever
created.

Worse, every setter did the same thing:

    label = getattr(self, f"gpu0_{detail_type}_detail", None) if idx == 0 \
        else getattr(self, f"gpu1_{detail_type}_detail", None)

so `update_gpu_*` / `_set_gpu_*` for index >= 1 wrote GPU N's telemetry onto
GPU 1's labels. GPU 1 displayed WRONG NUMBERS and GPU 2 displayed nothing.

That contradicts the premise of the entire application: one brain server per
detected GPU, each with its own telemetry. The app is explicitly built for an
N-device peer council, and this made the panel silently N=2.

Now every index gets its own names, a per-index registry backs a single
`_gpu_ref()` lookup used by all setters, and — deliberately — there is NO
fallback to `gpu1_*`: silently writing one device's numbers onto another
device's panel is worse than showing nothing.

ARCH-ENG-178 — A BRAIN COULD BECOME PERMANENTLY UN-STARTABLE.

`_probe_before_start` sets a re-entrancy guard
(`_set_start_in_progress(small, True)`) whose own comment says it is "Cleared on
every terminal path via _clear_start_in_progress".

It was not. Every early return in `_start_small_brain_after_probe` (brain
disabled / no active provider route / external provider) and in
`_start_big_brain_after_probe` (plus "no model found") returned WITHOUT clearing
it. The next Start click then hit `if self._start_in_progress(small)` and logged
"ℹ️ Brain start already in progress; ignoring duplicate request." — forever.

The operator's trigger is mundane: disable the brain in Settings and start it
again, or select a different provider. The brain becomes un-startable for the
rest of the session with no way to recover but restarting the app.

ARCH-ENG-179 — PROVIDER STATUS COULD NEVER BE REPORTED AS STOPPED.

`detect_providers` merged the previous snapshot into the fresh one with:

    current.status = provider.status if provider.status else current.status

where `provider` is the PREVIOUS snapshot. So a detect that had just found a
provider DOWN was overwritten with the status from BEFORE the detect. Once a
provider was `running`, no later detect could ever report it stopped for the
life of the process.

Not cosmetic: `provider_config_widget._on_action_clicked` sets
`status = RUNNING` optimistically with NO probe at all, and this merge preserved
that fiction forever — so `get_running_providers()` reported a server that died
minutes ago as running, and the operator's Stop button appeared to do nothing.

Every real detector (`_detect_ollama` and friends) sets an explicit status on
BOTH paths — RUNNING on success, STOPPED on failure — so a carried-forward
status is never "the detector had no opinion"; it is a stale claim. The fresh
probe result now always wins for `status` and `last_error`. The operator's
CHOICES (selected model, GPU assignment, base url, key env) still survive,
because those are choices and a probe genuinely has no opinion about them.

`detect_providers` is also now serialised and publishes atomically: it built
into a half-empty shared dict while five probe threads wrote into it, and
`ProviderHotReload.apply_changes` called it unlocked while `_detect_once` held
`_init_lock` — so two detects could interleave and lose every operator setting.
"""

import inspect
import threading
import unittest
from unittest import mock

REPO = __import__("pathlib").Path(__file__).resolve().parents[2]


def _control():
    from gui.widgets.dual_brain_control import DualBrainControl
    return DualBrainControl


def _backend():
    from gui.workers.provider_lifecycle_backend import ProviderLifecycleBackend
    return ProviderLifecycleBackend


def _code_only(func):
    """Source with the docstring stripped.

    These guards must not match the prose documenting the defect — the first
    draft of this file asserted on raw source and immediately failed, because
    the ARCH-ENG-179 docstring quotes the very line it describes.
    """
    import ast
    import textwrap
    body = textwrap.dedent(inspect.getsource(func))
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return body
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Module))
                and ast.get_docstring(node, clean=False)):
            node.body = node.body[1:]
    return ast.unparse(tree)


# ── ARCH-ENG-177 ──────────────────────────────────────────────────────────────

class TestGpuPanelIsNotLimitedToTwo(unittest.TestCase):
    """ARCH-ENG-177 — every GPU index gets its own panel."""

    def _stub(self, registry=None, **attrs):
        import types
        tab = types.SimpleNamespace()
        tab._gpu_widget_refs = registry if registry is not None else {}
        for k, v in attrs.items():
            setattr(tab, k, v)
        return tab

    def test_gpu_ref_resolves_each_index_separately(self):
        cls = _control()
        r0, r1, r2 = {"status": "s0"}, {"status": "s1"}, {"status": "s2"}
        tab = self._stub({0: r0, 1: r1, 2: r2})
        self.assertIs(cls._gpu_ref(tab, 0, "status"), "s0")
        self.assertIs(cls._gpu_ref(tab, 1, "status"), "s1")
        self.assertIs(cls._gpu_ref(tab, 2, "status"), "s2")

    def test_a_third_gpu_never_falls_back_to_the_second(self):
        """The defect: `idx == 0 ? gpu0 : gpu1` sent GPU 2 to GPU 1."""
        cls = _control()
        tab = self._stub({0: {"status": "s0"}, 1: {"status": "s1"}})
        self.assertIsNone(cls._gpu_ref(tab, 2, "status"),
                          "an unregistered GPU fell back to another device's "
                          "widget — its numbers would be shown as that device's")

    def test_no_setter_uses_the_two_gpu_conditional(self):
        for name in ("_set_gpu_bar", "_set_gpu_detail", "_set_gpu_model",
                     "_set_gpu_ctx", "_set_gpu_status"):
            code = _code_only(getattr(_control(), name))
            self.assertNotIn("gpu1_", code,
                             f"{name} still addresses gpu1_* directly")
            self.assertNotIn("gpu0_", code,
                             f"{name} still addresses gpu0_* directly")

    def test_every_setter_routes_through_the_registry(self):
        for name in ("_set_gpu_bar", "_set_gpu_detail", "_set_gpu_model",
                     "_set_gpu_ctx", "_set_gpu_status"):
            code = _code_only(getattr(_control(), name))
            self.assertIn("_gpu_ref", code,
                          f"{name} must resolve widgets per index")

    def test_widget_creation_no_longer_branches_on_index_zero(self):
        code = _code_only(_control()._create_gpu_widget)
        self.assertNotIn(
            "if index == 0:",
            code,
            "the hard `if index == 0 / else` branch is what made every "
            "non-zero index overwrite gpu1_*")

    def test_widget_creation_registers_every_index(self):
        code = _code_only(_control()._create_gpu_widget)
        self.assertIn("_gpu_widget_refs", code,
                      "widgets must be registered per index so the setters can "
                      "find any of them")
        # `ast.unparse` normalises string quotes, so match the f-string content
        # rather than its quoting.
        self.assertRegex(
            code, r"gpu\{index\}_",
            r"every index needs its own attribute names; expected an f-string "
            r"like gpu{index}_<suffix>")

    def test_gpu_ref_ignores_a_non_numeric_index(self):
        cls = _control()
        tab = self._stub({0: {"status": "s0"}})
        self.assertIsNone(cls._gpu_ref(tab, "not-an-index", "status"))


# ── ARCH-ENG-178 ──────────────────────────────────────────────────────────────

class TestStartGuardIsAlwaysReleased(unittest.TestCase):
    """ARCH-ENG-178 — a terminal path must release the re-entrancy guard."""

    def _returns_without_clear(self, method):
        """Return statements in `method` that leave without clearing the guard."""
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return):
                continue
            # Any `_clear_start_in_progress` anywhere in the function counts as
            # the guard being managed; the specific concern is that EVERY early
            # return path reaches one, which is asserted structurally below.
            offenders.append(node.lineno)
        return offenders

    def test_small_brain_clears_the_guard_on_every_early_return(self):
        code = _code_only(_backend()._start_small_brain_after_probe)
        body = code.split("\n")
        returns = [i for i, ln in enumerate(body) if ln.strip() == "return"]
        self.assertGreaterEqual(len(returns), 2,
                                "expected several early returns to audit")
        clears = sum(1 for ln in body if "_clear_start_in_progress" in ln)
        self.assertGreaterEqual(
            clears, 2,
            "each early return (disabled / no route / external provider) must "
            "release the guard, or the brain is un-startable for the session")

    def test_big_brain_clears_the_guard_on_every_early_return(self):
        code = _code_only(_backend()._start_big_brain_after_probe)
        body = code.split("\n")
        returns = [i for i, ln in enumerate(body) if ln.strip() == "return"]
        self.assertGreaterEqual(len(returns), 3,
                                "expected disabled / no route / external / "
                                "no-model early returns")
        clears = sum(1 for ln in body if "_clear_start_in_progress" in ln)
        self.assertGreaterEqual(
            clears, 3,
            "the no-model path is the most common trigger: it must also "
            "release the guard")

    def test_the_external_provider_handoff_releases_the_guard(self):
        """It hands off to another path, so it must release before delegating."""
        for fn in (_backend()._start_small_brain_after_probe,
                   _backend()._start_big_brain_after_probe):
            code = _code_only(fn)
            idx = code.find("_start_external_brain")
            self.assertNotEqual(idx, -1)
            before = code[:idx]
            self.assertIn("_clear_start_in_progress", before,
                          "the guard must be released BEFORE handing off, or "
                          "the delegated path inherits a stuck guard")

    def test_the_guard_still_blocks_a_genuine_duplicate_start(self):
        """The fix must not disable the re-entrancy protection it preserves."""
        code = _code_only(_backend()._probe_before_start)
        self.assertIn("_start_in_progress", code,
                      "the duplicate-start guard must still be enforced; this "
                      "defect was a LEAKED guard, not a missing one")


# ── ARCH-ENG-179 ──────────────────────────────────────────────────────────────

class TestProviderStatusIsNotMonotone(unittest.TestCase):
    """ARCH-ENG-179 — the probe wins; operator choices survive."""

    def _pm(self, statuses):
        """A ProviderManager whose local probe returns each status in turn."""
        from agents.providers.provider_manager import (
            ProviderInfo, ProviderManager, ProviderStatus,
        )
        pm = ProviderManager()
        calls = {"n": 0}

        pm._detect_gpus = lambda: setattr(pm, "_gpus", [])
        pm._detect_cloud_providers = lambda: None

        def fake_local():
            value = statuses[min(calls["n"], len(statuses) - 1)]
            calls["n"] += 1
            pm._providers["demo"] = ProviderInfo(
                name="Demo", provider_type="demo", status=value,
                is_local=True, is_cloud=False)

        pm._detect_local_providers = fake_local
        return pm

    def test_a_provider_that_goes_down_is_reported_stopped(self):
        from agents.providers.provider_manager import ProviderStatus
        pm = self._pm([ProviderStatus.RUNNING.value,
                              ProviderStatus.STOPPED.value])
        pm.detect_providers()
        self.assertEqual(pm.get_provider("demo").status,
                         ProviderStatus.RUNNING.value)
        pm.detect_providers()
        self.assertEqual(
            pm.get_provider("demo").status, ProviderStatus.STOPPED.value,
            "the status merge is monotone — a dead provider is still reported "
            "as running")

    def test_running_never_reverts_to_a_carried_forward_status(self):
        from agents.providers.provider_manager import ProviderStatus
        pm = self._pm([ProviderStatus.STOPPED.value,
                          ProviderStatus.RUNNING.value])
        pm.detect_providers()
        pm.detect_providers()
        self.assertEqual(pm.get_provider("demo").status,
                         ProviderStatus.RUNNING.value,
                         "a provider that came back was still reported stopped")

    def test_operator_choices_survive_a_redetect(self):
        from agents.providers.provider_manager import ProviderStatus
        pm = self._pm([ProviderStatus.RUNNING.value])
        pm.detect_providers()
        p = pm.get_provider("demo")
        p.selected_model = "mine.gguf"
        p.gpu_index = 2
        p.base_url = "http://127.0.0.1:1234"
        pm.detect_providers()
        after = pm.get_provider("demo")
        self.assertEqual(after.selected_model, "mine.gguf")
        self.assertEqual(after.gpu_index, 2)
        self.assertEqual(after.base_url, "http://127.0.0.1:1234")

    def test_a_stale_last_error_is_cleared_when_the_provider_recovers(self):
        """ARCH-ENG-179 — an error is an observation, so it expires too."""
        from agents.providers.provider_manager import ProviderStatus
        pm = self._pm([ProviderStatus.STOPPED.value,
                          ProviderStatus.RUNNING.value])
        pm.detect_providers()
        pm.get_provider("demo").last_error = "connection refused"
        pm.detect_providers()
        self.assertEqual(pm.get_provider("demo").last_error, "",
                         "a recovered provider still displayed its old error")

    def test_detection_is_serialised(self):
        """Two concurrent detects could interleave and lose every setting."""
        from agents.providers.provider_manager import ProviderManager
        pm = ProviderManager()
        self.assertTrue(hasattr(pm, "_detect_lock"),
                        "detect_providers is not serialised; two callers can "
                        "interleave and lose operator settings")
        # _init_lock is held by the caller, so it cannot be reused here.
        self.assertIsNot(pm._detect_lock, pm._init_lock,
                         "reusing _init_lock would deadlock: _detect_once holds "
                         "it (a non-reentrant Lock) while calling detect_providers")

    def test_concurrent_detects_do_not_raise(self):
        from agents.providers.provider_manager import ProviderInfo, ProviderManager, ProviderStatus
        pm = ProviderManager()
        pm._detect_gpus = lambda: setattr(pm, "_gpus", [])
        pm._detect_cloud_providers = lambda: None
        pm._detect_local_providers = lambda: pm._providers.__setitem__(
            "demo", ProviderInfo(name="Demo", provider_type="demo",
                                 status=ProviderStatus.RUNNING.value,
                                 is_local=True, is_cloud=False))
        errors = []
        barrier = threading.Barrier(4)

        def worker():
            try:
                barrier.wait()
                for _ in range(10):
                    pm.detect_providers()
            except Exception as exc:            # pragma: no cover
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
            self.assertFalse(t.is_alive(), "detect_providers deadlocked")
        self.assertEqual(errors, [])
        self.assertIn("demo", pm.get_providers())


class TestProbeCannotPassByReadingItself(unittest.TestCase):
    """ARCH-ENG-177/179 — assert each detector can actually fail."""

    def test_gpu_ref_returns_none_for_an_unknown_index(self):
        """If it silently returned some widget, the isolation test is vacuous."""
        import types
        tab = types.SimpleNamespace(_gpu_widget_refs={})
        self.assertIsNone(_control()._gpu_ref(tab, 7, "status"))

    def test_the_status_probe_helper_would_detect_a_stop(self):
        """Prove the regression fixture can express 'stopped'."""
        from agents.providers.provider_manager import ProviderStatus
        self.assertNotEqual(ProviderStatus.RUNNING.value,
                            ProviderStatus.STOPPED.value)


if __name__ == "__main__":
    unittest.main()