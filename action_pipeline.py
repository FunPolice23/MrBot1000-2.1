"""
action_pipeline.py — Controlled Action Pipeline for MrBot1000

Every proposed action (file creation, code modification, self-improvement)
passes through this pipeline before execution:

  1. PROPOSE  — agent describes the action in structured form
  2. VALIDATE — syntax check, API usage scan, null/error pattern check,
                spelling check (via Summarizer), import validation
  3. APPROVE  — Manager decides yes/no based on validation report
  4. EXECUTE  — only after approval; write file, run formatter, log result
  5. NOTIFY   — emit signal so UI + DB record the outcome

All actions are stored in the DB with their validation result and
execution outcome so the system can learn which proposals are good.
"""

from __future__ import annotations

import ast
import os
import re
import time
import json
import keyword
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple

ROOT_FOLDER = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────────────────────────────────────
#  Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProposedAction:
    """A structured action proposed by any agent."""
    action_type: str          # "create_file" | "modify_file" | "delete_file" |
                              # "run_code" | "self_improve" | "assist_agent"
    proposer:    str          # e.g. "Coder", "Manager"
    description: str          # human-readable description
    target_path: str = ""     # relative path within ROOT_FOLDER
    code:        str = ""     # code/content being proposed
    metadata:    Dict = field(default_factory=dict)
    proposal_id: str = ""

    def __post_init__(self):
        if not self.proposal_id:
            self.proposal_id = f"{self.proposer}_{int(time.time() * 1000) % 1_000_000}"


@dataclass
class ValidationResult:
    passed:   bool
    score:    float           # 0.0 – 1.0
    errors:   List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    fixed_code: Optional[str] = None   # auto-corrected version if available

    @property
    def summary(self) -> str:
        parts = []
        if self.errors:
            parts.append(f"ERRORS({len(self.errors)}): " +
                         "; ".join(self.errors[:3]))
        if self.warnings:
            parts.append(f"WARN({len(self.warnings)}): " +
                         "; ".join(self.warnings[:2]))
        return " | ".join(parts) if parts else "CLEAN"


@dataclass
class ExecutionResult:
    success:  bool
    message:  str
    path:     str = ""
    duration: float = 0.0
    skipped:  bool = False


# ─────────────────────────────────────────────────────────────────────────────
#  Validators
# ─────────────────────────────────────────────────────────────────────────────

class SyntaxValidator:
    """Parse Python source with ast.parse — catches all syntax errors."""

    @staticmethod
    def validate(code: str) -> ValidationResult:
        errors, warnings = [], []
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(False, 0.0,
                                    errors=[f"SyntaxError line {e.lineno}: {e.msg}"])
        except Exception as e:
            return ValidationResult(False, 0.0,
                                    errors=[f"Parse error: {e}"])

        # Walk the AST for common issues
        for node in ast.walk(tree):
            # Bare except (catches everything including KeyboardInterrupt)
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                warnings.append(
                    f"Line {node.lineno}: bare 'except:' — specify exception type")

            # print() left in production code
            if (isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and
                    node.func.id == "print"):
                warnings.append(f"Line {node.lineno}: print() in production code")

            # exec() / eval() — security risk
            if (isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and
                    node.func.id in ("exec", "eval")):
                errors.append(f"Line {node.lineno}: {node.func.id}() is forbidden")

            # Shadowing builtins
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args:
                    if arg.arg in dir(__builtins__) or keyword.iskeyword(arg.arg):
                        warnings.append(
                            f"Line {node.lineno}: arg '{arg.arg}' shadows builtin/keyword")

        score = 1.0 - len(errors) * 0.5 - len(warnings) * 0.05
        return ValidationResult(not errors, max(0.0, score), errors, warnings)


