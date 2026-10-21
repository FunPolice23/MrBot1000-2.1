"""Streaming OpenAI-compatible tool completion loop."""

import json
from typing import Any, Callable, Dict, List, Optional

from agents.safety.gate import SafetyDecision, SafetyGate
from agents.safety.calling import (
    _parse_tool_call_from_text, _remove_tool_syntax, _tool_trace_entry,
    _visible_response_content, execute_tool, get_all_tools,
)


# ARCH-ENG-173: every phrasing the runtime uses to say a tool did NOT run.
#
# The status used to be classified inline by SUBSTRING on "PENDING APPROVAL", a
# startswith("[BLOCKED"), and a startswith("[Tool") — duplicated at both the
# text-call and function-call sites. That missed two shapes the runtime really
# produces:
#
#   "[Approval unavailable: web_read was not executed: ...]"   <- approval queue down
#   "[Search error: ...]" / "[Web error: ...]"                 <- tool handlers
#
# Both fell through to "executed". The approval-queue case is the worst: the
# tool provably did NOT run, the operator had no chance to approve it, and the
# UI then printed "[TOOL] actual tool call: ..." and set real_evidence=True. A
# tool that was never executed was presented to the operator as a real one — the
# exact class ARCH-ENG-056/102/110 closed from the other direction.
#
# This is a DENY list and it is checked FIRST, so a refusal shape added later
# defaults to "did not run" rather than to "executed". One definition replaces
# both duplicated inline classifiers, so the two sites cannot drift again.
_NOT_EXECUTED_MARKERS = (
    "pending approval",
    "[blocked]",
    "[approval unavailable",
    "[tool error",
    "[tool execution error",
    "[authorization required",
    "[unknown tool",
    "not executed",
    # ── ARCH-ENG-214: derived from the handlers, not guessed ────────────────
    #
    # The original list covered eight shapes. The handlers emit THIRTY distinct
    # bracket prefixes, of which nineteen are failures -- so a handler that
    # returned `[Query error: no such table: opportunities]` classified as
    # "executed". It had executed nothing.
    #
    # That matters because the consequences are not cosmetic: `_tool_status`
    # feeds the trace the operator reads, `action_state="completed"`, and an
    # `execution_id` is minted for the call. A failed query was recorded in the
    # dialogue ledger as a completed tool action.
    #
    # These are enumerated by walking `ast.Return` in handlers.py,
    # web_eyes.py, workshop.py and legacy_tools.py and collecting every literal
    # that begins with a bracketed failure word. Success prefixes such as
    # `[Account added]` and `[Proposal created]` are deliberately NOT listed --
    # they really did execute, and classifying them as errors would be the
    # mirror-image lie.
    #
    # `tests/safety/test_arch_eng_214_tool_result_honesty.py` re-derives the
    # handler prefixes and fails if a new one is not covered here, so this list
    # cannot silently drift out of date again.
    "[search error",
    "[web error",
    "[read error",
    "[read refused",
    "[write error",
    "[write refused",
    "[command error",
    "[command refused",
    "[command timed out",
    "[query error",
    "[database not found",
    "[file not found",
    "[directory not found",
    "[list error",
    "[check error",
    "[fetch refused",
    "[account error",
    "[payment error",
    "[proposal error",
    "[analysis refused",
    "[workshop error",
    "[workshop folder error",
    "[workshop folder creation failed",
    "[workshop storage error",
    # ── ARCH-ENG-227: the propose tool's refusal ────────────────────────────
    #
    # `propose_code_patch` returns `[Patch refused: ...]` when the rehearsal
    # fails, an argument is missing, or no service is available. It executes
    # NOTHING in those cases -- no proposal is created and no file is touched --
    # so it must classify as not-executed, exactly like `[write refused]`.
    #
    # Found by the ARCH-ENG-214 anti-drift guard, which re-derives the handler
    # prefixes and fails when one is not covered here. That guard did its job:
    # without it this would have shipped as "executed" for a refusal that
    # executed nothing.
    "[patch refused",
    # ── ARCH-ENG-248: the typed workshop surface ────────────────────────────
    #
    # Ten read tools and seven write tools were added for 11G's AY-01. Each
    # failure shape reports that NOTHING was read or written:
    #   * the `[Workshop <area> error: ...]` family (one per tool);
    #   * explicit refusals -- a secret path, a status update that did not
    #     land, an account removal that did not happen;
    #   * "nothing stored" answers, which must not be recorded as an executed
    #     action any more than `[File not found]` is.
    # Successes ("[Script created]", "[Note added]", "[Account removed]",
    # "[Proposal status: ...]") are deliberately absent and are asserted
    # executed by the same ARCH-ENG-214 suite.
    "[workshop proposal error",
    "[workshop proposal list error",
    "[workshop proposal status error",
    "[workshop research error",
    "[workshop research list error",
    "[workshop script error",
    "[workshop script list error",
    "[workshop application error",
    "[workshop application list error",
    "[workshop account error",
    "[workshop account list error",
    "[workshop account remove error",
    "[workshop payment error",
    "[workshop payment list error",
    "[workshop deliverable error",
    "[workshop deliverable list error",
    "[workshop note error",
    "[workshop note list error",
    "[proposal status not updated",
    "[account not removed",
    "[no account stored for platform",
    "[no payment method stored",
    "[refused",
)


