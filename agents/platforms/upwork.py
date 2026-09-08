"""
agents/platforms/upwork.py — Upwork API adapter (v2.1 Phase 1).

Implements real Upwork API integration for:
- Job search with filters (budget, skills, duration)
- Job detail reading
- Proposal drafting (local)
- Proposal submission (human-gated)

Uses Upwork API v2 with OAuth 2.0.
Docs: https://developers.upwork.com/
"""

import time
import urllib.request
import urllib.parse
import json
from typing import List, Optional, Dict, Any

from .base import PlatformAdapter
from ..trust_boundary import HIGH_TRUST_ACTIONS


class UpworkAdapter(PlatformAdapter):
    """Upwork API adapter with real OAuth 2.0 integration."""
    
    platform = "upwork"
    ai_policy = "ai_allowed"  # Upwork permits AI-assisted work
    base_url = "https://www.upwork.com"
    api_base = "https://www.upwork.com/api"
    
    def __init__(self, gate, boundary=None, *, credentials=None, enabled=False):
        super().__init__(gate, boundary, credentials=credentials, enabled=enabled)
        self._access_token = None
        self._token_expires = 0
        self._rate_limit_remaining = 100
        self._rate_limit_reset = 0
    
    def instruction_url(self):
        return None
    
    def list_actions(self):
        return [
            "search_jobs",
            "read_job",
            "draft_proposal",
            "submit_proposal",
            "get_profile",
            "get_categories",
        ]
    
    def _do_action(self, action, payload, *, confirmed_by_human=False):
        if action == "search_jobs":
            return self._search_jobs(payload)
        if action == "read_job":
            return self._read_job(payload)
        if action == "draft_proposal":
            return self._draft_proposal(payload)
        if action == "submit_proposal":
            return self._submit_proposal(payload, confirmed_by_human)
        if action == "get_profile":
            return self._get_profile()
        if action == "get_categories":
            return self._get_categories()
        return {"ok": False, "reason": f"unknown action {action}"}
    
    def _ensure_auth(self):
        """Ensure we have a valid access token."""
        if self._access_token and time.time() < self._token_expires:
            return True
        
        if not self.credentials:
            return False
        
        # OAuth 2.0 token refresh
        try:
            token_url = "https://www.upwork.com/api/auth/v1/oauth2/token"
            data = urllib.parse.urlencode({
                "grant_type": "client_credentials",
                "client_id": self.credentials.get("client_id", ""),
                "client_secret": self.credentials.get("client_secret", ""),
            }).encode()
            
            req = urllib.request.Request(token_url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                self._access_token = result.get("access_token")
                self._token_expires = time.time() + result.get("expires_in", 3600)
                return True
        except Exception as e:
            return False
    
    def _api_call(self, endpoint: str, params: dict = None) -> dict:
        """Make an authenticated API call with rate limiting."""
        if not self._ensure_auth():
            return {"ok": False, "reason": "authentication failed"}
        
        # Check rate limit
        if self._rate_limit_remaining <= 0 and time.time() < self._rate_limit_reset:
            return {"ok": False, "reason": "rate limit exceeded"}
        
        url = f"{self.api_base}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self._access_token}")
        req.add_header("Accept", "application/json")
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                # Update rate limit tracking
                self._rate_limit_remaining = int(resp.headers.get("X-RateLimit-Remaining", 100))
                self._rate_limit_reset = float(resp.headers.get("X-RateLimit-Reset", 0))
                
                data = json.loads(resp.read().decode())
                return {"ok": True, "data": data}
        except urllib.error.HTTPError as e:
            return {"ok": False, "reason": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"ok": False, "reason": str(e)}
    
    def _search_jobs(self, payload: dict) -> dict:
        """Search for jobs with filters."""
        params = {
            "q": payload.get("query", ""),
            "category2": payload.get("category", ""),
            "subcategory2": payload.get("subcategory", ""),
            "budget_min": payload.get("budget_min", ""),
            "budget_max": payload.get("budget_max", ""),
            "duration": payload.get("duration", ""),
            "sort": payload.get("sort", "create_time+desc"),
            "paging": f"0:{payload.get('limit', 20)}",
        }
        
        # Remove empty params
        params = {k: v for k, v in params.items() if v}
        
        result = self._api_call("profiles/v2/search/jobs.json", params)
        
        if result.get("ok"):
            jobs = result["data"].get("jobs", [])
            opportunities = []
            for job in jobs:
                opportunities.append({
                    "id": job.get("id", ""),
                    "title": job.get("title", ""),
                    "description": job.get("snippet", "")[:500],
                    "budget": job.get("budget", {}),
                    "duration": job.get("duration", ""),
                    "category": job.get("category2", ""),
                    "subcategory": job.get("subcategory2", ""),
                    "client": job.get("client", {}),
                    "url": f"{self.base_url}/jobs/{job.get('id', '')}",
                    "created": job.get("create_time", ""),
                    "proposals": job.get("proposals_tier", ""),
                })
            return {"ok": True, "opportunities": opportunities, "count": len(opportunities)}
        
        return result
    
    def _read_job(self, payload: dict) -> dict:
        """Read full job details."""
        job_id = payload.get("job_id", "")
        if not job_id:
            return {"ok": False, "reason": "job_id required"}
        
        result = self._api_call(f"profiles/v2/jobs/{job_id}.json")
        
        if result.get("ok"):
            job = result["data"]
            return {
                "ok": True,
                "job": {
                    "id": job.get("id", ""),
                    "title": job.get("title", ""),
                    "description": job.get("description", ""),
                    "budget": job.get("budget", {}),
                    "duration": job.get("duration", ""),
                    "category": job.get("category2", ""),
                    "subcategory": job.get("subcategory2", ""),
                    "skills": job.get("skills", []),
                    "client": job.get("client", {}),
                    "url": f"{self.base_url}/jobs/{job.get('id', '')}",
                    "created": job.get("create_time", ""),
                    "proposals": job.get("proposals_tier", ""),
                    "job_type": job.get("job_type", ""),
                    "contractor_tier": job.get("contractor_tier", ""),
                }
            }
        
        return result
    
    def _draft_proposal(self, payload: dict) -> dict:
        """Draft a proposal locally (not submitted)."""
        job_id = payload.get("job_id", "")
        cover_letter = payload.get("cover_letter", "")
        rate = payload.get("rate", 0)
        
        if not job_id:
            return {"ok": False, "reason": "job_id required"}
        
        # Local draft only - never auto-submits
        return {
            "ok": True,
            "draft": {
                "job_id": job_id,
                "cover_letter": cover_letter,
                "rate": rate,
                "status": "draft",
                "note": "Local draft only. Use submit_proposal with human confirmation to send.",
            }
        }
    
    def _submit_proposal(self, payload: dict, confirmed_by_human: bool) -> dict:
        """Submit a proposal (requires human confirmation)."""
        if not confirmed_by_human:
            return {
                "ok": False,
                "reason": "submit_proposal requires human confirmation",
                "note": "This is a HIGH_TRUST action. The human must confirm before submission."
            }
        
        job_id = payload.get("job_id", "")
        cover_letter = payload.get("cover_letter", "")
        rate = payload.get("rate", 0)
        
        if not job_id:
            return {"ok": False, "reason": "job_id required"}
        
        # Build proposal payload
        proposal_data = {
            "job_id": job_id,
            "cover_letter": cover_letter,
            "rate": rate,
        }
        
        result = self._api_call("profiles/v2/proposals.json", proposal_data)
        
        if result.get("ok"):
            return {
                "ok": True,
                "proposal_id": result["data"].get("id", ""),
                "status": "submitted",
                "note": "Proposal submitted successfully.",
            }
        
        return result
    
    def _get_profile(self) -> dict:
        """Get current user profile."""
        return self._api_call("profiles/v2/users/me.json")
    
    def _get_categories(self) -> dict:
        """Get available job categories."""
        return self._api_call("profiles/v2/categories.json")