class ApiUsageValidator:
    """
    Check that any API calls in the code use known, valid patterns.
    Flags hallucinated method names on known libraries.
    """

    # Known safe patterns per library prefix
    KNOWN_PATTERNS: Dict[str, List[str]] = {
        "os.":        ["path", "getcwd", "listdir", "makedirs", "remove",
                       "rename", "environ", "getenv", "sep", "walk"],
        "Path":       ["read_text", "write_text", "exists", "mkdir", "glob",
                       "rglob", "stat", "name", "stem", "suffix", "parent",
                       "resolve", "relative_to", "as_posix", "unlink"],
        "sqlite3.":   ["connect", "Row", "IntegrityError"],
        "json.":      ["loads", "dumps", "load", "dump"],
        "re.":        ["search", "match", "findall", "sub", "compile",
                       "IGNORECASE", "DOTALL", "split"],
        "time.":      ["time", "sleep", "monotonic"],
        "threading.": ["Lock", "Thread", "Event"],
        "groq.":      ["Groq"],
    }

    # Patterns that look like hallucinated API calls
    SUSPICIOUS_PATTERNS = [
        r"\.generate\s*\(",        # LLM hallucination common pattern
        r"openai\.",               # Wrong API
        r"anthropic\.",            # Not used here
        r"langchain\.",            # Not a dependency
        r"\.embed\s*\(",           # No embedding endpoint configured
        r"requests\.async",       # Doesn't exist
        r"asyncio\.run_forever",  # Misuse
    ]

    @staticmethod
    def validate(code: str) -> ValidationResult:
        errors, warnings = [], []

        for pat in ApiUsageValidator.SUSPICIOUS_PATTERNS:
            matches = re.findall(pat, code)
            if matches:
                errors.append(f"Suspicious API call: {pat.strip()} "
                               f"({len(matches)} occurrence(s))")

        # Check groq client usage pattern
        if "groq" in code.lower():
            if "Groq(" in code and "api_key" not in code:
                warnings.append("Groq() called without api_key argument")
            if ".create(" in code and "max_tokens" not in code:
                warnings.append("LLM .create() call missing max_tokens")

        score = 1.0 - len(errors) * 0.4 - len(warnings) * 0.05
        return ValidationResult(not errors, max(0.0, score), errors, warnings)


class NullSafetyValidator:
    """
    Detect common null/None safety issues and bad attribute access patterns.
    """

    @staticmethod
    def validate(code: str) -> ValidationResult:
        errors, warnings = [], []
        lines = code.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Chained access without None check after function returning Optional
            if re.search(r'\)\.\w+', stripped) and "if " not in stripped:
                # Only warn on complex chains
                if stripped.count('.') >= 3:
                    warnings.append(
                        f"Line {i}: deep attribute chain without None guard")

            # dict access without .get()
            if re.search(r'\w+\[[\'"]\w+[\'"]\]', stripped):
                if "try" not in stripped and "if " not in stripped:
                    warnings.append(
                        f"Line {i}: dict key access without .get() or try/except")

            # Division without zero-check
            if re.search(r'[^=/!<>]\s*/\s*\w+', stripped):
                if re.search(r'/\s*(len|count|total|n_)', stripped):
                    warnings.append(
                        f"Line {i}: possible division-by-zero (check denominator)")

        score = 1.0 - len(errors) * 0.5 - len(warnings) * 0.03
        return ValidationResult(not errors, max(0.0, score), errors, warnings)


class SpellingValidator:
    """
    Basic English spelling check on string literals, comments, and
    identifiers.  Uses a small custom word list — the Summarizer agent
    can be called for a deeper natural-language check.
    """

    # Common typos that appear in AI-generated code
    COMMON_TYPOS = {
        "recieve": "receive", "occured": "occurred", "seperator": "separator",
        "sucessful": "successful", "sucessfully": "successfully",
        "existance": "existence", "arguement": "argument", "lenght": "length",
        "defenition": "definition", "begining": "beginning",
        "managment": "management", "respose": "response",
        "respone": "response", "paramater": "parameter",
        "paramters": "parameters", "definitley": "definitely",
        "statment": "statement", "fucntion": "function",
        "methode": "method", "excpetion": "exception",
        "returnd": "returned", "initalize": "initialize",
    }

    @staticmethod
    def validate(code: str) -> ValidationResult:
        errors, warnings = [], []
        fixed_lines = code.splitlines()
        modified = False

        for i, line in enumerate(fixed_lines):
            for typo, correct in SpellingValidator.COMMON_TYPOS.items():
                if typo in line.lower():
                    # Only flag/fix in comments and strings (not code identifiers)
                    if "#" in line or '"' in line or "'" in line:
                        warnings.append(
                            f"Line {i+1}: '{typo}' → '{correct}'")
                        fixed_lines[i] = re.sub(
                            re.escape(typo), correct,
                            fixed_lines[i], flags=re.IGNORECASE)
                        modified = True

        fixed = "\n".join(fixed_lines) if modified else None
        score = 1.0 - len(warnings) * 0.02
        return ValidationResult(True, max(0.5, score), errors, warnings,
                                fixed_code=fixed)


