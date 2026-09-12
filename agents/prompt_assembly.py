"""Shared prompt assembly helpers for the two model adapters."""


def assemble_role_prompt(
    base_prompt: str,
    role: str,
    query: str,
    personality,
    knowledge,
    extra: str = "",
    context_limit: int | None = None,
) -> str:
    """Append role-specific material in one predictable order.

    The caller owns the role contract and any model-specific tiering. This
    helper owns only the shared personality/context assembly and truncation.
    """
    prompt = base_prompt + extra
    prompt += personality.get_system_prompt_addon(role) or ""
    context = knowledge.build_context(role, query) or ""
    if context:
        if context_limit is not None:
            context = context[-context_limit:]
        prompt += f"\n\n# CURRENT CONTEXT\n{context}"
    return prompt