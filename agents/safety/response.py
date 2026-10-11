"""Pure response cleanup and text tool-call parsing."""

import re
from typing import Any, Optional

# (READONLY_TOOL_NAMES, MUTATING_TOOL_NAMES) -> derived alternation. Memoises the
# regex so `_remove_tool_syntax` does not rebuild it on every call (measured
# ~33us per rebuild against ~171us for the whole function), while still picking
# up a registry change immediately — the key is compared by identity/equality,
# so a mutated registry yields a fresh pattern.
_PATTERN_CACHE = None


def _tool_name_pattern() -> str:
    """Regex alternation of every real tool name, from the canonical registry.

    ``safety_gate`` is the single source of truth for which tools exist (the
    READONLY/MUTATING sets, aligned with the dispatch registry by
    ``tests/test_safety_gate_registry_alignment.py``). This module used to
    carry its own hand-typed copy of that list inside ``_remove_tool_syntax``,
    so a tool added to the registry would silently keep leaking its bare name
    into persona bubbles — the same drift hazard that produced five
    consecutive releases of tool-name-leak fixes. Deriving the alternation
    here means a new tool is stripped the moment it is registered.

    Longest-first ordering keeps the alternation from shadowing a longer name
    with a shorter one that happens to be a prefix.
    """
    from .gate import MUTATING_TOOL_NAMES, READONLY_TOOL_NAMES

    # Sort by (-length, name): longest-first so a shorter name can never shadow
    # a longer one, and alphabetical within a length so the generated pattern is
    # byte-identical on every run. Sorting on length alone leaves equal-length
    # names in frozenset (hash) order, which makes the pattern string differ
    # between interpreter runs — surprising for a "single source of truth"
    # derivation, and it would break any future snapshot or diff of it.
    global _PATTERN_CACHE
    if _PATTERN_CACHE is None or _PATTERN_CACHE[0] != (READONLY_TOOL_NAMES, MUTATING_TOOL_NAMES):
        names = sorted(
            READONLY_TOOL_NAMES | MUTATING_TOOL_NAMES,
            key=lambda n: (-len(n), n),
        )
        _PATTERN_CACHE = (
            (READONLY_TOOL_NAMES, MUTATING_TOOL_NAMES),
            "|".join(re.escape(n) for n in names),
        )
    return _PATTERN_CACHE[1]


