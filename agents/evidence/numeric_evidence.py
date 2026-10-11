"""agents/numeric_evidence.py — deterministic evidence check for monetary values.

Untrusted-input discipline: a model may only legitimately quote a number it was
shown in its context (or derive one from those). A monetary value in a reply that
appears nowhere in the supplied context is unsupported — it is either fabricated
or cannot be cited from the evidence at hand.

This check is pure string/Decimal work with no model judgment, so it cannot be
argued out of a finding by anything inside the untrusted text it is inspecting.
It reports; it does not block, so a legitimate arithmetic derivation is surfaced
rather than suppressed.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import List, Sequence, Tuple

# $1  $1.5  $1,234.56  $1.000e+82  $560.00
_MONEY = re.compile(
    r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)"
)


def _to_decimal(raw: str) -> Decimal | None:
    """Parse a matched number to an exact Decimal, or None if unusable.

    The value is deliberately NOT normalised. ``Decimal.normalize()`` applies the
    active decimal context precision (28 significant digits by default), so it
    rounds longer values before any comparison: 10**81 and 10**81 + 1 both became
    ``1E+81`` and compared equal. That is exactly the magnitude class this check
    exists to police, so normalising silently disabled it for the incident value.
    Decimal equality and hashing are already numeric, so ``Decimal("1.0")`` still
    matches ``Decimal("1.00")`` and set lookups stay valid without it.
    """
    cleaned = (raw or "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


def extract_monetary_values(text: str) -> List[Decimal]:
    """Every monetary value in the text, exact, deduplicated, order kept."""
    out: List[Decimal] = []
    seen: set[Decimal] = set()
    for match in _MONEY.finditer(text or ""):
        value = _to_decimal(match.group(1))
        if value is None or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def extract_monetary_spans(text: str) -> List[Tuple[str, Decimal]]:
    """(raw_text, value) for each monetary occurrence, in order, not deduped."""
    spans: List[Tuple[str, Decimal]] = []
    for match in _MONEY.finditer(text or ""):
        value = _to_decimal(match.group(1))
        if value is not None:
            spans.append((match.group(0), value))
    return spans


def unsupported_values(response_text: str, context_text: str) -> List[str]:
    """Monetary values cited in the response but absent from the supplied context.

    Returns the raw matched strings (e.g. ``"$9,999.00"``) for reporting. An empty
    list means every cited value is backed by the context.
    """
    supported = set(extract_monetary_values(context_text))
    out: List[str] = []
    seen: set[Decimal] = set()
    for raw, value in extract_monetary_spans(response_text):
        if value in supported or value in seen:
            continue
        seen.add(value)
        out.append(raw)
    return out


def has_unsupported_values(response_text: str, context_text: str) -> bool:
    """True when the response cites at least one value with no evidence."""
    return bool(unsupported_values(response_text, context_text))
