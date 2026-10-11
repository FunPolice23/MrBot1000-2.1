"""Scraper resilience helpers (v2.0.34s, Section C3).

Keeps web/freelance scraping alive under hostile conditions WITHOUT solving
captchas (that's out of scope + often ToS-violating). Three concerns:

1. User-Agent rotation  -> avoid a single static UA being fingerprinted/banned.
2. 429 / 503 backoff     -> honor the server's ``Retry-After`` (the *correct*,
   ToS-compliant behavior) instead of hammering. Capped so we never hang.
3. Captcha detection     -> if the response is a captcha interstitial, bail out
   gracefully (return [] / raise CaptchaBlockedError) so the caller can fall
   back to another source rather than retrying into a ban.

All helpers are pure / mock-friendly (no live network in tests).
"""

from __future__ import annotations

import re
import time
import email.utils
from typing import List, Optional


# A small, generic bot UA set. We do NOT spoof a real browser identity (that
# could be deceptive); these clearly identify the bot and rotate to avoid a
# single-UA ban.
USER_AGENTS: List[str] = [
    "MrBot1000/2.0 (+https://github.com/FunPolice23/MrBot1000)",
    "MrBot1000-Crawler/2.0 (research; +https://github.com/FunPolice23/MrBot1000)",
    "Mozilla/5.0 (compatible; MrBot1000/2.0; +https://github.com/FunPolice23/MrBot1000)",
]

_CAPTCHA_MARKERS = (
    "captcha",
    "cf-chl",
    "are you a robot",
    "are you a human",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "please verify",
    "security check",
    "unusual traffic",
    "rate limited",
    "too many requests",
)


class RateLimitedError(Exception):
    """Raised when a request is rate-limited and retries are exhausted."""


class CaptchaBlockedError(Exception):
    """Raised when the response appears to be a captcha/interstitial."""


def pick_ua(rotate: bool = True, idx: int = 0) -> str:
    """Return a User-Agent string.

    ``rotate`` True -> round-robin by ``idx`` (caller supplies an incrementing
    counter, e.g. a per-instance int). False -> first (stable) UA.
    """
    if not USER_AGENTS:
        return "MrBot1000/2.0"
    if not rotate:
        return USER_AGENTS[0]
    return USER_AGENTS[idx % len(USER_AGENTS)]


def detect_captcha(text: str) -> bool:
    """Cheap heuristic: does ``text`` look like a captcha/interstitial page?"""
    if not text:
        return False
    low = text.lower()
    return any(marker in low for marker in _CAPTCHA_MARKERS)


def _parse_retry_after(value: Optional[str], default: float,
                       max_wait: float = 60.0) -> float:
    """Parse an HTTP ``Retry-After`` value (seconds int, or HTTP-date).

    Returns ``default`` if missing/unparseable, and is always capped to
    ``max_wait`` so a bogus far-future date can't make us sleep for years.
    """
    if not value:
        return default
    value = value.strip()
    try:
        # Seconds form (most common).
        secs = float(value)
        if secs >= 0:
            return min(secs, max_wait)
    except ValueError:
        pass
    # HTTP-date form.
    try:
        t = email.utils.parsedate_to_datetime(value)
        if t is not None:
            delta = (t.timestamp() - time.time())
            if delta > 0:
                return min(delta, max_wait)
    except (TypeError, ValueError, OverflowError):
        pass
    return default


def honor_retry_after(resp, *, max_wait: float = 60.0,
                       default_wait: float = 5.0) -> float:
    """If ``resp`` is a 429/503 with Retry-After, sleep (capped) and return wait.

    Returns the number of seconds waited (0.0 if not rate-limited). Never raises
    for the sleep itself; the caller decides whether to retry.

    ``resp`` must expose ``.status_code`` and ``.headers`` (requests.Response-like)
    OR be a Mapping with ``status_code``/``headers`` keys (for tests).
    """
    status = getattr(resp, "status_code", None)
    if status is None and isinstance(resp, dict):
        status = resp.get("status_code")
    if status not in (429, 503):
        return 0.0
    headers = getattr(resp, "headers", None)
    if headers is None and isinstance(resp, dict):
        headers = resp.get("headers", {}) or {}
    raw = headers.get("Retry-After") if headers else None
    wait = _parse_retry_after(raw, default_wait)
    wait = min(wait, max_wait)
    if wait > 0:
        time.sleep(wait)
    return wait


def retry_on_429(func, *, max_retries: int = 3,
                 max_wait: float = 60.0,
                 default_wait: float = 5.0):
    """Call ``func`` (returns a requests.Response-like). On 429/503, honor
    Retry-After and retry up to ``max_retries``. On non-429 errors, re-raise
    (we don't retry client 4xx — that escalates ban risk). On captcha body,
    raise ``CaptchaBlockedError``. On exhausted retries, raise ``RateLimitedError``.

    ``func`` is invoked with no args; its return value is passed through.
    """
    last_resp = None
    for attempt in range(max_retries + 1):
        resp = func()
        last_resp = resp
        status = getattr(resp, "status_code", None)
        if status in (429, 503):
            waited = honor_retry_after(
                resp, max_wait=max_wait, default_wait=default_wait)
            # If a captcha body came back instead of a real 429 retry, bail.
            body = _resp_text(resp)
            if detect_captcha(body):
                raise CaptchaBlockedError(
                    "captcha/interstitial detected in rate-limit response")
            if attempt >= max_retries:
                raise RateLimitedError(
                    f"rate-limited after {max_retries} retries "
                    f"(Retry-After={waited:.1f}s)")
            continue
        # Not rate-limited: check the body for a captcha interstitial anyway.
        body = _resp_text(resp)
        if detect_captcha(body):
            raise CaptchaBlockedError("captcha/interstitial detected in response")
        return resp
    raise RateLimitedError("rate-limited (no response captured)")


def _resp_text(resp) -> str:
    if resp is None:
        return ""
    if hasattr(resp, "text"):
        try:
            return resp.text or ""
        except Exception:
            return ""
    if isinstance(resp, dict):
        return resp.get("text", "") or ""
    return str(resp)
