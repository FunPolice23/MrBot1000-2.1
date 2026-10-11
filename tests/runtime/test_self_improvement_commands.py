"""Regression tests for self_improvement_commands (approval-gated patch actions)."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agents.core.feature_flags import feature_enabled  # noqa: E402


@pytest.fixture(autouse=True)
def _enable_feature(monkeypatch):
    """Self-improvement is fail-closed; enable it for the happy-path tests.
    Tests that assert the disabled behavior set the flag themselves."""
    monkeypatch.setenv("MRBOT_ENABLE_SELF_IMPROVEMENT", "true")


@pytest.fixture()
def service():
    from agents.safety.approval import HumanApprovalQueue
    from agents.services.code_patch_service import CodePatchService

    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "gui"))
    q = HumanApprovalQueue()
    svc = CodePatchService(approval_queue=q, root_dir=root)
    yield svc, q, root
    import shutil
    shutil.rmtree(root, ignore_errors=True)


def _write_target(root, name="demo.py", content="original = 1\n"):
    target = os.path.join(root, "gui", name)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return target


def test_propose_enqueues_and_applies_nothing(service):
    from agents.services.self_improvement_commands import propose_code_patch
    svc, q, root = service
    target = _write_target(root)

    res = propose_code_patch(
        svc, authored_by="edward", motivation="fix bug",
        detail="replace constant", target_path=target, patch_text="patched = 2\n",
    )
    assert res["ok"] is True
    assert res["status"] == "pending_approval"
    assert q.pending_count() == 1
    # Nothing applied yet.
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "original = 1\n"


def test_approve_and_apply_patches_file(service):
    from agents.services.self_improvement_commands import propose_code_patch, approve_and_apply
    svc, q, root = service
    target = _write_target(root)

    res = propose_code_patch(
        svc, authored_by="jacob", motivation="improve",
        detail="bump value", target_path=target, patch_text="patched = 9\n",
    )
    patch_id = res["patch_id"]

    out = approve_and_apply(svc, patch_id)
    assert out["ok"] is True
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "patched = 9\n"


def test_approve_and_apply_bad_patch_rolls_back(service):
    from agents.services.self_improvement_commands import propose_code_patch, approve_and_apply
    svc, q, root = service
    target = _write_target(root)

    res = propose_code_patch(
        svc, authored_by="edward", motivation="test",
        detail="broken", target_path=target, patch_text="def broken(:\n",
    )
    out = approve_and_apply(svc, res["patch_id"])
    assert out["ok"] is False
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "original = 1\n"


def test_decline_never_applies(service):
    from agents.services.self_improvement_commands import propose_code_patch, decline_patch
    svc, q, root = service
    target = _write_target(root)

    res = propose_code_patch(
        svc, authored_by="edward", motivation="test",
        detail="no", target_path=target, patch_text="patched = 2\n",
    )
    out = decline_patch(svc, res["patch_id"])
    assert out["ok"] is True
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "original = 1\n"


def test_propose_blocked_when_feature_disabled(service, monkeypatch):
    from agents.services.self_improvement_commands import propose_code_patch
    svc, q, root = service
    target = _write_target(root)

    monkeypatch.setenv("MRBOT_ENABLE_SELF_IMPROVEMENT", "false")
    res = propose_code_patch(
        svc, authored_by="edward", motivation="test",
        detail="x", target_path=target, patch_text="patched = 2\n",
    )
    assert res["ok"] is False
    assert res["status"] == "blocked"
    assert q.pending_count() == 0
    with open(target, "r", encoding="utf-8") as f:
        assert f.read() == "original = 1\n"


def test_propose_rejects_path_escape(service):
    from agents.services.self_improvement_commands import propose_code_patch
    svc, q, root = service
    outside = os.path.join(os.path.dirname(root), "evil.py")

    res = propose_code_patch(
        svc, authored_by="edward", motivation="test",
        detail="escape", target_path=outside, patch_text="x = 1\n",
    )
    assert res["ok"] is False
    assert res["status"] == "rejected"
    assert q.pending_count() == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