class ImportValidator:
    """
    Verify that all imports in the code are from our allowed dependency set.
    """

    ALLOWED_STDLIB = {
        "os", "sys", "time", "json", "re", "math", "random", "threading",
        "queue", "pathlib", "datetime", "collections", "itertools",
        "functools", "typing", "dataclasses", "hashlib", "shutil",
        "mimetypes", "ast", "keyword", "traceback", "io", "copy",
        "contextlib", "weakref", "inspect", "abc", "enum",
    }

    ALLOWED_THIRD_PARTY = {
        "groq", "ollama", "PySide6", "dotenv", "requests", "sqlite3",
    }

    ALLOWED = ALLOWED_STDLIB | ALLOWED_THIRD_PARTY

    @staticmethod
    def validate(code: str) -> ValidationResult:
        errors, warnings = [], []
        try:
            tree = ast.parse(code)
        except Exception:
            return ValidationResult(True, 1.0)  # syntax check handles this

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                else:
                    names = [node.module.split(".")[0]] if node.module else []
                for name in names:
                    if name not in ImportValidator.ALLOWED:
                        errors.append(
                            f"Line {node.lineno}: import '{name}' not in "
                            f"allowed dependencies")

        score = 1.0 - len(errors) * 0.3
        return ValidationResult(not errors, max(0.0, score), errors, warnings)


class SecurityValidator:
    """Block dangerous operations."""

    BLOCKED_PATTERNS = [
        (r"\bsubprocess\b",        "subprocess module forbidden"),
        (r"\bos\.system\b",        "os.system() forbidden — use safe wrappers"),
        (r"\bos\.popen\b",         "os.popen() forbidden"),
        (r"\bopen\s*\(.+['\"]w",   "raw open() for writing — use safe_write_file()"),
        (r"__import__\s*\(",       "__import__() forbidden"),
        (r"\bshutil\.rmtree\b",    "shutil.rmtree() forbidden — destructive"),
        (r"\bos\.remove\b",        "os.remove() — use safe_write_file wrappers"),
        (r"socket\.",              "socket module forbidden"),
        (r"http\.server",         "http.server forbidden"),
    ]

    @staticmethod
    def validate(code: str) -> ValidationResult:
        errors = []
        for pat, msg in SecurityValidator.BLOCKED_PATTERNS:
            if re.search(pat, code):
                errors.append(msg)
        score = 0.0 if errors else 1.0
        return ValidationResult(not errors, score, errors)


# ─────────────────────────────────────────────────────────────────────────────
#  ActionPipeline
# ─────────────────────────────────────────────────────────────────────────────

