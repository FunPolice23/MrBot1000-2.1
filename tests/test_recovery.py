from agents.recovery import RecoveryTracker


def test_recovery_requires_state_change_or_new_evidence():
    tracker = RecoveryTracker(max_attempts=3)
    assert tracker.attempt("blocked", [])
    assert not tracker.attempt("blocked", [])
    assert tracker.attempt("blocked", ["ev-new"])
    assert tracker.attempt("different-state", [])
    assert tracker.exhausted
    assert not tracker.attempt("another-state", ["ev-last"])