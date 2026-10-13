"""Streaming OpenAI-compatible tool completion loop."""

import json
from typing import Any, Callable, Dict, List, Optional

from agents.safety.gate import SafetyDecision, SafetyGate
from agents.safety.calling import (
    _parse_tool_call_from_text, _remove_tool_syntax, _tool_trace_entry,
    _visible_response_content, execute_tool, get_all_tools,
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
    from agents.safety import calling as runtime
    """
    Chat with tool calling support.
    
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

    def _user_content() -> object:
        """Return the user turn content, multimodal when images are supplied."""
        if not images:
            return user_message
        parts: list = [{"type": "text", "text": user_message}]
        for img in images:
            if not img:
                continue
            url = str(img)
            if not (url.startswith("http://") or url.startswith("https://")
                    or url.startswith("data:")):
                # Local file -> data URL so OpenAI-compatible servers accept it.
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
        # Some local templates, notably Gemma's, reject the system role. Keep
        # the instruction content but present it as the first user turn.
        messages = [{
            "role": "user",
            "content": f"{system_prompt}\n\nCURRENT REQUEST:\n{user_message}",
        }]
    else:
        messages = [{"role": "system", "content": system_prompt}]
    
    # Add history (limited to last 10 messages to save context)
    if history:
        for msg in history[-10:]:
            messages.append(msg)

    if not flatten_system_prompt:
        messages.append({"role": "user", "content": _user_content()})
    executed_text_calls = set()
    executed_function_calls = set()

    # Cross-turn re-read guard (Phase A): the within-turn sets above stop a
    # model re-issuing the identical call in ONE chat_with_tools run, but each
    # new dialogue turn builds fresh sets — so a persona that already read a URL
    # in a PRIOR turn would read it again, forever (the "agents keep re-reading
    # the same page" loop). Seed the sets from the conversation history: if the
    # exact tool call already appears in the transcript, its result is already
    # visible to the model, so re-issuing it is stopped and it is told to answer
    # from what it has. Uses real history (not a cache), so a genuinely changed
    # page is still re-readable once it ages out of the last-10 window.
    _seed_executed_calls_from_history(history, executed_text_calls)

    for iteration in range(max_iterations):
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
        try:
            stream = client.chat.completions.create(**kwargs)
            msg = None
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
                # Streaming chunks carry choices[0].delta; non-streaming
                # responses carry choices[0].message. Check the delta FIRST:
                # Mock objects auto-create both attributes, so testing
                # .message first would misread a streaming mock as a
                # non-streaming response and lose the content.
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
            if not answer.strip() and reasoning_parts:
                answer = "".join(reasoning_parts)
            if not answer.strip() and msg is None:
                raise RuntimeError("empty stream response")
        except TypeError:
            # Some SDK/server combos reject extra_body/stream at call time;
            # fall back to a plain non-streaming call (no progress streaming).
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
        
        # If no tool calls via API, try to parse tool calls from text
        # This handles models that don't support function calling
        # Wrap answer in a simple object so _visible_response_content works.
        _msg_proxy = msg or type('MsgProxy', (), {
            'content': answer,
            'reasoning_content': None,
            'tool_calls': None,
        })()
        visible_content = _visible_response_content(_msg_proxy)

        if not _msg_proxy.tool_calls:
            # Parse tool calls from text (works for all models)
            text_tool_call = _parse_tool_call_from_text(visible_content)
            if text_tool_call:
                fn_name, fn_args = text_tool_call
                call_key = (fn_name, json.dumps(fn_args, sort_keys=True))
                if call_key in executed_text_calls:
                    # The model has already received this result. Returning
                    # the current answer prevents an endless read/search loop.
                    return _remove_tool_syntax(visible_content)
                executed_text_calls.add(call_key)
                # Execute the tool
                try:
                    from agents.safety.gate import SafetyGate
                    _gate = SafetyGate()
                    _allowed, _reason, _decision = _gate.check(fn_name, fn_args)
                    if _decision == "blocked":
                        result = f"[BLOCKED] Tool {fn_name} refused: {_reason}"
                    elif _decision == "needs_approval":
                        try:
                            from agents.safety.approval import ApprovalItem, ApprovalKind, HumanApprovalQueue
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
                            result = (
                                f"[PENDING APPROVAL] request_id={_app.id}; {fn_name} was not "
                                "executed. Tell the human that this request is awaiting review."
                            )
                        except Exception as _exc:
                            result = f"[Approval unavailable: {fn_name} was not executed: {_exc}]"
                    else:
                        result = runtime.execute_tool(fn_name, fn_args)
                    if tool_trace is not None:
                        tool_trace.append(_tool_trace_entry(
                            fn_name, fn_args, result, "text_call"))
                    _emit_tool({
                        "name": fn_name, "arguments": fn_args,
                        "status": ("pending_approval" if "PENDING APPROVAL" in result
                                   else "blocked" if result.startswith("[BLOCKED]")
                                   else "error" if result.startswith("[Tool")
                                   else "executed"),
                        "result_preview": result[:1000], "source": "text_call",
                    })
                    messages.append({
                        "role": "assistant",
                        "content": visible_content,
                    })
                    messages.append({
                        "role": "tool",
                        "content": result[:6000],
                    })
                    # Continue to get final answer
                    continue
                except Exception as e:
                    if tool_trace is not None:
                        tool_trace.append(_tool_trace_entry(
                            fn_name, fn_args, f"[Tool error: {e}]", "text_call"))
                    messages.append({
                        "role": "tool",
                        "content": f"[Tool execution error: {e}]",
                    })
                    continue
            return _remove_tool_syntax(visible_content)
        
        # Add assistant message with tool calls
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
        
        # Execute tool calls and add results
        duplicate_function_call = False
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                fn_args = {}

            # Stop a model that keeps re-issuing the identical tool call: the
            # result is already in the history above, so answer instead of
            # looping until max_iterations is exhausted.
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
                from agents.safety.gate import SafetyGate
                _gate = SafetyGate()
                _allowed, _reason, _decision = _gate.check(fn_name, fn_args)
                if _decision == "blocked":
                    result = f"[BLOCKED] Tool {fn_name} refused: {_reason}"
                elif _decision == "needs_approval":
                    try:
                        from agents.safety.approval import ApprovalItem, ApprovalKind, HumanApprovalQueue
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
                        result = (
                            f"[PENDING APPROVAL] request_id={_app.id}; {fn_name} was not "
                            "executed. Tell the human that this request is awaiting review."
                        )
                    except Exception as _exc:
                        result = f"[Approval unavailable: {fn_name} was not executed: {_exc}]"
                else:
                    result = runtime.execute_tool(fn_name, fn_args)
            except Exception as exc:
                result = f"[Tool execution error: {exc}]"
            if tool_trace is not None:
                tool_trace.append(_tool_trace_entry(
                    fn_name, fn_args, result, "function_call"))
            _emit_tool({
                "name": fn_name, "arguments": fn_args,
                "status": ("pending_approval" if "PENDING APPROVAL" in result
                           else "blocked" if result.startswith("[BLOCKED]")
                           else "error" if result.startswith("[Tool")
                           else "executed"),
                "result_preview": result[:1000], "source": "function_call",
            })
            
            messages.append({
                "tool_call_id": tc.id,
                "role": "tool",
                "content": result[:6000],  # Keep structured API previews usable
            })

        if duplicate_function_call:
            break
    
    # If we exhausted iterations, ask for final answer
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
        return _visible_response_content(final_response.choices[0].message)
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


__all__ = ["chat_with_tools"]