def _tool_status(result: str) -> str:
    """Classify a tool RESULT string into a status the UI can trust.

    ARCH-ENG-173. Deny-list first, so "did not run" always beats the
    executed default.
    """
    lowered = str(result or "").lstrip().lower()
    if "pending approval" in lowered:
        return "pending_approval"
    if any(marker in lowered for marker in _NOT_EXECUTED_MARKERS):
        return "blocked" if lowered.startswith("[blocked") else "error"
    return "executed"


def _tool_was_executed(result: str) -> bool:
    """True only when the result does NOT say the tool failed to run."""
    return _tool_status(result) == "executed"


def _describe_repeated_tool_call(fn_name: str, fn_args: dict) -> str:
    """Visible fallback when a model's reply is only a REPEATED tool call.

    ARCH-ENG-110. A compact local model (observed: LFM2.5 on the CPU small
    brain) frequently emits a bare tool call and nothing else — e.g.
    ``web_search("paid gigs october")``. The tool runs once, the result is
    appended to the history, and the model re-issues the identical call. The
    duplicate guard then returned ``_remove_tool_syntax(visible_content)``,
    which strips that pure tool call down to ``""``. An empty string is not a
    useful answer: the small brain raised "model returned an empty response",
    retried 3x (all empty), and Live mode showed a hard failure — a 100%
    failure rate for the small brain with no diagnostic in the log, because
    the empty return bypassed every existing capture point.

    A repeated call is a genuine, reportable outcome, so state it. The wording
    deliberately claims NOTHING about what the tool found — the result is
    already in the transcript above, and this text must never be read as
    evidence of a successful search (financial/epistemic truth rule).
    """
    args = fn_args if isinstance(fn_args, dict) else {}
    detail = ""
    for key in ("query", "url", "path", "sql", "command"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            detail = f" for {val.strip()[:160]}"
            break
    note = args.get("note")
    if isinstance(note, str) and note.strip():
        return note.strip()
    return (
        f"I already ran {fn_name}{detail} and its result is in our transcript "
        f"above. I re-requested the same call instead of answering from that "
        f"result, so here is my position: I have no new evidence beyond what "
        f"the tool already returned, and I would rather say so than repeat the "
        f"search. If you want me to go deeper, tell me what specifically to "
        f"verify next."
    )


def _seed_executed_calls_from_history(history, executed_text_calls: set) -> None:
    """Pre-seed the executed-text-call set from prior turns in the transcript.

    Scans each history message's text for text-form tool calls of the shape
    ``web_read("url")`` / ``web_search("query")`` and records
    ``(tool_name, {"url"|"query": arg})`` so the within-turn duplicate guard
    treats an already-shown result as already delivered. This stops the
    cross-turn re-read loop without caching page content: it only suppresses a
    call whose exact invocation is already visible in the conversation, and the
    last-10-message window means a stale entry ages out naturally.
    Never raises; a malformed history is simply skipped.
    """
    if not history:
        return
    import re
    # tool_name("arg")  — same shape _parse_tool_call_from_text recognizes.
    call_re = re.compile(
        r'\b(web_read|web_search|web_check)\s*\(\s*["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    arg_key = {"web_read": "url", "web_search": "query", "web_check": "url"}
    for msg in history:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        for m in call_re.finditer(content):
            name = m.group(1).lower()
            arg = m.group(2).strip()
            if not arg:
                continue
            executed_text_calls.add((name, json.dumps({arg_key[name]: arg}, sort_keys=True)))


def _build_chat_messages(
    system_prompt: str,
    user_message: str,
    history: list | None,
    flatten_system_prompt: bool,
    images: list | None,
) -> list:
    """Build the initial message list (ARCH-ENG-277, AG-01).

    ``flatten_system_prompt`` exists for local templates (notably Gemma's) that
    reject the system role: the instruction content is kept but presented as
    the first user turn. Images are converted to data URLs for local files so
    OpenAI-compatible servers accept them.
    """

    def _user_content() -> object:
        if not images:
            return user_message
        parts: list = [{"type": "text", "text": user_message}]
        for img in images:
            if not img:
                continue
            url = str(img)
            if not (url.startswith("http://") or url.startswith("https://")
                    or url.startswith("data:")):
                try:
                    import base64, mimetypes, os as _os
                    if _os.path.isfile(url):
                        mime = mimetypes.guess_type(url)[0] or "image/png"
                        with open(url, "rb") as fh:
                            b64 = base64.b64encode(fh.read()).decode("ascii")
                        url = f"data:{mime};base64,{b64}"
                    else:
                        continue
                except Exception:
                    continue
            parts.append({"type": "image_url", "image_url": {"url": url}})
        return parts

    if flatten_system_prompt:
        messages = [{
            "role": "user",
            "content": f"{system_prompt}\n\nCURRENT REQUEST:\n{user_message}",
        }]
    else:
        messages = [{"role": "system", "content": system_prompt}]

    # History is limited to the last 10 messages to save context.
    if history:
        for msg in history[-10:]:
            messages.append(msg)

    if not flatten_system_prompt:
        messages.append({"role": "user", "content": _user_content()})
    return messages


def _gate_tool_call(fn_name: str, fn_args: dict) -> str:
    """Apply the safety gate and return the exact text the model will see.

    Extracted from the two identical copies in the text-call and function-call
    branches (ARCH-ENG-277). One gate, one approval wording, one execution
    path: previously a fix to either branch silently skipped the other.
    """
    from agents.safety import calling as runtime
    from agents.safety.gate import SafetyGate
    _gate = SafetyGate()
    _allowed, _reason, _decision = _gate.check(fn_name, fn_args)
    if _decision == "blocked":
        return f"[BLOCKED] Tool {fn_name} refused: {_reason}"
    if _decision == "needs_approval":
        try:
            from agents.safety.approval import (
                ApprovalItem, ApprovalKind, HumanApprovalQueue)
            _app = HumanApprovalQueue.instance().enqueue(ApprovalItem(
                kind=ApprovalKind.ACTION,
                title=f"Chat tool request: {fn_name}",
                description=(
                    f"The chat requested {fn_name}. Review the arguments before "
                    "allowing any machine change or external action."
                ),
                requested_by="dialogue",
                details={"tool": fn_name, "arguments": fn_args},
                payload={"tool": fn_name, "arguments": fn_args},
            ))
            return (
                f"[PENDING APPROVAL] request_id={_app.id}; {fn_name} was not "
                "executed. Tell the human that this request is awaiting review."
            )
        except Exception as _exc:
            return f"[Approval unavailable: {fn_name} was not executed: {_exc}]"
    return runtime.execute_tool(fn_name, fn_args)


def _record_tool(
    tool_trace: list | None,
    emit_tool,
    fn_name: str,
    fn_args: dict,
    result: str,
    source: str,
) -> None:
    """Record one executed tool for the UI and the trace, in one place."""
    if tool_trace is not None:
        tool_trace.append(_tool_trace_entry(fn_name, fn_args, result, source))
    emit_tool({
        "name": fn_name, "arguments": fn_args,
        # ARCH-ENG-173: was an inline 3-way substring classifier that reported
        # "executed" for a tool that never ran. Both call sites use the same
        # classifier so they cannot drift apart.
        "status": _tool_status(result),
        "executed": _tool_was_executed(result),
        "result_preview": result[:1000], "source": source,
    })


def _run_generation(
    client,
    model: str,
    messages: list,
    max_tokens: int,
    temperature: float,
    extra_body: dict | None,
    tools: list | None,
    stream_progress: callable,
) -> tuple[str, object]:
    """Stream one generation, with the non-streaming and no-thinking fallbacks.

    Returns ``(answer_text, message_or_None)``. Raises RuntimeError when the
    stream produced neither content nor a complete message -- the caller's
    empty-response path is the only honest handling for that.
    """
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if extra_body:
        kwargs["extra_body"] = dict(extra_body)

    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    # Stream tokens so the caller can show live progress in the UI.
    kwargs["stream"] = True
    answer_parts: list[str] = []
    msg = None
    try:
        stream = client.chat.completions.create(**kwargs)
        # Tolerate both real Response iterators and mock iterators used in
        # tests. Some test mocks return bare iterators of chunk-like objects
        # whose .choices may be empty or missing; treat those as silent.
        # Other mocks return a single non-iterator response object with .choices.
        try:
            chunks = list(stream)
        except TypeError:
            chunks = [stream] if getattr(stream, "choices", None) else []
        reasoning_parts: list[str] = []
        for chunk in chunks:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            choice0 = choices[0]
            # Streaming chunks carry choices[0].delta; non-streaming responses
            # carry choices[0].message. Check the delta FIRST: mock objects
            # auto-create both attributes, so testing .message first would
            # misread a streaming mock and lose the content.
            delta = getattr(choice0, "delta", None)
            _delta_content = getattr(delta, "content", None) if delta is not None else None
            if isinstance(_delta_content, str):
                if _delta_content:
                    answer_parts.append(_delta_content)
                    if stream_progress is not None:
                        try:
                            stream_progress(_delta_content)
                        except Exception:
                            pass
                    continue
            _delta_reasoning = getattr(delta, "reasoning_content", None) if delta is not None else None
            if isinstance(_delta_reasoning, str) and _delta_reasoning:
                reasoning_parts.append(_delta_reasoning)
                # ARCH-ENG-106: also drive stream_progress on the reasoning
                # channel so the live tok/s bar tracks TOTAL generation
                # (thinking + answer). A reasoning-heavy model spends most of
                # its time in reasoning_content before any visible content.
                if stream_progress is not None:
                    try:
                        stream_progress(_delta_reasoning)
                    except Exception:
                        pass
                continue
            # Fall back to a complete message object (non-streaming shape).
            message = getattr(choice0, "message", None)
            _msg_content = getattr(message, "content", None) if message is not None else None
            if message is not None and isinstance(_msg_content, str):
                msg = message
                if _msg_content:
                    answer_parts.append(_msg_content)
                continue
        answer = "".join(answer_parts)
        # ARCH-ENG-180: THIS SUBSTITUTED THE REASONING CHANNEL FOR THE ANSWER.
        #
        #     if not answer.strip() and reasoning_parts:
        #         answer = "".join(reasoning_parts)
        #
        # When a reasoning model exhausts its token budget mid-thought it emits
        # a `reasoning` delta and never reaches the answer channel. That line
        # took raw chain-of-thought and returned it AS THE ANSWER, so it became
        # the persona's visible dialogue turn and was persisted as something
        # the persona "said".
        #
        # An empty answer channel is an EMPTY RESPONSE, and the tab already has
        # a deterministic handler for that. The reasoning is NEVER the reply.
        # `reasoning_parts` is deliberately not consumed here.
        del reasoning_parts
        if not answer.strip() and msg is None:
            raise RuntimeError("empty stream response")
    except TypeError:
        # Some SDK/server combos reject extra_body/stream at call time; fall
        # back to a plain non-streaming call (no progress streaming).
        kwargs.pop("stream", None)
        kwargs.pop("extra_body", None)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choices = getattr(response, "choices", None)
        if choices:
            msg = choices[0].message
            _content = getattr(msg, "content", None)
            answer = _content if isinstance(_content, str) else ""
        else:
            msg = None
            answer = ""

    if not answer.strip():
        thinking_key = kwargs.get("extra_body", {}).get("chat_template_kwargs", {}).get("enable_thinking")
        if thinking_key:
            kwargs.pop("extra_body", None)
            response = client.chat.completions.create(**kwargs)
            _choices = getattr(response, "choices", None)
            if _choices:
                msg = _choices[0].message
                _content = getattr(msg, "content", None)
                answer = _content if isinstance(_content, str) else ""

    return answer, msg


def _log_empty_visible(model: str, msg_proxy) -> None:
    """Capture the RAW content/reasoning behind an empty visible answer.

    ARCH-ENG-109: a stripped-to-nothing answer is diagnosable only if we know
    what the model actually produced (whole output inside a think block?
    tool-call syntax only? template artifact?). Goes to brain_failures.log.
    """
    if msg_proxy is None:
        return
    try:
        from app.failure_log import log_failure
        _raw_c = getattr(msg_proxy, "content", None)
        _raw_r = getattr(msg_proxy, "reasoning_content", None)
        # ARCH-ENG-110: a raw_content that is PURELY a tool call is a distinct
        # case from a think-block-only reply; record which it was.
        _raw_s = str(_raw_c or "")
        _parsed = _parse_tool_call_from_text(_raw_s) if _raw_s else None
        _kind = ("pure_tool_call=%s" % (_parsed[0],)) if _parsed else (
            "tool_syntax_only" if _raw_s and not _remove_tool_syntax(_raw_s).strip()
            else "stripped_to_empty")
        log_failure(
            "chat_with_tools EMPTY visible (model=%s, %s): raw_content=%r "
            "raw_reasoning=%r" % (
                model, _kind,
                (_raw_s[:600] if _raw_c else None),
                (str(_raw_r)[:600] if _raw_r else None)))
    except Exception:
        pass


def _text_tool_result(
    visible_content: str,
    executed_text_calls: set,
    messages: list,
    tool_trace: list | None,
    emit_tool,
) -> tuple[bool, str | None]:
    """Handle a tool call parsed out of plain text.

    Returns ``(handled, final_answer)``:
      * ``(True, text)``  -- return ``text`` as the answer
      * ``(True, None)``  -- a tool ran; the caller should continue the loop
      * ``(False, None)`` -- there was no parsable text call
    """
    text_tool_call = _parse_tool_call_from_text(visible_content)
    if not text_tool_call:
        return False, None

    fn_name, fn_args = text_tool_call
    call_key = (fn_name, json.dumps(fn_args, sort_keys=True))
    if call_key in executed_text_calls:
        # The model has already received this result. Returning the current
        # answer prevents an endless read/search loop.
        #
        # ARCH-ENG-110: the reply is OFTEN nothing but the tool call itself,
        # so stripping the syntax here returned "" -- an empty string with no
        # diagnostic. A repeated tool call is a real, visible outcome: report
        # it instead of vanishing.
        _dedup_answer = _remove_tool_syntax(visible_content)
        if _dedup_answer.strip():
            return True, _dedup_answer
        return True, _describe_repeated_tool_call(fn_name, fn_args)

    executed_text_calls.add(call_key)
    try:
        result = _gate_tool_call(fn_name, fn_args)
        _record_tool(tool_trace, emit_tool, fn_name, fn_args, result, "text_call")
        messages.append({
            "role": "assistant",
            "content": visible_content,
        })
        messages.append({
            "role": "tool",
            "content": result[:6000],
        })
        return True, None
    except Exception as e:
        if tool_trace is not None:
            tool_trace.append(_tool_trace_entry(
                fn_name, fn_args, f"[Tool error: {e}]", "text_call"))
        messages.append({
            "role": "tool",
            "content": f"[Tool execution error: {e}]",
        })
        return True, None


def _run_function_calls(
    msg,
    messages: list,
    executed_function_calls: set,
    tool_trace: list | None,
    emit_tool,
) -> bool:
    """Execute the API-shaped tool calls; True when a duplicate was hit."""
    # Add assistant message with tool calls.
    messages.append({
        "role": "assistant",
        "content": msg.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
            }
            for tc in msg.tool_calls
        ]
    })

    duplicate_function_call = False
    for tc in msg.tool_calls:
        fn_name = tc.function.name
        try:
            fn_args = json.loads(tc.function.arguments or "{}")
        except (json.JSONDecodeError, TypeError):
            fn_args = {}

        # Stop a model that keeps re-issuing the identical tool call: the
        # result is already in the history above, so answer instead of looping
        # until max_iterations is exhausted.
        call_key = (fn_name, json.dumps(fn_args, sort_keys=True))
        if call_key in executed_function_calls:
            duplicate_function_call = True
            messages.append({
                "tool_call_id": tc.id,
                "role": "tool",
                "content": (
                    "[Duplicate tool call stopped. The result for this exact "
                    "request is already above. Analyze that result and answer "
                    "the user without calling the tool again.]"
                ),
            })
            continue
        executed_function_calls.add(call_key)

        try:
            result = _gate_tool_call(fn_name, fn_args)
        except Exception as exc:
            result = f"[Tool execution error: {exc}]"
        _record_tool(tool_trace, emit_tool, fn_name, fn_args, result,
                     "function_call")

        messages.append({
            "tool_call_id": tc.id,
            "role": "tool",
            "content": result[:6000],  # Keep structured API previews usable
        })

    return duplicate_function_call


