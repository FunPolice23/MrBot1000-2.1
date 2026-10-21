# 10j — `agents/integrations/`

> **I-01 RESOLVED in v2.1.125 (ARCH-ENG-290).** The SSRF guard is now applied
> inside the browsing layer itself: `WebController.read_page()`,
> `WebController.scrape()` and `WebEyes.read_page()` refuse a URL that does not
> resolve to a public address before any `requests` or Playwright call. The tool
> boundary guard remains as the first line; this closes the direct-caller gap.

12 scripts, 3,078 lines. The layer that actually touches external services:
platform APIs, web browsing/scraping, and crypto wallets.

---

## Structure and reachability

| File | Lines | Reached from |
|---|---:|---|
| `__init__.py` | 2 | — |
| `microtask.py` | 156 | `discovery_sources`, `microtask_earner`, `earning_pipeline` |
| `web.py` | 192 | `web_discovery.py` |
| `upwork.py` | 218 | `discovery_sources`, `earning_pipeline`, `main` |
| `fiverr.py` | 238 | `discovery_sources`, `earning_pipeline` |
| `scraper.py` | 290 | `tab_workers.py` |
| `crypto.py` | 257 | `real_crypto_operator.py` — **0 tests** |
| `wallet_crypto.py` | 287 | `handlers.py` ×2, `legacy_tools.py` |
| `browser.py` | 414 | `freelance_finder`, `microtask_earner`, `tab_feature_builders` |
| `web_eyes.py` | 474 | `registration.py`, `handlers.py` ×2 |
| `wallet_manager.py` | 345 | `chain_verifier`, `payment`, `main` |
| `wallet.py` | 205 | `earning_tab.py` ×3, `payments_tab.py` |

**No orphans.** Every module has a live production consumer.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| I-01 | med | **The SSRF guard is applied at the tool boundary, not at the browsing layer.** `InstructionGate._is_safe_fetch_url` (`agents/safety/instructions.py:171`) is a genuinely good guard — scheme allowlist, literal-host blocklist including `169.254.169.254`, DNS resolution with a full `ipaddress` check on every returned address, and fail-closed on an unresolvable host. It is called from `instructions.py:78/109/208` (quarantined SKILL.md), `handlers.py:100` (the `web_read` tool) and `openai_compatible.py` (provider `base_url`). It is **never** called inside the three functions that actually fetch pages: `WebController.read_page` (`browser.py:115`), `WebController.scrape` (`:240`) and `WebEyes.read_page` (`web_eyes.py:200`) — verified by AST inspection of each function body, not by grep. `handlers.py:75` states the bypass outright: *"Every other URL went straight to `web_eyes.read_page(url)`."* ARCH-ENG-213 fixed the tool entry point and left the fetcher unguarded. Every caller reaching the browsing layer today happens to be trusted, so this is defence-in-depth rather than an exploitable hole — but the invariant is **conventional, not structural**, and it is maintained only by every future caller being careful. |
| I-02 | low | **Two URLs in one signature, only one guarded.** `RegistrationService.propose(platform, signup_url, instruction_url)` (`:98`) routes `instruction_url` through `gate.fetch_instruction(...)` at `:114` — guarded — then passes `signup_url` straight to `eyes.read_page(signup_url)` at `:132`. `register_with_vault` (`:212`) then drives `eyes.fill_form(signup_url, ...)` at `:264`, filling **operator secrets** into that unguarded URL. **Mitigating fact, checked before scoring:** `RegistrationService` is constructed in exactly one place, `gui/panels/registration_panel.py:54`, and `register_with_vault` is called from exactly one place, `:258`. `signup_url` is operator-typed into a GUI panel, so this is not a live SSRF. It becomes one the moment the panel sources a URL from a discovered listing instead of a human. |
| I-03 | low | **DNS-rebinding gap in the guard itself.** `_is_safe_fetch_url` resolves the hostname at `:189` and validates the resulting IPs, but `requests.get` at `:211` performs its own independent resolution. A hostile resolver can return a public address to the check and a private one to `requests`. The code at `:191-193` shows this was considered — *"A hostname that cannot be resolved cannot be proven public. Fail closed so a later resolver cannot redirect the request internally"* — but the mitigation is fail-closed-on-unresolvable, not IP pinning, so it does not actually close the rebinding window. Standard finding, low severity, and the comment's intent is right even though the mechanism falls short of it. |
| I-04 | low | **`crypto.py` — 257 lines of real crypto payment integration, zero tests.** One production consumer (`real_crypto_operator.py`). `wallet.py` has 8 test references and `wallet_manager.py` has several; `crypto.py` has none, despite being the module closest to irreversible money movement in this directory. Not a wiring defect — it is reachable — but the test posture is inverted relative to risk. |
| I-05 | info | **`web_eyes.py` carries a `print()`-based demo block** (`:462`, `print("Testing WebEyes...")`) in a module with a `get_web_eyes()` singleton at `:423`. Third `__main__`-demo finding after `document_scanner.py`'s `QualityController` (H-01) and `web_eyes.py`'s sibling in `integrations`. |

