"""
MrBot1000/agents/coder.py — Coder Worker Agent

Specialization: Python code analysis and REAL file modification.
Uses safe_write_file() from base_worker for secure writes.

Grounding: every prompt is injected with the REAL project file tree
(see project_file_tree) so the model only references files that exist.
"""

from __future__ import annotations
import os
import ast
import re
import difflib
from pathlib import Path
from typing import List, Dict, Any

from library import AgentLogger, PromptBuilder, ResponseParser
from agents.base_worker import WorkerAgent, ROOT_FOLDER, project_file_tree, PROTECTED_SOURCE_FILES


class CoderWorker(WorkerAgent):
    """
    Coder Agent: Analyzes code problems and performs actual file modifications.

    Instead of just reporting what it would change, this agent actually writes
    the changes to files using safe_write_file().
    """

    TEAM_SKILLS = [
        "Python", "PySide6", "Qt", "SQLite", "LLM integration",
        "code refactoring", "debugging", "API development"
    ]

    CODER_SYSTEM = (
        "You are the Coder worker for MrBot1000, an autonomous AI freelance agency. "
        "You modify the project's Python source files using safe_write_file().\n"
        "CRITICAL RULES:\n"
        "  • ONLY reference files that appear in the PROJECT FILE TREE below. "
        "Files not listed there DO NOT EXIST — never invent filenames like source.py "
        "or _argcomplete.py.\n"
        "  • Return ONLY the complete, corrected file content. No markdown fences, "
        "no commentary outside the code.\n"
        "  • Preserve working code; change only what the issue requires.\n"
        "  • The file must remain valid Python (it will be syntax-checked before write).\n"
    )

    def __init__(self, api_key: str, log_signal=None, db=None):
        super().__init__(api_key, log_signal, db=db)
        self._logger = AgentLogger(db=db, source="CoderWorker", signal=log_signal)
        self._changes_made = 0

    def _codebase_context(self) -> str:
        return (
            "PROJECT FILE TREE (the only real files — do not reference others):\n"
            + project_file_tree() + "\n"
        )

    def analyze_and_fix(self, file_path: str, issue_description: str) -> dict:
        """Analyze a file and implement fixes (real write)."""
        result: Dict[str, Any] = {
            "file": file_path,
            "exists": False,
            "changes": [],
            "success": False,
            "notes": "",
        }

        if not os.path.exists(file_path):
            result["notes"] = f"File not found: {file_path}"
            return result

        result["exists"] = True

        # ── PROTECTED APP SOURCE GUARD (proactive coder-self-destruction backstop) ──
        # Never spend a model call trying to rewrite the app's own import-critical
        # source (main.py, manager.py, …). The truncation guard in base_worker also
        # protects these, but we refuse up-front so we don't burn an ~80s main-model
        # call on a doomed edit — and so a "prepare a proposal" gig task can never
        # be misinterpreted as a refactor of host source.
        _bn = os.path.basename(file_path)
        if _bn in PROTECTED_SOURCE_FILES:
            result["notes"] = (
                f"BLOCKED: protected app source '{_bn}' — refusing overwrite "
                f"(coder self-destruction guard). Proposal/refactor tasks must not "
                f"edit the application's own source.")
            return result

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
        except Exception as e:
            result["notes"] = f"Read error: {e}"
            return result

        prompt = PromptBuilder()
        prompt.context(self._codebase_context())
        prompt.context(f"File: {file_path}")
        prompt.context(f"Issue: {issue_description}")
        prompt.context(f"Current code:\n{original_content[:3000]}")
        prompt.instruction(
            "Fix the issue and return ONLY the complete fixed file content."
        )

        raw = self.llm(user=prompt.build(), system=self.CODER_SYSTEM, max_tokens=4000)

        if raw.startswith("ERROR:"):
            result["notes"] = f"LLM error: {raw}"
            return result

        fixed_content = re.sub(r"```[a-z]*\n?|```", "", raw).strip()

        # ── TRUNCATION GUARD (2.0.20g) ──────────────────────────────────────
        # analyze_and_fix sends only the first 3000 chars of the file to the LLM
        # but asks for the "complete fixed file". On large files the model returns
        # only what it saw and DROPS the rest, which would overwrite a 677-line
        # file with a ~94-line fragment (or 0 bytes). Refuse any rewrite that
        # shrinks a substantial file beyond a threshold so the original is kept.
        if not fixed_content:
            result["notes"] = "LLM returned empty content — refused (would erase file)"
            return result
        if len(original_content) > 500 and len(fixed_content) < 0.5 * len(original_content):
            drop_pct = int(100 * (1 - len(fixed_content) / len(original_content)))
            result["notes"] = (
                f"REFUSED: rewrite would truncate file by {drop_pct}% "
                f"({len(original_content)}→{len(fixed_content)} chars). "
                f"LLM likely dropped content — keeping original.")
            return result

        try:
            ast.parse(fixed_content)
        except SyntaxError as e:
            result["notes"] = f"Invalid Python (not written): {e}"
            return result

        original_lines = original_content.splitlines(keepends=True)
        fixed_lines = fixed_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            original_lines, fixed_lines,
            fromfile='original', tofile='fixed', lineterm=''
        ))
        result["changes"] = diff

        if self.safe_write_file(file_path, fixed_content):
            result["success"] = True
            result["notes"] = "File updated successfully"
            self._changes_made += 1
        else:
            result["notes"] = "Write blocked or failed"

        return result

    def file_write(self, file_path: str, content: str, verify: bool = True) -> dict:
        """Write content to a file with optional validation."""
        result: Dict[str, Any] = {
            "file": file_path,
            "success": False,
            "size": len(content),
            "notes": "",
        }

        if verify:
            try:
                ast.parse(content)
            except SyntaxError as e:
                result["notes"] = f"Invalid Python: {e}"
                return result

        if self.safe_write_file(file_path, content):
            result["success"] = True
            result["notes"] = "File written successfully"
            self._changes_made += 1
        else:
            result["notes"] = "Write failed"

        return result

    def refactor(self, file_path: str, refactor_instructions: List[str]) -> dict:
        """Apply refactoring instructions to a file (real write)."""
        if not os.path.exists(file_path):
            return {"success": False, "notes": f"File not found: {file_path}"}

        with open(file_path, 'r', encoding='utf-8') as f:
            original = f.read()

        instructions_text = "\n".join(f"- {i}" for i in refactor_instructions)
        prompt = PromptBuilder()
        prompt.context(self._codebase_context())
        prompt.context(f"File: {file_path}")
        prompt.context(f"Refactor instructions:\n{instructions_text}")
        prompt.context(f"Current content:\n{original[:3000]}")
        prompt.instruction(
            "Apply these refactoring changes and return ONLY the complete file content."
        )

        raw = self.llm(user=prompt.build(), system=self.CODER_SYSTEM, max_tokens=4000)
        fixed = re.sub(r"```[a-z]*\n?|```", "", raw).strip()

        # ── TRUNCATION GUARD (2.0.20g) ── refuse rewrites that would shrink a
        # substantial file (LLM dropped content). Keeps the original intact.
        if not fixed:
            return {"success": False, "notes": "LLM returned empty content — refused"}
        if len(original) > 500 and len(fixed) < 0.5 * len(original):
            drop_pct = int(100 * (1 - len(fixed) / len(original)))
            return {"success": False,
                    "notes": f"REFUSED: rewrite would truncate by {drop_pct}% — keeping original"}

        if self.safe_write_file(file_path, fixed):
            return {"success": True, "notes": "Refactoring applied"}
        return {"success": False, "notes": "Write failed"}


# Register this worker automatically
def register_worker(registry):
    from agents.base_worker import WORKER_REGISTRY
    WORKER_REGISTRY["Coder"] = CoderWorker
