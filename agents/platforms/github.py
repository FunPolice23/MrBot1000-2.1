"""
agents/platforms/github.py — GitHub API adapter (v2.1 Phase 1).

Implements real GitHub API integration for:
- Issue search with labels (bounty, help wanted, good first issue)
- Issue detail reading
- PR creation (human-gated)
- Repository search

Uses GitHub REST/GraphQL API v3/v4 with PAT auth.
Docs: https://docs.github.com/en/rest
"""

import time
import urllib.request
import urllib.parse
import json
import base64
from typing import List, Optional, Dict, Any

from .base import PlatformAdapter
from ..trust_boundary import HIGH_TRUST_ACTIONS


class GitHubAdapter(PlatformAdapter):
    """GitHub API adapter with real PAT integration."""
    
    platform = "github"
    ai_policy = "ai_allowed"  # GitHub permits AI-assisted work
    base_url = "https://github.com"
    api_base = "https://api.github.com"
    
    def __init__(self, gate, boundary=None, *, credentials=None, enabled=False):
        super().__init__(gate, boundary, credentials=credentials, enabled=enabled)
        self._token = None
        self._rate_limit_remaining = 5000
        self._rate_limit_reset = 0
    
    def instruction_url(self):
        return None
    
    def list_actions(self):
        return [
            "search_issues",
            "read_issue",
            "search_repos",
            "read_repo",
            "create_pr",
            "create_issue",
            "get_user",
            "get_rate_limit",
        ]
    
    def _do_action(self, action, payload, *, confirmed_by_human=False):
        if action == "search_issues":
            return self._search_issues(payload)
        if action == "read_issue":
            return self._read_issue(payload)
        if action == "search_repos":
            return self._search_repos(payload)
        if action == "read_repo":
            return self._read_repo(payload)
        if action == "create_pr":
            return self._create_pr(payload, confirmed_by_human)
        if action == "create_issue":
            return self._create_issue(payload, confirmed_by_human)
        if action == "get_user":
            return self._get_user()
        if action == "get_rate_limit":
            return self._get_rate_limit()
        return {"ok": False, "reason": f"unknown action {action}"}
    
    def _ensure_auth(self):
        """Ensure we have a valid token."""
        if self.credentials and self.credentials.get("token"):
            self._token = self.credentials["token"]
            return True
        return False
    
    def _api_call(self, endpoint: str, params: dict = None, method: str = "GET", data: dict = None) -> dict:
        """Make an authenticated API call with rate limiting."""
        if not self._ensure_auth():
            return {"ok": False, "reason": "authentication failed - PAT required"}
        
        # Check rate limit
        if self._rate_limit_remaining <= 0 and time.time() < self._rate_limit_reset:
            return {"ok": False, "reason": "rate limit exceeded"}
        
        url = f"{self.api_base}/{endpoint}"
        if params and method == "GET":
            url += "?" + urllib.parse.urlencode(params)
        
        if data and method in ("POST", "PATCH"):
            body = json.dumps(data, default=str).encode()
        else:
            body = None
        
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"token {self._token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        if body:
            req.add_header("Content-Type", "application/json")
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                # Update rate limit tracking
                self._rate_limit_remaining = int(resp.headers.get("X-RateLimit-Remaining", 5000))
                self._rate_limit_reset = float(resp.headers.get("X-RateLimit-Reset", 0))
                
                data = json.loads(resp.read().decode())
                return {"ok": True, "data": data}
        except urllib.error.HTTPError as e:
            return {"ok": False, "reason": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"ok": False, "reason": str(e)}
    
    def _search_issues(self, payload: dict) -> dict:
        """Search for issues with labels."""
        query_parts = []
        
        if payload.get("query"):
            query_parts.append(payload["query"])
        
        if payload.get("labels"):
            for label in payload["labels"]:
                query_parts.append(f"label:{label}")
        
        if payload.get("language"):
            query_parts.append(f"language:{payload['language']}")
        
        if payload.get("state"):
            query_parts.append(f"state:{payload['state']}")
        else:
            query_parts.append("state:open")
        
        if payload.get("repo"):
            query_parts.append(f"repo:{payload['repo']}")
        
        if payload.get("author"):
            query_parts.append(f"author:{payload['author']}")
        
        if payload.get("assignee"):
            query_parts.append(f"assignee:{payload['assignee']}")
        else:
            query_parts.append("no:assignee")
        
        query = " ".join(query_parts)
        
        params = {
            "q": query,
            "sort": payload.get("sort", "created"),
            "order": payload.get("order", "desc"),
            "per_page": payload.get("limit", 30),
            "page": payload.get("page", 1),
        }
        
        result = self._api_call("search/issues", params)
        
        if result.get("ok"):
            items = result["data"].get("items", [])
            opportunities = []
            for item in items:
                opportunities.append({
                    "id": item.get("id", ""),
                    "number": item.get("number", ""),
                    "title": item.get("title", ""),
                    "description": item.get("body", "")[:500] if item.get("body") else "",
                    "url": item.get("html_url", ""),
                    "repo": item.get("repository_url", "").split("/")[-2:] if item.get("repository_url") else "",
                    "labels": [l.get("name", "") for l in item.get("labels", [])],
                    "author": item.get("user", {}).get("login", ""),
                    "created": item.get("created_at", ""),
                    "updated": item.get("updated_at", ""),
                    "comments": item.get("comments", 0),
                    "bounty_label": any("bounty" in l.lower() for l in [l.get("name", "") for l in item.get("labels", [])]),
                })
            return {
                "ok": True,
                "opportunities": opportunities,
                "count": len(opportunities),
                "total_count": result["data"].get("total_count", 0),
            }
        
        return result
    
    def _read_issue(self, payload: dict) -> dict:
        """Read full issue details."""
        owner = payload.get("owner", "")
        repo = payload.get("repo", "")
        issue_number = payload.get("issue_number", "")
        
        if not all([owner, repo, issue_number]):
            return {"ok": False, "reason": "owner, repo, and issue_number required"}
        
        result = self._api_call(f"repos/{owner}/{repo}/issues/{issue_number}")
        
        if result.get("ok"):
            issue = result["data"]
            return {
                "ok": True,
                "issue": {
                    "id": issue.get("id", ""),
                    "number": issue.get("number", ""),
                    "title": issue.get("title", ""),
                    "description": issue.get("body", "") if issue.get("body") else "",
                    "url": issue.get("html_url", ""),
                    "repo": f"{owner}/{repo}",
                    "labels": [l.get("name", "") for l in issue.get("labels", [])],
                    "author": issue.get("user", {}).get("login", ""),
                    "state": issue.get("state", ""),
                    "created": issue.get("created_at", ""),
                    "updated": issue.get("updated_at", ""),
                    "comments": issue.get("comments", 0),
                    "assignees": [a.get("login", "") for a in issue.get("assignees", [])],
                    "milestone": issue.get("milestone", {}).get("title", "") if issue.get("milestone") else "",
                }
            }
        
        return result
    
    def _search_repos(self, payload: dict) -> dict:
        """Search for repositories."""
        query_parts = []
        
        if payload.get("query"):
            query_parts.append(payload["query"])
        
        if payload.get("language"):
            query_parts.append(f"language:{payload['language']}")
        
        if payload.get("stars_min"):
            query_parts.append(f"stars:>={payload['stars_min']}")
        
        if payload.get("forks_min"):
            query_parts.append(f"forks:>={payload['forks_min']}")
        
        if payload.get("created_after"):
            query_parts.append(f"created:>={payload['created_after']}")
        
        query = " ".join(query_parts)
        
        params = {
            "q": query,
            "sort": payload.get("sort", "stars"),
            "order": payload.get("order", "desc"),
            "per_page": payload.get("limit", 30),
            "page": payload.get("page", 1),
        }
        
        result = self._api_call("search/repositories", params)
        
        if result.get("ok"):
            items = result["data"].get("items", [])
            repos = []
            for item in items:
                repos.append({
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "full_name": item.get("full_name", ""),
                    "description": item.get("description", "")[:500] if item.get("description") else "",
                    "url": item.get("html_url", ""),
                    "stars": item.get("stargazers_count", 0),
                    "forks": item.get("forks_count", 0),
                    "language": item.get("language", ""),
                    "created": item.get("created_at", ""),
                    "updated": item.get("updated_at", ""),
                    "open_issues": item.get("open_issues_count", 0),
                    "topics": item.get("topics", []),
                })
            return {
                "ok": True,
                "repos": repos,
                "count": len(repos),
                "total_count": result["data"].get("total_count", 0),
            }
        
        return result
    
    def _read_repo(self, payload: dict) -> dict:
        """Read repository details."""
        owner = payload.get("owner", "")
        repo = payload.get("repo", "")
        
        if not all([owner, repo]):
            return {"ok": False, "reason": "owner and repo required"}
        
        result = self._api_call(f"repos/{owner}/{repo}")
        
        if result.get("ok"):
            r = result["data"]
            return {
                "ok": True,
                "repo": {
                    "id": r.get("id", ""),
                    "name": r.get("name", ""),
                    "full_name": r.get("full_name", ""),
                    "description": r.get("description", "") if r.get("description") else "",
                    "url": r.get("html_url", ""),
                    "stars": r.get("stargazers_count", 0),
                    "forks": r.get("forks_count", 0),
                    "language": r.get("language", ""),
                    "created": r.get("created_at", ""),
                    "updated": r.get("updated_at", ""),
                    "open_issues": r.get("open_issues_count", 0),
                    "topics": r.get("topics", []),
                    "license": r.get("license", {}).get("name", "") if r.get("license") else "",
                    "default_branch": r.get("default_branch", "main"),
                }
            }
        
        return result
    
    def _create_pr(self, payload: dict, confirmed_by_human: bool) -> dict:
        """Create a pull request (requires human confirmation)."""
        if not confirmed_by_human:
            return {
                "ok": False,
                "reason": "create_pr requires human confirmation",
                "note": "This is a HIGH_TRUST action. The human must confirm before creation."
            }
        
        owner = payload.get("owner", "")
        repo = payload.get("repo", "")
        title = payload.get("title", "")
        body = payload.get("body", "")
        head = payload.get("head", "")
        base = payload.get("base", "main")
        
        if not all([owner, repo, title, head]):
            return {"ok": False, "reason": "owner, repo, title, and head required"}
        
        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        
        result = self._api_call(f"repos/{owner}/{repo}/pulls", method="POST", data=data)
        
        if result.get("ok"):
            pr = result["data"]
            return {
                "ok": True,
                "pr": {
                    "id": pr.get("id", ""),
                    "number": pr.get("number", ""),
                    "title": pr.get("title", ""),
                    "url": pr.get("html_url", ""),
                    "state": pr.get("state", ""),
                }
            }
        
        return result
    
    def _create_issue(self, payload: dict, confirmed_by_human: bool) -> dict:
        """Create an issue (requires human confirmation)."""
        if not confirmed_by_human:
            return {
                "ok": False,
                "reason": "create_issue requires human confirmation",
                "note": "This is a HIGH_TRUST action. The human must confirm before creation."
            }
        
        owner = payload.get("owner", "")
        repo = payload.get("repo", "")
        title = payload.get("title", "")
        body = payload.get("body", "")
        labels = payload.get("labels", [])
        
        if not all([owner, repo, title]):
            return {"ok": False, "reason": "owner, repo, and title required"}
        
        data = {
            "title": title,
            "body": body,
            "labels": labels,
        }
        
        result = self._api_call(f"repos/{owner}/{repo}/issues", method="POST", data=data)
        
        if result.get("ok"):
            issue = result["data"]
            return {
                "ok": True,
                "issue": {
                    "id": issue.get("id", ""),
                    "number": issue.get("number", ""),
                    "title": issue.get("title", ""),
                    "url": issue.get("html_url", ""),
                    "state": issue.get("state", ""),
                }
            }
        
        return result
    
    def _get_user(self) -> dict:
        """Get current user."""
        return self._api_call("user")
    
    def _get_rate_limit(self) -> dict:
        """Get rate limit status."""
        return self._api_call("rate_limit")
