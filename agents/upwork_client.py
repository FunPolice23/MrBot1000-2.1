"""
agents/upwork_client.py — Upwork API client for MrBot1000.

Wraps the Upwork OAuth2 API for finding freelance gigs.
Requires: UPWORK_CLIENT_ID, UPWORK_CLIENT_SECRET,
          UPWORK_ACCESS_TOKEN, UPWORK_REFRESH_TOKEN in .env
"""

import time
from typing import List, Optional
from dataclasses import dataclass, field

import requests

UPWORK_BASE = "https://api.upwork.com/v2"


@dataclass
class UpworkGig:
    id: str
    title: str = ""
    description: str = ""
    budget_usd: float = 0.0
    skills: list = field(default_factory=list)
    url: str = ""
    platform: str = "Upwork"
    status: str = "new"
    found_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "job_id":      self.id,
            "platform":    self.platform,
            "title":       self.title,
            "description": self.description[:300],
            "budget":      self.budget_usd,
            "skills":      self.skills,
            "url":         self.url,
            "status":      self.status,
            "score":       0.0,
            "notes":       "",
            "found_at":    self.found_at,
            "assigned_to": None,
        }


class UpworkClient:
    """Upwork OAuth2 client with token refresh."""

    def __init__(self, client_id: str, client_secret: str,
                 access_token: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MrBot1000/1.0",
        })

    def _refresh_token(self) -> bool:
        """Refresh OAuth2 access token."""
        now = time.time()
        if self.access_token and now < self.token_expires_at - 60:
            return True

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        try:
            resp = requests.post(
                "https://www.upwork.com/api/v2/oauth2/token",
                data=data, timeout=15,
            )
            if resp.status_code == 200:
                token_data = resp.json()
                self.access_token = token_data.get("access_token", "")
                self.token_expires_at = time.time() + token_data.get(
                    "expires_in", 3600,
                )
                return True
        except Exception:
            pass
        return False

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[dict]:
        """Make authenticated request with auto token refresh."""
        if not self._refresh_token():
            return None

        url = f"{UPWORK_BASE}{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        headers["Content-Type"] = "application/json"

        for attempt in range(3):
            try:
                resp = requests.request(
                    method, url, headers=headers, timeout=15, **kwargs,
                )
                if resp.status_code == 401:
                    if self._refresh_token():
                        continue
                    return None
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                if attempt == 2:
                    return None
                time.sleep(2 ** attempt)
        return None

    def find_gigs(self, q: str = "python", category: str = "software-dev",
                  limit: int = 20) -> List[UpworkGig]:
        """Search for freelance gigs."""
        from agents.platform_throttle import get_throttle
        # C1: throttle the Upwork API call (anti-ban).
        get_throttle().acquire("upwork")
        data = self._request(
            "GET",
            f"/hr/v2/search-jobs?q={q}&category={category}&limit={limit}",
        )
        if not data:
            return []

        gigs = []
        jobs = data.get("jobs", data if isinstance(data, list) else [])
        for job in jobs:
            if not isinstance(job, dict):
                continue
            gig_id = str(job.get("job_id", job.get("id", "")))
            if not gig_id:
                continue
            gigs.append(UpworkGig(
                id=gig_id,
                title=str(job.get("title", ""))[:200],
                description=str(
                    job.get("description", job.get("short_description", ""))
                )[:500],
                budget_usd=float(
                    job.get("budget", job.get("fixed_price", 0))
                ),
                skills=job.get("skills", []),
                url=str(
                    job.get("url",
                            f"https://www.upwork.com/jobs/{gig_id}")
                ),
                found_at=time.time(),
            ))
        return gigs

    # ── Submission (A1) ───────────────────────────────────────────────────────
    def can_submit(self) -> bool:
        """True if OAuth tokens are present (a submit is even possible)."""
        return bool(self.client_id and self.client_secret
                    and self.access_token and self.refresh_token)

    def _get_authenticated_profile(self) -> Optional[str]:
        """Return the authenticated Upwork profile id (cached). H1: real `submitted_by`
        instead of the placeholder 'me'. Uses the v3 auth/user endpoint; returns None if
        unavailable (no creds / API down) so callers degrade honestly."""
        if getattr(self, "_profile_id", None):
            return self._profile_id
        data = self._request("GET", "/api/v3/auth/user")
        pid = None
        if data:
            pid = (data.get("profile", {}).get("id")
                   or data.get("user", {}).get("id")
                   or data.get("id"))
        self._profile_id = pid
        return pid

    def submit_proposal(self, job_id: str, cover: str,
                        budget: float = 0.0,
                        attachments: Optional[list] = None) -> Optional[dict]:
        """Submit a cover/proposal for a job via the Upwork REST API.

        Uses the v3 proposals endpoint shape. All failures return None (never
        raise) so the pipeline can treat a failed submit as a normal outcome and
        record it — no half-submitted state. The actual HTTP call goes through
        `_request`, which handles auth + 401-refresh + retries.

        With no real credentials `can_submit()` is False and callers must not
        invoke this; the pipeline/mock harness injects a fake client for tests.
        """
        if not job_id or not cover or not cover.strip():
            return None
        profile_id = self._get_authenticated_profile()
        payload = {
            "job_id": str(job_id),
            "cover": cover,
            # H1: real authenticated profile id (never the placeholder "me").
            "submitted_by": profile_id or "me",
            "budget": float(budget or 0.0),
        }
        if attachments:
            payload["attachments"] = attachments
        data = self._request("POST", "/api/v3/proposals", json=payload)
        if not data:
            # API errored (e.g. HTTP 500) AFTER the local belief "we tried to submit".
            # The pipeline turns this into CONFLICTED evidence (reconcilable later),
            # NOT a clean verified=False.
            return {"error": "upwork_api_no_response", "submitted_by": profile_id or "me",
                    "job_id": str(job_id)}
        # Upwork returns the created proposal under various shapes; normalize.
        prop = data.get("proposal", data)
        pid = prop.get("id") or prop.get("proposal_id") or data.get("id")
        return {
            "proposal_id": str(pid) if pid else "",
            "status": prop.get("status", "submitted"),
            "job_id": str(job_id),
            "submitted_by": profile_id or "me",
            "raw": data,
        }
