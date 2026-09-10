#!/usr/bin/env python3
"""
prep_github_upload.py — Prepare MrBot1000 2.1 for GitHub upload.

Copies only the files that belong in a public repo to D:\\github_upload,
strips secrets, creates .env.example, and generates a .gitignore.

Run this script whenever you need to refresh D:\\github_upload before a commit.
"""
import os
import shutil
import sys

SRC = r"D:\MrBot1000_2.0"
DST = r"D:\github_upload"

# ── Files/dirs to EXCLUDE from GitHub ─────────────────────────────────────
EXCLUDE_DIRS = {
    "__pycache__",
    ".venv",
    ".pytest_cache",
    ".py_compile_check",
    ".git",
    ".hermes",
    ".mrbot_backups",
    ".ruff_cache",
    "data",
    "plans",
    "research",
    "proposals",
    "references",
}

EXCLUDE_FILES = {
    ".env",
    ".env_dual_brain",
    "wallet.key",
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "models_cache.json",
    "settings.json",
    "nul",
    "ai-copyright-report.md",
    "AUDIT_REPORT.md",
    "CHANGELOG_2.0-2.0.34au.md",
    "COMMS_REDESIGN.md",
    "CURRENT_STATE.md",
    "IMPROVEMENTS.md",
    "GITHUB_EARNING_ANALYSIS.md",
    "Skill.md",
    # Internal planning docs (not for public)
    "IDEA.md",
    "BLUEPRINT_v2.md",
    "ARCHITECTURE.md",
    # This script itself
    "prep_github_upload.py",
}

def should_exclude_file(fname: str) -> bool:
    if fname in EXCLUDE_FILES:
        return True
    for pattern in EXCLUDE_FILES:
        if pattern.startswith("*") and fname.endswith(pattern[1:]):
            return True
    return False

def should_exclude_dir(dname: str) -> bool:
    return dname in EXCLUDE_DIRS

def clean_dst():
    """Remove all files/dirs in DST."""
    if not os.path.exists(DST):
        os.makedirs(DST, exist_ok=True)
        return
    for item in os.listdir(DST):
        item_path = os.path.join(DST, item)
        try:
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
        except Exception as e:
            print(f"  Warning: could not remove {item_path}: {e}")
    try:
        shutil.rmtree(DST, ignore_errors=True)
    except Exception:
        pass
    os.makedirs(DST, exist_ok=True)

def copy_tree():
    """Copy directory tree, excluding unwanted files/dirs."""
    copied = 0
    skipped = 0
    errors = 0

    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if not should_exclude_dir(d)]
        rel = os.path.relpath(root, SRC)
        dst_dir = os.path.join(DST, rel) if rel != "." else DST
        os.makedirs(dst_dir, exist_ok=True)

        for fname in files:
            src_file = os.path.join(root, fname)
            dst_file = os.path.join(dst_dir, fname)
            if should_exclude_file(fname):
                skipped += 1
                continue
            try:
                shutil.copy2(src_file, dst_file)
                copied += 1
            except Exception as e:
                print(f"  ERROR copying {src_file}: {e}")
                errors += 1

    return copied, skipped, errors

