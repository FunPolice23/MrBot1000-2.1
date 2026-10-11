"""Safe account-profile readiness for platform opportunities.

The agent may prepare a draft from operator-approved public details, but it never
stores or invents passwords, API keys, identity documents, or verification data.
Creating an account and submitting a profile remain human-gated actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


_SENSITIVE_KEYS = {
    "password", "passphrase", "api_key", "apikey", "secret", "token",
    "private_key", "seed_phrase", "recovery_phrase", "ssn", "passport",
    "driver_license", "id_document", "verification_code",
}
_REQUIRED_PUBLIC_FIELDS = ("display_name", "email", "skills")


@dataclass(frozen=True)
class AccountProfile:
    """Operator-approved, non-secret profile data for a platform draft."""

    display_name: str = ""
    email: str = ""
    skills: List[str] = field(default_factory=list)
    bio: str = ""
    portfolio_urls: List[str] = field(default_factory=list)
    location: str = ""
    secret_refs: Dict[str, str] = field(default_factory=dict)

    def readiness(self) -> Dict[str, Any]:
        missing = [field for field in _REQUIRED_PUBLIC_FIELDS if not getattr(self, field)]
        issues: List[str] = []
        if self.email and ("@" not in self.email or "." not in self.email.rsplit("@", 1)[-1]):
            issues.append("email format requires operator review")
        if not isinstance(self.skills, list) or not self.skills:
            if "skills" not in missing:
                issues.append("skills must be a non-empty list")
        for key, value in self.secret_refs.items():
            if not key or not value:
                issues.append("secret references must have names and values")
        return {
            "ready_for_draft": not missing and not issues,
            "missing_fields": missing,
            "issues": issues,
            "requires_human_gate": True,
        }

    def public_draft(self) -> Dict[str, Any]:
        """Return only fields safe to place in a reviewable profile draft."""
        return {
            "display_name": self.display_name,
            "email": self.email,
            "skills": list(self.skills),
            "bio": self.bio,
            "portfolio_urls": list(self.portfolio_urls),
            "location": self.location,
        }


def validate_profile_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate operator-supplied profile data without retaining sensitive values."""
    found = {str(key).lower() for key in (data or {})}
    rejected = sorted(found & _SENSITIVE_KEYS)
    if rejected:
        return {
            "valid": False,
            "rejected_fields": rejected,
            "reason": "Sensitive values must remain in the operator's password manager or platform UI.",
        }
    profile = AccountProfile(
        display_name=str(data.get("display_name", "")).strip(),
        email=str(data.get("email", "")).strip(),
        skills=[str(item).strip() for item in data.get("skills", []) if str(item).strip()],
        bio=str(data.get("bio", "")).strip(),
        portfolio_urls=[str(item).strip() for item in data.get("portfolio_urls", []) if str(item).strip()],
        location=str(data.get("location", "")).strip(),
        secret_refs={str(k): str(v) for k, v in (data.get("secret_refs", {}) or {}).items()},
    )
    return {"valid": True, "profile": profile, **profile.readiness()}


__all__ = ["AccountProfile", "validate_profile_data"]
