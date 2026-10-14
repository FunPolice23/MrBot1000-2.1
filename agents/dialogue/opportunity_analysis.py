"""agents/dialogue/opportunity_analysis.py — deterministic candidate digest (A3).

``analyse_candidate(entry)`` turns one discovered candidate into a structured
digest the Dialogue personas can discuss *before* committing to it:

    {"requirements": [...], "viability": "...", "blockers": [...], "summary": str}

It parses four things the council keeps hitting on real listings, purely and
deterministically (NO LLM — a model must never be the authority on whether a
gig is actually doable):

  * **location**      — "US only", "must reside in …", country/region limits
  * **payment method**— PayPal / Payoneer / crypto / wire / … (and the listing's
                        structured ``payment_type``)
  * **deliverable**   — what the worker must actually produce
  * **paywall**       — the recurring HTTP 402 (Payment Required). A page that
                        will not reveal its terms without payment is a BLOCKER,
                        not a lead: its real requirements are unknowable, so the
                        candidate cannot be responsibly actioned.

``entry`` may be a ``PortfolioEntry`` (its ``opportunity_ref`` dict is the
serialized ``Opportunity``), an ``Opportunity``, or a plain dict. Missing
fields are treated as UNKNOWN and never guessed — a location the listing never
stated is not assumed to be unrestricted.

viability is a deterministic verdict, NOT a score converted to money:
  * ``blocked``      — a hard blocker (paywall/402) makes the candidate
                       unactionable regardless of its advertised value;
  * ``needs_review`` — a location/eligibility restriction or missing critical
                       info means a human must confirm fit before acting;
  * ``viable``       — no blocker and no unresolved hard requirement detected.

Nothing here verifies payment or earnings; it is a READ of the listing's own
claims (see the financial-truth rule: advertised_amount is a claim, never
verified revenue).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Detection vocabularies (deterministic, longest-sensible-first where order
#    matters). Kept small and auditable on purpose. ──────────────────────────

# A location restriction: the listing limits WHO may apply by geography.
_LOCATION_PATTERNS = [
    r"\b(?:us|u\.s\.|united states|usa)\s+only\b",
    r"\bonly\s+(?:open to\s+)?(?:us|u\.s\.|united states|usa)\b",
    r"\bmust\s+(?:be\s+)?(?:located|reside|live|based)\s+in\b",
    r"\b(?:located|residents?|reside|living)\s+in\s+the\s+(?:us|u\.s\.|united states|usa|uk|eu|canada|australia)\b",
    r"\b(?:eu|uk|canada|australia|germany|india|philippines)\s+only\b",
    r"\bremote\s*\(\s*(?:us|u\.s\.|usa|uk|eu)\s*\)",
    r"\bgeo[- ]?restricted\b",
    r"\bnot\s+available\s+in\s+your\s+(?:country|region|location)\b",
]

# A payment method the listing names (how the worker gets paid).
_PAYMENT_METHOD_PATTERNS = [
    (r"\bpaypal\b", "PayPal"),
    (r"\bpayoneer\b", "Payoneer"),
    (r"\bwise\b|\btransferwise\b", "Wise"),
    (r"\bbank\s+transfer\b|\bwire\s+transfer\b|\bwire\b|\bach\b", "bank transfer"),
    (r"\bdirect\s+deposit\b", "direct deposit"),
    (r"\b(?:usdc|usdt|dai)\b", "stablecoin"),
    (r"\bbitcoin\b|\bbtc\b|\bcrypto(?:currency)?\b|\bon[- ]chain\b", "crypto"),
    (r"\bstripe\b", "Stripe"),
    (r"\bvenmo\b|\bcash\s?app\b|\bzelle\b", "P2P transfer"),
    (r"\bcheck\b|\bcheque\b", "check"),
    (r"\bpoints?\b|\bstore\s+credit\b|\bgift\s+card\b", "points/credit"),
]

# A deliverable: what the worker must produce/submit.
_DELIVERABLE_PATTERNS = [
    r"\bdeliver(?:able)?s?\b[:\s]+([^\n.;]{3,80})",
    r"\byou(?:'ll| will)\s+(?:need to\s+)?(?:write|design|create|build|produce|submit|deliver|provide)\s+([^\n.;]{3,80})",
    r"\b(?:write|design|create|build|produce|draft)\s+(?:a|an|the)\s+([^\n.;]{3,80})",
    r"\bsubmit\s+(?:a|an|the)\s+([^\n.;]{3,80})",
]

# A paywall / payment-required gate: the terms are behind a paywall, so the
# real requirements are unknowable. HTTP 402 is the canonical signal.
_PAYWALL_TEXT_PATTERNS = [
    r"\bpayment\s+required\b",
    r"\bhttp\s*402\b|\bstatus\s*402\b|\b402\s+payment\b",
    r"\bpaywall\b",
    r"\bsubscribe\s+to\s+(?:view|read|see|access|continue)\b",
    r"\b(?:premium|members?[- ]only)\s+content\b",
    r"\blog\s?in\s+to\s+(?:view|see|read)\b",
    r"\bsign\s?up\s+to\s+(?:view|see|read|unlock)\b",
    r"\bupgrade\s+to\s+(?:view|read|see|unlock|access)\b",
]

# Payment-required HTTP status codes that mean "terms behind a paywall".
_PAYWALL_HTTP_STATUSES = {402, 403}


def _as_mapping(entry: Any) -> Dict[str, Any]:
    """Normalize any accepted entry shape into a flat field mapping.

    A ``PortfolioEntry`` carries the serialized ``Opportunity`` in
    ``opportunity_ref``; an ``Opportunity``/dict exposes its fields directly.
    Portfolio-level fields (``blocked_reason``, ``expected_value`` …) are merged
    in too, but the ref's own keys win on collision.
    """
    if entry is None:
        return {}
    if isinstance(entry, dict):
        return dict(entry)
    fields: Dict[str, Any] = {}
    ref = getattr(entry, "opportunity_ref", None)
    if isinstance(ref, dict):
        fields.update(ref)
    # Direct attributes (Opportunity or PortfolioEntry) — copy the ones we read.
    for key in (
        "title", "description", "location_requirements",
        "eligibility_requirements", "payment_type", "currency",
        "advertised_amount", "external_url", "platform", "category",
        "blocked_reason", "http_status", "fetch_status", "paywall",
        "requirements", "deliverable",
    ):
        val = getattr(entry, key, None)
        if val not in (None, ""):
            fields.setdefault(key, val)
    return fields


def _combined_text(fields: Dict[str, Any]) -> str:
    """The free-text surface we parse, lower-cased once."""
    parts = [
        str(fields.get("title", "")),
        str(fields.get("description", "")),
        str(fields.get("location_requirements", "")),
        str(fields.get("eligibility_requirements", "")),
        str(fields.get("deliverable", "")),
        str(fields.get("requirements", "")),
    ]
    return " \n ".join(p for p in parts if p).lower()


def _detect_location(fields: Dict[str, Any], text: str) -> List[str]:
    found: List[str] = []
    # A structured location_requirements field is authoritative when present.
    structured = str(fields.get("location_requirements", "")).strip()
    if structured:
        found.append(structured[:160])
    for pat in _LOCATION_PATTERNS:
        m = re.search(pat, text)
        if m:
            snippet = m.group(0).strip()
            if snippet and snippet not in found:
                found.append(snippet)
    return found


def _detect_payment_methods(fields: Dict[str, Any], text: str) -> List[str]:
    found: List[str] = []
    ptype = str(fields.get("payment_type", "")).strip().lower()
    if ptype and ptype not in ("usd", ""):
        # payment_type is a coarse kind; surface it as a requirement hint.
        found.append(f"payment_type={ptype}")
    seen = {f.split("=", 1)[-1] for f in found}
    for pat, label in _PAYMENT_METHOD_PATTERNS:
        if re.search(pat, text) and label not in seen:
            found.append(label)
            seen.add(label)
    return found


def _detect_deliverables(text: str) -> List[str]:
    found: List[str] = []
    for pat in _DELIVERABLE_PATTERNS:
        for m in re.finditer(pat, text):
            snippet = " ".join(m.group(1).split())[:120].strip()
            if snippet and snippet not in found:
                found.append(snippet)
    return found[:3]  # bound the digest


def _detect_paywall(fields: Dict[str, Any], text: str) -> List[str]:
    """A paywall / HTTP 402 makes the candidate's real terms unknowable."""
    reasons: List[str] = []
    # Explicit status carried on the entry (a caller records the fetch result).
    for key in ("http_status", "fetch_status"):
        status = fields.get(key)
        try:
            if status is not None and int(status) in _PAYWALL_HTTP_STATUSES:
                reasons.append(f"page returned HTTP {int(status)} (payment required)")
        except (TypeError, ValueError):
            pass
    if fields.get("paywall") is True:
        reasons.append("listing marked as paywalled")
    for pat in _PAYWALL_TEXT_PATTERNS:
        if re.search(pat, text):
            reasons.append("listing text indicates a paywall / payment required")
            break
    # De-dupe while preserving order.
    out: List[str] = []
    for r in reasons:
        if r not in out:
            out.append(r)
    return out


