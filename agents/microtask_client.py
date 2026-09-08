"""
agents/microtask_client.py — Microtask platform integration for MrBot1000.
"""

import os
import time
from typing import List
from dataclasses import dataclass, field

import requests


@dataclass
class MicrotaskGig:
    id: str
    platform: str = ""
    title: str = ""
    description: str = ""
    payout_usd: float = 0.0
    skills: list = field(default_factory=list)
    url: str = ""
    status: str = "new"
    found_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "job_id":      self.id,
            "platform":    self.platform,
            "title":       self.title,
            "description": self.description[:300],
            "budget":      self.payout_usd,
            "skills":      self.skills,
            "url":         self.url,
            "status":      self.status,
            "score":       0.0,
            "notes":       "",
            "found_at":    self.found_at,
            "assigned_to": None,
        }


class MicrotaskClient:
    """Client for microtask platforms that pay for AI/ML work."""

    PLATFORMS = {
        "remotasks": {
            "api": "https://www.remotasks.com/api/v1/tasks",
            "rss": "https://www.remotasks.com/feed",
        },
        "scale_ai": {
            "api": "https://api.scale.com/v1/jobs",
            "requires_api_key": True,
        },
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MrBot1000/1.0",
        })

    def find_gigs(self, platform: str = "remotasks",
                      query: str = "ai ml data"
                      ) -> List[MicrotaskGig]:
        from agents.platform_throttle import get_throttle
        # C1: throttle microtask platform searches (anti-ban).
        get_throttle().acquire("microtask")
        gigs = []

        if platform == "remotasks":
            gigs = self._search_remotasks(query)
        elif platform == "scale_ai":
            gigs = self._search_scale_ai(query)
        elif platform == "all":
            for plat in self.PLATFORMS:
                gigs.extend(
                    self.find_gigs(platform=plat, query=query),
                )

        return gigs

    def _search_remotasks(self, query: str) -> List[MicrotaskGig]:
        try:
            resp = self.session.get(
                f"{self.PLATFORMS['remotasks']['api']}"
                f"?q={query}",
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return [
                    MicrotaskGig(
                        id=str(task.get("id", i)),
                        platform="Remotasks",
                        title=str(task.get("title", ""))[:200],
                        description=str(
                            task.get("description", "")
                        )[:300],
                        payout_usd=float(
                            task.get("reward",
                                     task.get("payout", 0))
                        ),
                        skills=task.get("skills", []),
                        url=str(task.get("url", "")),
                        found_at=time.time(),
                    )
                    for i, task in enumerate(
                        data.get("tasks",
                                 data if isinstance(data, list)
                                 else [])
                    )
                ]
        except Exception:
            pass
        return []

    def _search_scale_ai(self, query: str) -> List[MicrotaskGig]:
        api_key = os.getenv("SCALE_AI_API_KEY", "")
        if not api_key:
            return []

        try:
            resp = self.session.get(
                self.PLATFORMS["scale_ai"]["api"],
                headers={
                    "Authorization": f"Bearer {api_key}",
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return [
                    MicrotaskGig(
                        id=str(job.get("id", i)),
                        platform="Scale AI",
                        title=str(job.get("title", ""))[:200],
                        description=str(
                            job.get("description", "")
                        )[:300],
                        payout_usd=float(
                            job.get("reward",
                                    job.get("payout", 0))
                        ),
                        skills=job.get("skills", []),
                        url=str(job.get("url", "")),
                        found_at=time.time(),
                    )
                    for i, job in enumerate(
                        data.get("jobs",
                                 data if isinstance(data, list)
                                 else [])
                    )
                ]
        except Exception:
            pass
        return []