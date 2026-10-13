"""Regression tests for malformed local-model Dialogue output."""

import unittest
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gui.tabs.dialogue_tab import DialogueTab, DialogueWorker, LIFECYCLE
from agents.cognition.personas import DRIVER, NAVIGATOR, persona_for_key
from agents.safety.calling import (
    chat_with_tools,
    _remove_reasoning_channels,
    _visible_response_content,
)
from agents.runtime.dual_brain import BrainConfig, BrainRole
from agents.providers.openai_compatible import resolve_chat_protocol
from agents.cognition.reasoning_modes import ReasoningMode, select_reasoning_mode


class TestDialogueResponseCorruption(unittest.TestCase):
    def test_glued_thinking_marker_is_stripped(self):
        """LFM2.5 emits a bare ' thinking' marker glued to the reply
        (' thinkingThe user...'). It must be stripped so the reasoning block is
        not shown as the persona's reply."""
        glued = (' thinkingThe user is asking for the "safest first step to '
                 'earn money online" in a single sentence.')
        cleaned = DialogueTab._clean_model_response(glued)
        self.assertFalse(cleaned.startswith("thinking"),
                         f"thinking marker not stripped: {cleaned!r}")
        self.assertTrue(cleaned.startswith("The user"),
                        f"reply text lost after strip: {cleaned!r}")

    def test_normal_reply_is_untouched(self):
        """A legitimate reply must not be mangled by the thinking-strip."""
        reply = "I recommend starting with freelance work."
        self.assertEqual(DialogueTab._clean_model_response(reply), reply)

    def test_corrupted_payload_is_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        binary_payload = "1" * 400 + "0" * 400 + "_" * 50
        repeated_meta = " ".join(
            ["The question asks about a policy outcome."] * 20
        )

        self.assertTrue(worker._is_bad_dialogue_response(binary_payload))
        self.assertTrue(worker._is_bad_dialogue_response(repeated_meta))
        self.assertFalse(worker._is_bad_dialogue_response(
            "I recommend one concrete next step and one risk check."
        ))

    def test_reasoning_about_prompt_loop_is_rejected(self):
        """A model stuck re-verifying its own reply against the phase contract
        ('I will output it. Wait, the prompt says...') degenerates into a loop
        that varies a trailing clause each cycle. It must be rejected."""
        worker = DialogueWorker.__new__(DialogueWorker)
        loop = (
            "I will output it. Wait, the prompt says \"Do not drift into "
            "unrelated topics.\" My response is focused. I will output it. "
            "One minor adjustment. I will output it. Wait, the prompt says "
            "\"Reply as a person speaking.\" My response has 4 sentences. "
            "It fits perfectly. I will output it. One minor adjustment. "
            "Final check of the prompt. It fits perfectly. I will output it. "
            "Wait, the prompt says \"Do not invent sources.\" I am not "
            "inventing anything. I will output it."
        )
        self.assertTrue(worker._is_bad_dialogue_response(loop))

    def test_normal_first_person_reply_not_flagged_as_loop(self):
        """A clean multi-sentence persona reply must NOT be mistaken for a loop
        by the strengthened repetition detector."""
        worker = DialogueWorker.__new__(DialogueWorker)
        clean = (
            "I will check the bug fix gig on uGig to see the specific Python "
            "code. Once I have the code, I will outline a plan to fix the bug "
            "and write tests. I need your approval to start the fix and submit "
            "the solution. This is the highest value option available right now."
        )
        self.assertFalse(worker._is_bad_dialogue_response(clean))

    def test_training_continuations_and_code_are_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        self.assertTrue(worker._is_bad_dialogue_response(
            "```python\nimport torch\nimport torch.nn as nn\ndef create_model():\n"
            "    return nn.Sequential(nn.Linear(4, 2), nn.ReLU())\n```"
        ))
        self.assertTrue(worker._is_bad_dialogue_response(
            "Gemma I'm learning about different cultures. " * 5
        ))
        self.assertTrue(worker._is_bad_dialogue_response(
            "Prompt: Describe a scene from your life. Response: Okay, here's a scene."
        ))

    def test_account_creation_cannot_be_declared_approved_by_research(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        self.assertTrue(worker._is_bad_dialogue_response(
            "The registration fields are only name and email, so I will create "
            "the account. No further approvals are needed."
        ))
        self.assertFalse(worker._is_bad_dialogue_response(
            "The registration fields are only name and email. Account creation "
            "is blocked pending explicit human approval."
        ))

    def test_tiny_model_identity_and_failed_research_fallbacks_are_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        self.assertTrue(worker._is_bad_dialogue_response(
            "The model is Gemma. I am an open-weights model with no internet access."
        ))
        self.assertTrue(worker._is_bad_dialogue_response(
            "I got a 403 Forbidden error, so I will rely on my existing knowledge "
            "and provide a generic guide based on typical freelance practices."
        ))

    def test_tiny_model_gets_safe_progress_response_after_failed_retries(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.max_tokens = 128
        fallback = worker._safe_fallback_response()
        self.assertTrue(fallback.startswith("BLOCKED:"))
        self.assertIn("No registration", fallback)
        self.assertNotIn("malformed or non-conversational", fallback)

    def test_tiny_fallback_responds_to_current_phase(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.max_tokens = 128
        worker.context = "CURRENT PHASE: discover\nPHASE INSTRUCTION: approve or block."
        fallback = worker._safe_fallback_response()
        self.assertIn("identity-document list is too broad", fallback)
        self.assertIn("jurisdiction", fallback)
        self.assertIn("BLOCKED:", fallback)

    def test_worker_forwards_streaming_dialogue_contract(self):
        calls = []

        class StreamingBrain:
            model = "served-model"

            def chat(self, *args, **kwargs):
                calls.append(kwargs)
                kwargs["stream_progress"]("partial response")
                return "A complete response."

        worker = DialogueWorker(
            StreamingBrain(), "current context", [], "Edward Hurst",
            max_retries=0,
        )
        events = []
        worker.progress.connect(lambda speaker, text, running:
                               events.append((speaker, text, running)))
        worker.run()

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["dialogue_mode"])
        self.assertEqual(calls[0]["max_tokens"], worker.max_tokens)
        self.assertTrue(callable(calls[0]["stream_progress"]))
        self.assertIn(("Edward Hurst", "partial response", True), events)
        self.assertIn(("Edward Hurst", "A complete response.", False), events)

    def test_worker_bootstraps_loaded_model_when_adapter_is_unselected(self):
        calls = []

        class UnselectedBrain:
            model = ""

            def _get_first_available_model(self):
                return "loaded-server-model"

            def chat(self, *args, **kwargs):
                calls.append(self.model)
                return "A complete response."

        worker = DialogueWorker(
            UnselectedBrain(), "current context", [], "Edward Hurst",
            max_retries=0,
        )
        worker.run()

        self.assertEqual(calls, ["loaded-server-model"])

    def test_truncated_inline_reasoning_gets_larger_recovery_budget(self):
        calls = []

        class ReasoningBrain:
            model = "qwen3-35b"

            def chat(self, *args, **kwargs):
                calls.append(kwargs.copy())
                kwargs["stream_progress"]("partial")
                if len(calls) == 1:
                    return "<think>still reasoning without a final answer"
                return "\nHello there."

        # Pin the turn budget so the assertion does not depend on the operator's
        # .env (v2.1.51's thinking headroom already pushes a reasoning brain's
        # base budget to >= 2048, which made the old `max(base, 2048)` recovery
        # a no-op — ARCH-ENG-056).
        env = {"DIALOGUE_AUTO_TOKENS": "false",
               "DIALOGUE_MAX_TOKENS_BIG": "1024",
               "DIALOGUE_MAX_TOKENS_SMALL": "512"}
        with patch.dict(os.environ, env):
            os.environ.pop("DIALOGUE_MAX_TOKENS", None)
            os.environ.pop("DIALOGUE_THINK_TOKENS", None)
            os.environ.pop("DIALOGUE_THINK_TOKENS_BIG", None)
            os.environ.pop("DIALOGUE_ENABLE_THINKING", None)
            worker = DialogueWorker(
                ReasoningBrain(), "current context", [], "Edward Hurst",
                max_retries=1,
            )
            worker.run()

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["max_tokens"], worker.max_tokens)
        # The recovery turn MUST be strictly larger than the turn that just
        # failed, otherwise the retry repeats the same truncation.
        self.assertGreater(calls[1]["max_tokens"], calls[0]["max_tokens"])
        # +2048 over the base turn (the old code returned base unchanged).
        self.assertEqual(calls[1]["max_tokens"],
                         calls[0]["max_tokens"] + 2048)

    def test_malformed_fallback_is_not_added_as_persona_turn(self):
        tab = DialogueTab.__new__(DialogueTab)
        tab._generation_id = 1
        tab.conversation_history = []
        tab.worker = object()
        tab.live_running = False
        tab.is_running = False
        tab.append_system = Mock()

        tab._on_response_ready(
            "[Dialogue model returned malformed or non-conversational output "
            "after retries. Check the loaded model and chat template before continuing.]",
            "Edward Hurst",
            1,
        )

        self.assertEqual(tab.conversation_history, [])
        self.assertIsNone(tab.worker)
        tab.append_system.assert_called_once()
        self.assertIn("could not produce a conversational response", 
                      tab.append_system.call_args.args[0])

    @patch("gui.tabs.dialogue_tab.QTimer.singleShot")
    def test_empty_response_retries_same_speaker_without_transcript_turn(self, single_shot):
        tab = DialogueTab.__new__(DialogueTab)
        tab._generation_id = 1
        tab.conversation_history = []
        tab.worker = object()
        tab.live_running = False
        tab.is_running = False
        tab.append_system = Mock()
        tab.respond = Mock()

        tab._on_response_ready("(empty)", "Edward Hurst", 1)

        self.assertEqual(tab.conversation_history, [])
        self.assertIsNone(tab.worker)
        self.assertEqual(tab._empty_response_retries, 1)
        single_shot.assert_called_once_with(250, tab.respond)
        self.assertIn("retrying the same turn", tab.append_system.call_args.args[0])

    def test_repeated_empty_response_retries_without_fake_persona_turn(self):
        tab = DialogueTab.__new__(DialogueTab)
        tab._generation_id = 1
        tab.conversation_history = []
        tab.worker = object()
        tab.live_running = True
        tab.is_running = False
        tab._empty_response_retries = 1
        tab.append_system = Mock()
        tab._live_failure_count = 0

        tab._on_response_ready("", "Edward Hurst", 1)

        self.assertEqual(tab.conversation_history[-1]["speaker"], "System")
        self.assertIsNone(tab.worker)
        self.assertEqual(tab._empty_response_retries, 2)
        self.assertIn("retrying with a recovery prompt", tab.append_system.call_args.args[0])

    @patch("gui.tabs.dialogue_tab.QTimer.singleShot")
    def test_live_never_stops_on_repeated_empty_response(self, single_shot):
        tab = DialogueTab.__new__(DialogueTab)
        tab._generation_id = 1
        tab.conversation_history = []
        tab.worker = object()
        tab.live_running = True
        tab.is_running = False
        tab._empty_response_retries = 3
        tab.append_system = Mock()
        tab.respond = Mock()

        tab._on_response_ready("", "Edward Hurst", 1)

        self.assertTrue(tab.live_running)
        self.assertEqual(tab.conversation_history[-1]["speaker"], "System")
        single_shot.assert_called_once()

    def _make_accept_stub(self):
        """DialogueTab stub with the attributes the accepted-turn path needs."""
        from types import SimpleNamespace
        tab = DialogueTab.__new__(DialogueTab)
        tab._generation_id = 1
        tab.conversation_history = []
        tab.worker = object()
        tab.live_running = False
        tab.is_running = False
        tab._empty_response_retries = 0
        tab._text_dup_retry_count = 0
        tab._semantic_retry_count = 0
        tab._live_failure_count = 0
        tab.current_speaker = "Edward Hurst"
        tab.natural_dialogue = None
        tab._agent_runtime = None
        tab._honesty = None
        tab._tier_cache = {}
        tab._auto_steps_left = 0
        tab.auto_btn = Mock()
        tab.big_brain = SimpleNamespace(model="qwen3.6-14b-a3b")
        tab.small_brain = SimpleNamespace(model="qwen3.6-14b-a3b")
        tab._append = Mock()
        tab._persist_dialogue_turn = Mock()
        tab.append_system = Mock()
        tab.respond = Mock()
        return tab

    def test_valid_response_is_accepted_not_discarded_or_retried(self):
        """A valid non-empty persona reply must reach the accept path — never
        be misclassified as empty (retried) nor replaced by a placeholder."""
        tab = self._make_accept_stub()
        tab._on_response_ready("I recommend starting with freelance work.",
                              "Edward Hurst", 1)
        # Accepted under the real text, not a "[... No response generated ...]"
        # placeholder.
        self.assertTrue(any(
            m.get("role") == "assistant" and m.get("content") ==
            "I recommend starting with freelance work."
            for m in tab.conversation_history))
        # The empty-retry message must not fire for a valid reply.
        self.assertNotIn(
            "could not produce a conversational response",
            tab.append_system.call_args.args[0] if tab.append_system.call_args else "",
        )
        # It must not be scheduled for a retry.
        tab.respond.assert_not_called()

    @patch("gui.tabs.dialogue_tab.QTimer.singleShot")
    def test_two_empties_then_valid_response_resets_budget(self, single_shot):
        """After the empty-retry budget is exhausted, an accepted valid turn
        resets _empty_response_retries to 0 so a later transient blank still
        gets its silent first retry."""
        tab = self._make_accept_stub()
        tab._empty_response_retries = 5  # budget exhausted state
        tab._on_response_ready("Here is my decision.", "Edward Hurst", 1)
        self.assertEqual(tab._empty_response_retries, 0)

    def test_valid_response_clears_placeholder_path(self):
        """A non-empty reply must not have `response` overwritten by the
        '[No response generated ...]' fallback literal."""
        tab = self._make_accept_stub()
        tab._on_response_ready("Let's commit to the Upwork approach.",
                              "Jacob Stanley", 1)
        self.assertTrue(any(
            m.get("role") == "assistant" and m.get("content") ==
            "Let's commit to the Upwork approach."
            for m in tab.conversation_history))
        self.assertFalse(any(
            m.get("content", "").startswith("[Jacob Stanley: No response generated")
            for m in tab.conversation_history))

    def test_still_empty_when_worker_marker_used(self):
        """The worker's '(empty)' marker must still count as an empty reply."""
        tab = self._make_accept_stub()
        tab._on_response_ready("(empty)", "Edward Hurst", 1)
        # Empty path: retried, not accepted as a persona turn; budget incremented.
        self.assertEqual(tab._empty_response_retries, 1)
        self.assertFalse(any(
            m.get("role") == "assistant" for m in tab.conversation_history))

    @patch("gui.tabs.dialogue_tab.QTimer.singleShot")
    def test_repeated_empty_still_gets_recovery_prompt(self, single_shot):
        """Truly empty replies must keep the recovery behavior unchanged (only
        when a session is active)."""
        tab = self._make_accept_stub()
        tab.live_running = True  # recovery path is only for active sessions
        tab._empty_response_retries = 1
        tab._on_response_ready("", "Edward Hurst", 1)
        self.assertEqual(tab._empty_response_retries, 2)
        self.assertEqual(tab.conversation_history[-1]["speaker"], "System")
        self.assertIn("retrying with a recovery prompt",
                      tab.append_system.call_args.args[0])

    def test_idle_empty_falls_back_to_placeholder(self):
        """When no session is active, an exhausted empty reply falls back to
        the bracketed '[No response generated]' placeholder persona turn."""
        tab = self._make_accept_stub()  # live_running=False, is_running=False
        tab._empty_response_retries = 3
        tab._on_response_ready("", "Edward Hurst", 1)
        self.assertTrue(any(
            m.get("role") == "assistant"
            and m.get("content", "").startswith("[Edward Hurst: No response generated")
            for m in tab.conversation_history))

    @patch("gui.tabs.dialogue_tab.QTimer.singleShot")
    def test_live_retries_malformed_fallback_without_stopping(self, single_shot):
        tab = DialogueTab.__new__(DialogueTab)
        tab._generation_id = 1
        tab.conversation_history = []
        tab.worker = object()
        tab.live_running = True
        tab.is_running = False
        tab.append_system = Mock()
        tab.respond = Mock()

        tab._on_response_ready(
            "[Dialogue model returned malformed or non-conversational output "
            "after retries. Check the loaded model and chat template before continuing.]",
            "Edward Hurst",
            1,
        )

        self.assertTrue(tab.live_running)
        self.assertEqual(tab.conversation_history[-1]["speaker"], "System")
        single_shot.assert_called_once()
        assert single_shot.call_args.args[0] == 250

    def test_non_progress_and_unrequested_image_continuations_are_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.context = "CURRENT PHASE: discover\nPHASE INSTRUCTION: approve or block."
        self.assertTrue(worker._is_bad_dialogue_response(
            "I'm ready to help Jacob and the human user move forward with the current phase. "
            "I'll rely on the read-only tools that are available."
        ))
        self.assertTrue(worker._is_bad_dialogue_response(
            "The image you sent is a depiction of a detailed surreal portrait."
        ))

    def test_pseudo_tool_requests_and_unverified_external_claims_are_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        self.assertTrue(worker._is_bad_dialogue_response(
            "ACTION: CALL TOOL | PLATFORM: Freelancer.com Tool request: "
            '{"query": {"endpoint": "/api/v1/payouts"}}'
        ))
        self.assertTrue(worker._is_bad_dialogue_response(
            "The platform has confirmed visibility and I've submitted your profile."
        ))
        self.assertFalse(worker._is_bad_dialogue_response(
            "I cannot verify the platform rules from the available evidence; BLOCKED."
        ))

    def test_narrated_tool_calls_and_unreturned_evidence_are_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        self.assertTrue(worker._is_bad_dialogue_response(
            "ACTION: CALL `web_read` to fetch the official policy page."
        ))
        self.assertTrue(worker._is_bad_dialogue_response(
            "The returned evidence confirms the platform enforces this $500K cap."
        ))

    def test_bare_tool_name_response_is_stripped_and_rejected(self):
        """A local model emitting a BARE tool name as its whole turn (or a
        trailing token) leaks tool syntax into the persona bubble. The visible
        text must have the tool name stripped, and an all-tool-syntax turn must
        be rejected so the retry path re-prompts for a real answer."""
        from agents.safety.response import _remove_tool_syntax
        self.assertEqual(_remove_tool_syntax("web_search"), "")
        self.assertEqual(_remove_tool_syntax("web_read"), "")
        self.assertEqual(
            _remove_tool_syntax(
                "Hold on. I need to verify the deposit requirements. web_read"),
            "Hold on. I need to verify the deposit requirements.")
        self.assertIn(
            "web_search to find the deposit contract",
            _remove_tool_syntax(
                "I will use web_search to find the deposit contract, then read it."))
        worker = DialogueWorker.__new__(DialogueWorker)
        self.assertTrue(worker._is_bad_dialogue_response("web_search"))
        self.assertTrue(worker._is_bad_dialogue_response("web_read"))
        self.assertFalse(worker._is_bad_dialogue_response(
            "I will use web_search to find the deposit contract, then read it."))

    def test_empty_bracket_and_narrated_read_intent_are_rejected(self):
        """Local models emit a tool call with empty/no args as `web_read[]` /
        `web_read()` / a dangling `[]`, and narrate read intent without ever
        calling the tool ('I'll read the page...[]'). Both must be stripped from
        the visible text and, when the whole turn is intent-without-evidence,
        rejected so the retry path forces a real answer or a real tool call."""
        from agents.safety.response import _remove_tool_syntax
        self.assertEqual(_remove_tool_syntax("web_read[]"), "")
        self.assertEqual(_remove_tool_syntax("web_read()"), "")
        self.assertEqual(_remove_tool_syntax("proceeding.[]"), "proceeding.")
        self.assertEqual(
            _remove_tool_syntax(
                "Let me read the uGig opportunity page directly. web_read[]"),
            "Let me read the uGig opportunity page directly.")
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.history = []
        for leak in (
            "I'll read the opportunity page to get the actual details before proceeding.[]",
            "Let me read the uGig opportunity page directly.[]",
            "Let me try reading the page one more time using the web_read tool "
            "as instructed. This is my only read-only tool call for this phase.[]",
            "I will read the actual opportunity page to get the real details "
            "before proceeding.[]",
            "I need verified evidence. Let me read one of the accessible GitHub "
            "bounty pages to evaluate its legitimacy. []",
        ):
            self.assertTrue(worker._is_bad_dialogue_response(leak), leak)
        for good in (
            "I read the uGig page and found it requires a wallet connection. "
            "The code review pays $80.",
            "The page is blocked with HTTP 402, so I cannot verify the "
            "requirements. We should pivot to the GitHub bounty.",
            "I used the web_read tool and the page returned HTTP 402, so I "
            "could not get the details.",
        ):
            self.assertFalse(worker._is_bad_dialogue_response(good), good)

    def test_promised_external_completion_without_tool_result_is_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        self.assertTrue(worker._is_bad_dialogue_response(
            "The returned evidence confirms the platform enforces this $500K cap."
        ))

    def test_bare_tool_name_in_leak_positions_is_stripped(self):
        """A bare tool name in an unambiguous leak position — colon/comma
        suffixed, several in a row, or right after sentence-ending punctuation —
        must be stripped from the visible text, while legitimate prose that
        mentions a tool (object of 'use', or 'the <tool> tool') is preserved."""
        from agents.safety.response import _remove_tool_syntax
        # Unambiguous leak positions -> stripped.
        self.assertEqual(_remove_tool_syntax("web_read:"), "")
        self.assertEqual(_remove_tool_syntax("web_search web_read web_check"), "")
        self.assertEqual(
            _remove_tool_syntax("proceeding. web_read"), "proceeding.")
        self.assertEqual(_remove_tool_syntax("web_read"), "")
        # The separator that belonged to the stripped token must go too, not
        # just the name. Stripping only the name left a dangling ',' / ':' at
        # the head of the visible bubble.
        self.assertEqual(
            _remove_tool_syntax("web_read, then I will assess the payout."),
            "then I will assess the payout.")
        self.assertEqual(
            _remove_tool_syntax("I need data. web_read, then I will assess."),
            "I need data. then I will assess.")
        self.assertEqual(_remove_tool_syntax("web_read: rest of the answer"),
                         "rest of the answer")
        self.assertEqual(_remove_tool_syntax("web_search, web_read, web_check"), "")
        # Legitimate prose mentioning a tool -> preserved.
        self.assertEqual(
            _remove_tool_syntax(
                "I will use web_search to find the deposit contract."),
            "I will use web_search to find the deposit contract.")
        self.assertEqual(
            _remove_tool_syntax(
                "The web_read tool returned an HTTP 402 error."),
            "The web_read tool returned an HTTP 402 error.")
        self.assertEqual(
            _remove_tool_syntax(
                "I used the web_search tool and found the page."),
            "I used the web_search tool and found the page.")

    def test_bare_tool_name_with_url_is_parsed_as_a_call(self):
        """A compact model that emits a BARE tool name followed by the URL/query
        (same or next line) must still be parsed as a real tool call so it
        executes instead of leaking as prose. Narrated intent with no URL must
        NOT parse (it is rejected upstream as a failed turn)."""
        from agents.safety.calling import _parse_tool_call_from_text
        self.assertEqual(
            _parse_tool_call_from_text(
                "I will read the page.\nweb_read\nhttps://ugig.net/gigs/fd151b68"),
            ("web_read", {"url": "https://ugig.net/gigs/fd151b68"}))
        self.assertEqual(
            _parse_tool_call_from_text("web_read https://ugig.net/"),
            ("web_read", {"url": "https://ugig.net/"}))
        self.assertEqual(
            _parse_tool_call_from_text(
                "Let me search.\nweb_search\nuGig bug fix bounty requirements"),
            ("web_search", {"query": "uGig bug fix bounty requirements"}))
        for leak in (
            "I'll read the opportunity page before proceeding.[]",
            "Let me read the uGig opportunity page directly.[]",
            "I will read the actual opportunity page to get the real details.",
            "web_read",
            "web_read[]",
        ):
            self.assertIsNone(_parse_tool_call_from_text(leak), leak)

    def test_failed_full_model_retry_returns_safe_transcript_response(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.context = "CURRENT PHASE: discover\nPHASE INSTRUCTION: approve or block."
        worker.max_tokens = 768
        fallback = worker._safe_fallback_response()
        self.assertTrue(fallback.startswith("BLOCKED:"))
        self.assertNotIn("Check the loaded model", fallback)

    def test_repeated_tool_intent_across_personas_is_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.history = [
            {"role": "assistant", "content": "I will review the returned policy."},
            {"role": "assistant", "content": "I will fetch the official policy."},
        ]
        self.assertTrue(worker._is_bad_dialogue_response(
            "I'll call one read-only tool now to fetch the official policy."
        ))

    def test_text_tool_calls_execute_with_single_dialogue_iteration(self):
        first = Mock(
            content='I will check this: web_search("Freelancer.com payout fees")',
            tool_calls=None,
        )
        final = Mock(content="The search returned no verified result.", tool_calls=None)
        client = Mock()
        client.chat.completions.create.side_effect = [
            Mock(choices=[Mock(message=first)]),
            Mock(choices=[Mock(message=final)]),
        ]
        with patch("agents.safety.calling.execute_tool", return_value="[no result]") as execute:
            result = chat_with_tools(
                client=client,
                model="ministral-3b",
                system_prompt="Persona",
                user_message="Verify the payout terms.",
                max_tokens=128,
                max_iterations=1,
                use_function_calling=False,
            )
        execute.assert_called_once_with(
            "web_search", {"query": "Freelancer.com payout fees"})
        self.assertEqual(result, "The search returned no verified result.")

    def test_registration_research_never_grants_account_approval(self):
        self.assertIn(
            "Registration is always an external commitment",
            LIFECYCLE[1][2],
        )
        self.assertIn(
            "creating or using an account always requires explicit human approval",
            LIFECYCLE[3][2],
        )

    def test_gemma_model_size_and_prompt_tier(self):
        tab = DialogueTab.__new__(DialogueTab)

        self.assertEqual(tab._estimate_model_size(
            "gemma 4 12b it qat q4"), 12)
        self.assertEqual(tab._estimate_model_size(
            "gemma 4 e4b q4"), 4)

        prompt = tab._model_output_contract("gemma 4 12b it qat q4")
        self.assertIn("Capability tier: full", prompt)
        self.assertIn(
            "COMPACT MODEL RESPONSE CONTRACT",
            tab._model_output_contract("granite-8b-instruct"),
        )

    def test_persona_prompts_have_distinct_parameter_tiers(self):
        persona = persona_for_key("Jacob Stanley")
        tiny = persona.build_system_prompt(goal="Choose one action", tier="tiny")
        compact = persona.build_system_prompt(goal="Choose one action", tier="compact")
        full = persona.build_system_prompt(goal="Choose one action", tier="full")
        self.assertIn("Answer only the current phase in 1-3 short sentences", tiny)
        self.assertIn("Follow the current phase instruction", compact)
        self.assertIn("# RESPONSE PROCESS", full)
        self.assertNotIn("# MEMORY", tiny)

    def test_persona_names_default_when_custom_settings_are_blank(self):
        with patch.dict(os.environ, {
            "BIG_BRAIN_NAME": "   ",
            "SMALL_BRAIN_NAME": "",
        }, clear=False):
            self.assertEqual(DRIVER.current_name, "Edward Hurst")
            self.assertEqual(NAVIGATOR.current_name, "Jacob Stanley")

    def test_persona_names_use_nonblank_custom_settings(self):
        with patch.dict(os.environ, {
            "BIG_BRAIN_NAME": "E. Hurst",
            "SMALL_BRAIN_NAME": "J. Stanley",
        }, clear=False):
            self.assertEqual(DRIVER.current_name, "E. Hurst")
            self.assertEqual(NAVIGATOR.current_name, "J. Stanley")

    def test_dialogue_capability_gate_rejects_tiny_and_base_models(self):
        tab = DialogueTab.__new__(DialogueTab)
        blocked, reason = tab._dialogue_model_blocked("granite-1b-tiny")
        self.assertTrue(blocked)
        self.assertIn("below 2B", reason)
        blocked, reason = tab._dialogue_model_blocked("mistralai/ministral-3-3b")
        self.assertFalse(blocked)
        self.assertEqual(reason, "")
        blocked, reason = tab._dialogue_model_blocked("llama-3.1-8b-base")
        self.assertTrue(blocked)
        self.assertIn("not dialogue-tuned", reason)
        blocked, reason = tab._dialogue_model_blocked("qwen2.5-7b-instruct")
        self.assertFalse(blocked)
        self.assertEqual(reason, "")

    def test_model_contracts_scale_output_without_inviting_topic_drift(self):
        tab = DialogueTab.__new__(DialogueTab)
        tiny = tab._model_output_contract("gemma-1b-it")
        compact = tab._model_output_contract("gemma-5b-it")
        full = tab._model_output_contract("qwen-32b-instruct")
        self.assertIn("TINY MODEL RESPONSE CONTRACT", tiny)
        self.assertIn("COMPACT MODEL RESPONSE CONTRACT", compact)
        self.assertIn("FULL MODEL RESPONSE CONTRACT", full)
        self.assertIn("Never invent websites", tiny)
        self.assertIn("Do not drift", full)

    def test_gemma_request_does_not_use_system_role_or_tools(self):
        message = Mock(content="A valid answer", tool_calls=None)
        response = Mock(choices=[Mock(message=message)])
        client = Mock()
        client.chat.completions.create.return_value = response

        with patch("agents.safety.calling._parse_tool_call_from_text", return_value=None):
            result = chat_with_tools(
                client=client,
                model="gemma 4 12b it qat q4",
                system_prompt="You are Edward Hurst.",
                user_message="Choose one action.",
                use_function_calling=False,
                flatten_system_prompt=True,
            )

        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(result, "A valid answer")
        self.assertNotIn("tools", request)
        self.assertEqual(request["messages"][0]["role"], "user")
        self.assertIn("You are Edward Hurst.", request["messages"][0]["content"])
        self.assertNotIn("system", {item["role"] for item in request["messages"]})

    def test_gemma4_is_not_forced_onto_legacy_template(self):
        config = BrainConfig(role=BrainRole.BIG)
        with patch(
            "agents.providers.gguf_meta.read_metadata",
            return_value={"general.architecture": "gemma4"},
        ):
            self.assertEqual(config._get_fallback_template("gemma-4-test.gguf"), "")

    def test_protocol_uses_live_template_capabilities(self):
        protocol = resolve_chat_protocol(
            "qwen3-12b",
            {"chat_template": "qwen", "chat_template_caps": {
                "supports_system_role": True,
                "supports_tools": True,
            }},
            default_tools=True,
        )
        self.assertFalse(protocol["flatten_system_prompt"])
        self.assertTrue(protocol["use_function_calling"])

        protocol = resolve_chat_protocol(
            "unknown-model",
            {"chat_template_caps": {
                "supports_system_role": False,
                "supports_tools": False,
            }},
            default_tools=True,
        )
        self.assertTrue(protocol["flatten_system_prompt"])
        self.assertFalse(protocol["use_function_calling"])

    def test_dialogue_worker_uses_bounded_turn_budget(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.brain = Mock(model="granite-1b-tiny")
        # Fixed manual budgets (auto-scaling off) so the per-brain Settings value
        # governs; a loaded .env would otherwise make this test order-dependent.
        env = {"DIALOGUE_AUTO_TOKENS": "false", "DIALOGUE_MAX_TOKENS_SMALL": "128",
               "DIALOGUE_MAX_TOKENS_BIG": "128"}
        with patch.dict(os.environ, env):
            os.environ.pop("DIALOGUE_MAX_TOKENS", None)
            DialogueWorker.__init__(
                worker, worker.brain, "context", [], "Jacob Stanley")
        self.assertEqual(worker.max_tokens, 128)

    def test_dialogue_worker_keeps_normal_budget_for_larger_models(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.max_tokens = 512
        worker.brain = Mock(model="granite-8b-instruct")
        # Auto-scaling off + per-brain manual budget: a larger model keeps the
        # normal (non-tiny) budget instead of the old tier-derived cap.
        env = {"DIALOGUE_AUTO_TOKENS": "false", "DIALOGUE_MAX_TOKENS_SMALL": "256",
               "DIALOGUE_MAX_TOKENS_BIG": "256"}
        with patch.dict(os.environ, env):
            os.environ.pop("DIALOGUE_MAX_TOKENS", None)
            DialogueWorker.__init__(
                worker, worker.brain, "context", [], "Jacob Stanley")
        self.assertEqual(worker.max_tokens, 256)

    def test_local_client_timeout_is_bounded(self):
        from agents.brains.big_brain import BigBrainAdapter
        with patch.dict(os.environ, {"LOCAL_LLM_TIMEOUT_SECONDS": "30"}):
            adapter = BigBrainAdapter(model="test-model")
            client = adapter._get_client()
        # The read budget honours the configured value; connect is bounded
        # separately and much lower so a dead llama-server fails fast.
        timeout = client.timeout
        read = getattr(timeout, "read", timeout)
        connect = getattr(timeout, "connect", timeout)
        self.assertEqual(read, 30.0)
        self.assertLessEqual(connect, 30.0)
        self.assertGreater(connect, 0)

    def test_dialogue_token_override_reaches_provider_request(self):
        message = Mock(content="Short answer", tool_calls=None)
        client = Mock()
        client.chat.completions.create.return_value = Mock(
            choices=[Mock(message=message)])
        chat_with_tools(
            client=client,
            model="gemma 4 12b",
            system_prompt="Persona",
            user_message="Choose one.",
            max_tokens=768,
            max_iterations=1,
            use_function_calling=False,
            flatten_system_prompt=True,
        )
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["max_tokens"], 768)

    def test_dialogue_disables_reasoning_only_for_dialogue_request(self):
        message = Mock(content="Short answer", tool_calls=None)
        client = Mock()
        # Stream-compatible mock: create() returns an iterable of chunks.
        # Each chunk has choices[0].delta.content.
        chunk = Mock()
        chunk.choices = [Mock()]
        chunk.choices[0].delta = Mock(content="Short answer")
        # Final chunk with empty content to signal end
        end_chunk = Mock()
        end_chunk.choices = [Mock()]
        end_chunk.choices[0].delta = Mock(content=None)
        client.chat.completions.create.return_value = iter([chunk, end_chunk])
        chat_with_tools(
            client=client,
            model="qwen3-8b",
            system_prompt="Persona",
            user_message="Choose one.",
            max_tokens=512,
            max_iterations=1,
            use_function_calling=False,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        # The streaming call should include extra_body.
        self.assertEqual(
            client.chat.completions.create.call_args_list[0].kwargs["extra_body"],
            {"chat_template_kwargs": {"enable_thinking": False}})

    def test_channel_reasoning_is_removed_from_visible_answer(self):
        self.assertEqual(
            _remove_reasoning_channels(
                "<|channel>thought\\nprivate notes"
                "<|channel>final\\nTake the first step."),
            "Take the first step.")

    def test_qwen_closed_thought_channel_preserves_following_answer(self):
        message = Mock(
            content=("<|channel>thought\\nprivate notes<channel|>"
                     "The answer is ready."),
            reasoning_content=None,
        )
        self.assertEqual(
            _visible_response_content(message), "The answer is ready.")

    def test_lfm_think_block_is_not_visible(self):
        message = Mock(
            content="<think>private notes</think>Use the small model first.",
            reasoning_content=None,
        )
        self.assertEqual(
            _visible_response_content(message), "Use the small model first.")

    def test_reasoning_only_message_returns_empty_visible_content(self):
        message = Mock(content="", reasoning_content="private notes")
        # When content is empty but reasoning_content has text, we fall back to
        # reasoning_content so the operator still receives the response.
        self.assertEqual(_visible_response_content(message), "private notes")

    def test_empty_provider_response_becomes_model_diagnostic(self):
        from agents.brains.big_brain import BigBrainAdapter
        brain = BigBrainAdapter(model="served-model", base_url="http://127.0.0.1:1234/v1")
        with patch("agents.safety.calling.chat_with_tools", return_value=""):
            response = brain.chat("Give one decision.", dialogue_mode=True)
        self.assertIn("model returned an empty response", response)
        self.assertIn("served-model", response)
        self.assertIn("127.0.0.1:1234/v1", response)

    def test_qwen_dialogue_disables_reasoning_budget_exhaustion(self):
        from agents.brains.big_brain import BigBrainAdapter

        brain = BigBrainAdapter(
            model="Qwen3.8-27B.gguf",
            base_url="http://127.0.0.1:1234/v1",
        )
        with patch("agents.safety.calling.chat_with_tools", return_value="Visible answer") as chat:
            brain.chat("Give one decision.", dialogue_mode=True)

        assert chat.call_args.kwargs["extra_body"] == {
            "chat_template_kwargs": {"enable_thinking": False}
        }

    def test_glm_and_lfm_models_get_explicit_family_profiles(self):
        from agents.providers.model_profile import get_model_profile

        assert get_model_profile(
            model_path="D:/llama.cpp/models/GLM-4.7-Flash.gguf"
        )["family"] == "glm"
        assert get_model_profile(
            model_path="D:/llama.cpp/LFM2.5-2.6B-Q5_K_M.gguf"
        )["family"] == "lfm"

    def test_stall_phrases_and_narrated_tool_calls_are_rejected(self):
        """Stall phrases and narrated tool calls must be rejected by
        DialogueWorker._is_bad_dialogue_response so they never
        enter the shared transcript."""
        worker = DialogueWorker(brain=None, context="", history=[], speaker="Edward Hurst")
        # "awaiting user input" is a stall phrase and must be rejected
        self.assertTrue(worker._is_bad_dialogue_response(
            "I am awaiting user input before I can proceed."))
        # Narrated tool calls must be rejected
        self.assertTrue(worker._is_bad_dialogue_response(
            "CALLING TOOL: web_search for active bounties."))
        # A concrete, evidence-grounded decision should NOT be rejected
        self.assertFalse(worker._is_bad_dialogue_response(
            "I found three active bounties on the platform."))

    def test_natural_dialogue_can_include_multiple_questions(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        response = (
            "The goal is broad, so I see several possible paths. "
            "Are you optimizing for speed? What skills do you already have? "
            "What risk level fits you? Which option should we compare first?"
        )
        self.assertFalse(worker._is_bad_dialogue_response(response))

    # ── Stale tests removed (2.1.1) ──────────────────────────────────
    # The following tests referenced methods that were removed during the
    # 2.1.1 dialogue refactor.  The features they tested no longer exist:
    #   _on_tool_activity        → removed; tool events no longer enter
    #                              the dialogue transcript as separate turns
    #   _get_control_context     → removed; pending-tool blocking is now
    #                              handled by the lifecycle, not the tab
    #   _get_opportunity_context → removed; opportunity context is now
    #                              assembled inline in get_dialogue_context()

    def test_dialogue_context_has_a_bounded_prompt(self):
        tab = DialogueTab.__new__(DialogueTab)
        tab.conversation_history = [
            {"speaker": "Edward Hurst", "content": "x" * 1000}
            for _ in range(200)
        ]
        tab._context_char_limit = 12000
        tab.goal = "Choose one action"
        tab.current_speaker = "Edward Hurst"
        tab._phase_index = 0
        tab.active_lifecycle = []
        context = tab.get_dialogue_context()
        self.assertLessEqual(len(context), 12000)

    def test_dialogue_context_requires_immediate_read_only_research(self):
        tab = DialogueTab.__new__(DialogueTab)
        tab.conversation_history = []
        tab.goal = "Evaluate a potential platform"
        tab.current_speaker = "Edward Hurst"
        tab._phase_index = 0
        from gui.tabs.dialogue_tab import LIFECYCLE
        tab.active_lifecycle = LIFECYCLE
        context = tab.get_dialogue_context()
        self.assertIn("CALL A READ-ONLY TOOL NOW", context)
        self.assertIn("use one read-only tool and rely only on its returned evidence", context)
        self.assertIn("Do not invent sources or results", context)
        self.assertIn("stop for human approval before", context)

    def test_dialogue_context_requires_self_check_and_recovery(self):
        tab = DialogueTab.__new__(DialogueTab)
        tab.conversation_history = []
        tab.goal = "Diagnose a broken dialogue"
        tab.current_speaker = "Edward Hurst"
        tab._phase_index = 0
        from gui.tabs.dialogue_tab import LIFECYCLE
        tab.active_lifecycle = LIFECYCLE
        context = tab.get_dialogue_context()
        self.assertIn("SELF-CHECK THE DIALOGUE", context)
        self.assertIn("CORRECT", context)
        self.assertIn("INVESTIGATE", context)
        self.assertIn("bounded local FIX", context)
        self.assertIn("repeating confirmation loop", context)

    def test_decorated_tool_only_lines_are_stripped(self):
        """A line whose only words are tool names is never a real sentence, but
        v2.1.30 only handled whitespace-separated runs. A probe found that
        pipe/semicolon separators (``web_read | web_search``), markdown and
        punctuation decoration (``**web_read**``, ``(web_read)``, ``> web_read``,
        ``web_read.`` / ``!`` / ``?``), an arrow (``web_read ->``) and an
        ``and`` join (``web_read and web_check``) all still leaked into the
        persona bubble. Every tool-only line must now strip to nothing."""
        from agents.safety.response import _remove_tool_syntax
        for leak in (
            "web_read | web_search",
            "web_read; web_search",
            "web_read, web_search",
            "> web_read",
            "web_read.",
            "web_read!",
            "web_read?",
            "(web_read)",
            "**web_read**",
            "web_read ->",
            "web_read and web_search",
            "web_read and web_check",
        ):
            with self.subTest(leak=leak):
                self.assertEqual(_remove_tool_syntax(leak), "")

    def test_tool_only_strip_does_not_mangle_real_prose(self):
        """The tool-only-line rule must not eat legitimate sentences. Two
        classes matter: verb-object prose on one line ("I'll use web_read.")
        and — the pre-existing 5c defect — a tool name that legitimately opens
        the NEXT line of a real answer. 5c's ``\\s+`` separator crossed the
        newline, so "...the payout was $80.\\nweb_search would not have helped
        here." lost its "web_search". The separator is now ``[ \\t]+``."""
        from agents.safety.response import _remove_tool_syntax
        for prose in (
            "I'll use web_read.",
            "Using web_read and web_check.",
            "I used web_search to find three freelance platforms.",
            "The web_read tool returned the pricing page.",
            "I read the page with web_read and the payout was $80.\n"
            "web_search would not have helped here.",
            "I checked the deposit terms.\n"
            "The contract requires 0.01 ETH.\n"
            "We should ask Jacob before proceeding.",
            "Here is my analysis:\n"
            "- uGig pays $80 for code review\n"
            "- Gitcoin has bounties open now",
        ):
            with self.subTest(prose=prose):
                self.assertEqual(_remove_tool_syntax(prose), prose)

    def test_first_person_tool_grounded_confirmation_is_not_rejected(self):
        """A persona that verified with a tool and reports its finding is doing
        exactly what the tool-first rule requires, so it must not be rejected.
        The external-claim tuple previously held the bare phrases
        "confirmed the" / "confirmed that", which rejected every first-person
        confirmation — and because each rejection re-prompts, the persona was
        trapped in a false-rejection retry loop (the recurring human-step loop
        the operator reported). Unverifiable EXTERNAL confirmations must still
        be rejected."""
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.history = []
        for good in (
            "I confirmed the $80 bounty by reading the listing.",
            "Using web_read and web_check, I confirmed the $80 bounty.",
            "I confirmed that the deadline is Friday.",
            "I read the page and confirmed the payout is $80.",
        ):
            with self.subTest(good=good):
                self.assertFalse(worker._is_bad_dialogue_response(good), good)
        for bad in (
            "The platform has confirmed my registration.",
            "The platform confirmed that I am approved.",
            "They confirmed the payout is on its way.",
            "The client confirmed that the job is mine.",
            "The employer has confirmed my application.",
            "The website confirmed the bounty is paid.",
            "It confirmed the transfer cleared.",
            "The listing confirmed the requirements.",
            "The platform has confirmed visibility.",
        ):
            with self.subTest(bad=bad):
                self.assertTrue(worker._is_bad_dialogue_response(bad), bad)

    def test_reasoning_mode_router_matches_task_shape(self):
        self.assertEqual(
            select_reasoning_mode("verify current skill.md evidence").mode,
            ReasoningMode.REACT)
        self.assertEqual(
            select_reasoning_mode("compare the best platforms", candidate_count=3).mode,
            ReasoningMode.TREE)
        self.assertEqual(
            select_reasoning_mode("implement a multi-stage workflow", dependency_count=3).mode,
            ReasoningMode.GRAPH)
        self.assertEqual(
            select_reasoning_mode("create a roadmap").mode,
            ReasoningMode.SKELETON)
        self.assertEqual(
            select_reasoning_mode("say hello").mode,
            ReasoningMode.DIRECT)


if __name__ == "__main__":
    unittest.main()