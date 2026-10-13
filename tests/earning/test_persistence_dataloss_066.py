"""ARCH-ENG-066/070 — persistence data-loss regression tests.

Both defects were reproduced by execution BEFORE the fix:

  066  `WorkshopManager.add_account` / `add_payment_method` did load+save in one
       flow, and the load swallowed the parse error and returned `{}`. The save
       then wrote that empty dict over the file, so ONE truncated byte erased
       every stored account / payment method — and the call still returned True.
       Reproduced: operator accounts ['fiverr','upwork'] -> add 'prolific' ->
       on disk: ['prolific'] only, `add_account()` == True.

  070  `main.py:_save_provider_list` wrote a whole-file dict containing only
       `{"providers": [...]}`, destroying the `devices` block that
       `device_registry.save_policy` maintains. Reproduced: after save_policy the
       file held devices.enabled/models/settings; after `_save_provider_list` it
       held only `providers`, and `load_policy` came back empty — every device
       reverting to default-ENABLED, including ones the operator had disabled.
"""

import json
import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.knowledge.workshop import Workshop
from agents.runtime.device_registry import (
    DevicePolicy,
    load_policy,
    merge_settings_file,
    save_policy,
)


def _workshop(tmpdir):
    """A Workshop rooted in a throwaway directory (never D:\\ai_workshop)."""
    return Workshop(root=tmpdir)


class TestCorruptStoreDoesNotEraseData(unittest.TestCase):
    """ARCH-ENG-066 — an unreadable store must refuse to write, not wipe."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arch_eng_066_")
        self.w = _workshop(self.tmp)

    def test_corrupt_accounts_file_is_not_overwritten(self):
        # Genuinely unparseable (missing closing brace) — a truncated write.
        with open(self.w._accounts_file, "w", encoding="utf-8") as f:
            f.write('{"fiverr": {"platform": "fiverr"}')

        ok = self.w.add_account("prolific", "u", "e@x.com")

        self.assertFalse(ok, "add_account must refuse rather than report success")
        with open(self.w._accounts_file, "r", encoding="utf-8") as f:
            on_disk = f.read()
        self.assertIn("fiverr", on_disk,
                      "the unreadable file must not be replaced by a one-key dict")

    def test_corrupt_payments_file_is_not_overwritten(self):
        with open(self.w._payments_file, "w", encoding="utf-8") as f:
            f.write('{"paypal": {"method": "paypal"}')  # truncated / invalid JSON

        ok = self.w.add_payment_method("wise", "acct-1")

        self.assertFalse(ok, "add_payment_method must refuse rather than report success")
        with open(self.w._payments_file, "r", encoding="utf-8") as f:
            on_disk = f.read()
        self.assertIn("paypal", on_disk)

    def test_healthy_store_still_accumulates(self):
        self.assertTrue(self.w.add_account("upwork", "u1", "a@x.com"))
        self.assertTrue(self.w.add_account("fiverr", "u2", "b@x.com"))
        names = sorted(a["platform"] for a in self.w.list_accounts())
        self.assertEqual(names, ["fiverr", "upwork"],
                         "a healthy store must keep accumulating, not reset")

        self.assertTrue(self.w.add_payment_method("paypal", "p@x.com"))
        self.assertTrue(self.w.add_payment_method("wise", "w@x.com"))
        self.assertEqual(len(self.w.list_payment_methods()), 2)

    def test_non_dict_json_is_treated_as_unreadable(self):
        with open(self.w._accounts_file, "w", encoding="utf-8") as f:
            json.dump(["not", "a", "dict"], f)
        self.assertFalse(self.w.add_account("x", "u", "e"))
        self.assertEqual(self.w.list_accounts(), [])

    def test_write_is_atomic_no_temp_left_behind(self):
        self.assertTrue(self.w.add_account("upwork", "u", "e@x.com"))
        leftovers = [str(p) for p in __import__("pathlib").Path(self.tmp).rglob("*.tmp")]
        self.assertEqual(leftovers, [], f"temp files left behind: {leftovers}")

    def test_interrupted_write_leaves_original_file_intact(self):
        """ARCH-ENG-066 crash-safety: an `os.replace` that fails mid-write must
        leave the ORIGINAL file byte-identical, not a truncated one."""
        self.assertTrue(self.w.add_account("upwork", "u", "e@x.com"))
        with open(self.w._accounts_file, "rb") as f:
            before = f.read()

        real_replace = os.replace

        def _boom(src, dst):
            raise OSError("simulated crash before replace")

        os.replace = _boom
        try:
            # add_account swallows the failure and returns False (fail-closed);
            # what matters is that the ON-DISK store is untouched.
            self.assertFalse(self.w.add_account("fiverr", "u2", "b@x.com"))
        finally:
            os.replace = real_replace

        with open(self.w._accounts_file, "rb") as f:
            after = f.read()
        self.assertEqual(before, after,
                         "a failed write must not corrupt the existing store")
        leftovers = [str(p) for p in __import__("pathlib").Path(self.tmp).rglob("*.tmp*")]
        self.assertEqual(leftovers, [], f"temp files left behind: {leftovers}")


class TestProviderListSavePreservesDevicePolicy(unittest.TestCase):
    """ARCH-ENG-070 — the Settings Save button must not erase per-device config."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arch_eng_070_")

    def test_merge_preserves_devices_block(self):
        policy = DevicePolicy()
        policy.enabled = {"gpu-abc": False, "cpu": True}
        policy.models = {"gpu-abc": "big.gguf"}
        policy.settings = {"gpu-abc": {"context": 65536, "gpu_layers": 40}}
        self.assertTrue(save_policy(policy, root=self.tmp))

        self.assertTrue(merge_settings_file(
            {"providers": [{"name": "ollama", "enabled": True}]}, root=self.tmp))

        # The device policy must survive a providers-only write.
        reloaded = load_policy(root=self.tmp)
        self.assertEqual(reloaded.enabled.get("gpu-abc"), False,
                         "a device the operator DISABLED must stay disabled")
        self.assertEqual(reloaded.models.get("gpu-abc"), "big.gguf")
        self.assertEqual(reloaded.settings.get("gpu-abc", {}).get("context"), 65536)

    def test_merge_preserves_unrelated_sibling_keys(self):
        path = os.path.join(self.tmp, "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"safety": {"approval_required": True}, "devices": {}}, f)

        self.assertTrue(merge_settings_file({"providers": []}, root=self.tmp))

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("safety"), {"approval_required": True},
                         "unrelated top-level keys must survive the merge")
        self.assertEqual(data.get("providers"), [])

    def test_corrupt_settings_is_quarantined_not_overwritten_silently(self):
        path = os.path.join(self.tmp, "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{corrupt")

        self.assertTrue(merge_settings_file({"providers": []}, root=self.tmp))

        quarantined = [n for n in os.listdir(self.tmp) if ".corrupt-" in n]
        self.assertTrue(quarantined,
                        "an unparseable settings.json must be rotated aside, not dropped")
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f).get("providers"), [])