def _remove_tool_syntax(text: str) -> str:
    """Remove visible tool-invocation fragments from a user-facing answer.

    Two forms leak into persona text from local models:
      1. A call with parentheses: ``web_search("query")``.
      2. A BARE tool name on its own (line or trailing token): ``web_search`` /
         ``web_read`` — the model emits the tool name as if it were the call,
         with no arguments. Left in, Edward's whole "response" can be just
         ``web_search`` and several replies end with a dangling ``web_read``.

    We strip a tool name only when it stands alone as a token/line (optionally
    followed by a parenthesised argument list), never when it is a word inside a
    real sentence, so ordinary prose that happens to mention a tool is kept.
    """
    if not text:
        return ""
    names = _tool_name_pattern()
    # 1. Full call with parentheses (anywhere in the text), including an empty
    #    ``tool()`` and a bracketed ``tool[]`` form some local models emit.
    text = re.sub(rf"\b(?:{names})\s*\(\s*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"\b(?:{names})\s*\[[^\]]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"\b(?:{names})\s*\([^\n]*\)", "", text, flags=re.IGNORECASE)
    # 2. Bare tool name standing alone on its own line (the whole line is just
    #    the name, optionally bracketed, optionally trailing whitespace).
    text = re.sub(
        rf"(?im)^[ \t]*-?\s*\[?\b(?:{names})\]?[ \t]*\(?[ \t]*$",
        "", text,
    )
    # 3. Bare tool name as a trailing token at the end of a line/sentence
    #    (e.g. "...before I can assess this. web_read" or "...proceeding.[]").
    text = re.sub(
        rf"(?i)([\.\?\!:]|\n)[ \t]*\[?\b(?:{names})\]?[ \t]*(?:\(|\[)?[ \t]*(?=\n|$)",
        r"\1", text,
    )
    # 4. Orphaned empty brackets left after a stripped tool call (``[]`` / ``()``).
    text = re.sub(r"(?m)^[ \t]*(?:\[\s*\]|\(\s*\))[ \t]*$", "", text)
    text = re.sub(r"[ \t]*\[\s*\][ \t]*(?=\n|$)", "", text)
    # 5. Bare tool name in unambiguous leak positions: colon/comma-suffixed
    #    ("web_read:"), or several in a row ("web_search web_read web_check"),
    #    or immediately after sentence-ending punctuation. A local model that
    #    emits the tool name as a bare token in these positions leaks it into the
    #    persona bubble. We deliberately do NOT strip a tool name that is the
    #    object of a verb ("use web_search to...") — that is legitimate prose and
    #    the ambiguity is not worth mangling a real answer. The "the <tool> tool"
    #    mention form is left intact by matching only these leak positions.
    # 5a. Trailing colon/comma after a bare tool name — and the separator
    #     itself. Removing only the name left a dangling ',' or ':' at the
    #     start of the visible bubble ("web_read, then I will assess" used to
    #     render as "I need data. , then I will assess"). Consume the one
    #     separator that belonged to the stripped token, plus the whitespace
    #     that followed it.
    text = re.sub(rf"(?i)(?<![\w/-])\b(?:{names})\b[ \t]*[,:][ \t]*", "", text)
    # 5b. A run of 2+ bare tool names separated only by whitespace or a
    #     punctuation separator ("web_search web_read" / "web_read|
    #     web_search" / "web_read; web_search"). Word separators like
    #     "and"/"then" keep their verb-bearing prose and are deliberately not
    #     matched, so "I used web_read and web_search" survives intact.
    text = re.sub(
        rf"(?i)(?<![\w/-])(?:\b(?:{names})\b[ \t|;,]*){{2,}}",
        "", text,
    )
    # 5c. Bare tool name immediately after sentence-ending punctuation ON THE
    #     SAME LINE. The separator is deliberately ``[ \t]+`` and not ``\s+``:
    #     ``\s+`` crosses a newline and would strip a tool name that
    #     legitimately opens the next line of real prose ("...the payout was
    #     $80.\nweb_search would not have helped here."). A leaked bare name
    #     always trails the punctuation on its own line, so same-line matching
    #     loses nothing.
    text = re.sub(
        rf"(?i)([\.\?\!][ \t]+)(?<![\w/-])\b(?:{names})\b(?!\s+tool\b)(?![\w/-])",
        r"\1", text,
    )
    # 5d. A whole line whose only words are tool names — optionally decorated
    #     with markdown/punctuation or joined by "and"/"then"/"->" — is never a
    #     real sentence ("web_read.", "**web_read**", "(web_read)",
    #     "> web_read", "web_read ->", "web_read and web_search"). Strip the
    #     whole line. A line that still holds any other letter is a real
    #     sentence ("I'll use web_read." / "The web_read tool returned") and is
    #     left alone.
    def _tool_only_line(match: "re.Match") -> str:
        body = match.group(0)
        if not re.search(rf"(?i)\b(?:{names})\b", body):
            return body
        residue = re.sub(rf"(?i)\b(?:{names})\b", " ", body)
        residue = re.sub(
            r"(?i)\b(?:and|then|or|also|plus|now|next)\b", " ", residue)
        return "" if not re.search(r"[A-Za-z]", residue) else body

    text = re.sub(r"(?m)^[^\n]+$", _tool_only_line, text)
    # 6. Clean up any double spaces / leading punctuation left by the strips.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"(?m)^[ \t]*[,;:][ \t]*$", "", text)
    return (
        text.replace("[web_search ]", "").replace("[web_read ]", "")
        .replace("[web_check ]", "").strip()
    )


def _remove_reasoning_channels(text: str) -> str:
    """Remove channel-formatted reasoning while preserving visible answer text."""
    if not text:
        return ""
    # Qwen/LFM-style closed thought blocks leave the answer after the close
    # marker; do this before handling an unclosed/reasoning-only response.
    text = re.sub(
        r"<\|channel\|?>\s*(?:thought|analysis)\b.*?"
        r"<channel\|>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"<\|channel\|?>\s*(?:thought|analysis)\b.*?"
        r"(?:<\|channel\|?>\s*(?:final|answer)\b|$)",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<\|channel\|?>\s*(?:final|answer)\b", "", text,
                  flags=re.IGNORECASE)
    return text.replace("\\n", "\n").strip()


def _remove_think_blocks(text: str) -> str:
    """Remove LFM/Gemma think blocks without exposing hidden reasoning."""
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    return text.strip()


