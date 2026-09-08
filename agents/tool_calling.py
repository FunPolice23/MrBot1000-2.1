"""
agents/tool_calling.py — Unified tool calling system for MrBot1000 personas.

Gives Marcus Rivera and Alex Vega real tool-calling abilities:
- Web search, browse, read pages
- Workshop operations (proposals, research, accounts, payments)
- File operations (read, write, list, search)
- System operations (run commands, query database)
- Real-time fact verification

Supports variable response length based on context:
- Quick chat: 2-5 sentences
- Planning: detailed with steps
- Research: comprehensive with sources
- Execution: action-oriented
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

PROJECT_ROOT = Path(__file__).parent.parent


# ── Tool Definitions ──────────────────────────────────────────────────────
# v2.1: Simplified tool definitions to avoid llama.cpp template parser errors.
# Removed `default` values, nested objects, and complex schemas that cause
# "Unable to generate parser for this template" errors.

def get_all_tools() -> List[Dict[str, Any]]:
    """Get all available tool definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for information. Returns titles, URLs, and snippets.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "web_read",
                "description": "Read a web page and extract clean text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to read"}
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "web_check",
                "description": "Check if a website is online.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to check"}
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "workshop_search",
                "description": "Search workshop files by name or content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "workshop_read",
                "description": "Read a file from the workshop.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "File path"}
                    },
                    "required": ["filepath"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "workshop_proposal",
                "description": "Create a new proposal document.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Proposal title"},
                        "client": {"type": "string", "description": "Client name"},
                        "description": {"type": "string", "description": "Proposal description"}
                    },
                    "required": ["title", "client", "description"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_read",
                "description": "Read a file from the project.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "file_write",
                "description": "Write content to a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "content": {"type": "string", "description": "Content to write"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a shell command and return output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to run"}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "query_db",
                "description": "Run a read-only SQL query against the local database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SELECT-only SQL query"}
                    },
                    "required": ["sql"]
                }
            }
        },
    ]


# ── Tool Execution ────────────────────────────────────────────────────────

def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """Execute a tool by name with given arguments."""
    try:
        # Web tools
        if name == "web_search":
            return _tool_web_search(arguments)
        elif name == "web_read":
            return _tool_web_read(arguments)
        elif name == "web_check":
            return _tool_web_check(arguments)
        
        # Workshop tools
        elif name == "workshop_list":
            return _tool_workshop_list(arguments)
        elif name == "workshop_read":
            return _tool_workshop_read(arguments)
        elif name == "workshop_write":
            return _tool_workshop_write(arguments)
        elif name == "workshop_search":
            return _tool_workshop_search(arguments)
        elif name == "workshop_proposal":
            return _tool_workshop_proposal(arguments)
        elif name == "workshop_account":
            return _tool_workshop_account(arguments)
        elif name == "workshop_payment":
            return _tool_workshop_payment(arguments)
        
        # File tools
        elif name == "file_read":
            return _tool_file_read(arguments)
        elif name == "file_write":
            return _tool_file_write(arguments)
        elif name == "file_list":
            return _tool_file_list(arguments)
        
        # System tools
        elif name == "run_command":
            return _tool_run_command(arguments)
        elif name == "query_db":
            return _tool_query_db(arguments)
        
        else:
            return f"[Unknown tool: {name}]"
    except Exception as e:
        return f"[Tool error: {e}]"


# ── Web Tool Implementations ──────────────────────────────────────────────

def _tool_web_search(args: Dict[str, Any]) -> str:
    """Search the web."""
    try:
        from agents.web_eyes import get_web_eyes
        eyes = get_web_eyes()
        results = eyes.search(args["query"], int(args.get("limit", 5)))
        return eyes.format_search_results(results)
    except Exception as e:
        return f"[Search error: {e}]"


def _tool_web_read(args: Dict[str, Any]) -> str:
    """Read a web page."""
    try:
        from agents.web_eyes import get_web_eyes
        eyes = get_web_eyes()
        page = eyes.read_page(args["url"])
        return eyes.format_page_summary(page)
    except Exception as e:
        return f"[Read error: {e}]"