class TestSaveProviderListCallSitePreservesDevicePolicy(unittest.TestCase):
    """ARCH-ENG-070 — the ACTUAL buggy call site, not just the helper.

    The reviewer found that reverting `main.py:_save_provider_list` to its
    destructive whole-file write still left the suite green: `merge_settings_file`
    was unit-tested but the function that had the bug was not.
    """

    def test_save_provider_list_preserves_devices_block(self):
        tmp = tempfile.mkdtemp(prefix="arch_eng_070_callsite_")
        # conftest installs a session-wide isolation override; save and RESTORE it
        # rather than deleting it, or later tests would write the live settings.json.
        prev_override = os.environ.get("MRBOT_DEVICE_SETTINGS_PATH")
        os.environ["MRBOT_DEVICE_SETTINGS_PATH"] = os.path.join(tmp, "settings.json")
        try:
            # `MainWindow` is a QWidget and cannot be constructed without a
            # QApplication; bind the real method to a minimal stub instead.
            from main import MainWindow

            policy = DevicePolicy()
            policy.enabled = {"gpu-abc": False}
            policy.models = {"gpu-abc": "big.gguf"}
            policy.settings = {"gpu-abc": {"context": 65536}}
            self.assertTrue(save_policy(policy))

            app = type("Stub", (), {})()
            app.log_signal = type("S", (), {"emit": lambda self, m: None})()
            app._role_enabled = lambda combo: (True, False)
            app.ollama_role = None
            MainWindow._save_provider_list(app)

            reloaded = load_policy()
            self.assertEqual(reloaded.enabled.get("gpu-abc"), False,
                             "a disabled device must survive a provider-list save")
            self.assertEqual(reloaded.models.get("gpu-abc"), "big.gguf")
            self.assertEqual(reloaded.settings.get("gpu-abc", {}).get("context"), 65536)
        finally:
            if prev_override is None:
                os.environ.pop("MRBOT_DEVICE_SETTINGS_PATH", None)
            else:
                os.environ["MRBOT_DEVICE_SETTINGS_PATH"] = prev_override
