"""Regression tests for malformed local-model Dialogue output."""

import unittest
import os
from unittest.mock import Mock, patch

from gui.dialogue_tab import DialogueTab, DialogueWorker, LIFECYCLE
from agents.personas import persona_for_key
from agents.tool_calling import (
    chat_with_tools,
    _remove_reasoning_channels,
    _visible_response_content,
)
from agents.dual_brain_runtime import BrainConfig, BrainRole
from agents.providers.openai_compatible import resolve_chat_protocol
from agents.reasoning_modes import ReasoningMode, select_reasoning_mode


class TestDialogueResponseCorruption(unittest.TestCase):
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

    def test_non_progress_and_unrequested_image_continuations_are_rejected(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.context = "CURRENT PHASE: discover\nPHASE INSTRUCTION: approve or block."
        self.assertTrue(worker._is_bad_dialogue_response(
            "I'm ready to help Alex and the human user move forward with the current phase. "
            "I'll rely on the read-only tools that are available."
        ))
        self.assertTrue(worker._is_bad_dialogue_response(
            "The image you sent is a depiction of a detailed surreal portrait."
        ))

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
        persona = persona_for_key("Alex Vega")
        tiny = persona.build_system_prompt(goal="Choose one action", tier="tiny")
        compact = persona.build_system_prompt(goal="Choose one action", tier="compact")
        full = persona.build_system_prompt(goal="Choose one action", tier="full")
        self.assertIn("Answer only the current phase in 1-3 short sentences", tiny)
        self.assertIn("Follow the current phase instruction", compact)
        self.assertIn("# RESPONSE PROCESS", full)
        self.assertNotIn("# MEMORY", tiny)

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

        with patch("agents.tool_calling._parse_tool_call_from_text", return_value=None):
            result = chat_with_tools(
                client=client,
                model="gemma 4 12b it qat q4",
                system_prompt="You are Marcus Rivera.",
                user_message="Choose one action.",
                use_function_calling=False,
                flatten_system_prompt=True,
            )

        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(result, "A valid answer")
        self.assertNotIn("tools", request)
        self.assertEqual(request["messages"][0]["role"], "user")
        self.assertIn("You are Marcus Rivera.", request["messages"][0]["content"])
        self.assertNotIn("system", {item["role"] for item in request["messages"]})

    def test_gemma4_is_not_forced_onto_legacy_template(self):
        config = BrainConfig(role=BrainRole.BIG)
        with patch(
            "agents.gguf_meta.read_metadata",
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
        with patch.dict(os.environ, {"DIALOGUE_TURN_MAX_TOKENS": "512"}):
            DialogueWorker.__init__(
                worker, worker.brain, "context", [], "Alex Vega")
        self.assertEqual(worker.max_tokens, 128)

    def test_dialogue_worker_keeps_normal_budget_for_larger_models(self):
        worker = DialogueWorker.__new__(DialogueWorker)
        worker.max_tokens = 512
        worker.brain = Mock(model="granite-8b-instruct")
        with patch.dict(os.environ, {"DIALOGUE_TURN_MAX_TOKENS": "512"}):
            DialogueWorker.__init__(
                worker, worker.brain, "context", [], "Alex Vega")
        self.assertEqual(worker.max_tokens, 512)

    def test_local_client_timeout_is_bounded(self):
        from agents.big_brain import BigBrainAdapter
        with patch.dict(os.environ, {"LOCAL_LLM_TIMEOUT_SECONDS": "30"}):
            adapter = BigBrainAdapter(model="test-model")
            client = adapter._get_client()
        self.assertEqual(client.timeout, 30.0)

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
        client.chat.completions.create.return_value = Mock(
            choices=[Mock(message=message)])
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
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["extra_body"],
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
        self.assertEqual(_visible_response_content(message), "")

    def test_dialogue_context_has_a_bounded_prompt(self):
        tab = DialogueTab.__new__(DialogueTab)
        tab.conversation_history = [
            {"speaker": "Marcus Rivera", "content": "x" * 1000}
            for _ in range(200)
        ]
        tab._context_char_limit = 12000
        tab.goal = "Choose one action"
        tab.current_speaker = "Marcus Rivera"
        tab._phase_index = 0
        tab.active_lifecycle = []
        context = tab.get_dialogue_context()
        self.assertLessEqual(len(context), 12000)

    def test_dialogue_context_requires_immediate_read_only_research(self):
        tab = DialogueTab.__new__(DialogueTab)
        tab.conversation_history = []
        tab.goal = "Evaluate a potential platform"
        tab.current_speaker = "Marcus Rivera"
        tab._phase_index = 0
        from gui.dialogue_tab import LIFECYCLE
        tab.active_lifecycle = LIFECYCLE
        context = tab.get_dialogue_context()
        self.assertIn("CALL A READ-ONLY TOOL NOW", context)
        self.assertIn("do not say you will search later", context)
        self.assertIn("use one read-only tool and rely only on its returned evidence", context)
        self.assertIn("Do not invent sources or results", context)
        self.assertIn("stop for human approval before", context)

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