def _tool_web_check(args: Dict[str, Any]) -> str:
    """Check website status."""
    try:
        from agents.web_eyes import get_web_eyes
        eyes = get_web_eyes()
        status = eyes.check_website_status(args["url"])
        if status.get("online"):
            return f"Online ({status.get('status_code')}) in {status.get('response_time')}s"
        else:
            return f"Offline: {status.get('error', 'unknown error')}"
    except Exception as e:
        return f"[Check error: {e}]"


# ── Workshop Tool Implementations ─────────────────────────────────────────

def _tool_workshop_list(args: Dict[str, Any]) -> str:
    """List workshop files."""
    try:
        from agents.workshop import get_workshop
        ws = get_workshop()
        files = ws.list_files(args.get("subdir", ""))
        if not files:
            return "No files found."
        lines = []
        for f in files:
            lines.append(f"- {f['name']} ({f['size']} bytes, {f['modified']})")
        return "\n".join(lines)
    except Exception as e:
        return f"[Workshop error: {e}]"


def _tool_workshop_read(args: Dict[str, Any]) -> str:
    """Read a workshop file."""
    try:
        from agents.workshop import get_workshop
        ws = get_workshop()
        return ws.read_file(args["filepath"])
    except Exception as e:
        return f"[Read error: {e}]"


def _tool_workshop_write(args: Dict[str, Any]) -> str:
    """Write a workshop file."""
    try:
        from agents.workshop import get_workshop
        ws = get_workshop()
        success = ws.write_file(args["filepath"], args["content"])
        return f"[Written to {args['filepath']}]" if success else "[Write failed]"
    except Exception as e:
        return f"[Write error: {e}]"


def _tool_workshop_search(args: Dict[str, Any]) -> str:
    """Search workshop files."""
    try:
        from agents.workshop import get_workshop
        ws = get_workshop()
        results = ws.search_files(args["query"])
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"- {r['name']} ({r['match']})")
        return "\n".join(lines)
    except Exception as e:
        return f"[Search error: {e}]"


def _tool_workshop_proposal(args: Dict[str, Any]) -> str:
    """Create a proposal."""
    try:
        from agents.workshop import get_workshop
        ws = get_workshop()
        filepath = ws.create_proposal(args["title"], args["client"], args["description"])
        return f"[Proposal created: {filepath}]"
    except Exception as e:
        return f"[Proposal error: {e}]"


def _tool_workshop_account(args: Dict[str, Any]) -> str:
    """Add an account."""
    try:
        from agents.workshop import get_workshop
        ws = get_workshop()
        ws.add_account(args["platform"], args["username"], args["email"])
        return f"[Account added: {args['platform']} ({args['username']})]"
    except Exception as e:
        return f"[Account error: {e}]"


def _tool_workshop_payment(args: Dict[str, Any]) -> str:
    """Add a payment method."""
    try:
        from agents.workshop import get_workshop
        ws = get_workshop()
        ws.add_payment_method(args["method"], args["identifier"], args.get("is_crypto", False))
        return f"[Payment method added: {args['method']} ({args['identifier']})]"
    except Exception as e:
        return f"[Payment error: {e}]"


# ── File Tool Implementations ─────────────────────────────────────────────

def _tool_file_read(args: Dict[str, Any]) -> str:
    """Read a file."""
    try:
        p = Path(args["path"])
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if not p.exists():
            return f"[File not found: {args['path']}]"
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[Read error: {e}]"


def _tool_file_write(args: Dict[str, Any]) -> str:
    """Write a file."""
    try:
        p = Path(args["path"])
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return f"[Wrote {p}]"
    except Exception as e:
        return f"[Write error: {e}]"


def _tool_file_list(args: Dict[str, Any]) -> str:
    """List directory."""
    try:
        p = Path(args["path"])
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if not p.exists() or not p.is_dir():
            return f"[Directory not found: {args['path']}]"
        return "\n".join(sorted([str(x.relative_to(PROJECT_ROOT)) for x in p.iterdir()]))
    except Exception as e:
        return f"[List error: {e}]"