def analyse_candidate(entry: Any) -> Dict[str, Any]:
    """Return a deterministic digest of one candidate for the Dialogue council.

    Pure: no I/O, no LLM, no network. Never raises on a malformed entry — a
    candidate we cannot parse yields an empty-but-valid digest with viability
    ``needs_review`` (missing info is itself a reason to review), never
    ``viable``.
    """
    fields = _as_mapping(entry)
    text = _combined_text(fields)

    requirements: List[Dict[str, str]] = []
    for loc in _detect_location(fields, text):
        requirements.append({"type": "location", "detail": loc})
    for pay in _detect_payment_methods(fields, text):
        requirements.append({"type": "payment_method", "detail": pay})
    for dele in _detect_deliverables(text):
        requirements.append({"type": "deliverable", "detail": dele})
    # An explicit eligibility requirement is a real gate to surface.
    elig = str(fields.get("eligibility_requirements", "")).strip()
    if elig:
        requirements.append({"type": "eligibility", "detail": elig[:160]})

    blockers = _detect_paywall(fields, text)

    # A location/eligibility restriction is a hard requirement the worker may
    # not satisfy — flag it for review rather than assume fit.
    hard_req_types = {"location", "eligibility"}

    if blockers:
        viability = "blocked"
    elif any(r["type"] in hard_req_types for r in requirements) or not text.strip():
        # A restriction we cannot self-clear, or a candidate with no readable
        # text at all, both need a human eye before acting.
        viability = "needs_review"
    else:
        viability = "viable"

    summary = _summarize(viability, requirements, blockers)
    return {
        "requirements": requirements,
        "viability": viability,
        "blockers": blockers,
        "summary": summary,
    }


