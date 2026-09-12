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
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path


# ── Workspace Paths ───────────────────────────────────────────────────────

WORKSHOP_ROOT = r"D:\ai_workshop"

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
    "templates": os.path.join(WORKSHOP_ROOT, "templates"),
    "notes": os.path.join(WORKSHOP_ROOT, "notes"),
    "crypto": os.path.join(WORKSHOP_ROOT, "crypto"),
    "memory": os.path.join(WORKSHOP_ROOT, "memory"),
}


class Workshop:
    """Workspace manager for persona agents."""
    
    def __init__(self, root: str = WORKSHOP_ROOT):
        self.root = root
        self._ensure_dirs()
        self._accounts_file = os.path.join(root, "accounts", "accounts.json")
        self._payments_file = os.path.join(root, "payments.json")
        self._tasks_file = os.path.join(root, "tasks.json")
    
    def _ensure_dirs(self):
        """Create all workshop directories if they don't exist."""
        for path in PATHS.values():
            os.makedirs(path, exist_ok=True)
    
    # ── File Operations ────────────────────────────────────────────────────
    
    def read_file(self, filepath: str) -> str:
        """Read a file from the workshop."""
        try:
            # Handle relative paths
            if not os.path.isabs(filepath):
                filepath = os.path.join(self.root, filepath)
            
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"
    
    def write_file(self, filepath: str, content: str) -> bool:
        """Write a file to the workshop."""
        try:
            if not os.path.isabs(filepath):
                filepath = os.path.join(self.root, filepath)
            
            # Create parent dirs if needed
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            return False
    
    def append_file(self, filepath: str, content: str) -> bool:
        """Append to a file in the workshop."""
        try:
            if not os.path.isabs(filepath):
                filepath = os.path.join(self.root, filepath)
            
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception:
            return False
    
    def list_files(self, subdir: str = "") -> List[Dict[str, Any]]:
        """List files in a workshop subdirectory."""
        try:
            dirpath = os.path.join(self.root, subdir) if subdir else self.root
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
            dirpath = os.path.join(self.root, subdir) if subdir else self.root
            return [d for d in os.listdir(dirpath) if os.path.isdir(os.path.join(dirpath, d))]
        except Exception:
            return []
    
    def file_exists(self, filepath: str) -> bool:
        """Check if a file exists."""
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.root, filepath)
        return os.path.exists(filepath)
    
    def get_file_info(self, filepath: str) -> Dict[str, Any]:
        """Get file info."""
        try:
            if not os.path.isabs(filepath):
                filepath = os.path.join(self.root, filepath)
            
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
        
        self.write_file(filepath, content)
        return filepath
    
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
        
        self.write_file(filepath, content_text)
        return filepath
    
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
        
        self.write_file(filepath, content)
        return filepath
    
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
        
        self.write_file(filepath, content)
        return filepath
    
    def list_applications(self) -> List[Dict[str, Any]]:
        """List all applications."""
        return self.list_files("applications")
    
    # ── Account Management ─────────────────────────────────────────────────
    
    def add_account(self, platform: str, username: str, email: str, 
                     password: str = "", url: str = "", notes: str = "") -> bool:
        """Add a platform account."""
        try:
            accounts = self._load_accounts()
            
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
        return accounts.get(platform, {})
    
    def list_accounts(self) -> List[Dict[str, str]]:
        """List all accounts."""
        accounts = self._load_accounts()
        return list(accounts.values())
    
    def remove_account(self, platform: str) -> bool:
        """Remove an account."""
        try:
            accounts = self._load_accounts()
            if platform in accounts:
                del accounts[platform]
                self._save_accounts(accounts)
            return True
        except Exception:
            return False
    
    def _load_accounts(self) -> Dict[str, Dict[str, str]]:
        """Load accounts from file."""
        try:
            if os.path.exists(self._accounts_file):
                with open(self._accounts_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}
    
    def _save_accounts(self, accounts: Dict[str, Dict[str, str]]):
        """Save accounts to file."""
        os.makedirs(os.path.dirname(self._accounts_file), exist_ok=True)
        with open(self._accounts_file, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)
    
    # ── Payment Methods ────────────────────────────────────────────────────
    
    def add_payment_method(self, method: str, identifier: str, 
                          memo: str = "", is_crypto: bool = False) -> bool:
        """Add a payment method."""
        try:
            payments = self._load_payments()
            
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
        return payments.get(method, {})
    
    def list_payment_methods(self) -> List[Dict[str, str]]:
        """List all payment methods."""
        payments = self._load_payments()
        return list(payments.values())
    
    def _load_payments(self) -> Dict[str, Dict[str, str]]:
        """Load payments from file."""
        try:
            if os.path.exists(self._payments_file):
                with open(self._payments_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}
    
    def _save_payments(self, payments: Dict[str, Dict[str, str]]):
        """Save payments to file."""
        with open(self._payments_file, "w", encoding="utf-8") as f:
            json.dump(payments, f, indent=2)
    
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
        
        self.write_file(filepath, content_text)
        return filepath
    
    def list_deliverables(self) -> List[Dict[str, Any]]:
        """List all deliverables."""
        return self.list_files("deliverables")
    
    # ── Templates ─────────────────────────────────────────────────────────
    
    def get_template(self, template_name: str) -> str:
        """Get a template by name."""
        templates = {
            "proposal": """# Proposal: [TITLE]

**Client:** [CLIENT]
**Platform:** [PLATFORM]
**Budget:** $[AMOUNT]

## Summary
[1-2 sentence pitch]

## Approach
[How you'll do the work]

## Timeline
[When you'll deliver]

## Why Me
[Your qualifications]

## Next Steps
[What the client should do next]
""",
            "application": """# Application: [POSITION]

**Platform:** [PLATFORM]
**Job Type:** [TYPE]

## Cover Letter
[Your pitch]

## Skills
- 

## Experience
- 

## Availability
[When you can start]
""",
            "research_note": """# [TITLE]

**Date:** [DATE]
**Tags:** [TAGS]

## Summary


## Key Findings
- 

## Action Items
- [ ] 

## Sources
- 
""",
            "invoice": """# Invoice

**From:** MrBot1000 (Edward Hurst + Jacob Stanley)
**To:** [CLIENT]
**Date:** [DATE]

## Services
| Item | Description | Amount |
|------|-------------|--------|
| [SERVICE] | [DESCRIPTION] | $[AMOUNT] |

**Total:** $[AMOUNT]

**Payment Method:** [METHOD]

## Notes
- Payment due within [DAYS] days
- 
""",
        }
        
        return templates.get(template_name, "Template not found")
    
    def save_template(self, name: str, content: str) -> str:
        """Save a custom template."""
        filename = f"template_{name}.md"
        filepath = os.path.join("templates", filename)
        self.write_file(filepath, content)
        return filepath
    
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
        
        self.write_file(filepath, content_text)
        return filepath
    
    def list_notes(self) -> List[Dict[str, Any]]:
        """List all notes."""
        return self.list_files("notes")
    
    # ── Search ─────────────────────────────────────────────────────────────
    
    def search_files(self, query: str, subdir: str = "") -> List[Dict[str, str]]:
        """Search files by name or content."""
        results = []
        dirpath = os.path.join(self.root, subdir) if subdir else self.root
        
        for root_dir, dirs, files in os.walk(dirpath):
            for filename in files:
                filepath = os.path.join(root_dir, filename)
                
                # Search by name
                if query.lower() in filename.lower():
                    results.append({
                        "name": filename,
                        "path": os.path.relpath(filepath, self.root),
                        "match": "filename",
                    })
                    continue
                
                # Search by content (text files only)
                if filename.endswith((".md", ".txt", ".py", ".js", ".json", ".csv")):
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                            if query.lower() in content.lower():
                                results.append({
                                    "name": filename,
                                    "path": os.path.relpath(filepath, self.root),
                                    "match": "content",
                                })
                    except Exception:
                        pass
        
        return results[:20]  # Limit results
    
    # ── Stats ──────────────────────────────────────────────────────────────
    
    def get_stats(self) -> Dict[str, int]:
        """Get workspace statistics."""
        stats = {}
        for key, path in PATHS.items():
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

def read_workshop_file(filepath: str) -> str:
    """Read a file from the workshop."""
    return get_workshop().read_file(filepath)

def write_workshop_file(filepath: str, content: str) -> bool:
    """Write a file to the workshop."""
    return get_workshop().write_file(filepath, content)

def list_workshop_files(subdir: str = "") -> List[Dict[str, Any]]:
    """List files in a workshop subdirectory."""
    return get_workshop().list_files(subdir)

def search_workshop(query: str) -> List[Dict[str, str]]:
    """Search workshop files."""
    return get_workshop().search_files(query)

def create_proposal(title: str, client: str, description: str, **kwargs) -> str:
    """Create a new proposal."""
    return get_workshop().create_proposal(title, client, description, **kwargs)

def create_research_note(title: str, content: str, **kwargs) -> str:
    """Create a research note."""
    return get_workshop().add_research(title, content, **kwargs)

def get_template(name: str) -> str:
    """Get a template."""
    return get_workshop().get_template(name)


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
