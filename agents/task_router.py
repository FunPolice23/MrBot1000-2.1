"""
Task router — classifies tasks and selects specialization + tools.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# Task types and their keywords
_TASK_TYPES = {
    "coding": ["code", "python", "script", "function", "class", "bug", "fix", "refactor", "implement", "api", "debug", "test"],
    "research": ["research", "find", "search", "look up", "docs", "documentation", "learn", "summarize", "what is", "explain"],
    "writing": ["write", "draft", "proposal", "cover letter", "email", "description", "content", "article"],
    "analysis": ["analyze", "evaluate", "compare", "metric", "report", "stats", "data", "opportunity", "score"],
    "verification": ["verify", "check", "validate", "fact-check", "confirm", "is this", "accurate"],
    "planning": ["plan", "roadmap", "breakdown", "steps", "milestone", "strategy", "timeline", "task list"],
    "browser": ["browse", "website", "form", "click", "navigate", "scrape", "extract", "web"],
}

# Tools available per task type
_TASK_TOOLS = {
    "coding": ["read_file", "write_file", "list_directory", "run_command", "query_database"],
    "research": ["web_search", "read_file", "list_directory", "query_database", "analyze_document"],
    "writing": ["read_file", "write_file", "list_directory", "web_search"],
    "analysis": ["read_file", "query_database", "list_directory", "web_search", "analyze_document"],
    "verification": ["read_file", "web_search", "query_database", "run_command"],
    "planning": ["read_file", "list_directory", "query_database", "write_file"],
    "browser": ["web_search", "read_file", "run_command", "query_database"],
}

# System prompt addons per specialization
_SPECIALIZATION_PROMPTS = {
    "coding": """
## CODING MODE
You are operating in coding mode. Write clean, tested, production-ready code.
- Use type hints and docstrings
- Follow PEP 8
- Add error handling
- Include usage examples
- Prefer stdlib first
""",
    "research": """
## RESEARCH MODE
You are operating in research mode. Gather and synthesize information.
- Cite sources when using web_search
- Distinguish facts from assumptions
- Prioritize recent information
- Structure findings clearly
""",
    "writing": """
## WRITING MODE
You are operating in writing mode. Produce clear, persuasive content.
- Match the requested tone
- Be concise but complete
- Use active voice
- Include calls to action where appropriate
""",
    "analysis": """
## ANALYSIS MODE
You are operating in analysis mode. Evaluate opportunities/data rigorously.
- Quantify when possible
- Identify risks and tradeoffs
- Rank options clearly
- Separate facts from opinions
""",
    "verification": """
## VERIFICATION MODE
You are operating in verification mode. Fact-check rigorously.
- Cross-reference multiple sources
- Flag unverifiable claims
- State confidence level
- Provide evidence for conclusions
""",
    "planning": """
## PLANNING MODE
You are operating in planning mode. Break goals into executable steps.
- Make steps atomic and verifiable
- Assign rough estimates
- Identify dependencies
- Highlight risks
""",
    "browser": """
## BROWSER AUTOMATION MODE
You are operating in browser automation mode. Interact with web interfaces carefully.
- Prefer API calls over scraping when possible
- Respect rate limits and robots.txt
- Describe actions clearly
- Flag any CAPTCHAs or anti-bot barriers
""",
}


def classify_task(text: str) -> str:
    """Classify a task by its primary type."""
    lower = text.lower().strip()
    scores = {}
    for task_type, keywords in _TASK_TYPES.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score:
            scores[task_type] = score
    
    if not scores:
        return "general"
    return max(scores, key=scores.get)


def get_tools_for_task(task_type: str) -> List[Dict]:
    """Get tool definitions appropriate for the task type."""
    from agents.tools import TOOL_DEFS
    tool_names = _TASK_TOOLS.get(task_type, ["read_file", "list_directory", "web_search"])
    return [t for t in TOOL_DEFS if t["function"]["name"] in tool_names]


def get_specialization_prompt(task_type: str) -> str:
    """Get the system prompt addon for a task type."""
    return _SPECIALIZATION_PROMPTS.get(task_type, "")


def get_all_tools() -> List[Dict]:
    """Get all available tool definitions."""
    from agents.tools import TOOL_DEFS
    return list(TOOL_DEFS)
