"""
agents/workshop.py — Workshop workspace manager for MrBot1000 personas.

Gives Edward Hurst and Jacob Stanley a real workspace at D:\ai_workshop for:
- Proposals: create, store, manage client proposals
- Research: read/write research files, PDFs, documents
- Scripts: create scripts for automation, data processing
- Applications: fill out real applications, forms, account registrations
- Account management: track forum accounts, platform profiles
- Payment methods: track CashApp, crypto wallets, payment info
- Deliverables: store completed work ready for delivery

All files persist on disk so the personas can build real assets over time.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path


# ── Atomic JSON writes ────────────────────────────────────────────────────

def _atomic_write_json(path: str, data: Any) -> None:
    """Write `data` to `path` atomically (temp + fsync + os.replace).

    ARCH-ENG-066: the workshop's account/payment stores wrote in place, so a crash
    mid-write left a truncated file. The paired read then failed, returned `{}`, and
    the next save overwrote the file with that empty dict — permanent, silent loss of
    every stored account or payment method. `os.replace` is atomic on Windows, so a
    reader sees either the complete old file or the complete new one, never a partial.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    # Unique per process: two Workshop instances sharing a root would otherwise
    # collide on the same temp filename and clobber each other's write.
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        # Never leave a half-written temp behind to be mistaken for real data.
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Workspace Paths ───────────────────────────────────────────────────────

WORKSHOP_ROOT = os.getenv("MRBOT_WORKSHOP_ROOT") or os.getenv(
    "AI_WORKSHOP_ROOT") or r"D:\ai_workshop"
# ARCH-ENG-221: WAS 10 GiB.
#
# The target machine has 32 GB of RAM, and a 10 GB workshop quota lets the
# workspace consume a third of the machine's entire memory budget as disk,
# starving the page cache and swap headroom that a locally-hosted 8-10 GB GGUF
# model depends on. The quota is still overridable via MRBOT_WORKSHOP_MAX_BYTES
# for an operator who wants the old headroom.
DEFAULT_WORKSHOP_MAX_BYTES = 2 * 1024 * 1024 * 1024
WORKSHOP_MAX_BYTES = int(os.getenv(
    "MRBOT_WORKSHOP_MAX_BYTES", str(DEFAULT_WORKSHOP_MAX_BYTES)))

# ARCH-ENG-221: largest single file `read_file` will return.
#
# `read_file` did an uncapped `f.read()`, and its result flows to
# `redact_secrets(...)` in `agents/safety/handlers.py:247` and then into a tool
# result -- i.e. into RAM *and* into the model's context window. With a 2 GiB
# quota, one call could try to pull 2 GiB into a prompt. The truncation is
# explicit rather than silent, so the model can see that it is looking at a
# fragment instead of believing it read the whole file.
WORKSHOP_MAX_READ_BYTES = int(os.getenv(
    "MRBOT_WORKSHOP_MAX_READ_BYTES", str(256 * 1024)))
WORKSHOP_TRUNCATION_MARKER = (
    "\n\n[... TRUNCATED: file is {shown:,} of {total:,} bytes. "
    "Use read_file_slice(start, end) for the rest.]")

# ARCH-ENG-221: how long a computed disk-usage total may be reused when idle.
_USAGE_CACHE_TTL_S = 30.0

# ARCH-ENG-221: was a bare `results[:20]` applied after the walk. Hoisted so the
# walk itself can stop, which is where all the cost was.
_SEARCH_FILE_LIMIT = 20