def _final_answer(
    client,
    model: str,
    messages: list,
    max_tokens: int,
    temperature: float,
) -> str:
    """Ask for the closing answer after the tool loop, never returning ""."""
    messages.append({
        "role": "user",
        "content": "Based on the tool results above, provide your final answer."
    })

    final_response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    # Tolerate both real Response objects and mock iterators used in tests.
    if hasattr(final_response, "choices"):
        _final_visible = _visible_response_content(final_response.choices[0].message)
        # ARCH-ENG-109: the post-tool final answer is the other place an empty
        # response can originate (the loop capture only covers the first
        # generation). Record the raw content/reasoning when it strips empty.
        if not _final_visible.strip():
            try:
                from app.failure_log import log_failure
                _fm = final_response.choices[0].message
                _fc = getattr(_fm, "content", None)
                _fr = getattr(_fm, "reasoning_content", None)
                log_failure(
                    "chat_with_tools EMPTY FINAL (model=%s): raw_content=%r "
                    "raw_reasoning=%r" % (
                        model,
                        (str(_fc)[:600] if _fc else None),
                        (str(_fr)[:600] if _fr else None)))
            except Exception:
                pass
            # ARCH-ENG-110: never hand back "" from the post-tool final answer.
            # A compact model that re-emits the tool call here strips to empty,
            # and an empty string surfaced as "model returned an empty
            # response" in Live mode. State the outcome instead of vanishing.
            return _describe_repeated_tool_call(
                "the requested tool",
                {"note": "the model re-issued the tool call after its result "
                         "was already returned"})
        return _final_visible

    acc: list[str] = []
    for chunk in (final_response or []):
        if getattr(chunk, "choices", None):
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                acc.append(delta.content)
    return _visible_response_content(type('MsgProxy', (), {
        'content': ''.join(acc),
        'reasoning_content': None,
        'tool_calls': None,
    })())