# ── System Tool Implementations ───────────────────────────────────────────

def _tool_run_command(args: Dict[str, Any]) -> str:
    """Run a shell command."""
    try:
        result = subprocess.run(
            args["command"],
            shell=True,
            cwd=str(PROJECT_ROOT if not args.get("cwd") else args["cwd"]),
            capture_output=True,
            text=True,
            timeout=int(args.get("timeout", 30)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode != 0:
            return f"[Exit {result.returncode}]\nSTDOUT:\n{out}\nSTDERR:\n{err}"
        return out if out else "[Command succeeded with no output]"
    except subprocess.TimeoutExpired:
        return "[Command timed out]"
    except Exception as e:
        return f"[Command error: {e}]"


def _tool_query_db(args: Dict[str, Any]) -> str:
    """Query the database."""
    try:
        db_path = str(PROJECT_ROOT / "agent.db")
        if not os.path.exists(db_path):
            return "[Database not found]"
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(args["sql"]).fetchall()
        conn.close()
        limit = int(args.get("limit", 50))
        results = [dict(row) for row in rows[:limit]]
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"[Query error: {e}]"


# ── Tool Calling Loop ─────────────────────────────────────────────────────

def chat_with_tools(
    client,
    model: str,
    system_prompt: str,
    user_message: str,
    history: list = None,
    max_iterations: int = 5,
    max_tokens: int = 4096,
    temperature: float = 0.5,
    use_function_calling: bool = True,
) -> str:
    """
    Chat with tool calling support.
    
    v2.1 fix: Added use_function_calling parameter. When False, tools are not
    passed to the API (avoids 400 errors on llama.cpp). Instead, tool calls
    are parsed from text format in the response.
    """
    tools = get_all_tools() if use_function_calling else None
    
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    
    # Add history (limited to last 10 messages to save context)
    if history:
        for msg in history[-10:]:
            messages.append(msg)
    
    messages.append({"role": "user", "content": user_message})
    
    for iteration in range(max_iterations):
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        
        response = client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        
        # If no tool calls via API, try to parse tool calls from text
        # This handles models that don't support function calling
        if not msg.tool_calls:
            # Parse tool calls from text (works for all models)
            text_tool_call = _parse_tool_call_from_text(msg.content)
            if text_tool_call and iteration == 0 and max_iterations > 1:
                fn_name, fn_args = text_tool_call
                # Execute the tool
                try:
                    result = execute_tool(fn_name, fn_args)
                    messages.append({
                        "role": "assistant",
                        "content": msg.content,
                    })
                    messages.append({
                        "role": "tool",
                        "content": result[:2000],
                    })
                    # Continue to get final answer
                    continue
                except Exception as e:
                    messages.append({
                        "role": "tool",
                        "content": f"[Tool execution error: {e}]",
                    })
                    continue
            return msg.content or ""
        
        # Add assistant message with tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in msg.tool_calls
            ]
        })
        
        # Execute tool calls and add results
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                fn_args = {}
            
            result = execute_tool(fn_name, fn_args)
            
            messages.append({
                "tool_call_id": tc.id,
                "role": "tool",
                "content": result[:2000],  # Limit tool result size
            })
    
    # If we exhausted iterations, ask for final answer
    messages.append({
        "role": "user",
        "content": "Based on the tool results above, provide your final answer."
    })
    
    final_response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    
    return final_response.choices[0].message.content or ""