def create_env_example():
    """Create a clean .env.example file that matches the actual codebase."""
    # Read the real .env to get the actual var names
    real_vars = {}
    env_path = os.path.join(SRC, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    real_vars[key.strip()] = value.strip()

    # Group vars by category
    categories = {
        "LLM Provider API Keys": [
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NOUS_API_KEY",
            "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
            "DEEPSEEK_API_KEY", "MISTRAL_API_KEY", "TOGETHER_API_KEY",
            "SCALE_AI_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY",
        ],
        "Dual Brain (llama.cpp)": [
            "BIG_BRAIN_PROVIDER", "BIG_BRAIN_URL", "BIG_BRAIN_MODEL",
            "BIG_BRAIN_DEVICE", "BIG_BRAIN_PORT", "BIG_BRAIN_CONTEXT",
            "BIG_BRAIN_GPU_LAYERS", "BIG_BRAIN_ENABLED",
            "SMALL_BRAIN_PROVIDER", "SMALL_BRAIN_URL", "SMALL_BRAIN_MODEL",
            "SMALL_BRAIN_DEVICE", "SMALL_BRAIN_PORT", "SMALL_BRAIN_CONTEXT",
            "SMALL_BRAIN_GPU_LAYERS", "SMALL_BRAIN_ENABLED",
            "DUAL_BRAIN_HEALTH_TIMEOUT",
        ],
        "Ollama (Local)": [
            "DISABLE_OLLAMA", "OLLAMA_MAIN_MODEL", "OLLAMA_CHAT_MODEL",
            "OLLAMA_MODEL", "OLLAMA_TIMEOUT", "OLLAMA_KEEP_ALIVE",
        ],
        "OpenAI": [
            "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_CHAT_MODEL",
            "OPENAI_MAIN_ENABLED", "OPENAI_CHAT_ENABLED", "OPENAI_HIDE",
            "DISABLE_OPENAI",
        ],
        "Anthropic": [
            "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_CHAT_MODEL",
            "ANTHROPIC_MAIN_ENABLED", "ANTHROPIC_CHAT_ENABLED", "ANTHROPIC_HIDE",
            "DISABLE_ANTHROPIC",
        ],
        "Additional Providers": [
            "OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "OPENROUTER_CHAT_MODEL",
            "OPENROUTER_MAIN_ENABLED", "OPENROUTER_CHAT_ENABLED", "OPENROUTER_HIDE", "DISABLE_OPENROUTER",
            "GEMINI_BASE_URL", "GEMINI_MODEL", "GEMINI_CHAT_MODEL",
            "GEMINI_MAIN_ENABLED", "GEMINI_CHAT_ENABLED", "GEMINI_HIDE", "DISABLE_GEMINI",
            "GROQ_BASE_URL", "GROQ_MODEL", "GROQ_CHAT_MODEL",
            "GROQ_MAIN_ENABLED", "GROQ_CHAT_ENABLED", "GROQ_HIDE", "DISABLE_GROQ",
            "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_CHAT_MODEL",
            "DEEPSEEK_MAIN_ENABLED", "DEEPSEEK_CHAT_ENABLED", "DEEPSEEK_HIDE", "DISABLE_DEEPSEEK",
            "MISTRAL_BASE_URL", "MISTRAL_MODEL", "MISTRAL_CHAT_MODEL",
            "MISTRAL_MAIN_ENABLED", "MISTRAL_CHAT_ENABLED", "MISTRAL_HIDE", "DISABLE_MISTRAL",
            "TOGETHER_BASE_URL", "TOGETHER_MODEL", "TOGETHER_CHAT_MODEL",
            "TOGETHER_MAIN_ENABLED", "TOGETHER_CHAT_ENABLED", "TOGETHER_HIDE", "DISABLE_TOGETHER",
            "NVIDIA_BASE_URL", "NVIDIA_MODEL", "NVIDIA_CHAT_MODEL",
            "NVIDIA_MAIN_ENABLED", "NVIDIA_CHAT_ENABLED", "NVIDIA_HIDE", "DISABLE_NVIDIA",
            "VLLM_BASE_URL", "VLLM_MODEL", "VLLM_CHAT_MODEL",
            "VLLM_MAIN_ENABLED", "VLLM_CHAT_ENABLED", "VLLM_HIDE", "DISABLE_VLLM",
            "LM_STUDIO_BASE_URL", "LM_STUDIO_MODEL", "LM_STUDIO_CHAT_MODEL",
            "LM_STUDIO_MAIN_ENABLED", "LM_STUDIO_CHAT_ENABLED", "LM_STUDIO_HIDE", "DISABLE_LM_STUDIO",
            "KOBOLDCPP_BASE_URL", "KOBOLDCPP_MODEL", "KOBOLDCPP_CHAT_MODEL",
            "KOBOLDCPP_MAIN_ENABLED", "KOBOLDCPP_CHAT_ENABLED", "KOBOLDCPP_HIDE", "DISABLE_KOBOLDCPP",
        ],
        "Agent Settings": [
            "AGENT_NAME", "AGENT_USERNAME",
            "HEARTBEAT_INTERVAL", "STARTUP_DELAY_SECS", "AUTO_RESEARCH",
            "RESEARCH_CACHE_TTL", "RESEARCH_MAX_CHARS", "RESEARCH_MAX_TOTAL_CHARS",
            "RESEARCH_BUNDLE_CHARS", "DEEP_READ_MAX_CHARS", "MAX_FILE_SIZE_MB",
            "FILENAME_BLOCKLIST", "BLOCKED_MIME_TYPES",
        ],
        "Thinking Mode": [
            "THINKING_ENABLED", "THINK_LEVEL", "MAIN_THINK_LEVEL",
            "MAX_TOKENS", "MAIN_CONTEXT_TOKENS", "CHAT_CONTEXT_TOKENS",
        ],
        "Pipeline (Earning Automation)": [
            "PIPELINE_ENABLED", "PIPELINE_ALLOW_WRITE", "PIPELINE_ALLOW_SELF_IMPROVE",
        ],
        "Wallet & Payout": [
            "ATOMIC_SOLANA_ADDRESS", "CASHAPP_TAG",
            "WALLET_ENC_KEY", "WALLET_ROOT",
        ],
        "Platform Tokens": [
            "UPWORK_CLIENT_ID", "UPWORK_CLIENT_SECRET",
            "UPWORK_ACCESS_TOKEN", "UPWORK_REFRESH_TOKEN",
            "TWITTER_BEARER_TOKEN", "DISCORD_BOT_TOKEN",
        ],
        "Web Search": [
            "WEB_PROVIDER", "WEB_SEARCH_MAX_RESULTS",
            "TAVILY_API_KEY", "BRAVE_API_KEY",
        ],
        "UI / Theme": [
            "MRBOT_THEME", "MRBOT_THEME_BG", "MRBOT_THEME_PANEL",
            "MRBOT_THEME_FG", "MRBOT_THEME_ACCENT", "MRBOT_THEME_HIGHLIGHT",
            "MRBOT_THEME_DISABLED",
            "MRBOT_FX_ANTIALIASING", "MRBOT_FX_SOFT_SHADOWS", "MRBOT_FX_HOVER_GLOW",
            "MRBOT_FX_TRANSITIONS", "MRBOT_FX_ANIMATIONS",
            "MRBOT_FX_QUALITY", "MRBOT_FX_RENDER_QUALITY",
            "MRBOT_FX_COMPACT_DENSITY", "MRBOT_FX_ROUNDED_CORNERS",
            "MRBOT_FX_BUTTON_STYLE",
            "COMPACT_STATUS_REPORTS",
        ],
        "Advanced": [
            "LLM_COST_AWARE", "LLM_DAILY_BUDGET_USD",
            "LLM_CB_ENABLED", "LLM_CB_FAILURES", "LLM_CB_COOLDOWN",
            "IDLE_HEARTBEAT_COOLDOWN", "MANAGER_QUEUE_MAXSIZE",
            "MODEL_ARCH_TTL", "MEMORY_ENABLED", "MEMORY_KEEP",
            "OPPORTUNITY_DISCOVERY_INTERVAL", "OPPORTUNITY_EXPIRY_HOURS",
            "AUTO_APPLY_THRESHOLD", "AUTO_SUBMIT_THRESHOLD",
            "PROPOSAL_AB_MIN_SAMPLES", "PROPOSAL_MODEL_ROLE",
            "SCHEDULER_INTERVAL", "JOB_SEARCH_INTERVAL",
            "STREAM_ERROR_STREAK_LIMIT", "STREAM_FAST_POLL", "STREAM_IDLE_POLL",
            "STREAM_MAX_BACKOFF", "WINRATE_DECLINE_BELOW",
            "MRBOT_SAFE_MODE", "MRBOT_SESSION", "MRBOT_VERSION",
            "MRBOT_SHARED_CONTEXT_PATH", "SHARED_CONTEXT_PATH",
            "QT_QPA_PLATFORM",
        ],
    }

    # Build the file
    lines = [
        "# MrBot1000 2.1 — Environment Configuration",
        "# Copy this file to .env and fill in your values.",
        "# NEVER commit .env to version control!",
        "",
    ]

    # Track which vars we've written
    written = set()

    for category, var_list in categories.items():
        lines.append(f"# ── {category} {'─' * (60 - len(category))}")
        for var in var_list:
            if var in real_vars:
                value = real_vars[var]
                # Mask sensitive values - never show any part of the real value
                if "KEY" in var or "TOKEN" in var or "SECRET" in var or "WALLET" in var or "PASSWORD" in var:
                    lines.append(f"{var}=")
                elif "ADDRESS" in var or "TAG" in var or "USERNAME" in var:
                    lines.append(f"{var}=")
                else:
                    # If the value IS a comment (starts with #), use empty
                    if value.strip().startswith("#"):
                        lines.append(f"{var}=")
                    else:
                        lines.append(f"{var}={value}")
                written.add(var)
        lines.append("")

    # Add any remaining vars from .env that weren't categorized
    remaining = set(real_vars.keys()) - written
    if remaining:
        lines.append(f"# ── Other {'─' * 55}")
        for var in sorted(remaining):
            value = real_vars[var]
            # Mask sensitive values
            if "KEY" in var or "TOKEN" in var or "SECRET" in var or "WALLET" in var or "PASSWORD" in var:
                lines.append(f"{var}=")
            elif "ADDRESS" in var or "TAG" in var or "USERNAME" in var:
                lines.append(f"{var}=")
            else:
                # If the value IS a comment (starts with #), use empty
                if value.strip().startswith("#"):
                    lines.append(f"{var}=")
                else:
                    lines.append(f"{var}={value}")

    content = "\n".join(lines) + "\n"

    path = os.path.join(DST, ".env.example")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Created: {path}")

def create_gitattributes():
    """Create a .gitattributes file to normalize line endings."""
    gitattributes = """# Auto detect text files and normalize line endings to LF on checkout
* text=auto

# Python files
*.py text eol=lf
*.pyx text eol=lf
*.pxd text eol=lf

# Config files
*.txt text eol=lf
*.md text eol=lf
*.json text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
*.toml text eol=lf
*.cfg text eol=lf
*.ini text eol=lf
*.env* text eol=lf

# Scripts
*.sh text eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf

# Binary files
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.ico binary
*.svg binary
*.pdf binary
*.zip binary
*.gz binary
*.tar binary
*.gguf binary
*.bin binary
*.db binary
*.sqlite binary
"""
    path = os.path.join(DST, ".gitattributes")
    with open(path, "w", encoding="utf-8") as f:
        f.write(gitattributes)
    print(f"  Created: {path}")

def create_gitignore():
    gitignore = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
ENV/
env/
*.egg-info/
dist/
build/
*.egg

# MrBot1000 secrets — NEVER commit!
.env
wallet.key
*.db
*.db-shm
*.db-wal
models_cache.json
settings.json

# MrBot1000 local data
data/
plans/
research/
proposals/
references/
nul

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
desktop.ini

# Logs
*.log
logs/

# Test cache
.pytest_cache/
.py_compile_check/
htmlcov/
.coverage
"""
    path = os.path.join(DST, ".gitignore")
    with open(path, "w", encoding="utf-8") as f:
        f.write(gitignore)
    print(f"  Created: {path}")

def create_readme():
    readme = """# MrBot1000 2.1 — Dual-Brain AI Earning Agent

A local-first, human-gated AI agent that helps you earn money across multiple paths:
freelance, micro-tasks, crypto, bounties, and trading.

## 🧠 Dual-Brain Architecture

- **Marcus (Big Brain)** — 7B-14B model on primary GPU (strategy, deep reasoning, writing)
- **Alex (Small Brain)** — 1.5B-3B model on secondary GPU (chat, review, fast responses)
- Both collaborate on tasks, catch each other's mistakes, and require human approval for real-money actions

## 🚀 Quick Start

1. Clone the repo
2. Copy `.env.example` to `.env` and fill in your API keys
3. Install dependencies: `pip install -r requirements.txt`
4. Start llama.cpp with your models
5. Run: `python main.py`

## 📁 Project Structure

```
MrBot1000_2.0/
├── main.py                 # Application entry point
├── agents/                 # AI agent logic
│   ├── big_brain.py        # Primary reasoning engine
│   ├── small_brain.py      # Secondary chat/review engine
│   ├── earning_pipeline.py # Multi-path earning orchestrator
│   ├── goal_system.py      # Goal tracking
│   ├── event_logger.py     # Hash-chained audit ledger
│   ├── alerting.py         # Real-time alerting rules
│   └── ...
├── gui/                    # PySide6 desktop interface
│   ├── dual_brain_control.py
│   ├── earning_tab.py
│   ├── analytics_tab.py
│   └── ...
├── prompts/                # System prompts for each brain
├── skills/                 # Agent skill definitions
├── scripts/                # Launch scripts (llama.cpp, LM Studio)
├── tests/                  # Test suite
├── requirements.txt        # Python dependencies
└── README.md
```

## 🛡️ Safety First

- **Every real-money action requires explicit human approval**
- **Cost caps** prevent runaway LLM spending
- **Hash-chained audit ledger** for tamper-evident records
- **Survival tiers** reduce spending when credits are low

## 📊 Earning Paths

| Path | Description | Status |
|------|-------------|--------|
| Freelance | Upwork/Fiverr proposal writing | ✅ |
| Micro-tasks | Prolific/DataAnnotation | ✅ |
| Crypto | On-chain payments | ✅ |
| Bounty | GitHub/Gitcoin bounties | 🔜 |
| Trading | Paper → Live trading | 🔜 |
| Content | Content marketing | 🔜 |

## 📜 License

See LICENSE file for details.

## 🤝 Contributing

PRs welcome! See CONTRIBUTING.md for guidelines.
"""
    path = os.path.join(DST, "README.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(readme)
    print(f"  Created: {path}")

def main():
    print("=" * 60)
    print("  MrBot1000 2.1 — GitHub Upload Preparation")
    print("=" * 60)
    print()

    # Clean destination
    print(f"Cleaning: {DST}")
    clean_dst()
    print(f"Destination: {DST}")
    print()

    # Copy files
    print("Copying project files...")
    copied, skipped, errors = copy_tree()
    print(f"  Copied:  {copied}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors:  {errors}")
    print()

    # Create supporting files
    print("Creating supporting files...")
    create_env_example()
    create_gitignore()
    create_gitattributes()
    create_readme()
    print()

    # Summary
    print("=" * 60)
    print("  Done!")
    print("=" * 60)
    print()
    print(f"Upload directory: {DST}")
    print()
    print("Next steps:")
    print(f"  1. Review the files in {DST}")
    print(f"  2. cd {DST}")
    print(f"  3. git init")
    print(f"  4. git add .")
    print(f"  5. git commit -m 'Initial commit: MrBot1000 2.1'")
    print(f"  6. git remote add origin <your-repo-url>")
    print(f"  7. git push -u origin main")
    print()

if __name__ == "__main__":
    main()
