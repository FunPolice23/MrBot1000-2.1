#!/usr/bin/env python3
"""Sync MrBot1000 source to the external publish mirror for GitHub publishing.

The publish mirror lives OUTSIDE the project tree (default D:/github_upload)
so the running program never sees or edits it. Override with GITHUB_UPLOAD_DIR.

Copies only safe files, strips secrets, and refreshes the README.
"""

import shutil
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
# External, independent publish mirror (NOT inside the project tree).
DEST = Path(os.environ.get("GITHUB_UPLOAD_DIR", r"D:\github_upload"))

# Files and folders to include (authoritative allow-list; the recursive
# fallback below is a safety net, but this list is the source of truth).
INCLUDE = [
    # Docs
    "README.md",
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "IDEA.md",
    "Skill.md",
    "Agent.md",
    # Config
    ".env.example",
    ".gitignore",
    "requirements.txt",
    "requirements.lock.txt",  # v2.0.24c transitive lock (reproducible installs)
    # Core
    "main.py",
    "manager.py",
    "action_pipeline.py",
    "ui.py",
    "theme_config.py",
    "database.py",
    "earning_pipeline.py",
    "earning_memory.py",
    "library.py",
    "startup_validation.py",
    "__init__.py",
    # Tests
    "tests",
    # Agents
    "agents/__init__.py",
    "agents/base_worker.py",
    "agents/coder.py",
    "agents/summarizer.py",
    "agents/shared_context.py",
    "agents/chat_router.py",
    "agents/analyst_worker.py",
    "agents/airdrop_scanner.py",
    "agents/airdrop_claimer.py",
    "agents/content_generator.py",
    "agents/defi_scanner.py",
    "agents/document_scanner.py",
    "agents/earning_discoverer.py",
    "agents/fiverr_client.py",
    "agents/job_search_worker.py",
    "agents/microtask_client.py",
    "agents/social_earning_platform.py",
    "agents/upwork_client.py",
    "agents/wallet_manager.py",
    "agents/opportunity_lifecycle.py",
    "agents/task_workspace.py",
    "agents/workflow_planner.py",
    # v2.0.22 security layer
    "agents/instruction_gate.py",
    "agents/trust_boundary.py",
    "agents/prompt_sanitize.py",  # v2.0.24c prompt-injection hardening
    "agents/web_provider.py",  # v2.0.23d configurable web search provider
    "agents/platforms/__init__.py",
    "agents/platforms/base.py",
    "agents/platforms/fiverr.py",
    "agents/platforms/reddit.py",
    # Skills
    "skills/__init__.py",
    "skills/social-discovery.md",
    "skills/opportunity-evaluation.md",
    "skills/opportunity-filtering.md",
    "skills/opportunity-execution.md",
    "skills/opportunity-lifecycle.md",
    "skills/document-qa.md",
    "skills/job-execution-plan.md",
]

# Patterns to exclude anywhere in tree
EXCLUDE_PATTERNS = [
    ".env", ".env.local", ".env.*.local",
    "*.db", "*.sqlite", "*.sqlite3",
    "*.db-wal", "*.db-shm",
    "*.pyc", "*.pyo",
    "__pycache__",
    "*.log",
    ".hermes",
    "CanvasHudController.cs",
    "clawgig_client.py",
    "js_*.py",          # sanitization scratch artifacts (e.g. js_clean.py)
]

SKIP_DIRS = {".hermes", "__pycache__", ".git", "github_upload"}
SKIP_FILES = {"CanvasHudController.cs", "clawgig_client.py"}


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIRS:
        return True
    if path.name in SKIP_FILES:
        return True
    for pat in EXCLUDE_PATTERNS:
        if path.match(pat):
            return True
    return False


def sync() -> None:
    DEST.mkdir(parents=True, exist_ok=True)

    copied = []
    skipped = []

    for rel in INCLUDE:
        src = ROOT / rel
        if not src.exists():
            print(f"MISSING: {rel}")
            skipped.append(rel)
            continue
        if should_skip(src):
            print(f"SKIP (excluded): {rel}")
            skipped.append(rel)
            continue
        dst = DEST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists() and dst.is_file():
                dst.unlink()
            shutil.copytree(src, dst, ignore=lambda d, f: [], dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        copied.append(rel)

    # Also copy any new root-level .py files plus agent/skill/test files that weren't listed explicitly
    candidates = []
    candidates.extend(ROOT.glob("*.py"))
    for folder in ("agents", "skills", "tests"):
        base = ROOT / folder
        if base.exists():
            candidates.extend(base.rglob("*"))

    for src in sorted(candidates):
        if src.is_dir() or should_skip(src):
            continue
        rel = src.relative_to(ROOT)
        if str(rel) not in copied:
            dst = DEST / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(str(rel))

    print(f"\nCopied {len(copied)} files to {DEST}")
    if skipped:
        print(f"Skipped {len(skipped)} items")

    # Sanitize .env.example copy
    env_src = DEST / ".env.example"
    if env_src.exists():
        text = env_src.read_text(encoding="utf-8")
        text = text.replace("OLLAMA_CHAT_MODEL=llama3.2", "OLLAMA_CHAT_MODEL=your-chat-model-here")
        text = text.replace("OLLAMA_MODEL=llama3.2", "OLLAMA_MODEL=your-main-model-here")
        # Replace any obvious placeholder keys
        lines = []
        for line in text.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip()
                if v and not v.startswith("your-") and not v.startswith("#"):
                    lines.append(f"{k}=your-{k.lower().replace('_','-')}-here")
                    continue
            lines.append(line)
        env_src.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("Sanitized .env.example")

    # Refresh README from template
    readme_src = ROOT / "README.md"
    if readme_src.exists():
        shutil.copy2(readme_src, DEST / "README.md")
        print("Refreshed README.md")


if __name__ == "__main__":
    sync()