def _parse_tool_call_from_text(text: str) -> Optional[tuple]:
    """Parse tool call patterns from text.
    
    Looks for patterns like:
    - web_search("query")
    - web_search('query')
    - web_read("url")
    - web_check("url")
    - workshop_proposal("title", "client", "description")
    - workshop_search("query")
    - workshop_read("filepath")
    
    Returns (function_name, arguments_dict) or None if no pattern found.
    """
    if not text:
        return None
    
    import re
    
    # Define patterns for each tool
    patterns = [
        (r'web_search\s*\(\s*["\'](.+?)["\']\s*\)', 'web_search', {'query': 1}),
        (r'web_read\s*\(\s*["\'](.+?)["\']\s*\)', 'web_read', {'url': 1}),
        (r'web_check\s*\(\s*["\'](.+?)["\']\s*\)', 'web_check', {'url': 1}),
        (r'workshop_search\s*\(\s*["\'](.+?)["\']\s*\)', 'workshop_search', {'query': 1}),
        (r'workshop_read\s*\(\s*["\'](.+?)["\']\s*\)', 'workshop_read', {'filepath': 1}),
        (r'workshop_list\s*\(\s*\)', 'workshop_list', {}),
        (r'workshop_proposal\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'workshop_proposal', {'title': 1, 'client': 2, 'description': 3}),
        (r'workshop_account\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'workshop_account', {'platform': 1, 'username': 2, 'email': 3}),
        (r'workshop_payment\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'workshop_payment', {'method': 1, 'identifier': 2}),
        (r'file_read\s*\(\s*["\'](.+?)["\']\s*\)', 'file_read', {'path': 1}),
        (r'file_write\s*\(\s*["\'](.+?)["\']\s*,\s*["\'](.+?)["\']\s*\)', 'file_write', {'path': 1, 'content': 2}),
        (r'file_list\s*\(\s*["\'](.+?)["\']\s*\)', 'file_list', {'path': 1}),
        (r'run_command\s*\(\s*["\'](.+?)["\']\s*\)', 'run_command', {'command': 1}),
        (r'query_db\s*\(\s*["\'](.+?)["\']\s*\)', 'query_db', {'sql': 1}),
    ]
    
    for pattern, fn_name, arg_map in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            args = {}
            for arg_name, group_num in arg_map.items():
                try:
                    args[arg_name] = match.group(group_num)
                except IndexError:
                    args[arg_name] = ""
            return (fn_name, args)
    
    return None


# ── Response Length Control ───────────────────────────────────────────────

def get_max_tokens_for_context(context_type: str) -> int:
    """Get max tokens based on context type.
    
    v2.1: Removed the hard cap at 4096. With 32k context, the model should
    be able to use the full context length for detailed reasoning, research,
    and action planning.
    """
    return {
        "chat": 2048,        # Quick responses
        "plan": 8192,        # Detailed planning
        "research": 16384,   # Comprehensive research
        "execute": 4096,     # Action-oriented
        "explain": 8192,     # Thorough explanation
        "verify": 4096,      # Focused verification
    }.get(context_type, 8192)


def classify_context_type(message: str) -> str:
    """Classify the context type based on message content."""
    lower = message.lower()
    
    if any(w in lower for w in ["explain", "how does", "what is", "why", "describe", "tell me about"]):
        return "explain"
    elif any(w in lower for w in ["research", "find", "search", "look up", "investigate", "analyze"]):
        return "research"
    elif any(w in lower for w in ["plan", "strategy", "approach", "steps", "roadmap"]):
        return "plan"
    elif any(w in lower for w in ["do", "execute", "run", "create", "write", "build", "implement"]):
        return "execute"
    elif any(w in lower for w in ["verify", "check", "confirm", "is it true", "fact"]):
        return "verify"
    else:
        return "chat"


# ── Anti-Hallucination ────────────────────────────────────────────────────

def add_anti_hallucination_rules(system_prompt: str) -> str:
    """Add anti-hallucination rules to system prompt."""
    rules = """
    
## ANTI-HALLUCINATION RULES
- NEVER make up facts, URLs, prices, or statistics. If you don't know, say so.
- ALWAYS cite sources when providing factual information.
- When you use web_search or web_read, cite the URL.
- If you're unsure about something, say "I'm not sure" or verify with a tool.
- NEVER claim to have done something you haven't actually done.
- NEVER simulate winning money, completing tasks, or achieving goals.
- Be honest about your limitations as an AI.
- If you say "I will search" or "I will check" — YOU MUST ACTUALLY CALL THE TOOL.
- Do not make up statistics (e.g., "76% of small businesses...") without citing a source.
- If you don't have data, say "I don't have data on that" instead of inventing numbers.
"""
    return system_prompt + rules
