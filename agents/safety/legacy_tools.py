"""
Tool definitions for Big Brain tool calling.
Uses OpenAI-compatible function/tool calling schema.
"""
from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.safety.policy import command_argv, resolve_command_cwd, resolve_project_path
from agents.safety.handlers import _is_secret_file, refuse_secret_argv

# Project root
PROJECT_ROOT = resolve_project_path(".")

# ARCH-ENG-133: `read_file`/`write_file`/`run_command` here are reached through
# the Big Brain tool loop, where SafetyGate classifies `read_file` as an ALIAS of
# `file_read` (READONLY => ALLOWED) and dispatches to execute_tool — i.e. to the
# handlers in THIS module, not to the hardened `_tool_file_read` in handlers.py.
# The private readers below therefore have to re-apply the same two layers the
# hardened path applies, using the SAME authority (`_is_secret_file`) so there is
# one blocklist, not two that can drift:
#   1. SECRET FILES are refused outright (the value IS the whole file).
#   2. every other file's content passes through `redact_secrets`, so a secret
#      pasted into a readable file (README, notes) is scrubbed before it enters
#      model context.
# `write_file`/`run_command` are already NEEDS_APPROVAL in the gate; refusing a
# secret path here as well is defence in depth and returns a refusal string
# (never raises) so the model gets a usable tool result.

_SECRET_READ_REFUSAL = (
    " is a credential/key store and is never returned to the model. "
    "Read .env.example for the key names, and ask the operator for any "
    "value."
)


def _redact(text: str) -> str:
    """Layer 2: scrub secret-shaped substrings before model context."""
    from agents.integrations.wallet_crypto import redact_secrets
    return redact_secrets(text)


def _is_secret_path(path: str) -> bool:
    """True when the resolved path names a credential/key store."""
    try:
        return _is_secret_file(resolve_project_path(path, allow_missing=True))
    except (ValueError, OSError):
        # Outside the workspace (or unresolvable): treat the NAME as the signal.
        try:
            return _is_secret_file(Path(str(path)))
        except Exception:
            return False


def _read_file(path: str) -> str:
    try:
        p = resolve_project_path(path)
    except FileNotFoundError:
        return f"[File not found: {path}]"
    except ValueError as e:
        return f"[Read error: {e}]"
    if _is_secret_file(p):
        return f"[Read refused: {path}{_SECRET_READ_REFUSAL}]"
    return _redact(p.read_text(encoding="utf-8", errors="replace"))


def _write_file(path: str, content: str) -> str:
    try:
        p = resolve_project_path(path, allow_missing=True)
    except ValueError as e:
        return f"[Write error: {e}]"
    if _is_secret_file(p):
        return (
            f"[Write refused: {path} is a credential/key store and is never "
            "written by the model. Edit it only via explicit operator action; "
            "read .env.example for the key names.]"
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"[Wrote {p}]"


def _list_dir(path: str) -> List[str]:
    try:
        p = resolve_project_path(path)
    except (FileNotFoundError, ValueError):
        return [f"[Directory not found: {path}]"]
    return sorted([str(x.relative_to(PROJECT_ROOT)) for x in p.iterdir()])


def _run_command(cmd: str, cwd: Optional[str] = None) -> str:
    # ARCH-ENG-133 defence in depth: the gate already queues run_command for
    # approval, but a command that NAMES a secret store (type .env, cat
    # wallet.key, ...) must never execute even behind an approval — the file
    # contents would land in model context either way. Refusal string, no raise.
    try:
        argv = command_argv(cmd)
    except ValueError as e:
        # Same message the pre-fix code produced for unparseable commands.
        return f"[Command error: {e}]"
    # ARCH-ENG-211: this scan is no longer private to this function. It used to
    # exist ONLY here, which meant the other dispatcher -- the hardened one in
    # handlers._tool_run_command -- never consulted it. So `type .env` was
    # refused through the Big Brain tool loop and executed through dispatch.
    # The hardened path was strictly more permissive than the path it replaced.
    #
    # Both now call `refuse_secret_argv`, which uses the same `_is_secret_file`
    # authority this module already imported -- so ARCH-ENG-133's "one
    # blocklist, not two that can drift" is finally true of the *dispatchers*,
    # not just of the blocklist.
    refusal = refuse_secret_argv(argv)
    if refusal:
        return refusal
    try:
        safe_cwd = resolve_command_cwd(cwd)
        result = subprocess.run(
            argv,
            shell=False,
            cwd=str(safe_cwd),
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            encoding="utf-8", errors="replace",
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode != 0:
            return f"[Exit {result.returncode}]\nSTDOUT:\n{out}\nSTDERR:\n{err}"
        return out if out else "[Command succeeded with no output]"
    except subprocess.TimeoutExpired:
        return "[Command timed out after 30s]"
    except Exception as e:
        return f"[Command error: {e}]"


# Tool definitions in OpenAI function schema
TOOL_DEFS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Returns the file text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative or absolute file path"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text content to a file. Creates parent directories as needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute file path"},
                    "content": {"type": "string", "description": "Text content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and folders in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute directory path"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and capture stdout/stderr. Use for tests, git, python, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "cwd": {"type": "string", "description": "Optional working directory"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results, default 5", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_document",
            "description": "Read a file and return a structured summary: purpose, key functions, issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to analyze"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "Run a read-only SQL query against the local SQLite database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SELECT-only SQL query"},
                    "limit": {"type": "integer", "description": "Max rows to return", "default": 50}
                },
                "required": ["sql"]
            }
        }
    },
]