def _summarize(viability: str, requirements: List[Dict[str, str]],
               blockers: List[str]) -> str:
    """A one-line, prompt-friendly digest (deterministic)."""
    if viability == "blocked":
        head = "BLOCKED: " + (blockers[0] if blockers else "paywall")
    else:
        head = viability.replace("_", " ").upper()
    bits = []
    locs = [r["detail"] for r in requirements if r["type"] == "location"]
    pays = [r["detail"] for r in requirements if r["type"] == "payment_method"]
    deles = [r["detail"] for r in requirements if r["type"] == "deliverable"]
    if locs:
        bits.append("location: " + "; ".join(locs[:2]))
    if pays:
        bits.append("pay via: " + ", ".join(pays[:3]))
    if deles:
        bits.append("deliver: " + "; ".join(deles[:2]))
    return head + ((" — " + " | ".join(bits)) if bits else "")


# ── A1: ranked board adapter ────────────────────────────────────────────────
#
# The Dialogue board must show the council the BEST opportunities first, with a
# score and a one-word "why" per row. The authority is the same GoT planner the
# earning pipeline uses (`agents.earning.got.OpportunityGraphPlanner`), so the
# board and the pipeline agree on rank.
#
# Deliberately NOT `rank_opportunities` (the ranking.py wrapper): that wrapper
# reads `opportunity.id`, which `PortfolioEntry` does not have (it carries
# `opportunity_id`), so it would raise AttributeError on board entries. The
# planner's own `_id()` (`.id` → `.opportunity_id` → "") handles BOTH
# `PortfolioEntry` and `Opportunity`, and degrades missing `intelligence`/
# evidence to zero — cold-start safe. Pure: no GUI, no DB, no network.

