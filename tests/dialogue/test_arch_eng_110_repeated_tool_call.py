"""ARCH-ENG-110: a repeated bare tool call must never yield an empty answer.

Root cause (observed in Live mode, LFM2.5 on the CPU small brain): a compact
model emits a bare tool call and nothing else, e.g.
``web_search("paid gigs october")``. The tool runs, the result is appended to
the history, and the model re-issues the identical call. The duplicate guard
returned ``_remove_tool_syntax(visible_content)``, which strips that pure tool
call to ``""``. The empty string bypassed every diagnostic capture point, so
``brain_failures.log`` showed three bare ``small_brain empty answer`` lines and
no explanation; the small brain retried 3x and Live mode failed 100% of the
time with "model returned an empty response".

These tests pin the fix: a repeated tool call produces a VISIBLE answer, and
the honest wording never claims the tool found anything.
"""

import json

import pytest

# Import order matters: agents.safety.calling re-exports chat_with_tools from
# agents.dialogue.chat_completion, so importing safety.calling FIRST resolves
# the module cycle. Importing chat_completion first raises ImportError.
from agents.safety.calling import chat_with_tools  # noqa: F401
from agents.dialogue import chat_completion

_describe_repeated_tool_call = chat_completion._describe_repeated_tool_call

CALL = 'web_search("paid gigs october")'


class _Delta:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class _Choice:
    def __init__(self, delta=None, message=None):
        self.delta = delta
        self.message = message


class _Chunk:
    def __init__(self, content):
        self.choices = [_Choice(delta=_Delta(content=content))]


class _Msg:
    def __init__(self, content):
        self.content = content
        self.reasoning_content = None
        self.tool_calls = None


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(message=_Msg(content))]


class _RepeatClient:
    """Every generation is the identical bare tool call (the observed failure)."""

    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                if kwargs.get("stream"):
                    return iter([_Chunk(CALL)])
                return _Response(CALL)


def _run(client):
    return chat_with_tools(
        client=client,
        model="LFM2.5-2.6B-Q5_K_M.gguf",
        system_prompt="system",
        user_message="what should we do next?",
        history=[],
        max_tokens=2048,
        temperature=0.5,
        use_function_calling=False,
        flatten_system_prompt=True,
        max_iterations=2,
    )


def test_repeated_tool_call_returns_visible_answer():
    """The exact production failure must no longer produce an empty string."""
    answer = _run(_RepeatClient())
    assert answer.strip(), "repeated tool call must not collapse to an empty answer"
    # The raw tool-call syntax must be gone from what the operator sees.
    assert "web_search(" not in answer
    assert "web_search" in answer  # it names what it already ran


def test_repeated_tool_call_wording_makes_no_evidence_claim():
    """Financial/epistemic truth: the fallback must not assert results."""
    answer = _run(_RepeatClient()).lower()
    for claim in ("i found", "results show", "i verified", "confirmed",
                  "here are the results", "i retrieved"):
        assert claim not in answer, f"fallback must not claim evidence: {claim!r}"
    # It must instead state the absence of new evidence.
    assert "no new evidence" in answer


def test_describe_repeated_tool_call_includes_the_argument():
    text = _describe_repeated_tool_call("web_search", {"query": "paid gigs october"})
    assert "paid gigs october" in text
    assert "web_search" in text


def test_describe_repeated_tool_call_is_safe_without_args():
    assert _describe_repeated_tool_call("query_db", {}).strip()
    assert _describe_repeated_tool_call("query_db", None).strip()


def test_normal_answer_after_tool_call_is_preserved():
    """Regression guard: a real answer must pass through untouched."""

    class _OnceClient:
        calls = 0

        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    if kwargs.get("stream"):
                        _OnceClient.calls += 1
                        return iter([_Chunk(
                            CALL if _OnceClient.calls == 1
                            else "Here is my actual answer about the gigs."
                        )])
                    return _Response("Final answer text.")

    answer = _run(_OnceClient())
    assert answer == "Here is my actual answer about the gigs."


def test_post_tool_final_answer_never_empty():
    """The post-tool final-answer return path must also never hand back ''."""
    # The model answers on turn 1 but the FINAL (non-stream) call repeats the
    # tool call, so _visible_response_content strips it to empty.
    class _FinalRepeatClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    if kwargs.get("stream"):
                        return iter([_Chunk("Some first-pass text that is not a tool call.")])
                    return _Response(CALL)

    answer = _run(_FinalRepeatClient())
    assert answer.strip()
    assert "web_search(" not in answer


def test_bare_unbindable_tool_name_never_empty():
    """A bare tool name with no arguments must not collapse to an empty answer.

    'web_read' alone is NOT parseable (no URL to bind) so
    _parse_tool_call_from_text returns None, but _remove_tool_syntax still
    strips it — the same empty-answer failure class as the repeated call.
    """
    class _BareToolNameClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    if kwargs.get("stream"):
                        return iter([_Chunk("web_read")])
                    return _Response("web_read")

    answer = _run(_BareToolNameClient())
    assert answer.strip(), "a bare unbound tool name must not yield an empty answer"
    assert "nothing was executed" in answer


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
