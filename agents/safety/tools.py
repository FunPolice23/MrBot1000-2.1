"""Canonical tool schema registry."""

from typing import Any, Dict, List


def get_all_tools() -> List[Dict[str, Any]]:
    """Get all available tool definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web for candidate sources. Returns titles, URLs, and snippets; "
                    "search results are discovery evidence, not verification. Read a source URL "
                    "before making a current or consequential factual claim."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "description": "Maximum results, usually 3-8"}
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
                "name": "workshop_list",
                "description": "List files in an organized workshop folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subdir": {"type": "string", "description": "Relative folder, such as proposals or research"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "workshop_write",
                "description": "Write a text document inside the shared workshop.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Relative path inside ai_workshop"},
                        "content": {"type": "string", "description": "Text content"}
                    },
                    "required": ["filepath", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "workshop_mkdir",
                "description": "Create an organized folder inside the shared workshop.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "folder": {"type": "string", "description": "Relative folder path inside ai_workshop"}
                    },
                    "required": ["folder"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "workshop_storage",
                "description": "Show workshop quota usage and available disk space.",
                "parameters": {"type": "object", "properties": {}}
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
                "description": "Run a read-only SQL query against an allowlisted local database (default: agent).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SELECT-only SQL query"},
                        "db": {"type": "string", "description": "Store name: agent (default) | earning | memory | portfolio | autonomous_runs | goals | job_search | dual_brain"},
                        "limit": {"type": "integer", "description": "Max rows (default 50, max 500)"}
                    },
                    "required": ["sql"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "record_payment",
                "description": "Record a verified payment against an opportunity. HIGH-TRUST: requires an approved approval_id; never invents an amount.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "opportunity_id": {"type": "string"},
                        "amount": {"type": "number", "description": "Positive payout amount (from the human/evidence, never invented)"},
                        "evidence_ref": {"type": "string", "description": "Payment reference / evidence id"},
                        "approval_id": {"type": "string", "description": "APPROVED approval item id (required)"}
                    },
                    "required": ["opportunity_id", "amount", "approval_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "social_post",
                "description": "Post content to a social/agent network. HIGH-TRUST: requires an approved approval_id and a confirmed write endpoint; never fabricates a post.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "network": {"type": "string", "description": "Target network (e.g. moltbook)"},
                        "content": {"type": "string"},
                        "approval_id": {"type": "string", "description": "APPROVED approval item id (required)"}
                    },
                    "required": ["network", "content", "approval_id"]
                }
            }
        },
    ]


__all__ = ["get_all_tools"]
