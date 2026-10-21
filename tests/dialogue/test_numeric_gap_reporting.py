"""tests/dialogue/test_numeric_gap_reporting.py — ARCH-ENG-157.

ARCH-ENG-156 wired ``DialogueHonestyService.check_numeric_support`` into every
dialogue turn and proved the wiring non-vacuous with source-level mutation
tests. What it missed is one level up: **the check's finding had no reader.**
The call site discarded the returned gap list, and ``numeric_gap_count`` /
``numeric_gaps()`` had no consumer outside the test suite — so the deterministic
detector ran on every turn, recorded a fabricated dollar figure, and told
nobody. A persona could state an amount it was never shown and the operator's
only signal was a counter that never reached the screen. That is the same
"guard that cannot be seen" defect class ARCH-ENG-156 removed from the check
itself, now present on the *reporting* side.

These tests drive the real ``DialogueTab._on_response_ready`` and assert the
operator is actually told. Per the vacuity lessons (ARCH-ENG-152, 156), the
critical assertions are covered by a source-level mutation test that deletes
the reporting line on disk and must make the real-wiring test FAIL.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from gui.tabs.dialogue_tab import DialogueTab  # noqa: E402
from agents.cognition.dialogue_honesty import DialogueHonestyService  # noqa: E402


class _StubBrain:
    model = "D:/llama.cpp/models/Qwen3.5-4B-UD-Q5_K_XL.gguf"
    base_url = ""


def _tab(context: str = ""):
    """A DialogueTab with ``__init__`` bypassed, driven through the real
    ``_on_response_ready`` so the reporting call site is exercised for real."""
    from unittest.mock import MagicMock, patch

    with patch.object(DialogueTab, "__init__", lambda self, *a, **k: None):
        tab = DialogueTab()
    tab.current_speaker = "Edward Hurst"
    tab.goal = "earn money"
    tab.live_running = False
    tab.is_running = False
    tab.worker = None
    tab.conversation_history = []
    tab._last_request_context = context
    tab._honesty = DialogueHonestyService()
    tab._capture_action_proposal = MagicMock()
    tab._maybe_record_convergence = MagicMock()
    tab._persist_dialogue_turn = MagicMock()
    tab.natural_dialogue = None
    tab._agent_runtime = None
    tab._speaker_for = lambda n: None
    tab._brain_for = lambda n: _StubBrain()
    tab._tier_for_speaker = lambda n: "small"
    tab._schedule_live_continuation = MagicMock()
    tab._auto_steps_left = 0
    tab._text_dup_retry_count = 0
    tab._semantic_retry_count = 0
    tab._live_failure_count = 0
    tab._empty_response_retries = 0
    tab._live_turns_since_evidence = 0
    tab._live_evidence_nudge_limit = 6
    tab._tier_cache = {}
    # The tab renders through chat_display; a MagicMock absorbs _append() and
    # append_system()'s real widget writes while we capture the system lines.
    tab.chat_display = MagicMock()
    # Every system line the tab emits, captured without a live QTextEdit.
    tab.system_lines = []
    tab.append_system = lambda t: tab.system_lines.append(t)
    return tab


# ── The finding reaches the operator ────────────────────────────────────────

def test_fabricated_value_is_reported_to_the_operator():
    tab = _tab("Human: how did the Upwork job go?")
    tab._on_response_ready("I earned $9,999.00 on Upwork today.", "Edward Hurst")

    assert tab._honesty.to_dict()["numeric_gap_count"] == 1, "check still runs"
    assert len(tab.system_lines) == 1, (
        "the finding must reach the operator — this is the defect ARCH-ENG-157 "
        "fixes; before it, the gap was recorded and never displayed")
    line = tab.system_lines[0]
    assert "Edward Hurst" in line, "the notice must name the persona"
    assert "$9,999.00" in line, "the notice must show the unsupported value"
    assert "does not appear in the context" in line


def test_supported_value_is_not_reported():
    tab = _tab("The listing advertises $9,999.00 for this job.")
    tab._on_response_ready("The listing pays $9,999.00.", "Edward Hurst")
    assert tab.system_lines == [], (
        "a value the model was actually shown must not alarm the operator")


def test_no_request_context_records_and_reports_nothing():
    tab = _tab("")
    tab._on_response_ready("I earned $9,999.00.", "Edward Hurst")
    assert tab._honesty.to_dict()["numeric_gap_count"] == 0
    assert tab.system_lines == []


# ── It stays a reporter, never a gate ───────────────────────────────────────

def test_the_report_does_not_block_or_edit_the_turn():
    tab = _tab("Human: anything?")
    tab._on_response_ready("I made $200 and $300 and $400.", "Edward Hurst")
    assert any(
        m.get("speaker") == "Edward Hurst" and "made $200" in m.get("content", "")
        for m in tab.conversation_history), "the turn must land unchanged"
    # ...and the notice is additive, not a replacement.
    assert len(tab.system_lines) == 1


def test_a_display_failure_cannot_cost_the_operator_the_turn():
    """The reporting path must never raise into the turn. append_system can
    fail (widget gone, teardown); the reply is already committed by then."""
    tab = _tab("Human: anything?")

    def _boom(_text):
        raise RuntimeError("display exploded")

    tab.append_system = _boom
    tab._on_response_ready("I made $200 today.", "Edward Hurst")
    assert any("made $200" in m.get("content", "") for m in tab.conversation_history)
    assert tab._honesty.to_dict()["numeric_gap_count"] == 1


def test_wording_is_a_report_not_a_verdict():
    """The notice must never assert the model lied or that a value is false —
    an arithmetically derived number is legitimate. It also must not become
    financial truth: verified revenue comes only from payment evidence."""
    tab = _tab("Human: anything?")
    tab._on_response_ready("I earned $9,999.00.", "Edward Hurst")
    text = tab.system_lines[0].lower()
    # Verdict language that would turn an unsupported value into a proven lie.
    for banned in ("is false", "is fabricated", "has lied", "lied about",
                   "hallucinated", "invented this", "is not real"):
        assert banned not in text, f"the notice asserts a verdict: {banned!r}"
    # The report/gate distinction must be explicit in the right direction.
    assert "reported, not blocked" in text, (
        "the notice must state it does not block the turn")
    assert "verify" in text, "it must ask the operator to verify"


# ── Untrusted text must not reach the GUI unescaped ─────────────────────────

def test_untrusted_values_are_html_escaped():
    tab = _tab("Human: anything?")
    tab._report_numeric_gaps(
        "Edward Hurst", ['$<script>alert(1)</script>', '$9,999.00'])
    assert len(tab.system_lines) == 1
    assert "<script>" not in tab.system_lines[0], (
        "unescaped model text reached the HTML display")
    assert "&lt;script&gt;" in tab.system_lines[0]


def test_report_is_bounded():
    tab = _tab("Human: anything?")
    tab._report_numeric_gaps("Edward Hurst", [f"${i}.00" for i in range(1, 13)])
    assert len(tab.system_lines) == 1
    assert "(+7 more)" in tab.system_lines[0], (
        "a long gap list must not flood the transcript")


def test_empty_gaps_produce_no_notice():
    tab = _tab("Human: anything?")
    tab._report_numeric_gaps("Edward Hurst", [])
    assert tab.system_lines == []


# ── The vacuity probe: deleting the reporting line must fail this suite ──────

def test_reporting_line_deletion_is_caught():
    """Mutation test. ARCH-ENG-156's lesson applied one level up: a test that
    cannot fail proves nothing. Deleting the line that surfaces the finding
    must make ``test_fabricated_value_is_reported_to_the_operator`` fail in a
    fresh interpreter — otherwise this whole file is vacuous.
    """
    import subprocess
    import tempfile

    src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "gui", "tabs", "dialogue_tab.py")

    with open(src, "rb") as fh:
        original = fh.read()

    target = b"                    self._report_numeric_gaps(speaker, numeric_gaps)"
    assert target in original, (
        "the reporting call site moved — update this mutation test's target "
        "string or the mutation is testing nothing")

    mutated = original.replace(target, b"                    pass  # MUTATION: reader removed")

    tmpdir = tempfile.mkdtemp(prefix="arch157_")
    # Run against a copy of the repo so the real file is never touched.
    import shutil
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    work = os.path.join(tmpdir, "repo")
    shutil.copytree(
        repo_root, work,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.db*", "logs",
                                      "NUL", ".venv", "node_modules"))
    work_src = os.path.join(work, "gui", "tabs", "dialogue_tab.py")
    with open(work_src, "wb") as fh:
        fh.write(mutated)

    probe = os.path.join(tmpdir, "probe.py")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write(
            "import os, sys\n"
            "sys.path.insert(0, %r)\n"
            "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
            "from unittest.mock import MagicMock, patch\n"
            "from PySide6.QtWidgets import QApplication\n"
            "_a = QApplication.instance() or QApplication([])\n"
            "from gui.tabs.dialogue_tab import DialogueTab\n"
            "from agents.cognition.dialogue_honesty import DialogueHonestyService\n"
            "with patch.object(DialogueTab, '__init__', lambda s,*a,**k: None):\n"
            "    t = DialogueTab()\n"
            "t.current_speaker='Edward Hurst'; t.goal='earn money'\n"
            "t.live_running=False; t.is_running=False; t.worker=None\n"
            "t.conversation_history=[]; t._last_request_context='Human: how did it go?'\n"
            "t._honesty=DialogueHonestyService()\n"
            "t._capture_action_proposal=MagicMock(); t._maybe_record_convergence=MagicMock()\n"
            "t._persist_dialogue_turn=MagicMock(); t.natural_dialogue=None\n"
            "t._agent_runtime=None; t._speaker_for=lambda n: None\n"
            "t._brain_for=lambda n: type('B',(),{'model':'m','base_url':''})()\n"
            "t._tier_for_speaker=lambda n: 'small'\n"
            "t._schedule_live_continuation=MagicMock()\n"
            "t._auto_steps_left=0; t._text_dup_retry_count=0; t._semantic_retry_count=0\n"
            "t._live_failure_count=0; t._empty_response_retries=0\n"
            "t._live_turns_since_evidence=0; t._live_evidence_nudge_limit=6\n"
            "t._tier_cache={}\n"
            "from unittest.mock import MagicMock\n"
            "t.chat_display=MagicMock()\n"
            "lines=[]\n"
            "t.append_system=lambda x: lines.append(x)\n"
            "t._on_response_ready('I earned $9,999.00 on Upwork today.','Edward Hurst')\n"
            "assert lines, 'the operator was never told'\n" % work)

    proc = subprocess.run([sys.executable, probe], capture_output=True, text=True,
                          timeout=300)

    # The mutated repo must FAIL the assertion — that is what proves the
    # unmutated test can fail.
    assert proc.returncode != 0, (
        "VACUOUS GUARD: deleting the reporting line did NOT fail the probe. "
        "The test cannot detect its own regression.\n" + proc.stdout + proc.stderr)
    assert "the operator was never told" in (proc.stderr + proc.stdout), (
        "the probe failed for an unrelated reason, not the missing reader:\n"
        + proc.stderr[-1500:])

    # The real file must be byte-identical afterwards.
    with open(src, "rb") as fh:
        assert fh.read() == original, (
            "the mutation test damaged the source file")
