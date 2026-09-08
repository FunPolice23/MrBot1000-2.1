"""
agents/instruction_gate.py — Instruction Provenance Gate (v2.0.22 S1)

Security trust anchor for MrBot1000's external platform interaction.

DESIGN PRINCIPLE (operator directive):
    Any instruction/playbook fetched from the web (e.g. a remote SKILL.md) is
    UNTRUSTED DATA, never an agent directive. Treating it as a directive is a
    prompt-injection vector. Discovered instructions are auto-quarantined and
    flagged for human review. They stay PENDING until a human either:
      - APPROVES  -> moved to the allowlist (trusted / executable)
      - REJECTS   -> moved to the blacklist (url + content_hash + related ids);
                     blacklisted items are ALWAYS ignored (never fetched/run).

All future platform adapters MUST route their instruction fetches through this
module. It is the single choke point that enforces the provenance policy.

No network call is made for blacklisted URLs. Unknown instructions are stored
but never returned as `trusted=True`.
"""

import hashlib
import time

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency fallback
    requests = None

from typing import Optional


class QuarantinedInstruction:
    """Result of a gate check/fetch. `trusted` means it may be acted upon."""

    def __init__(self, url: str, status: str, content: str = "",
                 content_hash: str = "", title: str = "", kind: str = "skill.md",
                 quarantine_id: Optional[int] = None):
        self.url = url
        self.status = status            # pending | allowed | blocked
        self.content = content
        self.content_hash = content_hash
        self.title = title
        self.kind = kind
        self.quarantine_id = quarantine_id

    @property
    def trusted(self) -> bool:
        """Only explicitly-allowed instructions are trusted for action."""
        return self.status == "allowed"

    def __repr__(self):
        return (f"<QuarantinedInstruction url={self.url!r} status={self.status} "
                f"trusted={self.trusted} hash={self.content_hash[:10]}>")


