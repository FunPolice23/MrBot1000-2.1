"""
Tool definitions for Big Brain tool calling.
Uses OpenAI-compatible function/tool calling schema.
"""
from __future__ import annotations

import os
import json
import subprocess
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


def _read_file(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.exists():
        return f"[File not found: {path}]"
    return p.read_text(encoding="utf-8", errors="replace")


def _write_file(path: str, content: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"[Wrote {p}]"


def _list_dir(path: str) -> List[str]:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.exists() or not p.is_dir():
        return [f"[Directory not found: {path}]"]
    return sorted([str(x.relative_to(PROJECT_ROOT)) for x in p.iterdir()])


def _run_command(cmd: str, cwd: Optional[str] = None) -> str:
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(PROJECT_ROOT if not cwd else cwd),
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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


def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """Execute a tool by name with given arguments."""
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
            from hermes_tools import web_search
            result = web_search(arguments["query"], limit=int(arguments.get("limit", 5)))
            lines = []
            for item in result.get("data", {}).get("web", []):
                lines.append(f"- {item.get('title','')}: {item.get('url','')}")
            return "\n".join(lines) if lines else "[No results]"
        elif name == "analyze_document":
            content = _read_file(arguments["path"])
            # Simple analysis - return first 2000 chars as summary
            return f"[Analysis of {arguments['path']}]\n\n{content[:2000]}..."
        elif name == "query_database":
            db_path = str(PROJECT_ROOT / "agent.db")
            if not os.path.exists(db_path):
                return "[Database not found]"
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(arguments["sql"]).fetchall()
            conn.close()
            limit = int(arguments.get("limit", 50))
            results = []
            for row in rows[:limit]:
                results.append(dict(row))
            return json.dumps(results, indent=2, default=str)
        else:
            return f"[Unknown tool: {name}]"
    except Exception as e:
        return f"[Tool error: {e}]"