def _visible_response_content(message: Any, profile: dict[str, Any] = None) -> str:
    """Extract only user-visible answer text from an OpenAI message.

    For thinking/reasoning models (Qwen3-Think, DeepSeek, NVIDIA Nemotron),
    the provider may place private thought in ``reasoning_content`` and the
    final answer in ``content``. When ``content`` is empty but
    ``reasoning_content`` carries the only visible output, fall back to it so
    the operator still receives a response instead of an opaque empty error.

    If a ``profile`` is provided, use the family-specific thinking extractor
    to strip inline ``<think>`` or ``<|channel>thought`` blocks from the
    visible output.
    """
    content = getattr(message, "content", None) or ""
    reasoning = getattr(message, "reasoning_content", None)
    # When the provider puts thought in content, the format-specific cleaners
    # do the same without requiring a model-family name.
    if not isinstance(content, str):
        return ""
    cleaned = _remove_think_blocks(_remove_reasoning_channels(content))
    if not cleaned and reasoning and isinstance(reasoning, str):
        cleaned = _remove_think_blocks(_remove_reasoning_channels(reasoning))
    # Apply family-specific thinking extraction if profile provided.
    if profile and cleaned:
        import re
        thinking_kind = profile.get("thinking", "none")
        if thinking_kind == "channel_thought":
            # Gemma 4: strip inline <|channel>thought ... <channel|>
            cleaned = re.sub(r"<\|\s*channel\s*>thought\s*.*?\s*<\s*channel\s*\|>", "", cleaned, flags=re.DOTALL).strip()
        elif thinking_kind == "enable_thinking_param":
            # Qwen/DeepSeek: reasoning_content already handled above, but also
            # strip any leftover <think> blocks in content just in case.
            cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()
    return cleaned


def _parse_tool_call_from_text(text: str) -> Optional[tuple]:
    """Parse tool call patterns from text.
    
    Looks for patterns like:
    - web_search("query")
    - web_search('query')
    - web_read("url")
    - web_check("url")
    - workshop_proposal("title", "client", "description")
    - workshop_search("query")
    - workshop_read("filepath")
    
    Returns (function_name, arguments_dict) or None if no pattern found.
    """
    if not text:
        return None
    
    import re
    
    # Define patterns for each tool
    patterns = [
        (r'web_search\s*\(\s*["\'](.+?)["\']\s*\)', 'web_search', {'query': 1}),
        (r'web_read\s*\(\s*["\'](.+?)["\']\s*\)', 'web_read', {'url': 1}),
        (r'web_check\s*\(\s*["\'](.+?)["\']\s*\)', 'web_check', {'url': 1}),
        (r'workshop_search\s*\(\s*["\'](.+?)["\']\s*\)', 'workshop_search', {'query': 1}),
        (r'workshop_read\s*\(\s*["\'](.+?)["\']\s*\)', 'workshop_read', {'filepath': 1}),
        (r'workshop_list\s*\(\s*\)', 'workshop_list', {}),
        (r'workshop_write\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'workshop_write', {'filepath': 1, 'content': 2}),
        (r'workshop_mkdir\s*\(\s*["\'](.+?)["\']\s*\)', 'workshop_mkdir', {'folder': 1}),
        (r'workshop_storage\s*\(\s*\)', 'workshop_storage', {}),
        (r'workshop_proposal\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'workshop_proposal', {'title': 1, 'client': 2, 'description': 3}),
        (r'workshop_account\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'workshop_account', {'platform': 1, 'username': 2, 'email': 3}),
        (r'workshop_payment\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'workshop_payment', {'method': 1, 'identifier': 2}),
        (r'file_read\s*\(\s*["\'](.+?)["\']\s*\)', 'file_read', {'path': 1}),
        (r'file_write\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'file_write', {'path': 1, 'content': 2}),
        (r'file_list\s*\(\s*["\'](.+?)["\']\s*\)', 'file_list', {'path': 1}),
        (r'run_command\s*\(\s*["\'](.+?)["\']\s*\)', 'run_command', {'command': 1}),
        (r'query_db\s*\(\s*["\'](.+?)["\']\s*\)', 'query_db', {'sql': 1}),
    ]
    
    for pattern, fn_name, arg_map in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            args = {}
            for arg_name, group_num in arg_map.items():
                try:
                    args[arg_name] = match.group(group_num)
                except IndexError:
                    args[arg_name] = ""
            return (fn_name, args)

    # Recovery for compact models that emit a BARE tool name (no quoted args)
    # followed by the URL/query on the same or the next line, e.g.
    #   web_read
    #   https://ugig.net/gigs/...
    # or "web_search\nthe bug fix bounty". Without this the call is treated as
    # prose and never executes (the small brain's observed failure). Only a
    # plausible URL (web_read/web_check) or a short query (web_search) is bound.
    bare = re.search(
        r"\b(web_read|web_check|web_search)\b[ \t]*(?:\(|\[)?[ \t]*\n?"
        r"[ \t]*(https?://\S+|\"[^\"]+\"|'[^']+'|[^\n]{3,120})",
        text, re.IGNORECASE,
    )
    if bare:
        fn = bare.group(1).lower()
        raw = bare.group(2).strip().strip("\"'")
        if fn == "web_search":
            if raw and not raw.lower().startswith(("http://", "https://")):
                return ("web_search", {"query": raw})
        else:  # web_read / web_check need a URL
            if raw.lower().startswith(("http://", "https://")):
                return (fn, {"url": raw})
    return None


__all__ = ["_remove_tool_syntax", "_remove_reasoning_channels", "_remove_think_blocks", "_visible_response_content", "_parse_tool_call_from_text"]