def _entry_id(entry: Any) -> str:
    """Mirror OpportunityGraphPlanner._id: `.id`, else `.opportunity_id`, else ""."""
    return str(getattr(entry, "id", getattr(entry, "opportunity_id", "")) or "")


def rank_board_entries(
    entries: Any,
    evidence_store: Any = None,
    log_fn: Any = None,
    limit: Any = None,
) -> List[Any]:
    """Rank board entries best-first via the GoT planner.

    Returns ``list[(entry, utility_score: float, why: str)]`` ordered by
    ``utility_score`` descending (stable, so equal scores keep discovery order).
    ``limit`` (int>0) bounds the result to the caller's budget. Any entry the
    planner does not rank, or any planner/import failure, degrades to
    ``(entry, 0.0, "unranked")`` — the board never drops a row and never fabricates
    a score. This READS a graph rank; it does not verify payment or earnings.
    """
    log = log_fn if callable(log_fn) else (lambda _m: None)
    items = list(entries or [])
    if not items:
        return []

    # Evidence snapshot (guarded; cold-start safe when the store is absent).
    evidence_by_id: Dict[str, Any] = {}
    if evidence_store is not None:
        for entry in items:
            eid = _entry_id(entry)
            try:
                for ev in evidence_store.for_subject("opportunity", eid):
                    try:
                        evidence_by_id[ev.id] = ev
                    except Exception:
                        pass
            except Exception as exc:
                log(f"[BoardRank] evidence unavailable for {eid or '?'}: {exc}")

    def _cold_start() -> List[Any]:
        triples = [(e, 0.0, "unranked") for e in items]
        return triples[:limit] if (isinstance(limit, int) and limit > 0) else triples

    try:
        from agents.earning.got import OpportunityGraphPlanner
    except Exception as exc:
        log(f"[BoardRank] planner import failed, cold-start order: {exc}")
        return _cold_start()

    try:
        planner = OpportunityGraphPlanner(items, evidence_by_id=evidence_by_id)
        ranks = planner.rank()
    except Exception as exc:
        log(f"[BoardRank] planner failed, cold-start order: {exc}")
        return _cold_start()

    rank_by_id = {r.opportunity_id: r for r in ranks}
    triples: List[Any] = []
    for entry in items:
        eid = _entry_id(entry)
        r = rank_by_id.get(eid)
        if r is None:
            triples.append((entry, 0.0, "unranked"))
        else:
            score = float(getattr(r, "utility_score", 0.0) or 0.0)
            why = str(getattr(r, "recommendation", "") or "unranked")
            triples.append((entry, score, why))

    # highest utility first; stable sort keeps discovery order on ties.
    triples.sort(key=lambda t: -t[1])
    if isinstance(limit, int) and limit > 0:
        triples = triples[:limit]
    return triples


__all__ = ["analyse_candidate", "rank_board_entries"]