PATHS = {
    "root": WORKSHOP_ROOT,
    "proposals": os.path.join(WORKSHOP_ROOT, "proposals"),
    "research": os.path.join(WORKSHOP_ROOT, "research"),
    "documents": os.path.join(WORKSHOP_ROOT, "documents"),
    "scripts": os.path.join(WORKSHOP_ROOT, "scripts"),
    "applications": os.path.join(WORKSHOP_ROOT, "applications"),
    "accounts": os.path.join(WORKSHOP_ROOT, "accounts"),
    "deliverables": os.path.join(WORKSHOP_ROOT, "deliverables"),
    "learning": os.path.join(WORKSHOP_ROOT, "learning"),
    # ARCH-ENG-245 (AY-02, 11G): the "templates" category was removed with
    # the dead template subsystem -- get_template served four hardcoded
    # skeleton strings it never wrote to disk, save_template wrote files
    # into templates/ that NOTHING could ever read back, and nothing wrote
    # or read either (22 dead of 52 methods). Proposal copy is superseded by
    # the live, data-driven A/B mechanism (agents/knowledge/
    # proposal_templates.py, wired at agents/earning/proposal.py:25); the
    # document skeletons an LLM persona can generate natively. Keeping the
    # PATHS entry would have mkdir'd an empty templates/ directory at every
    # Workshop init, forever, for no writer and no reader.
    "notes": os.path.join(WORKSHOP_ROOT, "notes"),
    "crypto": os.path.join(WORKSHOP_ROOT, "crypto"),
    "memory": os.path.join(WORKSHOP_ROOT, "memory"),
}


class WorkshopWriteError(RuntimeError):
    """A workshop write was refused or failed.

    ARCH-ENG-215. `Workshop.write_file` returns False for an unsafe path, an
    exceeded storage quota, an empty disk, a permission error, or any other
    exception. Seven creator methods discarded that boolean and returned the
    path unconditionally, so the caller was told a document existed when no
    file had been written.

    The agent-visible consequence: `workshop_proposal` returned
    `[Proposal created: proposals/proposal_acme_20261018.md]` for a file that
    did not exist, and the model told the operator it had prepared the proposal.
    """

    def __init__(self, what: str, filepath: str, reason: str = ""):
        self.what = what
        self.filepath = filepath
        super().__init__(
            f"{what} could not be written to {filepath}"
            + (f": {reason}" if reason else "")
            + ". The file was NOT created. Check the workshop storage quota, "
              "the path, and write permissions, then retry."
        )


