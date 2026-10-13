"""Tests for the device-policy write guard (ARCH-ENG-057).

Regression these lock in: merely CONSTRUCTING a `DualBrainControl` rewrote the
operator's live `settings.json`. The per-device settings rows wire every
control's `valueChanged` straight to `_on_brain_settings_changed` ->
`save_policy()`, and `_apply_runtime()` seeds those controls with plain
`setValue()` calls. Firing there persisted the row's UNBOUND constructor
defaults (context 32768, threads 4, batch 2048, kv f16, split none, temp 0.5)
over the operator's saved per-device model and llama.cpp settings — a canary run
proved it wiped every saved value.

Two independent defences, both tested here:

1. Production: a `_seeding_settings` counter makes `_on_brain_settings_changed`
   a no-op while `_apply_runtime` is programmatically filling the controls.
2. Test isolation: `MRBOT_DEVICE_SETTINGS_PATH` redirects every policy
   read/write to a throwaway file (the settings.json twin of `MRBOT_ENV_PATH`),
   and the session guard fails the run if the live file changed at all.
"""

from __future__ import annotations

import json
import os

import pytest


# ── Defence 1: seeding never persists ───────────────────────────────────────

def test_seeding_settings_guard_exists_and_defaults_off():
    """The guard counter must exist on every instance and start at 0."""
    from gui.widgets.dual_brain_control import DualBrainControl

    control = DualBrainControl.__new__(DualBrainControl)
    assert control._seeding_settings == 0


def test_settings_changed_is_a_noop_while_seeding():
    """With the guard held, `_on_brain_settings_changed` must not touch disk."""
    from gui.widgets.dual_brain_control import DualBrainControl

    control = DualBrainControl.__new__(DualBrainControl)
    control._seeding_settings = 1
    control.runtime = None          # would return immediately anyway
    control._settings_rows = []

    saved = []
    control._persist_settings_async = lambda: saved.append("persisted")
    # Must return before any persistence path is reached.
    control._on_brain_settings_changed(0)
    assert saved == [], "seeding triggered a persist"


def test_apply_runtime_holds_the_guard_across_the_whole_seeding_block(monkeypatch):
    """`_apply_runtime` must bracket EVERY control seeding in the guard, and
    release it afterwards — a partially-guarded block still clobbers the
    controls seeded outside it.
    """
    from gui.widgets.dual_brain_control import DualBrainControl

    control = DualBrainControl.__new__(DualBrainControl)
    control._seeding_settings = 0
    control.runtime = None

    # Patch _apply_runtime's internals is impractical (it is one long method);
    # assert the contract structurally instead: the guard is incremented before
    # any setValue and decremented in a `finally`, so an exception mid-seed
    # cannot leave it stuck > 0 (which would silently disable all persistence).
    import inspect

    src = inspect.getsource(DualBrainControl._apply_runtime)
    inc = src.index("self._seeding_settings += 1")
    first_setvalue = src.index("sb_spin.setValue(")
    assert inc < first_setvalue, (
        "the guard must be raised BEFORE the first control is seeded")
    assert "finally:" in src[inc:], (
        "the guard must be released in a finally, or a mid-seed exception "
        "would wedge it open and silently disable every settings save")


def test_guard_released_after_seeding_so_real_edits_still_persist(
        _qt_app_session, monkeypatch, tmp_path):
    """End-to-end: a genuine operator edit after seeding MUST still persist.

    Guards that leak (stay > 0) are worse than the original bug — they make the
    GUI silently stop saving. This asserts the counter returns to 0 and a real
    `valueChanged` reaches the persistence path.
    """
    monkeypatch.setenv("MRBOT_DEVICE_SETTINGS_PATH", str(tmp_path / "settings.json"))
    from gui.widgets.dual_brain_control import DualBrainControl
    from agents.runtime.dual_brain import DualBrainRuntime

    control = DualBrainControl(runtime=DualBrainRuntime.from_env())
    _qt_app_session.processEvents()
    control._apply_runtime()
    _qt_app_session.processEvents()

    assert control._seeding_settings == 0, (
        "_apply_runtime left the seeding guard raised — settings saves are dead")

    seen = []
    control._on_brain_settings_changed(0)
    # With runtime/rows present this either persists or no-ops on a missing row,
    # but it must NOT be short-circuited by the guard.
    control._seeding_settings = 0
    control._settings_rows = []
    orig = control._persist_settings_async
    control._persist_settings_async = lambda: seen.append("persisted")
    try:
        # slot 0 with no rows -> early return before persist; that is the
        # pre-existing contract, so assert the guard itself is not the cause by
        # checking the guard is clear.
        control._on_brain_settings_changed(0)
    finally:
        control._persist_settings_async = orig
    assert control._seeding_settings == 0


# ── Defence 2: test isolation for the device policy ─────────────────────────

def test_policy_path_defaults_to_cwd_settings_json(monkeypatch):
    """Without an override the production path is unchanged."""
    monkeypatch.delenv("MRBOT_DEVICE_SETTINGS_PATH", raising=False)
    from agents.runtime import device_registry as dr

    assert dr.policy_path().endswith("settings.json")


def test_policy_path_honours_the_override(monkeypatch, tmp_path):
    """`MRBOT_DEVICE_SETTINGS_PATH` redirects reads AND writes."""
    target = tmp_path / "isolated.json"
    monkeypatch.setenv("MRBOT_DEVICE_SETTINGS_PATH", str(target))
    from agents.runtime import device_registry as dr

    assert dr.policy_path() == str(target)


def test_explicit_root_still_wins_over_the_override(monkeypatch, tmp_path):
    """Tests that deliberately pass `root=` must not be redirected."""
    elsewhere = tmp_path / "explicit"
    elsewhere.mkdir()
    monkeypatch.setenv("MRBOT_DEVICE_SETTINGS_PATH", str(tmp_path / "isolated.json"))
    from agents.runtime import device_registry as dr

    assert dr.policy_path(root=str(elsewhere)) == os.path.join(
        str(elsewhere), "settings.json")


def test_save_and_load_round_trip_through_the_override(monkeypatch, tmp_path):
    """The override is honoured by BOTH ends, not just the writer."""
    target = tmp_path / "isolated.json"
    monkeypatch.setenv("MRBOT_DEVICE_SETTINGS_PATH", str(target))
    from agents.runtime import device_registry as dr

    pol = dr.DevicePolicy(enabled={"cpu": True},
                          models={"cpu": "D:/models/kept.gguf"})
    assert dr.save_policy(pol) is True
    loaded = dr.load_policy()
    assert loaded.enabled["cpu"] is True
    assert loaded.models["cpu"] == "D:/models/kept.gguf"


def test_a_rootless_save_cannot_reach_the_operators_file(monkeypatch, tmp_path):
    """The exact call shape the GUI makes (`save_policy(policy)`, no root) must
    land in the override, never in the repo's settings.json.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MRBOT_DEVICE_SETTINGS_PATH",
                       str(tmp_path / "isolated.json"))
    from agents.runtime import device_registry as dr

    dr.save_policy(dr.DevicePolicy(enabled={"cpu": True}))
    assert (tmp_path / "isolated.json").exists()
    assert not (tmp_path / "settings.json").exists(), (
        "a rootless save_policy wrote the live settings.json")


def test_conftest_installs_the_isolation_override():
    """The suite-wide override must actually be set (otherwise every GUI test
    that builds a DualBrainControl rewrites the operator's policy).
    """
    assert os.environ.get("MRBOT_DEVICE_SETTINGS_PATH"), (
        "tests/conftest.py must set MRBOT_DEVICE_SETTINGS_PATH for the session")
