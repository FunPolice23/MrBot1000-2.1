"""Prompting Engine for MrBot1000 — adaptive prompt construction.

Maps the best prompting technique to each task type and brain role:
- ToT (Tree of Thought): multi-path exploration for complex research/planning
- CoT (Chain of Thought): step-by-step reasoning for dialogue/discussion
- ReAct + CoT + tools: dynamic decision-making with tool execution
- Skeleton of Thought: structured outlines for proposals/articles
- Agentic: autonomous goal-seeking with tool loops
- Prompt chaining: multi-step workflows (research → plan → execute)
- Meta prompting: self-critique and refinement
- Zero/Few-shot: examples for specific output formats

Memory integration:
- Short-term: conversation context, recent tool results
- Long-term: successful prompt patterns per task type (stored in db)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

# Prompting techniques mapped to use cases
TECHNIQUES = {
    "cot": {
        "name": "chain_of_thought",
        "description": "Step-by-step reasoning inline. Good for quick dialogue, simple Q&A.",
        "prompt_suffix": "\nThink step by step.",
        "use_when": ["dialogue", "quick_qa", "simple_calculation", "factual_lookup"],
    },
    "tot": {
        "name": "tree_of_thought",
        "description": "Explore multiple reasoning paths before converging. Good for research/planning.",
        "prompt_suffix": (
            "\nConsider 3 different approaches to this problem. "
            "For each approach, evaluate pros/cons. "
            "Then choose the best path and explain why."
        ),
        "use_when": ["research", "planning", "strategy", "comparison", "evaluation", "deep_analysis"],
    },
    "react_cot_tools": {
        "name": "react_cot_tools",
        "description": "Observe → Reason → Act loop with thinking. Good for dynamic decisions.",
        "prompt_suffix": (
            "\nFor each step: observe what you know, reason about what to do next, "
            "then either use a tool or give your final answer. "
            "Always think before acting."
        ),
        "use_when": ["dynamic_decision", "opportunity_evaluation", "workflow_execution", "multi_step_task"],
    },
    "skeleton_thought": {
        "name": "skeleton_of_thought",
        "description": "First outline the structure, then fill in. Good for proposals/articles.",
        "prompt_suffix": (
            "\nFirst, outline the structure (key sections/points). "
            "Then expand each section with specific, actionable content."
        ),
        "use_when": ["proposal", "article", "report", "course_plan", "structured_output"],
    },
    "agentic": {
        "name": "agentic",
        "description": "Autonomous loop: perceive → plan → execute → verify. Good for complex goals.",
        "prompt_suffix": (
            "\nYou are an autonomous agent working toward a goal. "
            "1) Perceive: what do you know? What's missing?\n"
            "2) Plan: what's the next concrete step?\n"
            "3) Execute: call a tool or produce output.\n"
            "4) Verify: did it work? What next?\n"
            "Loop until the goal is reached or you need human input."
        ),
        "use_when": ["complex_goal", "multi_tool_workflow", "autonomous_research", "self_directed_task"],
    },
    "prompt_chaining": {
        "name": "prompt_chaining",
        "description": "Chain multiple sub-prompts where each output feeds the next. Good for pipelines.",
        "prompt_suffix": (
            "\nBreak this into sub-tasks. Complete each one before moving to the next. "
            "Output intermediate results so the next step can build on them."
        ),
        "use_when": ["pipeline", "multi_stage", "research_then_plan", "analyze_then_write"],
    },
    "meta_prompting": {
        "name": "meta_prompting",
        "description": "Self-critique: generate → critique → refine. Good for high-stakes outputs.",
        "prompt_suffix": (
            "\nGenerate your response, then critique it: "
            "what's weak, what's missing, what could be wrong? "
            "Then produce a refined version."
        ),
        "use_when": ["high_stakes", "final_submission", "proposal_review", "self_critique"],
    },
    "few_shot": {
        "name": "few_shot",
        "description": "Provide 2-3 examples to steer output format. Good for structured outputs.",
        "prompt_suffix": "",  # examples injected separately
        "use_when": ["format_specific", "classification", "extraction", "templated_output"],
    },
}


def select_technique(task_type: str, context: Optional[Dict] = None) -> str:
    """Select the best prompting technique for a task type.
    
    Returns the technique key (e.g. "tot", "cot", "react_cot_tools").
    """
    context = context or {}
    urgency = context.get("urgency", "normal")  # urgent, normal, deep
    complexity = context.get("complexity", "medium")  # low, medium, high
    has_tools = context.get("has_tools", True)
    
    # Urgent/simple → CoT (fastest)
    if urgency == "urgent" or complexity == "low":
        return "cot"
    
    # Deep research/planning → ToT (most thorough)
    if complexity == "high" and task_type in ("research", "planning", "strategy"):
        return "tot"
    
    # Dynamic decisions with tools → ReAct + CoT
    if task_type in ("dynamic_decision", "opportunity_evaluation", "workflow_execution"):
        return "react_cot_tools"
    
    # Structured writing → Skeleton of Thought
    if task_type in ("proposal", "article", "report", "course_plan"):
        return "skeleton_thought"
    
    # Complex multi-step goals → Agentic
    if task_type in ("complex_goal", "multi_tool_workflow", "autonomous_research"):
        return "agentic"
    
    # Pipeline tasks → Prompt Chaining
    if task_type in ("pipeline", "multi_stage"):
        return "prompt_chaining"
    
    # High-stakes outputs → Meta Prompting
    if context.get("high_stakes") or task_type in ("final_submission", "proposal_review"):
        return "meta_prompting"
    
    # Default: CoT for most dialogue, ToT for analysis
    if task_type in ("dialogue", "quick_qa"):
        return "cot"
    if task_type in ("analysis", "evaluation", "comparison"):
        return "tot"
    
    return "cot"


def get_technique_suffix(technique_key: str) -> str:
    """Get the prompt suffix for a technique."""
    tech = TECHNIQUES.get(technique_key, TECHNIQUES["cot"])
    return tech.get("prompt_suffix", "")


def build_few_shot_examples(task_type: str) -> List[Dict[str, str]]:
    """Return few-shot examples for a task type.
    
    Each example has 'input' and 'output' keys.
    """
    examples = {
        "opportunity_evaluation": [
            {
                "input": "Evaluate: Python data scraping gig on Upwork, $50 budget, no experience required.",
                "output": (
                    "VERDICT: LOW PRIORITY (0.35)\n"
                    "REASON: Saturated market, low barrier = high competition. $50 budget is below optimal threshold.\n"
                    "RECOMMENDATION: Skip unless you have portfolio pieces to differentiate."
                ),
            },
            {
                "input": "Evaluate: Custom LLM fine-tuning for legal docs, $500 budget, 2-week deadline, matches our skills.",
                "output": (
                    "VERDICT: HIGH PRIORITY (0.85)\n"
                    "REASON: Niche domain, good budget, matches our LLM expertise, tight deadline filters competitors.\n"
                    "RECOMMENDATION: Apply with targeted proposal highlighting past LLM work."
                ),
            },
        ],
        "course_recommendation": [
            {
                "input": "Recommend courses for: learning to build AI agents with local LLMs.",
                "output": (
                    "TIER 1 (Start here):\n"
                    "- 'Building AI Agents with LangChain' (Coursera, free audit)\n"
                    "- 'Local LLM Fine-Tuning' (HuggingFace docs, hands-on)\n\n"
                    "TIER 2 (Deepen):\n"
                    "- 'Advanced RAG Systems' (DeepLearning.AI)\n"
                    "- 'CUDA Programming for LLMs' (NVIDIA DLI, if GPU work)\n\n"
                    "TIER 3 (Specialize):\n"
                    "- 'Production LLM Deployment' (O'Reilly)\n"
                    "- 'Reinforcement Learning from Human Feedback' (Stanford CS224N)"
                ),
            },
        ],
    }
    return examples.get(task_type, [])


def adaptive_prompt(
    task_type: str,
    base_prompt: str,
    context: Optional[Dict] = None,
    examples: Optional[List[Dict]] = None,
) -> str:
    """Construct an adaptive prompt with the right technique + memory.
    
    Args:
        task_type: Type of task (research, dialogue, planning, etc.)
        base_prompt: The core system/user prompt
        context: Dict with urgency, complexity, has_tools, high_stakes, etc.
        examples: Optional few-shot examples to prepend
    
    Returns:
        The enhanced prompt with technique suffix + examples.
    """
    context = context or {}
    technique = select_technique(task_type, context)
    suffix = get_technique_suffix(technique)
    
    parts = [base_prompt]
    
    # Inject few-shot examples if provided or if task benefits from them
    if examples is None and technique == "few_shot":
        examples = build_few_shot_examples(task_type)
    
    if examples:
        example_block = "\n\n# EXAMPLES\n"
        for i, ex in enumerate(examples, 1):
            example_block += f"\nExample {i}:\nInput: {ex['input']}\nOutput: {ex['output']}\n"
        parts.append(example_block)
    
    # Inject technique guidance
    if suffix:
        parts.append(f"\n{suffix}")
    
    # Inject memory of what worked before (from long-term memory)
    memory_suffix = _memory_suffix_for_task(task_type)
    if memory_suffix:
        parts.append(f"\n# WHAT WORKED BEFORE\n{memory_suffix}")
    
    return "\n".join(parts)


def _memory_suffix_for_task(task_type: str) -> str:
    """Retrieve memory of successful patterns for a task type.
    
    Reads from the long-term memory store in the database.
    Returns a short string with tips, or empty string if none.
    """
    try:
        from database import AgentDB
        db = AgentDB()
        # Query for recent successful prompt patterns
        row = db.fetchone(
            "SELECT detail FROM prompt_memory WHERE task_type = ? "
            "ORDER BY success_count DESC, last_used DESC LIMIT 1",
            (task_type,),
        )
        if row and row[0]:
            data = json.loads(row[0]) if isinstance(row[0], str) else {}
            tips = data.get("tips", [])
            if tips:
                return "; ".join(tips[:3])  # Top 3 tips
    except Exception:
        pass
    return ""


def record_successful_pattern(task_type: str, technique: str, tips: List[str], success: bool = True):
    """Record a successful/unsuccessful prompt pattern for future use.
    
    Called after a task completes to remember what worked.
    """
    try:
        from database import AgentDB
        db = AgentDB()
        # Ensure table exists
        db.execute("""
            CREATE TABLE IF NOT EXISTS prompt_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                technique TEXT NOT NULL,
                detail TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Upsert pattern
        existing = db.fetchone(
            "SELECT id, success_count, fail_count FROM prompt_memory "
            "WHERE task_type = ? AND technique = ?",
            (task_type, technique),
        )
        detail = json.dumps({"tips": tips, "technique_meta": TECHNIQUES.get(technique, {})})
        if existing:
            if success:
                db.execute(
                    "UPDATE prompt_memory SET success_count = success_count + 1, "
                    "last_used = CURRENT_TIMESTAMP, detail = ? WHERE id = ?",
                    (detail, existing[0]),
                )
            else:
                db.execute(
                    "UPDATE prompt_memory SET fail_count = fail_count + 1, "
                    "last_used = CURRENT_TIMESTAMP WHERE id = ?",
                    (existing[0],),
                )
        else:
            db.execute(
                "INSERT INTO prompt_memory (task_type, technique, detail, success_count, fail_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_type, technique, detail, 1 if success else 0, 0 if success else 1),
            )
        db.commit()
    except Exception:
        pass  # Non-critical — memory recording should never break the main flow