---

## Verified as sound

**`_is_safe_fetch_url` is a real guard, not a name.** It rejects non-`http(s)`
schemes, blocks `localhost` / `0.0.0.0` / `::1` / `169.254.169.254`, resolves the
hostname, and rejects any resolved address that is private, loopback, link-local,
reserved or multicast. The fail-closed branch on resolution failure is correct in
direction. `tests/safety/test_arch_eng_213_web_read_ssrf.py` exists specifically to
prove it is not vacuous, and `handlers.py:69` describes it accurately. This is the
standard I hold the rest of the browsing layer to — it simply is not applied there.

**`registration.py`'s trust design is the most adversarially-specified module in
the project.** Its docstring sets out a five-step flow and, crucially, states the
threat it is defending against in the opening line: create an account *"WITHOUT
ever letting an untrusted SKILL.md drive it, and WITHOUT the agent ever handling a
secret."* Each step is bounded: FETCH returns content marked `trusted=False`
explicitly as reference material rather than executable authority; PROPOSE ends
*"The agent drafts; it does not decide"*; APPROVE requires an explicit human
action and notes *"An untrusted instruction can never satisfy this"*; FILL
requires the caller to supply secrets, with the module refusing to invent or
persist any credential; VERIFY re-reads the page and reports as evidence. Every
mutating action (`create_account`, `set_password`, `login`, `grant_oauth`) is in
`HIGH_TRUST_ACTIONS`.

**`register_with_vault` fails closed without a store** —
`tests/platforms/test_registration_gate.py:120` asserts it, and the flow sources
secrets from a vault rather than the agent.

---

## Assessment

This directory has no dead code, which continues the pattern of the last three
areas: the orphaned subsystems are all in `agents/earning/`, and the plumbing and
integration layers are consistently wired.

I-01 is the finding worth acting on, but it should be sized honestly. It is not a
live vulnerability — every current caller of the browsing layer is either an
operator-facing GUI panel or an earning finder operating on configured endpoints.
The defensible claim is narrower and more useful: **the SSRF invariant is a
convention that currently holds, rather than a property of the code.** That is
exactly the shape of failure this sweep has documented seven times now, in
non-security contexts — and it is the one context where it would actually hurt.

I-04 is worth noting separately because it is not a wiring defect and so does not
fit the pattern. `crypto.py` is reachable and correct-looking; it simply has no
tests while its two sibling wallet modules do. Risk-posture inversion rather than
dead code.

I-02 is recorded at low severity specifically because the check came back
favourable. The asymmetry between `instruction_url` and `signup_url` inside a
single function signature is real and would be worth fixing on its own merits —
but the moment it would become a credential-exfiltration path is the moment the
panel stops taking the URL from a human, and that change has not happened yet.
Worth recording now precisely because the trigger is foreseeable.