class InstructionGate:
    """Central provenance gate for external instructions/playbooks."""

    def __init__(self, db, *,
                 fetcher=None,
                 timeout: int = 15,
                 user_agent: str = "MrBot1000/2.0.22 (+https://github.com/FunPolice23/MrBot1000)"):
        self.db = db
        self.timeout = timeout
        self.user_agent = user_agent
        # Allow dependency injection of the fetcher (tests / alternate providers).
        self._fetcher = fetcher or self._default_fetch

    # -- public API --------------------------------------------------------

    def check(self, url: str, *, kind: str = "skill.md") -> QuarantinedInstruction:
        """Check an instruction URL's trust status WITHOUT fetching content.
        Returns a QuarantinedInstruction describing the current state."""
        if self.db.in_instruction_blacklist(url):
            return QuarantinedInstruction(url, "blocked")
        # SSRF guard (v2.0.24b): never surface a non-public URL as reviewable.
        if not self._is_safe_fetch_url(url):
            return QuarantinedInstruction(url, "blocked")
        if self.db.in_instruction_allowlist(url):
            return QuarantinedInstruction(url, "allowed")
        # Unknown: do we already have it quarantined (pending) by url?
        row = self._find_pending_by_url(url)
        if row is not None:
            return QuarantinedInstruction(
                url, "pending", content=row.get("content", ""),
                content_hash=row.get("content_hash", ""),
                title=row.get("title", ""), kind=kind,
                quarantine_id=row.get("id"))
        return QuarantinedInstruction(url, "pending")

    def fetch_instruction(self, url: str, *, kind: str = "skill.md",
                          title: str = "") -> QuarantinedInstruction:
        """Fetch an external instruction through the gate.

        - Blacklisted URL -> returns `blocked`, NO network call.
        - Allowlisted URL -> returns `allowed` with content (re-fetched fresh).
        - Unknown URL -> fetches, stores as `pending`, returns `pending` with
          content but `trusted=False`. Content is NEVER auto-executed.
        """
        # Blacklist short-circuit: never even hit the network.
        if self.db.in_instruction_blacklist(url):
            return QuarantinedInstruction(url, "blocked")

        # SSRF guard (v2.0.24b): applied BEFORE trust checks so a malicious or
        # allowlisted-but-internal URL can never be fetched. A quarantined
        # SKILL.md URL is attacker-influenced; never let it reach loopback,
        # private, link-local, or cloud-metadata addresses.
        if not self._is_safe_fetch_url(url):
            return QuarantinedInstruction(url, "blocked")

        # Allowed: fetch fresh (URL may have changed), still trust it.
        if self.db.in_instruction_allowlist(url):
            content = self._fetcher(url)
            h = self._hash(content)
            return QuarantinedInstruction(url, "allowed", content=content,
                                         content_hash=h, title=title, kind=kind)

        # Unknown -> fetch, compute hash, check for a previously-seen identical
        # content (hash match) that was already reviewed.
        content = self._fetcher(url)
        h = self._hash(content)
        existing = self.db.find_quarantined_by_hash(h)
        if existing is not None:
            # Same content was seen before; mirror its reviewed status.
            status = existing.get("status", "pending")
            return QuarantinedInstruction(
                url, status, content=content, content_hash=h,
                title=existing.get("title", title), kind=kind,
                quarantine_id=existing.get("id"))

        # Truly new and unknown -> quarantine as pending for human review.
        qid = self.db.add_quarantined_instruction(url, kind, title, h, content)
        return QuarantinedInstruction(url, "pending", content=content,
                                     content_hash=h, title=title, kind=kind,
                                     quarantine_id=qid)

    def review(self, quarantine_id: int, approve: bool, *,
               url: str = "", content_hash: str = "",
               related: str = "") -> str:
        """Human-in-the-loop decision. approve -> allowlist, else -> blacklist
        (with related identifiers for durable ignoring). Returns new status."""
        return self.db.review_instruction(
            quarantine_id, approve, url=url,
            content_hash=content_hash, related=related)

    def pending(self, limit: int = 100):
        return self.db.list_pending_instructions(limit)

    def counts(self) -> dict:
        return self.db.count_instruction_lists()

    # -- internals ---------------------------------------------------------

    def _find_pending_by_url(self, url: str):
        if hasattr(self.db, "find_pending_by_url"):
            return self.db.find_pending_by_url(url)
        return None

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256((content or "").encode("utf-8", "replace")).hexdigest()

    # --- SSRF guard (v2.0.24b) ---------------------------------------------
    # A quarantined SKILL.md URL is attacker-influenced (it comes from a remote
    # platform). Without this, a malicious URL could point at internal services
    # (http://127.0.0.1:PORT), cloud metadata (http://169.254.169.254/latest/),
    # or a private host, and we would fetch + log its contents -> credential
    # theft / internal recon. We only allow public http(s) hosts.
    @staticmethod
    def _is_safe_fetch_url(url: str) -> bool:
        from urllib.parse import urlparse
        import ipaddress
        try:
            p = urlparse(url)
        except Exception:
            return False
        if p.scheme not in ("http", "https"):
            return False
        host = (p.hostname or "").strip().lower()
        if not host:
            return False
        # Block obvious literals / metadata.
        if host in ("localhost", "0.0.0.0", "::1", "169.254.169.254"):
            return False
        # Resolve hostname -> IP(s) and reject anything non-public.
        import socket
        try:
            infos = socket.getaddrinfo(host, None)
        except Exception:
            # Cannot resolve (offline / no resolver). We cannot confirm the host
            # is internal, so we ALLOW the fetch to proceed — the existing
            # timeout/error handling covers genuinely unreachable hosts, and
            # refusing here would break offline operation and legitimate public
            # URLs. The SSRF protection still triggers when DNS *does* resolve to
            # a loopback/private/link-local/metadata address.
            return True
        for info in infos:
            ip_str = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                return False
        return True

    def _default_fetch(self, url: str) -> str:
        if requests is None:
            raise RuntimeError("requests unavailable for instruction fetch")
        if not self._is_safe_fetch_url(url):
            raise RuntimeError(
                f"refusing to fetch non-public URL (SSRF guard): {url}")
        resp = requests.get(url, timeout=self.timeout,
                            headers={"User-Agent": self.user_agent})
        resp.raise_for_status()
        return resp.text
