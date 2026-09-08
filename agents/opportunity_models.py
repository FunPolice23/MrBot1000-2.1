"""agents/opportunity_models.py — Generalized paid-opportunity model + taxonomy.

Single canonical structured representation of ANY legitimate online opportunity
where a person performs useful work (or an allowed activity) in exchange for
monetary compensation or a legitimate reward.

This is deliberately NOT a freelance-gig model. It covers writing, research, data
work, QA, bug bounties, airdrops, referral, studies, microtasks, etc.

Key design rules (per project requirements):
- The taxonomy is a *set*, not a hardcoded final list. Unknown categories are
  preserved verbatim so the system can represent work it has never seen.
- A discovered listing is NEVER treated as verified merely because an LLM
  classified it. `provenance` always records the external origin; validation is a
  separate deterministic step (see `validate_opportunity`), and LLM evaluation only
  assigns a score — it never flips `validation_status` to "verified".
- `identity_key()` gives a normalized fingerprint so the same opportunity found by
  two sources is deduplicated.
"""

from __future__ import annotations

import time
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


# ── Flexible taxonomy ────────────────────────────────────────────────────────
# A growing set of known categories. NOT exhaustive by design — the system must
# be able to represent opportunities outside this set. Unknown values are kept.
TAXONOMY: set = {
    "writing", "reading", "proofreading", "editing", "research", "summarization",
    "transcription", "data_entry", "data_labeling", "qa_testing", "software_testing",
    "coding", "debugging", "technical_writing", "content_creation",
    "virtual_assistance", "design", "research_assistance", "microtask", "paid_study",
    "freelance", "bug_bounty", "open_source_bounty", "paid_contest", "api_data_task",
    "crypto_reward", "airdrop", "retroactive_reward", "referral", "other",
}

# Known currencies (ISO-4217-ish + common crypto). Anything else -> currency_known=False.
KNOWN_CURRENCIES: set = {
    "USD", "EUR", "GBP", "CAD", "AUD", "JPY", "INR", "BRL", "NGN", "PHP", "ZAR",
    "BTC", "ETH", "SOL", "USDC", "USDT", "DAI", "MATIC", "BNB", "AVAX", "ARB",
    "OP", "TON", "XMR", "LTC", "DOGE", "TRX", "ADA", "DOT", "ATOM", "HIVE",
    "TOKEN", "POINTS", "OTHER",
}

# Keyword -> canonical category. Heuristic and extensible; not authoritative.
_CATEGORY_KEYWORDS: Dict[str, str] = {
    "proofread": "writing", "edit": "writing", "write": "writing", "blog": "writing",
    "author": "writing", "copywrit": "writing",
    "review": "reading", "read": "reading", "moderat": "reading",
    "summar": "summarization", "abstract": "summarization",
    "transcrib": "transcription", "caption": "transcription",
    "label": "data_labeling", "annotat": "data_labeling", "dataset": "data_labeling",
    "data entry": "data_entry", "typing": "data_entry", "form fill": "data_entry",
    "qa": "qa_testing", "quality": "qa_testing", "tester": "software_testing",
    "debug": "debugging", "code": "coding", "develop": "coding", "program": "coding",
    "bounty": "bug_bounty", "vulnerability": "bug_bounty", "cve": "bug_bounty",
    "bug": "bug_bounty", "issue": "bug_bounty", "pr ": "open_source_bounty",
    "retro": "retroactive_reward", "airdrop": "airdrop", "faucet": "airdrop",
    "referr": "referral", "affiliate": "referral",
    "survey": "paid_study", "study": "paid_study", "research participant": "paid_study",
    "contest": "paid_contest", "hackathon": "paid_contest",
    "design": "design", "logo": "design", "ui": "design", "ux": "design",
    "assist": "virtual_assistance", "va ": "virtual_assistance", "admin": "virtual_assistance",
    "microtask": "microtask", "task": "microtask", "click": "microtask",
    "api": "api_data_task", "scrap": "api_data_task", "crawl": "api_data_task",
    "crypto": "crypto_reward", "staking": "crypto_reward", "yield": "crypto_reward",
    "freelance": "freelance", "gig": "freelance",
    "research assist": "research_assistance", "analyst": "research",
    "technical writ": "technical_writing", "doc": "technical_writing",
}


def classify_category(text: str) -> str:
    """Best-effort canonical category from free text. Falls back to 'other'.

    Intentionally simple + deterministic (no LLM). Unknown text -> 'other',
    which is preserved; the taxonomy is not a closed list.
    """
    t = (text or "").lower()
    # Longest-keyword-first so "data entry" wins over "data".
    for kw in sorted(_CATEGORY_KEYWORDS, key=len, reverse=True):
        if kw in t:
            return _CATEGORY_KEYWORDS[kw]
    return "other"


