"""Task 10 — post-apply monitoring / self-healing.

After an approved patch applies and verifies, the service records the outcome
(verified_at + status). A later monitor re-verifies applied patches; if one has
regressed (e.g. its file no longer compiles), it emits a NEW human-gated
proposal referencing the original — it never auto-reverses the change without
approval.
"""
from __future__ import annotations

import os

import pytest

from agents.services.code_patch_service import CodePatch, CodePatchService
from agents.safety.approval import HumanApprovalQueue


@pytest.fixture
def svc(tmp_path):
    q = HumanApprovalQueue()
    service = CodePatchService(approval_queue=q, root_dir=str(tmp_path))
    os.makedirs(os.path.join(str(tmp_path), "gui"), exist_ok=True)
    target = os.path.join(str(tmp_path), "gui", "unit.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("VALUE = 1\n")
    return service, q, target


def _good_patch(target, value=2):
    return CodePatch(
        target_path=target, authored_by="edward",
        motivation="bump constant", detail="raise VALUE",
        patch_text=f"VALUE = {value}\n",
    )


def test_apply_records_verified_outcome(svc):
    """A successful apply must record verified_at + status in the ledger."""
    service, q, target = svc
    patch = _good_patch(target)
    service.propose(patch)
    q.approve(patch.patch_id)
    res = service.apply_approved(patch, approval_id=patch.patch_id)
    assert res["ok"] is True

    recs = service.applied_patches()
    assert len(recs) == 1
    rec = recs[0]
    assert rec["patch_id"] == patch.patch_id
    assert rec["target_path"] == target
    assert rec["status"] == "verified"
    assert rec["verified_at"] > 0
    assert os.path.exists(rec["backup_path"])


def test_monitor_no_regression_emits_nothing(svc):
    """If the applied patch file still verifies, monitor returns [] and status stays verified."""
    service, q, target = svc
    patch = _good_patch(target)
    service.propose(patch)
    q.approve(patch.patch_id)
    service.apply_approved(patch, approval_id=patch.patch_id)

    proposals = service.monitor_applied()
    assert proposals == []
    assert service.applied_patches()[0]["status"] == "verified"


def test_monitor_flags_regression_and_proposes_but_does_not_reverse(svc):
    """If the target later stops compiling, monitor emits a new gated proposal
    referencing the original and NEVER touches the file itself."""
    service, q, target = svc
    patch = _good_patch(target)
    service.propose(patch)
    q.approve(patch.patch_id)
    service.apply_approved(patch, approval_id=patch.patch_id)
    assert open(target).read().strip() == "VALUE = 2"

    # Simulate a later regression: the file becomes invalid.
    with open(target, "w", encoding="utf-8") as f:
        f.write("def broken(:\n")
    before_mtime = os.path.getmtime(target)

    proposals = service.monitor_applied()
    assert len(proposals) == 1
    new = proposals[0]
    # New proposal references the original patch id.
    assert patch.patch_id in new.motivation or patch.patch_id in new.detail
    # It is human-gated in the queue (pending), NOT applied automatically.
    assert service.applied_patches()[0]["status"] == "regressed"
    assert service._is_approved(new.patch_id) is False
    # The file was NOT modified by the monitor (no auto-reverse).
    assert os.path.getmtime(target) == before_mtime
    assert open(target).read() == "def broken(:\n"


def test_monitor_proposal_reverts_to_backup_on_approval(svc):
    """The self-heal proposal's patch_text reverts to the original backup, so a
    human approving it cleanly restores the last-known-good content."""
    service, q, target = svc
    patch = _good_patch(target)
    service.propose(patch)
    q.approve(patch.patch_id)
    service.apply_approved(patch, approval_id=patch.patch_id)
    backup = service.applied_patches()[0]["backup_path"]
    orig = open(backup, encoding="utf-8").read()

    with open(target, "w", encoding="utf-8") as f:
        f.write("def broken(:\n")
    proposals = service.monitor_applied()
    assert len(proposals) == 1
    assert proposals[0].patch_text == orig

    # Approving the new proposal reverts to the backup content.
    q.approve(proposals[0].patch_id)
    res = service.apply_approved(proposals[0], approval_id=proposals[0].patch_id)
    assert res["ok"] is True
    assert open(target).read() == orig