class Workshop:
    """Workspace manager for persona agents."""
    
    def __init__(self, root: str = None, max_bytes: int = None):
        configured_root = root or WORKSHOP_ROOT
        self.root = str(Path(configured_root).expanduser().resolve())
        self.max_bytes = max(0, int(WORKSHOP_MAX_BYTES if max_bytes is None else max_bytes))
        # ARCH-ENG-221: (monotonic_now, total_bytes). None means "not computed".
        self._usage_cache: Optional[tuple[float, int]] = None
        self.paths = {
            name: os.path.join(self.root, name)
            for name in PATHS
            if name != "root"
        }
        self.paths["root"] = self.root
        self._ensure_dirs()
        self._accounts_file = os.path.join(self.paths["accounts"], "accounts.json")
        self._payments_file = os.path.join(self.root, "payments.json")
        self._tasks_file = os.path.join(self.root, "tasks.json")
    
    def _ensure_dirs(self):
        """Create all workshop directories if they don't exist.

        ARCH-ENG-221: no `_invalidate_usage()` here, deliberately -- `makedirs`
        creates zero-byte directories, so the usage total cannot have changed.
        Adding the call would be noise implying a mutation that did not happen.
        """
        for path in self.paths.values():
            os.makedirs(path, exist_ok=True)

    def _safe_path(self, filepath: str) -> Optional[str]:
        """Resolve a path strictly inside this workshop root."""
        if not isinstance(filepath, str) or not filepath.strip():
            return None
        candidate = Path(filepath).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.root) / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(Path(self.root))
        except ValueError:
            return None
        return str(candidate)

    def _usage_bytes(self) -> int:
        """Total bytes on disk under the workshop root.

        ARCH-ENG-221: THIS WAS A FULL RECURSIVE WALK ON EVERY SINGLE WRITE.

        `_can_write` calls `storage_stats()` -> `_usage_bytes()` from both
        `write_file` and `append_file`, so creating or appending to a single file
        cost a `Path.rglob("*")` plus an `is_file()` and a `stat()` syscall for
        every file in the entire workshop tree. At a few thousand files that is
        seconds on NTFS, serialised in front of every tool-driven file creation.

        Now cached, and invalidated by every mutator in this class. The
        invalidation is what makes the cache CORRECT (a TTL alone would let the
        quota be exceeded by a burst of writes); the TTL only bounds the idle
        cost when nothing is being written.
        """
        now = time.monotonic()
        cached = self._usage_cache
        if cached is not None and (now - cached[0]) < _USAGE_CACHE_TTL_S:
            return cached[1]
        total = 0
        for path in Path(self.root).rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        self._usage_cache = (now, total)
        return total

    def _invalidate_usage(self) -> None:
        """ARCH-ENG-221: drop the cached usage total after a mutation."""
        self._usage_cache = None

    def storage_stats(self) -> Dict[str, int]:
        """Return quota and physical free-space information for the workshop."""
        usage = self._usage_bytes()
        free = shutil.disk_usage(self.root).free
        return {
            "used_bytes": usage,
            "max_bytes": self.max_bytes,
            "remaining_bytes": max(0, self.max_bytes - usage),
            "free_disk_bytes": free,
        }

    def _can_write(self, path: str, content_size: int) -> bool:
        current_size = 0
        if os.path.isfile(path):
            try:
                current_size = os.path.getsize(path)
            except OSError:
                return False
        delta = max(0, content_size - current_size)
        stats = self.storage_stats()
        return delta <= stats["remaining_bytes"] and delta <= stats["free_disk_bytes"]

    def create_folder(self, folder: str) -> bool:
        """Create an organized folder inside the workshop root."""
        path = self._safe_path(folder)
        if not path:
            return False
        try:
            os.makedirs(path, exist_ok=True)
            self._invalidate_usage()  # ARCH-ENG-221
            return True
        except OSError:
            return False
    
    # ── File Operations ────────────────────────────────────────────────────
    
    def read_file(self, filepath: str) -> str:
        """Read a file from the workshop."""
        try:
            filepath = self._safe_path(filepath)
            if not filepath:
                return "Error reading file: path is outside workshop"
            total = os.path.getsize(filepath)
            limit = WORKSHOP_MAX_READ_BYTES
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                text = f.read(limit)
            if total > len(text.encode("utf-8", "replace")):
                text += WORKSHOP_TRUNCATION_MARKER.format(shown=limit, total=total)
            return text
        except Exception as e:
            return f"Error reading file: {e}"
    
    def _write_or_raise(self, filepath: str, content: str, what: str) -> str:
        """Write, and refuse to report success if the write did not happen.

        ARCH-ENG-215. Every creator method below returned `filepath`
        unconditionally after discarding `write_file`'s boolean. That is the
        same shape as the ARCH-ENG-204 backup bug (log a warning, write anyway,
        report success) and it is the one this codebase keeps producing: a
        claim the code has not verified.

        Raising is safe here because every tool handler already wraps the call
        in `try/except Exception` and returns `[<Tool> error: ...]`, which the
        ARCH-ENG-214 deny-list classifies as NOT executed. So the failure now
        travels the whole chain truthfully: disk -> raise -> `[Proposal error]`
        -> `_tool_status` -> `error` in the transcript.
        """
        if not self.write_file(filepath, content):
            raise WorkshopWriteError(what, filepath)
        return filepath

    def write_file(self, filepath: str, content: str) -> bool:
        """Write a file to the workshop."""
        try:
            filepath = self._safe_path(filepath)
            if not filepath or not isinstance(content, str):
                return False
            if not self._can_write(filepath, len(content.encode("utf-8"))):
                return False
            # Create parent dirs if needed
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self._invalidate_usage()  # ARCH-ENG-221
            return True
        except Exception as e:
            return False
    
    def append_file(self, filepath: str, content: str) -> bool:
        """Append to a file in the workshop."""
        try:
            filepath = self._safe_path(filepath)
            if not filepath or not isinstance(content, str):
                return False
            if not self._can_write(filepath, os.path.getsize(filepath) + len(content.encode("utf-8"))
                                   if os.path.exists(filepath) else len(content.encode("utf-8"))):
                return False
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(content)
            self._invalidate_usage()  # ARCH-ENG-221
            return True
        except Exception:
            return False
    
    def list_files(self, subdir: str = "") -> List[Dict[str, Any]]:
        """List files in a workshop subdirectory."""
        try:
            dirpath = self._safe_path(subdir or ".")
            if not dirpath or not os.path.isdir(dirpath):
                return []
            results = []
            
            for item in os.listdir(dirpath):
                itempath = os.path.join(dirpath, item)
                if os.path.isfile(itempath):
                    stat = os.stat(itempath)
                    results.append({
                        "name": item,
                        "path": os.path.relpath(itempath, self.root),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
            
            return sorted(results, key=lambda x: x["modified"], reverse=True)
        except Exception:
            return []
    
    def list_dirs(self, subdir: str = "") -> List[str]:
        """List subdirectories."""
        try:
            dirpath = self._safe_path(subdir or ".")
            if not dirpath or not os.path.isdir(dirpath):
                return []
            return [d for d in os.listdir(dirpath) if os.path.isdir(os.path.join(dirpath, d))]
        except Exception:
            return []
    
    def file_exists(self, filepath: str) -> bool:
        """Check if a file exists."""
        filepath = self._safe_path(filepath)
        return bool(filepath and os.path.exists(filepath))
    
    def get_file_info(self, filepath: str) -> Dict[str, Any]:
        """Get file info."""
        try:
            filepath = self._safe_path(filepath)
            if not filepath:
                return {}
            stat = os.stat(filepath)
            return {
                "name": os.path.basename(filepath),
                "path": os.path.relpath(filepath, self.root),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "type": os.path.splitext(filepath)[1],
            }
        except Exception:
            return {}
    
    # ── Proposals ─────────────────────────────────────────────────────────
    
    def create_proposal(self, title: str, client: str, description: str, 
                       platform: str = "", budget: str = "", deadline: str = "") -> str:
        """Create a new proposal document."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w\-_]', '_', title.lower())[:50]
        filename = f"proposal_{safe_title}_{timestamp}.md"
        filepath = os.path.join("proposals", filename)
        
        content = f"""# Proposal: {title}

**Client:** {client}
**Platform:** {platform}
**Budget:** {budget}
**Deadline:** {deadline}
**Created:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

## Description
{description}

## Requirements
- [ ] 

## Deliverables
- [ ] 

## Payment Method
- 

## Status
- [ ] Draft
- [ ] Sent
- [ ] Accepted
- [ ] In Progress
- [ ] Delivered
- [ ] Paid

## Notes

"""
        
        return self._write_or_raise(filepath, content, "Proposal")
    
    def get_proposal(self, filename: str) -> str:
        """Read a proposal file."""
        return self.read_file(os.path.join("proposals", filename))
    
    def list_proposals(self) -> List[Dict[str, Any]]:
        """List all proposals."""
        return self.list_files("proposals")
    
    def update_proposal_status(self, filename: str, status: str) -> bool:
        """Update proposal status."""
        filepath = os.path.join("proposals", filename)
        content = self.read_file(filepath)
        
        # Replace status line
        content = re.sub(r'\n## Status\n.*', f'\n## Status\n- {status}', content)
        return self.write_file(filepath, content)
    
    # ── Research ───────────────────────────────────────────────────────────
    
    def add_research(self, title: str, content: str, tags: List[str] = None) -> str:
        """Add a research note."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w\-_]', '_', title.lower())[:50]
        filename = f"research_{safe_title}_{timestamp}.md"
        filepath = os.path.join("research", filename)
        
        tags_str = ", ".join(tags) if tags else ""
        
        content_text = f"""# {title}

**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Tags:** {tags_str}

## Summary
{content}

## Key Findings
- 

## Action Items
- [ ] 

## Sources
- 

"""
        
        return self._write_or_raise(filepath, content_text, "Research note")
    
    def read_research(self, filename: str) -> str:
        """Read a research file."""
        return self.read_file(os.path.join("research", filename))
    
    def list_research(self) -> List[Dict[str, Any]]:
        """List all research files."""
        return self.list_files("research")
    
    # ── Scripts ────────────────────────────────────────────────────────────
    
    def create_script(self, name: str, language: str, description: str, code: str) -> str:
        """Create a new script."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\-_]', '_', name.lower())[:50]
        
        ext_map = {
            "python": ".py",
            "bash": ".sh",
            "powershell": ".ps1",
            "javascript": ".js",
            "batch": ".bat",
        }
        ext = ext_map.get(language.lower(), ".txt")
        
        filename = f"script_{safe_name}_{timestamp}{ext}"
        filepath = os.path.join("scripts", filename)
        
        content = f"""#!/usr/bin/env {language}
\"\"\"
Script: {name}
Language: {language}
Description: {description}
Created: {datetime.now().strftime("%Y-%m-%d %H:%M")}
\"\"\"

{code}
"""
        
        return self._write_or_raise(filepath, content, "Script")
    
    def read_script(self, filename: str) -> str:
        """Read a script file."""
        return self.read_file(os.path.join("scripts", filename))
    
    def list_scripts(self) -> List[Dict[str, Any]]:
        """List all scripts."""
        return self.list_files("scripts")
    
    # ── Applications ───────────────────────────────────────────────────────
    
    def create_application(self, platform: str, job_type: str, details: Dict[str, str]) -> str:
        """Create a job application document."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_platform = re.sub(r'[^\w\-_]', '_', platform.lower())[:30]
        filename = f"app_{safe_platform}_{timestamp}.md"
        filepath = os.path.join("applications", filename)
        
        content = f"""# Application: {platform}

**Job Type:** {job_type}
**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

## Details
"""
        for key, value in details.items():
            content += f"- **{key}:** {value}\n"
        
        content += """
## Status
- [ ] Draft
- [ ] Submitted
- [ ] In Review
- [ ] Interview
- [ ] Accepted
- [ ] Rejected

## Notes

"""
        
        return self._write_or_raise(filepath, content, "Application document")
    
    def list_applications(self) -> List[Dict[str, Any]]:
        """List all applications."""
        return self.list_files("applications")
    
    # ── Account Management ─────────────────────────────────────────────────
    
    def add_account(self, platform: str, username: str, email: str, 
                     password: str = "", url: str = "", notes: str = "") -> bool:
        """Add a platform account."""
        try:
            accounts = self._load_accounts()
            if accounts is None:
                # ARCH-ENG-066: the store is corrupt/unreadable. Writing now would
                # replace it with a single-account dict and erase every other stored
                # account while this call reported success. Refuse instead; the
                # operator can repair or delete the file.
                return False

            accounts[platform] = {
                "platform": platform,
                "username": username,
                "email": email,
                "password": password,
                "url": url,
                "notes": notes,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            
            self._save_accounts(accounts)
            return True
        except Exception:
            return False
    
    def get_account(self, platform: str) -> Dict[str, str]:
        """Get account info for a platform."""
        accounts = self._load_accounts()
        return (accounts or {}).get(platform, {})
    
    def list_accounts(self) -> List[Dict[str, str]]:
        """List all accounts."""
        accounts = self._load_accounts()
        return list((accounts or {}).values())
    
    def remove_account(self, platform: str) -> bool:
        """Remove an account."""
        try:
            accounts = self._load_accounts()
            if accounts is None:
                # ARCH-ENG-066: refuse to write over an unreadable store.
                return False
            if platform in accounts:
                del accounts[platform]
                self._save_accounts(accounts)
            return True
        except Exception:
            return False
    
    def _load_accounts(self) -> Dict[str, Dict[str, str]]:
        """Load accounts from file.

        ARCH-ENG-066: this used to swallow the parse error and `return {}`. The paired
        `_save_accounts` then wrote that empty dict over the file, so ONE truncated or
        corrupt byte erased every stored platform account — and `add_account()` still
        returned True. The caller is now told the store is unreadable instead of being
        handed a silent empty dict to overwrite with.
        """
        if not os.path.exists(self._accounts_file):
            return {}
        try:
            with open(self._accounts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None  # type: ignore[return-value]
        if not isinstance(data, dict):
            return None  # type: ignore[return-value]
        return data

    def _save_accounts(self, accounts: Dict[str, Dict[str, str]]):
        """Save accounts to file atomically (temp + fsync + os.replace).

        A crash mid-write can no longer leave a truncated policy behind — that
        truncation is what made the read above fail and destroyed the data
        (ARCH-ENG-066).
        """
        _atomic_write_json(self._accounts_file, accounts)
        self._invalidate_usage()  # ARCH-ENG-221
    
    # ── Payment Methods ────────────────────────────────────────────────────
    
    def add_payment_method(self, method: str, identifier: str, 
                          memo: str = "", is_crypto: bool = False) -> bool:
        """Add a payment method."""
        try:
            payments = self._load_payments()
            if payments is None:
                # ARCH-ENG-066: writing now would erase every other stored payment
                # method while this call reported success.
                return False

            payments[method] = {
                "method": method,
                "identifier": identifier,
                "memo": memo,
                "is_crypto": is_crypto,
                "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }

            self._save_payments(payments)
            return True
        except Exception:
            return False

    def get_payment_method(self, method: str) -> Dict[str, str]:
        """Get payment method info."""
        payments = self._load_payments()
        return (payments or {}).get(method, {})

    def list_payment_methods(self) -> List[Dict[str, str]]:
        """List all payment methods."""
        payments = self._load_payments()
        return list((payments or {}).values())
    
    def _load_payments(self) -> Dict[str, Dict[str, str]]:
        """Load payments from file.

        ARCH-ENG-066: same corrupt-read data-loss defect as `_load_accounts` — a
        truncated file returned `{}`, and `add_payment_method` then wrote that empty
        dict over the file, erasing every other payment method while reporting
        success. `None` signals "unreadable" so the caller can refuse to write.
        """
        if not os.path.exists(self._payments_file):
            return {}
        try:
            with open(self._payments_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None  # type: ignore[return-value]
        if not isinstance(data, dict):
            return None  # type: ignore[return-value]
        return data

    def _save_payments(self, payments: Dict[str, Dict[str, str]]):
        """Save payments to file atomically (temp + fsync + os.replace)."""
        _atomic_write_json(self._payments_file, payments)
        self._invalidate_usage()  # ARCH-ENG-221
    
    # ── Deliverables ───────────────────────────────────────────────────────
    
    def add_deliverable(self, title: str, content: str, 
                       client: str = "", platform: str = "") -> str:
        """Add a deliverable."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w\-_]', '_', title.lower())[:50]
        filename = f"deliverable_{safe_title}_{timestamp}.md"
        filepath = os.path.join("deliverables", filename)
        
        content_text = f"""# {title}

**Client:** {client}
**Platform:** {platform}
**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

{content}

"""
        
        return self._write_or_raise(filepath, content_text, "Deliverable")
    
    def list_deliverables(self) -> List[Dict[str, Any]]:
        """List all deliverables."""
        return self.list_files("deliverables")
    
    # ARCH-ENG-245 (AY-02, 11G): the template subsystem -- get_template
    # (four hardcoded skeleton strings nothing ever requested) and
    # save_template (wrote template files NOTHING could read back; the pair
    # was never connected) -- is DELETED. Proposal copy is superseded by the
    # live A/B mechanism in agents/knowledge/proposal_templates.py; document
    # skeletons are what an LLM persona generates natively.
    # ── Notes ──────────────────────────────────────────────────────────────
    
    def add_note(self, title: str, content: str, tags: List[str] = None) -> str:
        """Add a note."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w\-_]', '_', title.lower())[:50]
        filename = f"note_{safe_title}_{timestamp}.md"
        filepath = os.path.join("notes", filename)
        
        tags_str = ", ".join(tags) if tags else ""
        
        content_text = f"""# {title}

**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Tags:** {tags_str}

{content}
"""
        
        return self._write_or_raise(filepath, content_text, "Note")
    
    def list_notes(self) -> List[Dict[str, Any]]:
        """List all notes."""
        return self.list_files("notes")
    
    # ── Search ─────────────────────────────────────────────────────────────
    
    def search_files(self, query: str, subdir: str = "") -> List[Dict[str, str]]:
        """Search files by name or content.

        ARCH-ENG-221: TWO COSTS WERE PAID IN FULL AND THEN THROWN AWAY.

        1. `content = f.read()` was uncapped, so every candidate file was read
           whole -- with a 2 GiB quota that is a 2 GiB read per candidate.
           Content matching now reads at most `WORKSHOP_MAX_READ_BYTES`, which
           is ample for a substring test and bounded for a file of any size.
           A match beyond that window is missed, so the row says which window
           was searched rather than implying a whole-file search.

        2. `return results[:20]` truncated the list AFTER the walk had already
           read every file in the tree. The cap saved the caller 20 rows and
           saved the machine nothing. The walk now stops as soon as the cap is
           reached.
        """
        results: List[Dict[str, str]] = []
        dirpath = self._safe_path(subdir or ".")
        if not dirpath or not os.path.isdir(dirpath):
            return []

        limit = WORKSHOP_MAX_READ_BYTES
        scope_note = f"content (first {limit // 1024} KiB)"
        needle = query.lower()
        for root_dir, dirs, files in os.walk(dirpath):
            for filename in files:
                filepath = os.path.join(root_dir, filename)

                # Search by name
                if needle in filename.lower():
                    results.append({
                        "name": filename,
                        "path": os.path.relpath(filepath, self.root),
                        "match": "filename",
                    })
                    if len(results) >= _SEARCH_FILE_LIMIT:
                        return results
                    continue

                # Search by content (text files only)
                if filename.endswith((".md", ".txt", ".py", ".js", ".json", ".csv")):
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read(limit)
                            if needle in content.lower():
                                results.append({
                                    "name": filename,
                                    "path": os.path.relpath(filepath, self.root),
                                    "match": scope_note,
                                })
                                if len(results) >= _SEARCH_FILE_LIMIT:
                                    return results
                    except Exception:
                        pass

        return results
    
    # ── Stats ──────────────────────────────────────────────────────────────
    
    def get_stats(self) -> Dict[str, int]:
        """Get workspace statistics."""
        stats = {}
        for key, path in self.paths.items():
            if os.path.exists(path):
                count = len([f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))])
                stats[key] = count
        return stats
    
    def get_workspace_summary(self) -> str:
        """Get a summary of the workspace."""
        stats = self.get_stats()
        
        parts = ["## 📁 Workspace Summary"]
        for key, count in stats.items():
            if count > 0:
                parts.append(f"- **{key}:** {count} files")
        
        parts.append(f"\n**Accounts:** {len(self.list_accounts())}")
        parts.append(f"**Payment Methods:** {len(self.list_payment_methods())}")
        
        return "\n".join(parts)


# ── Singleton ──────────────────────────────────────────────────────────────

_workshop = None

def get_workshop() -> Workshop:
    """Get the global Workshop instance."""
    global _workshop
    if _workshop is None:
        _workshop = Workshop()
    return _workshop


# ── Convenience Functions ──────────────────────────────────────────────────





def create_proposal(title: str, client: str, description: str, **kwargs) -> str:
    """Create a new proposal."""
    return get_workshop().create_proposal(title, client, description, **kwargs)






if __name__ == "__main__":
    # Quick test
    print("Testing Workshop...")
    
    ws = Workshop()
    
    # Test stats
    print("\n=== STATS ===")
    stats = ws.get_stats()
    for key, count in stats.items():
        if count > 0:
            print(f"  {key}: {count} files")
    
    # Test proposal creation
    print("\n=== CREATE PROPOSAL ===")
    filepath = ws.create_proposal(
        title="Test Proposal",
        client="Test Client",
        description="This is a test proposal",
        platform="Upwork",
        budget="$100",
        deadline="2025-12-31"
    )
    print(f"Created: {filepath}")
    
    # Test accounts
    print("\n=== ACCOUNTS ===")
    ws.add_account("Fiverr", "test_user", "test@example.com", notes="Test account")
    accounts = ws.list_accounts()
    for acc in accounts:
        print(f"  {acc.get('platform')}: {acc.get('username')}")
    
    # Test payments
    print("\n=== PAYMENTS ===")
    ws.add_payment_method("CashApp", "$csmith7899", "Primary CashApp", is_crypto=False)
    ws.add_payment_method("ETH", "0x1234...abcd", "Ethereum wallet", is_crypto=True)
    payments = ws.list_payment_methods()
    for pm in payments:
        print(f"  {pm.get('method')}: {pm.get('identifier')}")
    
    # Test search
    print("\n=== SEARCH ===")
    results = ws.search_files("test")
    for r in results:
        print(f"  {r.get('name')} ({r.get('match')})")