@dataclass
class Opportunity:
    """Structured representation of a discovered paid/rewarded opportunity.

    `provenance` is ALWAYS set by the source that produced it (source::external_url)
    so externally-sourced evidence remains identifiable, and an LLM-classified
    listing is never mistaken for a verified external fact.
    """

    opportunity_id: str
    source: str
    platform: str
    title: str
    description: str

    category: str = "other"
    subcategory: str = ""
    task_type: str = ""

    required_skills: List[str] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)

    payment_type: str = "usd"          # usd | crypto | token | points | other
    currency: str = "USD"
    advertised_amount: float = 0.0
    estimated_net_value: float = 0.0   # after fees/costs; 0 = unknown
    estimated_effort: float = 0.0      # hours
    estimated_duration: float = 0.0    # hours (or relative to deadline)

    deadline: float = 0.0              # unix ts; 0 = none
    location_requirements: str = ""
    eligibility_requirements: str = ""

    automation_potential: float = 0.0 # 0..1
    human_required: bool = True

    risk_level: str = "low"            # low | medium | high
    scam_risk: float = 0.0             # 0..1
    source_reliability: float = 0.5    # 0..1

    validation_status: str = "unvalidated"  # unvalidated | valid | invalid

    discovered_at: float = field(default_factory=time.time)
    external_id: str = ""
    external_url: str = ""
    provenance: str = ""               # "source_name::external_url" — set by source

    def identity_key(self) -> str:
        """Normalized identity for cross-source dedup (not just id)."""
        # Identity is WHAT the opportunity is (url/id/title/platform), NOT which
        # source found it — so the same listing discovered by two sources dedups.
        norm = " ".join([
            (self.external_url or "").strip().lower(),
            self.platform.strip().lower(),
            (self.external_id or "").strip().lower(),
            self.title.strip().lower(),
        ])
        return hashlib.md5(norm.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Opportunity":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class ValidationResult:
    status: str                       # "valid" | "invalid"
    reasons: List[str] = field(default_factory=list)
    currency_known: bool = True
    payment_present: bool = False


def validate_opportunity(o: Opportunity) -> ValidationResult:
    """Deterministic VALIDATION of a discovered listing (never uses the LLM).

    Distinguishes DISCOVERY (the listing exists) from VALIDATION (it has the
    minimum structural integrity to be considered). A positive LLM evaluation
    must NOT call this to flip status to verified. This only checks structure.
    """
    reasons: List[str] = []
    if not (o.title or "").strip():
        reasons.append("missing title")
    if not (o.description or "").strip():
        reasons.append("missing description")
    if not (o.external_url or o.external_id or o.platform):
        reasons.append("missing external reference")

    payment_present = o.advertised_amount > 0 or o.estimated_net_value > 0
    if not payment_present:
        reasons.append("missing payment information (amount=0)")

    cur = (o.currency or "").strip().upper()
    currency_known = cur in KNOWN_CURRENCIES
    if not currency_known:
        reasons.append(f"unknown currency: {o.currency!r}")

    status = "invalid" if reasons else "valid"
    return ValidationResult(
        status=status, reasons=reasons,
        currency_known=currency_known, payment_present=payment_present,
    )


# ── Pluggable source interface ────────────────────────────────────────────────

class OpportunitySource(ABC):
    """A pluggable discovery source. Subclass and register with DiscoveryEngine."""

    name: str = "source"

    @abstractmethod
    def discover(self) -> List[Opportunity]:
        """Return discovered opportunities. Must NOT invent from LLM text."""
        raise NotImplementedError

    def is_enabled(self) -> bool:
        return True


class BaseOpportunitySource(OpportunitySource):
    """Convenience base: subclasses implement `_discover()`; provenance is coerced.

    v2.0.36p: `discover()` accepts an optional `query` (and `categories`) so the
    Dynamic Discovery Scheduler can drive a SPECIFIC search term per task instead
    of every source always re-running its hardcoded default query. Sources that
    cannot scope by query simply ignore it. Default None keeps the engine/tests
    (which call `discover()` with no args) unaffected.
    """

    name = "base"

    def discover(self, query: Optional[str] = None,
                 categories: Optional[List[str]] = None) -> List[Opportunity]:
        out: List[Opportunity] = []
        for o in self._discover(query=query, categories=categories):
            if not o.provenance:
                o.provenance = f"{self.name}::{o.external_url or o.title}"
            out.append(o)
        return out

    def _discover(self, query: Optional[str] = None,
                  categories: Optional[List[str]] = None) -> List[Opportunity]:
        return []


class OpportunityDeduplicator:
    """Normalized identity fingerprinting across sources."""

    def __init__(self):
        self._seen: set = set()

    def seen(self, o: Opportunity) -> bool:
        return o.identity_key() in self._seen

    def add(self, o: Opportunity) -> None:
        self._seen.add(o.identity_key())

    def filter(self, opps: List[Opportunity]) -> List[Opportunity]:
        out: List[Opportunity] = []
        for o in opps:
            if not self.seen(o):
                self.add(o)
                out.append(o)
        return out

    def reset(self) -> None:
        self._seen.clear()


class OpportunityRegistry:
    """Holds registered sources and runs them with failure isolation."""

    def __init__(self):
        self._sources: List[OpportunitySource] = []

    def register(self, src: OpportunitySource) -> None:
        self._sources.append(src)

    def sources(self) -> List[OpportunitySource]:
        return list(self._sources)

    def run_all(self):
        """Return (results, errors). A failing source is isolated (errors[name])."""
        results: List[Opportunity] = []
        errors: Dict[str, str] = {}
        for src in self._sources:
            if not src.is_enabled():
                continue
            try:
                results.extend(src.discover())
            except Exception as e:  # noqa: BLE001 - isolate one bad source
                errors[src.name] = str(e)
        return results, errors
