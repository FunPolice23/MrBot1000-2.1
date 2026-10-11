"""Pure manager intent and worker-routing policies."""

from __future__ import annotations


INTENT_KEYWORDS = {
    "task": [
        "improve", "fix", "refactor", "add", "implement", "update",
        "create", "optimize", "scan", "review", "build", "write",
    ],
    "question": [
        "what", "how", "why", "which", "when", "status", "explain",
        "tell me", "describe", "show", "list", "report",
    ],
    "command": [
        "pause", "stop", "start", "reset", "clear", "run", "execute",
        "assign", "search", "scan jobs",
    ],
}

WORKER_ROUTING = {
    "JobSearch": [
        "job", "gig", "find work", "search", "fiverr", "upwork",
        "freelance", "earn", "apply", "listing",
    ],
    "Analyst": [
        "analyse", "analyze", "metric", "report", "complexity",
        "duplicate", "quality", "debt", "chart", "stats",
    ],
    "Summarizer": [
        "summary", "explain", "simplify", "translate", "describe",
        "what happened", "tldr", "recap",
    ],
    "Coder": [
        "code", "bug", "fix", "refactor", "implement", "write",
        "function", "class", "module", "file", "python",
    ],
}


def classify_intent(text: str) -> str:
    lower = text.lower().strip()
    scores = {
        intent: sum(1 for keyword in keywords if keyword in lower)
        for intent, keywords in INTENT_KEYWORDS.items()
    }
    first_word = lower.split()[0] if lower.split() else ""
    if first_word in ("pause", "resume", "stop", "start", "reset", "clear"):
        return "command"
    if "?" in text:
        return "question"
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "question"


def route_to_worker(text: str) -> str:
    lower = text.lower()
    scores = {
        role: sum(1 for keyword in keywords if keyword in lower)
        for role, keywords in WORKER_ROUTING.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Coder"


__all__ = [
    "INTENT_KEYWORDS",
    "WORKER_ROUTING",
    "classify_intent",
    "route_to_worker",
]
