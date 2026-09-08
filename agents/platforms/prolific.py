"""
agents/platforms/prolific.py — Prolific API adapter (v2.1 Phase 1).

Implements real Prolific API integration for:
- Study search with filters (reward, duration, participant eligibility)
- Study detail reading
- Study submission (human-gated)

Uses Prolific API v1 with API key auth.
Docs: https://docs.prolific.com/docs/api-docs/public/
"""

import time
import urllib.request
import urllib.parse
import json
from typing import List, Optional, Dict, Any

from .base import PlatformAdapter
from ..trust_boundary import HIGH_TRUST_ACTIONS


class ProlificAdapter(PlatformAdapter):
    """Prolific API adapter with real API key integration."""
    
    platform = "prolific"
    ai_policy = "human_only"  # Prolific requires human participants
    base_url = "https://www.prolific.com"
    api_base = "https://api.prolific.com/api/v1"
    
    def __init__(self, gate, boundary=None, *, credentials=None, enabled=False):
        super().__init__(gate, boundary, credentials=credentials, enabled=False)  # Disabled by default
        self._api_key = None
        self._rate_limit_remaining = 60
        self._rate_limit_reset = 0
    
    def instruction_url(self):
        return None
    
    def list_actions(self):
        return [
            "search_studies",
            "read_study",
            "check_eligibility",
            "submit_participation",
            "get_profile",
        ]
    
    def _do_action(self, action, payload, *, confirmed_by_human=False):
        if action == "search_studies":
            return self._search_studies(payload)
        if action == "read_study":
            return self._read_study(payload)
        if action == "check_eligibility":
            return self._check_eligibility(payload)
        if action == "submit_participation":
            return self._submit_participation(payload, confirmed_by_human)
        if action == "get_profile":
            return self._get_profile()
        return {"ok": False, "reason": f"unknown action {action}"}
    
    def _ensure_auth(self):
        """Ensure we have a valid API key."""
        if self.credentials and self.credentials.get("api_key"):
            self._api_key = self.credentials["api_key"]
            return True
        return False
    
    def _api_call(self, endpoint: str, params: dict = None, method: str = "GET", data: dict = None) -> dict:
        """Make an authenticated API call with rate limiting."""
        if not self._ensure_auth():
            return {"ok": False, "reason": "authentication failed - API key required"}
        
        # Check rate limit
        if self._rate_limit_remaining <= 0 and time.time() < self._rate_limit_reset:
            return {"ok": False, "reason": "rate limit exceeded"}
        
        url = f"{self.api_base}/{endpoint}"
        if params and method == "GET":
            url += "?" + urllib.parse.urlencode(params)
        
        if data and method == "POST":
            body = json.dumps(data).encode()
        else:
            body = None
        
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"Bearer {self._api_key}")
        req.add_header("Accept", "application/json")
        if body:
            req.add_header("Content-Type", "application/json")
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                # Update rate limit tracking
                self._rate_limit_remaining = int(resp.headers.get("X-RateLimit-Remaining", 60))
                self._rate_limit_reset = float(resp.headers.get("X-RateLimit-Reset", 0))
                
                data = json.loads(resp.read().decode())
                return {"ok": True, "data": data}
        except urllib.error.HTTPError as e:
            return {"ok": False, "reason": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"ok": False, "reason": str(e)}
    
    def _search_studies(self, payload: dict) -> dict:
        """Search for available studies."""
        params = {
            "state": payload.get("state", "ACTIVE"),
            "min_reward": payload.get("min_reward", ""),
            "max_reward": payload.get("max_reward", ""),
            "duration_min": payload.get("duration_min", ""),
            "duration_max": payload.get("duration_max", ""),
            "study_type": payload.get("study_type", ""),
            "sort": payload.get("sort", "publish_at"),
            "limit": payload.get("limit", 20),
            "offset": payload.get("offset", 0),
        }
        
        # Remove empty params
        params = {k: v for k, v in params.items() if v}
        
        result = self._api_call("studies/", params)
        
        if result.get("ok"):
            studies = result["data"].get("results", [])
            opportunities = []
            for study in studies:
                opportunities.append({
                    "id": study.get("id", ""),
                    "title": study.get("name", ""),
                    "description": study.get("description", "")[:500],
                    "reward": study.get("reward", 0),
                    "duration": study.get("estimated_completion_time", 0),
                    "study_type": study.get("study_type", ""),
                    "url": f"{self.base_url}/studies/{study.get('id', '')}",
                    "published": study.get("published_at", ""),
                    "participants": study.get("total_available_places", 0),
                    "eligibility": study.get("eligibility_criteria", []),
                })
            return {"ok": True, "opportunities": opportunities, "count": len(opportunities)}
        
        return result
    
    def _read_study(self, payload: dict) -> dict:
        """Read full study details."""
        study_id = payload.get("study_id", "")
        if not study_id:
            return {"ok": False, "reason": "study_id required"}
        
        result = self._api_call(f"studies/{study_id}/")
        
        if result.get("ok"):
            study = result["data"]
            return {
                "ok": True,
                "study": {
                    "id": study.get("id", ""),
                    "title": study.get("name", ""),
                    "description": study.get("description", ""),
                    "reward": study.get("reward", 0),
                    "duration": study.get("estimated_completion_time", 0),
                    "study_type": study.get("study_type", ""),
                    "url": f"{self.base_url}/studies/{study.get('id', '')}",
                    "published": study.get("published_at", ""),
                    "participants": study.get("total_available_places", 0),
                    "eligibility": study.get("eligibility_criteria", []),
                    "requirements": study.get("requirements", []),
                    "naivety": study.get("naivety", ""),
                    "devices": study.get("devices", []),
                }
            }
        
        return result
    
    def _check_eligibility(self, payload: dict) -> dict:
        """Check eligibility for a study."""
        study_id = payload.get("study_id", "")
        if not study_id:
            return {"ok": False, "reason": "study_id required"}
        
        result = self._api_call(f"studies/{study_id}/eligibility/")
        
        if result.get("ok"):
            eligibility = result["data"]
            return {
                "ok": True,
                "eligible": eligibility.get("eligible", False),
                "reasons": eligibility.get("reasons", []),
            }
        
        return result
    
    def _submit_participation(self, payload: dict, confirmed_by_human: bool) -> dict:
        """Submit participation (requires human confirmation)."""
        if not confirmed_by_human:
            return {
                "ok": False,
                "reason": "submit_participation requires human confirmation",
                "note": "Prolific requires human participants. AI cannot complete studies."
            }
        
        study_id = payload.get("study_id", "")
        if not study_id:
            return {"ok": False, "reason": "study_id required"}
        
        # Note: Prolific requires human participants, so this is a no-op
        return {
            "ok": False,
            "reason": "Prolific requires human participants. AI cannot complete studies.",
            "note": "This action is disabled by policy."
        }
    
    def _get_profile(self) -> dict:
        """Get current user profile."""
        return self._api_call("users/me/")