def execute_tool(name: str, arguments: Dict[str, Any],
                 authorization: object | None = None) -> str:
    """Execute a tool by name with given arguments.

    ARCH-ENG-164 — THIS DISPATCHER HAD NO AUTHORIZATION.

    `agents/safety/dispatch.py:execute_tool` is the gated entry point: it runs
    `AuthorizedActionDispatcher.authorize`, enqueues an approval item when the
    gate returns NEEDS_APPROVAL, and hands mutating handlers the
    `_DISPATCH_CAPABILITY` token they require. This function implemented a
    SECOND, parallel dispatcher that did none of that — it executed
    `write_file` and `run_command` directly, with only the secret-path and argv
    policy checks below standing between a model and the filesystem.

    It was not an active exploit: the only caller (`agents/brains/big_brain.py`)
    ran `safety_gate.check(...)` itself and only called this on ALLOWED. But the
    function itself was a public, unguarded API, and
    `agents/earning/router.py:get_tools_for_task` / `get_all_tools` advertised its
    `TOOL_DEFS` — including `write_file` and `run_command` — to model-facing
    callers. Any new importer would have inherited an unguarded path by accident,
    which is exactly how the second dispatcher came to exist.

    Mutating tools now require the same `_DISPATCH_CAPABILITY` token the hardened
    handlers require. Read-only tools keep working unchanged so the ARCH-ENG-133
    secret-redaction guarantees (which are tested here) still hold — they never
    needed a gate, only the two layers applied below.

    ARCH-ENG-164 also removed a dead import: the `web_search` branch did
    `from hermes_tools import web_search`, and `hermes_tools` has never been a
    dependency of this project (it appears in no requirements file), so that
    branch raised ImportError on every stock install and the blanket
    `except Exception` turned it into a "[Tool error: ...]" string. It now
    delegates to the real web tool in `agents.safety.calling`.
    """
    # Mutating tools require proof that the SafetyGate approved this call.
    # The names are this module's own (`read_file`/`write_file`), which the
    # gate classifies as ALIASES of `file_read`/`file_write`; `MUTATING_TOOLS`
    # holds the canonical names, so check both spellings rather than
    # canonicalizing (canonicalizing would rewrite `read_file` -> `file_read`
    # and fall through this module's dispatch table to "[Unknown tool]").
    from agents.safety.calling import _DISPATCH_CAPABILITY
    try:
        from agents.safety.calling import _MUTATING_TOOLS
        mutating = (name in _MUTATING_TOOLS
                    or name in ("write_file", "run_command", "file_write"))
    except Exception:
        mutating = name in ("write_file", "run_command", "file_write")
    if mutating and authorization is not _DISPATCH_CAPABILITY:
        return (f"[Authorization required: {name} must be invoked through the "
                f"SafetyGate-approved dispatcher]")

    try:
        if name == "read_file":
            return _read_file(arguments["path"])
        elif name == "write_file":
            return _write_file(arguments["path"], arguments["content"])
        elif name == "list_directory":
            return "\n".join(_list_dir(arguments["path"]))
        elif name == "run_command":
            return _run_command(arguments["command"], arguments.get("cwd"))
        elif name == "web_search":
            # ARCH-ENG-164: was `from hermes_tools import web_search`, a package
            # this project has never depended on. Use the real tool.
            from agents.safety.calling import _tool_web_search
            return _tool_web_search(arguments)
        elif name == "analyze_document":
            # ARCH-ENG-133: analyze_document reads through the same private
            # reader, so a secret path would be dumped into model context inside
            # the analysis block. Refuse before reading anything.
            doc_path = arguments["path"]
            if _is_secret_path(doc_path):
                return f"[Analysis refused: {doc_path}{_SECRET_READ_REFUSAL}]"
            content = _read_file(doc_path)
            # Simple analysis - return first 2000 chars as summary
            return f"[Analysis of {doc_path}]\n\n{content[:2000]}..."
        elif name == "query_database":
            from agents.safety.sql import execute_readonly_query
            db_path = str(PROJECT_ROOT / "agent.db")
            if not os.path.exists(db_path):
                return "[Database not found]"
            return execute_readonly_query(
                arguments["sql"], db_path, arguments.get("limit", 50))
        else:
            return f"[Unknown tool: {name}]"
    except Exception as e:
        return f"[Tool error: {e}]"