def get_brain_recommendation(brain_role: str, task_type: str, model_path: str = "", model_name: str = "") -> Dict[str, Any]:
    """Get recommendations for which prompting technique to use.
    
    Model-agnostic: detects actual model capabilities from metadata/name,
    not from which brain slot it fills. A 3B model in Big Brain slot gets
    fast techniques; a 27B model in Small Brain slot gets heavy techniques.
    
    Returns dict with recommended_technique, context overrides.
    """
    # Detect model param size from name or metadata
    param_b = _detect_param_size(model_path, model_name)
    
    # Heavy models (14B+): ToT, agentic, meta — complex reasoning
    if param_b >= 14:
        if task_type in ("research", "planning", "strategy"):
            return {"recommended_technique": "tot", "complexity": "high", "urgency": "normal"}
        if task_type in ("dynamic_decision", "opportunity_evaluation"):
            return {"recommended_technique": "react_cot_tools", "complexity": "high", "has_tools": True}
        if task_type in ("complex_goal", "multi_tool_workflow"):
            return {"recommended_technique": "agentic", "complexity": "high"}
        if task_type in ("proposal", "article", "report"):
            return {"recommended_technique": "skeleton_thought", "complexity": "high"}
        return {"recommended_technique": "cot", "complexity": "medium"}
    
    # Medium models (7-14B): balanced — CoT, ReAct, prompt chaining
    if param_b >= 7:
        if task_type in ("research", "planning"):
            return {"recommended_technique": "tot", "complexity": "medium", "urgency": "normal"}
        if task_type in ("dynamic_decision", "opportunity_evaluation"):
            return {"recommended_technique": "react_cot_tools", "complexity": "medium", "has_tools": True}
        if task_type in ("proposal", "article"):
            return {"recommended_technique": "skeleton_thought", "complexity": "medium"}
        if task_type in ("pipeline", "multi_stage"):
            return {"recommended_technique": "prompt_chaining", "complexity": "medium"}
        return {"recommended_technique": "cot", "complexity": "medium"}
    
    # Small models (<7B): fast, focused — CoT, few-shot, prompt chaining
    if task_type in ("dialogue", "quick_qa"):
        return {"recommended_technique": "cot", "complexity": "low", "urgency": "urgent"}
    if task_type in ("format_specific", "extraction", "classification"):
        return {"recommended_technique": "few_shot", "complexity": "low"}
    if task_type in ("pipeline", "multi_stage"):
        return {"recommended_technique": "prompt_chaining", "complexity": "low"}
    return {"recommended_technique": "cot", "complexity": "low"}


def _detect_param_size(model_path: str = "", model_name: str = "") -> float:
    """Detect model parameter count in billions.
    
    Tries multiple sources:
    1. Model name (e.g. "Qwen3-27B", "Llama-3.2-3B")
    2. GGUF metadata (general.size_param or similar)
    3. File size heuristic (if all else fails)
    
    Returns param count in billions (e.g. 27.0 for 27B model).
    """
    # Try model name first
    name = model_name or model_path or ""
    if name:
        name_lower = name.lower()
        import re
        # Match "number" followed by "b" followed by separator or end
        # e.g. "4b_thinking" → 4, "27b-ud" → 27, "3b" at end → 3
        match = re.search(r"(?:^|[-_])(\d+\.?\d*)b(?:[-_]|$)", name_lower)
        if match:
            return float(match.group(1))
    
    # Try GGUF metadata
    if model_path:
        try:
            from agents.gguf_meta import read_metadata
            meta = read_metadata(model_path) or {}
            # GGUF stores size_param as number of params
            size_param = meta.get("general.size_param") or meta.get("general.parameters")
            if size_param:
                return float(size_param) / 1e9
        except Exception:
            pass
    
    # Default: assume medium (7B) if we can't detect
    return 7.0
