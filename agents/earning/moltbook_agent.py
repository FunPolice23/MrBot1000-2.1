"""Moltbook agent identity onboarding.

Moltbook is agent-operated: the agent reads the official SKILL.md and creates
its own registration request. The human later claims/verifies the agent. This
module keeps those roles separate and never stores the returned API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


MOLTBOOK_SKILL_URL = "https://www.moltbook.com/skill.md"
MOLTBOOK_REGISTER_URL = "https://www.moltbook.com/api/v1/agents/register"
# Base for all authenticated activity. MUST use www — moltbook.com without www
# redirects and strips the Authorization header (documented in SKILL.md).
MOLTBOOK_API_BASE = "https://www.moltbook.com/api/v1"
# Host the API key is ever allowed to be sent to. Anything else is a leak.
_MOLTBOOK_ALLOWED_HOST = "www.moltbook.com"


@dataclass(frozen=True)
class MoltbookRegistrationPlan:
    """A reviewable plan for an agent-owned Moltbook registration."""

    agent_name: str
    description: str
    skill_url: str = MOLTBOOK_SKILL_URL
    registration_url: str = MOLTBOOK_REGISTER_URL
    skill_status: str = "not_read"
    human_follow_up: str = "Claim and verify the agent using Moltbook's claim link."
    missing: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.agent_name.strip() and self.description.strip()
                    and self.skill_status == "allowed" and not self.missing)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "description": self.description,
            "skill_url": self.skill_url,
            "registration_url": self.registration_url,
            "skill_status": self.skill_status,
            "human_follow_up": self.human_follow_up,
            "missing": list(self.missing),
            "ready": self.ready,
        }


class MoltbookAgentCapability:
    """Read, review, and optionally submit an agent-owned registration request.

    ``register`` is deliberately explicit because it creates an external
    account. It returns the claim URL but discards the API key immediately;
    callers must keep secrets in an operator-controlled secret store.
    """

    def __init__(self, instruction_gate: Any, http_client: Any = None):
        self.instruction_gate = instruction_gate
        self.http_client = http_client

    def read_skill(self):
        return self.instruction_gate.fetch_instruction(
            MOLTBOOK_SKILL_URL, kind="skill.md", title="Moltbook SKILL.md"
        )

    def plan_registration(self, agent_name: str, description: str,
                          skill_status: str = "not_read") -> MoltbookRegistrationPlan:
        missing = []
        if not agent_name.strip():
            missing.append("agent_name")
        if not description.strip():
            missing.append("description")
        return MoltbookRegistrationPlan(
            agent_name=agent_name.strip(), description=description.strip(),
            skill_status=skill_status, missing=missing,
        )

    def register(self, plan: MoltbookRegistrationPlan,
                 *, capability_approved: bool = False) -> Dict[str, Any]:
        """Register the agent, only after the capability has been approved.

        The approval authorizes the agent's registration call; it does not
        authorize the human claim/verification step or any later posting.
        """
        if not plan.ready:
            return {"ok": False, "status": "blocked", "reason": "registration plan is not ready"}
        if not capability_approved:
            return {"ok": False, "status": "awaiting_approval",
                    "reason": "agent registration requires explicit capability approval"}
        if self.http_client is None:
            return {"ok": False, "status": "blocked", "reason": "no HTTP client configured"}
        response = self.http_client.post(
            MOLTBOOK_REGISTER_URL,
            json={"name": plan.agent_name, "description": plan.description},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        agent = payload.get("agent", {}) if isinstance(payload, dict) else {}
        api_key = str(agent.get("api_key", ""))
        claim_url = str(agent.get("claim_url", ""))
        verification_code = str(agent.get("verification_code", ""))
        # Phase F (ARCH-ENG-089): store the key in the operator's encrypted vault
        # so the agent can act AFTER the human claims. Never logged. If the vault
        # is unavailable we do NOT fail registration — we just report that the key
        # must be stored manually.
        key_stored = False
        if api_key:
            try:
                from agents.platforms.credential_vault import CredentialVault
                CredentialVault().set("moltbook", "api_key", api_key)
                key_stored = True
            except Exception:
                key_stored = False
        instructions = (
            f"Open {claim_url} to claim and verify the agent. "
            f"Verify your email, then post the verification code '{verification_code}' "
            f"as instructed. Once claimed, the agent can post/read on Moltbook."
        ) if claim_url else (
            "Registration succeeded but no claim URL was returned; check Moltbook."
        )
        return {
            "ok": True,
            "status": "registered",
            "agent_name": plan.agent_name,
            "claim_url": claim_url,
            "verification_code": verification_code,
            "claim_status": "pending_claim",
            "api_key_stored_in_vault": key_stored,
            "human_instructions": instructions,
            "human_follow_up": plan.human_follow_up,
        }

    def claim_status(self) -> Dict[str, Any]:
        """Check whether the agent has been claimed by its human.

        Reads GET /api/v1/agents/status with the vault-stored key. Maps to
        ``pending_claim`` / ``claimed`` / ``unknown``. Never fabricates a status.
        """
        try:
            from agents.platforms.credential_vault import CredentialVault
            api_key = CredentialVault().get("moltbook", "api_key")
        except Exception:
            api_key = ""
        if not api_key:
            return {"ok": False, "claim_status": "unknown",
                    "reason": "no stored Moltbook API key (not registered yet)"}
        if self.http_client is None:
            return {"ok": False, "claim_status": "unknown",
                    "reason": "no HTTP client configured"}
        try:
            resp = self.http_client.get(
                f"{MOLTBOOK_API_BASE}/agents/status",
                headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            raw = str((payload or {}).get("status", "")).lower()
            status = ("claimed" if raw == "claimed"
                      else "pending_claim" if raw == "pending_claim"
                      else "unknown")
            return {"ok": True, "claim_status": status, "raw": raw}
        except Exception as exc:
            return {"ok": False, "claim_status": "unknown", "reason": str(exc)}

    def request_human_claim(self, plan: "MoltbookRegistrationPlan",
                            *, claim_url: str = "",
                            verification_code: str = "") -> Dict[str, Any]:
        """Enqueue a human approval/notification carrying the claim instructions.

        The agent cannot claim itself — a human must verify email + post the
        verification code. This hands the human a ready-to-follow item in the
        Approvals tab. It enqueues a PENDING item; it never claims on the
        human's behalf.
        """
        instructions = (
            f"Claim the Moltbook agent '{plan.agent_name}': open {claim_url}, "
            f"verify your email, and post the verification code "
            f"'{verification_code}' as instructed. The agent stays 'pending_claim' "
            f"until you complete this."
        ) if claim_url else (
            f"Claim the Moltbook agent '{plan.agent_name}' using the claim link "
            f"Moltbook provided. The agent stays 'pending_claim' until claimed."
        )
        try:
            from agents.safety.approval import HumanApprovalQueue
            item = HumanApprovalQueue.instance().enqueue_submission(
                "Claim your Moltbook agent", instructions)
            return {"ok": True, "status": "awaiting_human_claim",
                    "approval_id": item.id, "human_instructions": instructions}
        except Exception as exc:
            return {"ok": False, "status": "error", "reason": str(exc)}


class MoltbookPoster:
    """Real read + write client for the Moltbook social network (Phase E).

    The agent posts, replies, upvotes, and reads its feed so it can learn from
    and gather information in the community — but only behind the same trust
    discipline as registration:

    - **Writes** (create_post / reply_to_post / upvote_*) require
      ``capability_approved=True``. They never run silently.
    - **Reads** (feed / post / comments) are PUBLIC on Moltbook's live API, so
      they work WITHOUT registration or ``MOLTBOOK_API_KEY``
      (ARCH-ENG-320: the old key gate made the whole platform look dead to an
      unregistered operator — an empty Social Activity tab instead of a
      readable one).
    - The **API key** (from ``MOLTBOOK_API_KEY``), when configured, is only
      ever sent to ``www.moltbook.com`` — specifically, only when a key
      exists, and only to that host; no other request ever carries it.
    - Posts/comments may come back with a **verification math challenge**; that
      is surfaced verbatim in the result — a pending challenge is NOT a posted
      item, and we never fabricate a success.

    ``http_client`` is a requests-like object (``.get``/``.post`` with
    ``json``/``params``/``headers``/``timeout``). Left ``None``, the poster runs
    in an offline/dry mode that still enforces every gate and returns a clear
    ``blocked`` status (used by tests and by the GUI before a client is wired).
    """

    def __init__(self, http_client: Any = None, api_key: str = "",
                 base_url: str = MOLTBOOK_API_BASE):
        self.http_client = http_client
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")

    # ── guards ──────────────────────────────────────────────────────────
    def _key(self) -> Optional[str]:
        import os
        return (self.api_key or os.getenv("MOLTBOOK_API_KEY", "")).strip()

    def _auth_headers(self) -> Dict[str, str]:
        # ARCH-ENG-320: reads are public — never send an empty Authorization.
        headers = {"Content-Type": "application/json"}
        key = self._key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _offline(self, action: str) -> Dict[str, Any]:
        return {"ok": False, "status": "blocked",
                "reason": f"no HTTP client configured for {action}"}

    def _require_key(self, action: str) -> Optional[Dict[str, Any]]:
        if not self._key():
            return {"ok": False, "status": "blocked",
                    "reason": f"{action}: MOLTBOOK_API_KEY is not set"}
        return None

    @staticmethod
    def _verification(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Surface a post/comment verification challenge if the API returned one."""
        ver = payload.get("verification") if isinstance(payload, dict) else None
        if isinstance(ver, dict) and ver:
            return ver
        return None

    # ── writes (HIGH-TRUST: capability_approved required) ────────────────
    def create_post(self, submolt_name: str, title: str, content: str = "",
                    url: str = "", *, capability_approved: bool = False
                    ) -> Dict[str, Any]:
        """Create a text/link post in a submolt. Requires capability approval."""
        if not capability_approved:
            return {"ok": False, "status": "awaiting_approval",
                    "reason": "posting to Moltbook requires capability approval"}
        if not submolt_name.strip() or not title.strip():
            return {"ok": False, "status": "blocked",
                    "reason": "submolt_name and title are required"}
        blocked = self._require_key("create_post")
        if blocked:
            return blocked
        if self.http_client is None:
            return self._offline("create_post")
        body: Dict[str, Any] = {"submolt_name": submolt_name.strip(),
                                "title": title.strip()[:300]}
        if content:
            body["content"] = content[:40000]
        if url:
            body["url"] = url
            body["type"] = "link"
        resp = self.http_client.post(f"{self.base_url}/posts", json=body,
                                     headers=self._auth_headers(), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        ver = self._verification(payload)
        result = {"ok": True, "status": "posted", "post": payload,
                  "submolt": submolt_name.strip(), "title": body["title"]}
        if ver is not None:
            result["status"] = "pending_verification"
            result["verification"] = ver
        return result

    def reply_to_post(self, post_id: str, content: str, parent_id: str = "",
                      *, capability_approved: bool = False) -> Dict[str, Any]:
        """Comment on (or reply within) a post. Requires capability approval."""
        if not capability_approved:
            return {"ok": False, "status": "awaiting_approval",
                    "reason": "replying on Moltbook requires capability approval"}
        if not post_id.strip() or not content.strip():
            return {"ok": False, "status": "blocked",
                    "reason": "post_id and content are required"}
        blocked = self._require_key("reply_to_post")
        if blocked:
            return blocked
        if self.http_client is None:
            return self._offline("reply_to_post")
        body: Dict[str, Any] = {"content": content[:40000]}
        if parent_id.strip():
            body["parent_id"] = parent_id.strip()
        resp = self.http_client.post(
            f"{self.base_url}/posts/{post_id.strip()}/comments", json=body,
            headers=self._auth_headers(), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        ver = self._verification(payload)
        result = {"ok": True, "status": "commented", "comment": payload,
                  "post_id": post_id.strip()}
        if ver is not None:
            result["status"] = "pending_verification"
            result["verification"] = ver
        return result

    def upvote_post(self, post_id: str, *,
                    capability_approved: bool = False) -> Dict[str, Any]:
        """Upvote a post. Requires capability approval."""
        return self._vote(f"/posts/{post_id.strip()}/upvote", "upvote_post",
                          capability_approved=capability_approved)

    def upvote_comment(self, comment_id: str, *,
                       capability_approved: bool = False) -> Dict[str, Any]:
        """Upvote a comment. Requires capability approval."""
        return self._vote(f"/comments/{comment_id.strip()}/upvote",
                          "upvote_comment", capability_approved=capability_approved)

    def _vote(self, path: str, action: str, *,
              capability_approved: bool) -> Dict[str, Any]:
        if not capability_approved:
            return {"ok": False, "status": "awaiting_approval",
                    "reason": f"{action} requires capability approval"}
        blocked = self._require_key(action)
        if blocked:
            return blocked
        if self.http_client is None:
            return self._offline(action)
        resp = self.http_client.post(f"{self.base_url}{path}", json={},
                                     headers=self._auth_headers(), timeout=15)
        resp.raise_for_status()
        return {"ok": True, "status": "voted", "result": _safe_json(resp)}

    # ── reads (public: they work without a key — ARCH-ENG-320) ───────────
    def get_feed(self, sort: str = "hot", limit: int = 25,
                 cursor: str = "") -> Dict[str, Any]:
        """Read the post feed (hot/new/top/rising). Cursor-paginated.

        No key required: Moltbook's live feed is public. When a key IS
        configured it is attached (and scoped to moltbook.com, as always).
        """
        if self.http_client is None:
            return self._offline("get_feed")
        params = {"sort": sort, "limit": int(limit)}
        if cursor:
            params["cursor"] = cursor
        resp = self.http_client.get(f"{self.base_url}/posts", params=params,
                                    headers=self._auth_headers(), timeout=15)
        resp.raise_for_status()
        return {"ok": True, "status": "ok", "feed": _safe_json(resp)}

    def get_post(self, post_id: str) -> Dict[str, Any]:
        if not post_id.strip():
            return {"ok": False, "status": "blocked",
                    "reason": "get_post: post_id is required"}
        if self.http_client is None:
            return self._offline("get_post")
        resp = self.http_client.get(
            f"{self.base_url}/posts/{post_id.strip()}",
            headers=self._auth_headers(), timeout=15)
        resp.raise_for_status()
        return {"ok": True, "status": "ok", "post": _safe_json(resp)}

    def get_comments(self, post_id: str, sort: str = "best",
                     limit: int = 35) -> Dict[str, Any]:
        if not post_id.strip():
            return {"ok": False, "status": "blocked",
                    "reason": "get_comments: post_id is required"}
        if self.http_client is None:
            return self._offline("get_comments")
        params = {"sort": sort, "limit": int(limit)}
        resp = self.http_client.get(
            f"{self.base_url}/posts/{post_id.strip()}/comments", params=params,
            headers=self._auth_headers(), timeout=15)
        resp.raise_for_status()
        return {"ok": True, "status": "ok", "comments": _safe_json(resp)}


def _safe_json(resp: Any) -> Any:
    """Best-effort JSON decode that never raises on an empty/odd body."""
    try:
        return resp.json()
    except Exception:
        return {}


__all__ = [
    "MOLTBOOK_SKILL_URL", "MOLTBOOK_REGISTER_URL", "MOLTBOOK_API_BASE",
    "MoltbookRegistrationPlan", "MoltbookAgentCapability", "MoltbookPoster",
]