class ActionPipeline:
    """
    Validates and executes proposed actions.

    Usage
    -----
    pipeline = ActionPipeline(root_folder, db=db, log_fn=log_fn)
    result   = pipeline.process(proposed_action)

    Callbacks
    ---------
    on_validated(action, result)    — called after validation
    on_executed(action, result)     — called after execution
    on_rejected(action, reason)     — called when validation fails
    """

    def __init__(self, root_folder: str, db=None, log_fn: Callable = None, safe_mode: bool = False):
        self.root    = Path(root_folder).resolve()
        self.db      = db
        self._log    = log_fn or print
        self._lock   = threading.Lock()
        self.safe_mode = safe_mode or os.getenv("MRBOT_SAFE_MODE", "").lower() in {"1", "true", "yes", "on"}

        # External callbacks
        self.on_validated: Optional[Callable] = None
        self.on_executed:  Optional[Callable] = None
        self.on_rejected:  Optional[Callable] = None

        # Summarizer reference for language correction
        self._summarizer_worker = None
        
        # Self-improvement permission (from env)
        self.allow_self_improve = os.getenv("PIPELINE_ALLOW_SELF_IMPROVE", "false").lower() == "true"

        # Validators in priority order
        self._validators = [
            ("Security",    SecurityValidator()),
            ("Syntax",      SyntaxValidator()),
            ("Imports",     ImportValidator()),
            ("API Usage",   ApiUsageValidator()),
            ("Null Safety", NullSafetyValidator()),
            ("Spelling",    SpellingValidator()),
        ]

    def set_summarizer(self, worker):
        """Inject Summarizer worker for deep language checks."""
        self._summarizer_worker = worker

    def process(self, action: ProposedAction) -> ExecutionResult:
        """Full pipeline: validate → (optionally) fix → execute."""
        self._log(f"[Pipeline] Processing {action.action_type} from "
                  f"{action.proposer}: {action.description[:60]}")

        # Only validate Python code actions
        if action.code and action.action_type in (
                "create_file", "modify_file", "self_improve"):
            vr = self._run_validators(action.code)
            self._log_validation(action, vr)

            if self.on_validated:
                self.on_validated(action, vr)

            if not vr.passed:
                reason = vr.summary
                self._log(f"[Pipeline] REJECTED {action.proposal_id}: {reason}")
                self._store_action(action, "rejected", reason)
                if self.on_rejected:
                    self.on_rejected(action, reason)
                return ExecutionResult(False, f"Validation failed: {reason}")

            # Auto-apply spelling fixes if available
            if vr.fixed_code:
                action.code = vr.fixed_code
                self._log(f"[Pipeline] Auto-applied spelling fixes")

        # Execute
        result = self._execute(action)
        outcome = "skipped" if result.skipped else ("executed" if result.success else "failed")
        self._store_action(action, outcome, result.message)
        if self.on_executed:
            self.on_executed(action, result)

        return result

    def _run_validators(self, code: str) -> ValidationResult:
        all_errors, all_warnings = [], []
        current_code = code
        min_score    = 1.0
        fixed_code   = None

        for name, validator in self._validators:
            try:
                vr = validator.validate(current_code)
                all_errors.extend([f"[{name}] {e}" for e in vr.errors])
                all_warnings.extend([f"[{name}] {w}" for w in vr.warnings])
                min_score = min(min_score, vr.score)
                if vr.fixed_code:
                    current_code = vr.fixed_code
                    fixed_code   = current_code
                if not vr.passed and name == "Security":
                    # Security failures are instant-reject
                    break
            except Exception as e:
                all_warnings.append(f"[{name}] Validator error: {e}")

        passed = not all_errors
        return ValidationResult(passed, min_score,
                                all_errors, all_warnings, fixed_code)

    def _execute(self, action: ProposedAction) -> ExecutionResult:
        t0 = time.time()
        if self.safe_mode:
            self._log(
                f"[Pipeline] SAFE MODE: skipped execution for {action.action_type} "
                f"{action.target_path or action.description[:40]}"
            )
            return ExecutionResult(
                True,
                f"Safe mode enabled; skipped {action.action_type} without changing files",
                path=action.target_path,
                duration=time.time() - t0,
                skipped=True,
            )
        try:
            if action.action_type == "create_file":
                return self._exec_create_file(action)
            elif action.action_type == "modify_file":
                return self._exec_modify_file(action)
            elif action.action_type == "delete_file":
                return self._exec_delete_file(action)
            elif action.action_type == "self_improve":
                if not getattr(self, 'allow_self_improve', False):
                    return ExecutionResult(
                        False,
                        "Self-improvement disabled: check PIPELINE_ALLOW_SELF_IMPROVE setting"
                    )
                return self._exec_self_improve(action)
            elif action.action_type == "assist_agent":
                return self._exec_assist(action)
            else:
                return ExecutionResult(False,
                                       f"Unknown action type: {action.action_type}")
        except Exception as e:
            return ExecutionResult(False, f"Execution error: {e}",
                                   duration=time.time() - t0)

    def _safe_path(self, rel: str) -> Optional[Path]:
        """Resolve a relative path and verify it stays inside ROOT_FOLDER."""
        rel = rel.lstrip("/\\")
        full = (self.root / rel).resolve()
        try:
            if not full.is_relative_to(self.root):
                return None
        except AttributeError:
            # Compatibility fallback for Python versions without is_relative_to.
            if not str(full).startswith(str(self.root) + os.sep):
                return None
            if full == self.root:
                return None
        return full

    def _exec_create_file(self, action: ProposedAction) -> ExecutionResult:
        if not action.target_path:
            return ExecutionResult(False, "No target_path specified")
        path = self._safe_path(action.target_path)
        if not path:
            return ExecutionResult(False, "Path escapes root folder — blocked")

        path.parent.mkdir(parents=True, exist_ok=True)

        # Don't overwrite existing files without explicit flag
        if path.exists() and not action.metadata.get("overwrite"):
            return ExecutionResult(False,
                                   f"File already exists: {action.target_path}. "
                                   "Set metadata['overwrite']=True to replace.")

        path.write_text(action.code, encoding="utf-8")
        self._log(f"[Pipeline] CREATED {action.target_path} "
                  f"({len(action.code):,} chars)")
        return ExecutionResult(True,
                               f"Created {action.target_path}",
                               path=str(path))

    def _exec_modify_file(self, action: ProposedAction) -> ExecutionResult:
        if not action.target_path:
            return ExecutionResult(False, "No target_path specified")
        path = self._safe_path(action.target_path)
        if not path:
            return ExecutionResult(False, "Path escapes root folder — blocked")
        if not path.exists():
            return ExecutionResult(False,
                                   f"File not found: {action.target_path}")

        # Backup original
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"),
                          encoding="utf-8")

        path.write_text(action.code, encoding="utf-8")
        self._log(f"[Pipeline] MODIFIED {action.target_path} "
                  f"(backup: {backup.name})")
        return ExecutionResult(True,
                               f"Modified {action.target_path} (backup saved)",
                               path=str(path))

    def _exec_delete_file(self, action: ProposedAction) -> ExecutionResult:
        # Deletes are only allowed with explicit confirmation flag
        if not action.metadata.get("confirmed"):
            return ExecutionResult(False,
                                   "Delete requires metadata['confirmed']=True")
        path = self._safe_path(action.target_path)
        if not path or not path.exists():
            return ExecutionResult(False, f"File not found: {action.target_path}")
        path.unlink()
        self._log(f"[Pipeline] DELETED {action.target_path}")
        return ExecutionResult(True, f"Deleted {action.target_path}",
                               path=str(path))

    def _exec_self_improve(self, action: ProposedAction) -> ExecutionResult:
        """
        Self-improvement: the agent proposes a new version of one of its
        own files.  Treated same as modify_file with extra validation score
        threshold (must be ≥ 0.85).
        """
        vr = self._run_validators(action.code)
        if vr.score < 0.85:
            return ExecutionResult(
                False,
                f"Self-improvement rejected: score {vr.score:.2f} < 0.85. "
                f"{vr.summary}")
        action.action_type = "modify_file"
        return self._exec_modify_file(action)

    def _exec_assist(self, action: ProposedAction) -> ExecutionResult:
        """
        Agent-to-agent assist: route the task result to another agent.
        The actual routing is handled outside (in manager.py); here we
        just log and confirm receipt.
        """
        target = action.metadata.get("target_agent", "Unknown")
        self._log(f"[Pipeline] ASSIST {action.proposer} → {target}: "
                  f"{action.description[:60]}")
        return ExecutionResult(
            True,
            f"Assist task forwarded to {target}",
        )

    def _log_validation(self, action: ProposedAction, vr: ValidationResult):
        status = "PASS" if vr.passed else "FAIL"
        self._log(
            f"[Validate] {status} score={vr.score:.2f} "
            f"id={action.proposal_id} | {vr.summary}"
        )

    def _store_action(self, action: ProposedAction,
                      outcome: str, message: str):
        if not self.db:
            return
        try:
            self.db.log_action(
                trigger=f"Pipeline/{action.proposer}/{action.action_type}",
                action_text=(
                    f"[{outcome.upper()}] {action.description[:120]} | "
                    f"path={action.target_path} | {message[:100]}"
                )
            )
        except Exception:
            pass

    def validate_only(self, code: str) -> ValidationResult:
        """Public helper — just validate without executing."""
        return self._run_validators(code)

    def quick_check(self, code: str) -> Tuple[bool, str]:
        """Fast yes/no check for UI display."""
        try:
            vr = self.validate_only(code)
            return vr.passed, vr.summary
        except Exception as e:
            return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
