import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from agents.shared_context import get_shared_context


def _format_lifecycle_status(lifecycle: List[dict], compact: bool = True) -> str:
    """Return a compact, human-readable lifecycle summary for chat prompts."""
    if not lifecycle:
        return ""

    if not compact:
        return "=== Opportunity Lifecycle ===\n" + json.dumps(lifecycle, indent=2)

    lines = ["=== Opportunity Status Report ==="]
    active_count = sum(1 for item in lifecycle if (item.get("status") or "").lower() not in {"failed", "paid"})
    completed_count = sum(1 for item in lifecycle if (item.get("status") or "").lower() in {"paid", "failed"})
    priority_focus = "follow up" if active_count else "review completed outcomes"
    primary_action = "Act on the highest-priority opening now." if active_count else "Review completed outcomes and close the loop on payouts."
    lines.append(f"Overall: {active_count} active opportunity(s) tracked and {completed_count} completed/closed.")
    lines.append(f"Board-ready snapshot: prioritize {priority_focus}.")
    lines.append(f"Primary action: {primary_action}")

    ranked_items = sorted(
        lifecycle[-5:],
        key=lambda item: (
            0 if (item.get("status") or "").lower() in {"active", "in_progress", "submitted", "researching"} else 1,
            -(float(item.get("last_amount") or 0.0)),
        ),
    )

    for index, item in enumerate(ranked_items, start=1):
        opp_id = item.get("opportunity_id", "unknown")
        stage = item.get("current_stage", "unknown")
        status = item.get("status", "unknown")
        amount = item.get("last_amount") or 0.0
        note = item.get("note") or ""
        amount_text = f"${amount:,.2f}" if isinstance(amount, (int, float)) else str(amount)
        if status.lower() in {"active", "in_progress", "submitted", "researching"}:
            recommendation = "Act now"
            if stage.lower() in {"submitted", "in_progress"}:
                recommendation = "Follow up now"
        else:
            recommendation = "Confirm outcome"
        line = f"- {opp_id}: Stage: {stage} | Status: {status} | Amount: {amount_text}"
        if note:
            line += f" | Note: {note}"
        priority_label = "High" if recommendation == "Act now" else "Medium"
        line += f" | Recommendation: {recommendation}."
        line += f" | Priority: {priority_label}."
        if index == 1 and recommendation == "Act now":
            line += " Highest priority opportunity."
        lines.append(line)

    return "\n".join(lines)


@dataclass
class ChatDecision:
    route_to: str
    use_main_model: bool
    reason: str


