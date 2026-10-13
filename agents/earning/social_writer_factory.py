"""Build the confirmed social writer for the social_post tool (Phase E).

The social_post tool (agents/safety/handlers.py) refuses to post unless a
confirmed write endpoint is wired via ``set_social_writer``. This factory is the
ONE place that wires it — a real MoltbookPoster over requests — and it is only
installed when a Moltbook API key is present. Left uninstalled, social_post
refuses cleanly (never fabricates a post).

The writer the tool calls takes a single dict payload
``{network, content, approval_id}`` and returns a human-readable result string.
It ALWAYS posts with ``capability_approved=True`` because the tool has already
verified an APPROVED approval item before invoking the writer.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def build_moltbook_writer() -> Optional[Callable[[dict], str]]:
    """Return a social_post writer backed by a real MoltbookPoster, or None.

    Returns None (no writer) when MOLTBOOK_API_KEY is unset or requests is
    unavailable — the social_post tool then refuses rather than faking a post.
    """
    import os

    if not os.getenv("MOLTBOOK_API_KEY", "").strip():
        return None
    try:
        import requests  # noqa: F401
    except Exception:
        return None

    from agents.earning.moltbook_agent import MoltbookPoster

    poster = MoltbookPoster(http_client=requests, api_key=os.getenv("MOLTBOOK_API_KEY", ""))

    def _writer(payload: dict) -> str:
        network = str(payload.get("network", "")).strip().lower()
        content = str(payload.get("content", "")).strip()
        submolt = str(payload.get("submolt_name", "general")).strip() or "general"
        post_id = str(payload.get("post_id", "")).strip()
        parent_id = str(payload.get("parent_id", "")).strip()
        if network not in ("moltbook", ""):
            return f"unsupported network '{network}' (only moltbook is wired)"
        try:
            if post_id:
                # Reply / comment on an existing post.
                result = poster.reply_to_post(
                    post_id, content, parent_id=parent_id,
                    capability_approved=True)
            else:
                # New post. First line becomes the title (<=300 chars); the rest
                # is the body. Never invents content — it uses exactly what the
                # human approved.
                lines = content.split("\n", 1)
                title = lines[0][:300]
                body = lines[1] if len(lines) > 1 else ""
                result = poster.create_post(
                    submolt, title, body, capability_approved=True)
        except Exception as exc:
            return f"post failed: {exc}"
        status = result.get("status", "unknown")
        if status == "pending_verification":
            return (f"submitted but PENDING VERIFICATION (solve the moltbook "
                    f"challenge before it is visible): {result.get('verification')}")
        if status in ("posted", "commented"):
            # The API echoes the created object under post/comment; unwrap the
            # nested id so the human sees a concrete reference.
            obj = result.get("post") if status == "posted" else result.get("comment")
            obj = obj or {}
            ref = obj.get("id") or obj.get("post_id") or obj.get("comment_id") or ""
            if not ref and isinstance(obj.get("post"), dict):
                ref = obj["post"].get("id", "")
            return f"{status}" + (f" (id {ref})" if ref else "")
        return f"not posted — {result.get('reason', status)}"

    return _writer


__all__ = ["build_moltbook_writer"]