#  AgentCollaboration — routes assist requests between agents
# ─────────────────────────────────────────────────────────────────────────────

class AgentCollaboration:
    """
    Allows agents to request help from each other through the pipeline.

    Each agent role has defined capabilities it can offer to others.
    The Manager calls request_assist() to route a task to the best helper.
    """

    # What each agent can help WITH
    CAPABILITIES: Dict[str, List[str]] = {
        "Summarizer": [
            "text correction", "spelling check", "grammar", "simplify",
            "explain", "rephrase", "natural language", "tone", "clarity",
            "proposal writing", "english improvement",
        ],
        "Analyst": [
            "metrics", "code quality", "complexity analysis",
            "performance review", "duplicate detection", "debt score",
            "file analysis", "statistical summary",
        ],
        "Coder": [
            "code implementation", "bug fix", "refactor", "write function",
            "write class", "create module", "python", "debug",
            "code review", "unit test",
        ],
        "JobSearch": [
            "find jobs", "search gigs", "evaluate job fit",
            "platform search", "proposal match",
        ],
        "Manager": [
            "strategy", "prioritise", "schedule", "coordinate",
            "decision making", "overall plan",
        ],
    }

    @staticmethod
    def best_helper(task_description: str,
                    exclude: str = "") -> str:
        """Return the role best suited to help with the given task."""
        lower = task_description.lower()
        scores: Dict[str, int] = {}
        for role, caps in AgentCollaboration.CAPABILITIES.items():
            if role == exclude:
                continue
            scores[role] = sum(1 for cap in caps if cap in lower)
        if not scores:
            return "Manager"
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "Manager"

    @staticmethod
    def describe_capabilities(role: str) -> str:
        caps = AgentCollaboration.CAPABILITIES.get(role, [])
        return f"{role} can help with: {', '.join(caps[:8])}"