class ChatRouter:
    """Route human chat between chat and main-model workflows while building runtime context."""

    def __init__(self):
        self.chat_keywords = [
            "what", "who", "when", "where", "why", "how", "explain", "tell me",
            "summarize", "status", "what happened", "describe", "show me", "report"
        ]
        self.main_keywords = [
            "analyze", "analysis", "review", "inspect", "compare", "evaluate", "score",
            "job search", "opportunity", "report", "results", "metrics", "best", "recommend"
        ]
        self.task_keywords = [
            "fix", "implement", "add", "update", "create", "refactor", "optimize",
            "change", "build", "write", "modify", "debug", "improve"
        ]

    def classify(self, message: str) -> ChatDecision:
        text = (message or "").lower()
        if any(keyword in text for keyword in self.task_keywords):
            return ChatDecision(route_to="manager", use_main_model=True, reason="task")

        if any(keyword in text for keyword in self.main_keywords):
            return ChatDecision(route_to="summarizer", use_main_model=True, reason="analysis")

        return ChatDecision(route_to="summarizer", use_main_model=False, reason="conversation")

    def build_runtime_context(self, research_folder: Optional[str], user_message: str = "",
                               lifecycle=None, evidence_store=None, memory=None) -> str:
        """Build chat context.

        P3 (comms redesign): prefer LIVE authoritative services (lifecycle
        tracker / evidence_store / earning_memory) when supplied, so the Chat
        model sees current state without a JSON-file round-trip. Falls back to
        the legacy SharedContext JSON file when no live provider is given.
        """
        folder = Path(research_folder or "")
        parts: List[str] = []

        try:
            # ── Live authoritative providers (preferred, P3 comms redesign) ──
            if lifecycle is not None:
                try:
                    snap = lifecycle.get_all_states() if hasattr(lifecycle, "get_all_states") \
                        else getattr(lifecycle, "_states", {})
                    if isinstance(snap, dict):
                        lifecycle_rows = [v.to_dict() if hasattr(v, "to_dict") else v
                                          for v in snap.values()]
                    else:
                        lifecycle_rows = snap or []
                    if lifecycle_rows:
                        compact_report = _format_lifecycle_status(lifecycle_rows, compact=True)
                        if compact_report:
                            parts.append(compact_report)
                except Exception:
                    pass
            elif evidence_store is not None or memory is not None:
                try:
                    if memory is not None and hasattr(memory, "get_opportunity_history"):
                        hist = memory.get_opportunity_history("__all__") or []
                        if hist:
                            parts.append(_format_lifecycle_status(hist, compact=True))
                except Exception:
                    pass
            else:
                # ── Legacy SharedContext JSON fallback (read-only) ──────────
                shared_context_path = None
                if folder.exists():
                    for candidate in [
                        folder / "shared_context.json",
                        folder / "shared.json",
                        folder / ".shared_context.json",
                    ]:
                        if candidate.exists():
                            shared_context_path = str(candidate)
                            break
                    if not shared_context_path:
                        for candidate in sorted(folder.rglob("shared*.json")):
                            if candidate.is_file():
                                shared_context_path = str(candidate)
                                break
                if not shared_context_path:
                    shared_context_path = os.getenv("SHARED_CONTEXT_PATH") or os.getenv("MRBOT_SHARED_CONTEXT_PATH")

                shared_context = get_shared_context(shared_context_path) if shared_context_path else get_shared_context()
                lifecycle = shared_context.get_opportunity_lifecycle()
                if lifecycle:
                    compact_enabled = os.getenv("COMPACT_STATUS_REPORTS", "true").lower() == "true"
                    compact_report = _format_lifecycle_status(lifecycle, compact=compact_enabled)
                    if compact_report:
                        parts.append(compact_report)

                research_snapshot = shared_context.get_latest_research_snapshot()
                if research_snapshot:
                    path = research_snapshot.get("research_path") or "(not set)"
                    count = research_snapshot.get("research_file_count", 0)
                    excerpt = (research_snapshot.get("research_excerpt") or "").strip()
                    if excerpt:
                        excerpt = excerpt[:2500]
                    parts.append(
                        "=== SHARED RESEARCH SNAPSHOT ===\n"
                        f"Folder: {path}\n"
                        f"Files scanned: {count}\n"
                        f"Research excerpt:\n{excerpt or '(no excerpt available)'}"
                    )
        except Exception:
            pass

        if not folder.exists():
            if parts:
                header = f"User question: {user_message}\n"
                return header + "\n\n".join(parts)
            return "(no runtime context available)"

        allowed_ext = {".json", ".txt", ".md", ".py", ".yaml", ".yml", ".csv"}

        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in allowed_ext:
                continue
            if path.name.startswith("."):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if path.name.lower().startswith("shared") or "context" in path.name.lower():
                continue

            if path.suffix.lower() == ".json":
                try:
                    payload = json.loads(text)
                    preview = json.dumps(payload, indent=2)[:6000]
                except Exception:
                    preview = text[:6000]
            else:
                preview = text[:5000]

            if not preview.strip():
                continue

            if path.name.endswith(".json"):
                parts.append(f"=== {path.name} ===\n{preview}")
            elif "job" in path.name.lower() or "analysis" in path.name.lower() or "report" in path.name.lower() or "knowledge" in path.name.lower():
                parts.append(f"=== {path.name} ===\n{preview}")

        if not parts:
            return "(no relevant runtime context files found)"

        header = f"User question: {user_message}\n"
        return header + "\n\n".join(parts[:8])
