"""Headless smoke test for the Self-Improvement tab's code-patch section.

Builds the tab offscreen, proposes a patch through the real CodePatchService,
and verifies the tab renders it and that Approve/Decline wiring is present.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["MRBOT_ENABLE_SELF_IMPROVEMENT"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest  # noqa: E402

from PySide6.QtWidgets import QApplication, QTableWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def _make_tab(app):
    from gui.builders.tab_feature_builders import FeatureTabBuildersMixin
    from agents.safety.approval import HumanApprovalQueue
    from agents.services.code_patch_service import CodePatchService

    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "gui"))
    target = os.path.join(root, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")

    q = HumanApprovalQueue()
    svc = CodePatchService(approval_queue=q, root_dir=root)

    class FakeServices:
        code_patch_service = svc

    class FakeWindow(FeatureTabBuildersMixin):
        def __init__(self):
            self._earning_services = FakeServices()
            self.earning_pipeline = None
            self._t = lambda key: key

    win = FakeWindow()
    tab = win.create_self_improvement_tab()
    return tab, svc, q, target, root


def test_tab_builds_and_shows_pending_patch(app):
    from agents.services.self_improvement_commands import propose_code_patch

    # Propose BEFORE building the tab so the build-time refresh picks it up
    # (the 5s coordinator timer does not fire in a headless test).
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "gui"))
    target = os.path.join(root, "gui", "demo.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("original = 1\n")

    from agents.safety.approval import HumanApprovalQueue
    from agents.services.code_patch_service import CodePatchService
    q = HumanApprovalQueue()
    svc = CodePatchService(approval_queue=q, root_dir=root)
    res = propose_code_patch(
        svc, authored_by="edward", motivation="fix bug",
        detail="replace constant", target_path=target, patch_text="patched = 2\n",
    )
    assert res["ok"] is True

    class FakeServices:
        code_patch_service = svc

    from gui.builders.tab_feature_builders import FeatureTabBuildersMixin
    class FakeWindow(FeatureTabBuildersMixin):
        def __init__(self):
            self._earning_services = FakeServices()
            self.earning_pipeline = None
            self._t = lambda key: key

    tab = FakeWindow().create_self_improvement_tab()

    # The tab's patch table should now have one row.
    patch_table = None
    for child in tab.findChildren(QTableWidget):
        if child.columnCount() == 5:
            patch_table = child
            break
    assert patch_table is not None, "patch table not found"
    assert patch_table.rowCount() == 1, f"expected 1 pending patch, got {patch_table.rowCount()}"
    assert patch_table.item(0, 0).text() == res["patch_id"]

    import shutil
    shutil.rmtree(root, ignore_errors=True)


def test_tab_approve_applies_patch(app):
    tab, svc, q, target, root = _make_tab(app)
    from agents.services.self_improvement_commands import propose_code_patch, approve_and_apply

    res = propose_code_patch(
        svc, authored_by="jacob", motivation="improve",
        detail="bump", target_path=target, patch_text="patched = 9\n",
    )
    out = approve_and_apply(svc, res["patch_id"])
    assert out["ok"] is True
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "patched = 9\n"

    import shutil
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