def chat_with_tools(
    client,
    model: str,
    system_prompt: str,
    user_message: str,
    history: list = None,
    max_iterations: int = 5,
    max_tokens: int = 4096,
    temperature: float = 0.5,
    use_function_calling: bool = True,
    flatten_system_prompt: bool = False,
    extra_body: dict | None = None,
    tool_trace: list | None = None,
    stream_progress: callable = None,
    on_tool_trace: callable = None,
    images: list | None = None,
) -> str:
    """Chat with tool calling support.

    ARCH-ENG-277 (AG-01): this used to be one 525-line function with nine
    return points. It is now an orchestrator over phase helpers -- message
    building, one streamed generation, text-call handling, API-call handling,
    and the closing answer -- so a change to a phase cannot silently skip its
    twin. Behaviour and wording are unchanged; the characterization tests pin
    every branch.

    v2.1 fix: Added use_function_calling parameter. When False, tools are not
    passed to the API (avoids 400 errors on llama.cpp). Instead, tool calls
    are parsed from text format in the response.

    stream_progress: optional callback(str_chunk) invoked for each streamed
    token so the caller can show live generation progress.

    on_tool_trace: optional callback(tool_event_dict) invoked as soon as a tool
    call is executed, so the caller can render real tool activity (separate from
    persona narration) without waiting for the final answer.

    images: optional list of image URLs / data-URLs / local paths. When present,
    the final user message becomes multimodal content for vision-capable models.
    """
    tools = get_all_tools() if use_function_calling else None

    def _emit_tool(event: dict) -> None:
        if on_tool_trace is not None:
            try:
                on_tool_trace(event)
            except Exception:
                pass

    messages = _build_chat_messages(
        system_prompt, user_message, history, flatten_system_prompt, images)

    executed_text_calls = set()
    executed_function_calls = set()

    # Cross-turn re-read guard (Phase A): the within-turn sets above stop a
    # model re-issuing the identical call in ONE chat_with_tools run, but each
    # new dialogue turn builds fresh sets -- so a persona that already read a
    # URL in a PRIOR turn would read it again, forever. Seed the sets from the
    # conversation history: if the exact call already appears in the
    # transcript, its result is already visible, so re-issuing it is stopped.
    _seed_executed_calls_from_history(history, executed_text_calls)

    for iteration in range(max_iterations):
        answer, msg = _run_generation(
            client, model, messages, max_tokens, temperature,
            extra_body, tools, stream_progress)

        # If no tool calls via API, try to parse tool calls from text.
        # Wrap answer in a simple object so _visible_response_content works.
        _msg_proxy = msg or type('MsgProxy', (), {
            'content': answer,
            'reasoning_content': None,
            'tool_calls': None,
        })()
        visible_content = _visible_response_content(_msg_proxy)

        if not visible_content.strip():
            _log_empty_visible(model, _msg_proxy)

        if not _msg_proxy.tool_calls:
            handled, final_answer = _text_tool_result(
                visible_content, executed_text_calls, messages,
                tool_trace, _emit_tool)
            if handled:
                if final_answer is not None:
                    return final_answer
                continue

            # ARCH-ENG-110: a reply whose text is ONLY a bare tool name that
            # the parser could not bind (e.g. "web_read" with no URL) parses to
            # None but still strips to "" -- the same empty-answer failure
            # class. Fall back to an honest statement rather than returning "".
            _plain = _remove_tool_syntax(visible_content)
            if _plain.strip():
                return _plain
            return _describe_repeated_tool_call(
                "a tool",
                {"note": "I named a tool without usable arguments, so nothing "
                         "was executed and I have no result to report. Tell me "
                         "the specific URL or query and I will run it properly."})

        if _run_function_calls(
                msg, messages, executed_function_calls,
                tool_trace, _emit_tool):
            break

    # If we exhausted iterations, ask for the final answer.
    return _final_answer(client, model, messages, max_tokens, temperature)

__all__ = ["chat_with_tools"]
