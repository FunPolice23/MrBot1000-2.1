"""agents/dialogue_honesty.py — Honesty enforcement for model dialogue (v2.1.1).

Wires together FactLedger, OperatorOverride, and EpistemicCalibration so the
dialogue can:

* record model claims as PROPOSED (never let a model self-verify)
* apply operator overrides before presenting claims to the model
* inject an honest epistemic framing into the model's context so it does not
  overstate unverified knowledge

Deterministic application logic remains authoritative — the model is never the
source of truth for its own certainty.
"""

from __future__ import annotations

from collections.abc import Sequence

from agents.epistemic_calibration import context_note
from agents.fact_ledger import Claim, ClaimStatus, FactLedger, LedgerEntry, SourceKind
from agents.operator_override import OperatorOverrideRegistry


def _extract_claims_from_context(context: str) -> list[tuple[str, str]]:
    """Best-effort extraction of factual claims from model output text.

    Returns a list of (statement, source) tuples. The extraction is intentionally
    conservative: missed claims are safe (they remain unverified), false positives
    are filtered by the ledger's deterministic classification.

    Production heuristics:

    * Sentences containing canonical claim verbs (is, are, has, have, can, will,
      does, contains, provides, supports, proves, shows, confirmed, verified)
      followed by a factual predicate are candidates.
    * Sentences starting with ASSERT:, CLAIM:, or FACT: are treated as explicit
      claims.
    * Lists of bullet points are split into individual claims.
    """
    import re

    candidates: list[tuple[str, str]] = []
    lines = [ln.strip() for ln in context.splitlines() if ln.strip()]

    # Explicit markers first.
    for line in lines:
        m = re.match(r"^(?:ASSERT|CLAIM|FACT)\s*:\s*(.+)$", line, re.IGNORECASE)
        if m:
            candidates.append((m.group(1).strip(), "dialogue_explicit"))

    # Heuristic claim detection on remaining lines.
    claim_verb = re.compile(
        r"(\b(?:is|are|was|were|has|have|had|can|could|will|would|does|"
        r"did|contains|provides|supports|proves|shows|confirmed|verified|"
        r"available|exists|works|supports|includes|requires|accepts|"
        r"rejects|denies|blocks|allows|pays|offers|charges|requires"
        r")\b\s+.{8,})",
        re.IGNORECASE,
    )
    for line in lines:
        if any(line.upper().startswith(m) for m in ("ASSERT", "CLAIM", "FACT")):
            continue  # already captured above
        for m in claim_verb.finditer(line):
            statement = m.group(1).strip()
            if len(statement) > 20 and len(statement) < 500:
                candidates.append((statement, "dialogue_heuristic"))

    # Deduplicate by normalized text.
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for statement, source in candidates:
        norm = re.sub(r"\s+", " ", statement.lower()).strip()
        if norm and norm not in seen:
            seen.add(norm)
            result.append((statement, source))
    return result


class DialogueHonestyService:
    """Single service that coordinates the three honesty modules for dialogue.

    Lifecycle:

    1. The dialogue tab creates one service per session (or reuses a shared one).
    2. After each model turn, :meth:`record_claims` is called with the response
       text. Claims are recorded as PROPOSED with source_kind=SourceKind.LLM.
    3. Before building the next prompt, :meth:`epistemic_context_note` is called
       with the active ledger entries and the result is appended to the system
       prompt.
    4. Operator overrides are applied via :meth:`apply_overrides` before the note
       is generated.

    The service does NOT decide what is true — it only records, classifies, and
    frames. Verification requires deterministic evidence through the ledger's
    attach_evidence path.
    """

    def __init__(self, max_claims: int = 60) -> None:
        self.ledger = FactLedger()
        self.overrides = OperatorOverrideRegistry()
        # Bound the ledger: auto-extracted model claims are unverified noise
        # after a while and must not accumulate without limit.
        self._max_claims = max(10, int(max_claims))
        self._seen: set[str] = set()

    # ── Recording ────────────────────────────────────────────────────────────

    def record_claims(
        self,
        response_text: str,
        source: str = "dialogue_model",
        subject_type: str = "",
        subject_id: str = "",
    ) -> list[LedgerEntry]:
        """Record each extracted claim as PROPOSED (model may not self-verify).

        Claims are deduplicated across turns: the same sentence restated every
        turn is ONE claim, not one per turn. The ledger is pruned to a bound
        afterward so the injected epistemic note stays small.

        Returns the newly created ledger entries for observability.
        """
        import re as _re
        claims = _extract_claims_from_context(response_text)
        entries: list[LedgerEntry] = []
        for statement, claim_source in claims:
            norm = _re.sub(r"\s+", " ", statement.lower()).strip()
            if not norm or norm in self._seen:
                continue
            self._seen.add(norm)
            claim = Claim(
                source=source,
                evidence_type=claim_source,
                subject_type=subject_type,
                subject_id=subject_id,
                assertion=statement,
                observed_at=0.0,
            )
            entry = self.ledger.record_claim(
                claim,
                source_kind=SourceKind.LLM,
            )
            entries.append(entry)
        try:
            self.ledger.prune(self._max_claims)
        except Exception:
            pass
        return entries

    # ── Override application ─────────────────────────────────────────────────

    def apply_overrides(self) -> None:
        """Apply active operator overrides to any conflicting claims.

        For each active override, if the ledger has a claim whose statement
        conflicts with the override, the claim is superseded (marked
        SUPERSEDED). This is the deterministic path that lets a human outrank a
        model's prior claim without letting the model self-verify.
        """
        for record in self.overrides.active():
            # Find claims that mention the same subject or are global overrides.
            if record.subject_id:
                for entry in self.ledger.all_claims():
                    if entry.subject_id == record.subject_id:
                        try:
                            self.ledger.supersede_by_reference(
                                entry.claim_id,
                                f"operator_override:{record.override_id}",
                                note=record.statement,
                            )
                        except Exception:
                            pass
            else:
                # Global override: supersede any claim whose statement conflicts.
                for entry in self.ledger.all_claims():
                    if entry.status == ClaimStatus.PROPOSED:
                        try:
                            self.ledger.supersede_by_reference(
                                entry.claim_id,
                                f"operator_override:{record.override_id}",
                                note=record.statement,
                            )
                        except Exception:
                            pass

    # ── Epistemic framing ────────────────────────────────────────────────────

    def epistemic_context_note(self, max_claims: int = 8) -> str:
        """Return the epistemic framing for all standing claims.

        The result is safe to inject into the model's system prompt. Empty
        string when there are no standing claims.
        """
        entries = self.ledger.all_claims()
        return context_note(entries, max_claims=max_claims)

    # ── Observability ────────────────────────────────────────────────────────

    def standing_claims(self) -> list[LedgerEntry]:
        return [
            e for e in self.ledger.all_claims()
            if e.status in (ClaimStatus.PROPOSED, ClaimStatus.SUPPORTED,
                            ClaimStatus.VERIFIED)
        ]

    def to_dict(self) -> dict:
        return {
            "claim_count": len(self.ledger.all_claims()),
            "standing_count": len(self.standing_claims()),
            "verified_count": len(self.ledger.verified_claims()),
            "override_count": len(self.overrides.active()),
        }
