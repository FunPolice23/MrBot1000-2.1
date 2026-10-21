# 11y — `agents/services/mrbot_cli.py` depth pass (501 lines, 12 module functions)

> **LOW TIER CLOSED in v2.1.125.** AR-01 (ARCH-ENG-267): every documented
> invocation used `python -m agents.mrbot_cli`, but the module lives at
> `agents/services/mrbot_cli.py`, so all six examples died with
> `ModuleNotFoundError`. The docstring now names the real path, and a test
> resolves every documented command against `SUBCOMMANDS`. W-03
> (ARCH-ENG-274) added the read-only `opportunities <keyword>` command.
>

Depth-pass #25 of 83. **1 dead of 12** — and it confirms `10p`'s **O-03** with the root cause
the area sweep could not see. Also the tenth reference form the sweep has had to learn.

---

## Structure

```
L   25-83    .env reading          L  125-243  cmd_providers    (78)
L   86-98    probe_models          L  244-333  cmd_dialogue    (86)
L  101-105   device_from_env       L  334-384  cmd_db_stats    (48)
L  107-120   gpu_mem_info          L  386-432  cmd_logs/cmd_health
L  435-472   SUBCOMMANDS table     L  475-497  main            (23)
```

Docstring: *"mrbot_cli — read-only CLI for inspecting a live or offline MrBot1000 runtime."*

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| AR-01 | low | **`10p`'s O-03 confirmed, with the root cause: all six documented invocations name a module path that does not exist.** The docstring `:5-10` gives `python -m agents.mrbot_cli {providers,models,dialogue,db-stats,health}` for every command. The module lives at `agents/services/mrbot_cli.py`; `agents/mrbot_cli.py`, `agents/runtime/mrbot_cli.py` and a root-level `mrbot_cli.py` are all **absent**. Every documented command therefore fails with `ModuleNotFoundError: No module named 'agents.mrbot_cli'`. The correct form is `python -m agents.services.mrbot_cli`. The CLI itself is fine — `if __name__ == "__main__": raise SystemExit(main())` at `:500-501` works from its real location, and `tests/runtime/test_mrbot_cli.py:17` imports it correctly as `from agents.services import mrbot_cli`. **Only the documentation is wrong.** |
| AR-02 | info | **`device_from_env` (`:101`, 4 lines) is genuinely dead** — zero references anywhere in the repository, zero tests. A `(env, which)` lookup returning a configured device string. |

---

## AR-01 — the move that orphaned the docs

The restructure plans record what happened:

```
.hermes/plans/2026-10-09_213000-agents-restructure.md:229
    - `mrbot_cli.py` -> `agents/runtime/mrbot_cli.py`  (MOVE)
.hermes/plans/2026-10-09_220000-broad-restructure.md:63
    mrbot_cli, cli_interface
```

The module was relocated at least twice (`agents/` → `agents/runtime/` →
`agents/services/`), and the docstring's usage block was never updated to follow. That is
why `10p` could only record the symptom — *"nothing imports it"* and *"documents an
invocation path that does not exist"* — without being able to say why: from inside the file
the path looks plausible, and the module-level sweep had no way to know the module had been
moved.

The fix is a six-line docstring edit. It is worth fixing anyway, because a read-only
inspection CLI is exactly the tool an operator reaches for when something is wrong, and its
first documented command is the one guaranteed to fail.

---

## The tenth reference form — dict-valued dispatch

Six of the twelve module functions (`cmd_providers`, `cmd_models`, `cmd_dialogue`,
`cmd_db_stats`, `cmd_logs`, `cmd_health` — **266 lines**) were reported dead by the AST
scan and are all live. `main:482-486` registers them:

```python
for name, spec in SUBCOMMANDS.items():
    p = sub.add_parser(name, help=spec["help"])
    if spec["args"] is not None:
        spec["args"](p)
    p.set_defaults(func=spec["func"])
```

The function objects sit as **dict values** in `SUBCOMMANDS` (`:435-472`) and are invoked
through `args.func(args)` at `:493`. Neither the AST `Call`-target scan nor a name-based
regex sees this: the names appear once, inside a dict literal, and never as a callee.

That is the **tenth** form the sweep has now had to learn, after absolute imports,
dict-valued dispatch in general, attribute-access return types, relative imports,
package-facade re-exports, `from pkg import module as alias`, subpackage paths,
`from pkg import module`, self-exclusion from the caller search (`11s`), and comment-only
references (`11v`). **Recorded as a scan limitation, not a finding** — 266 lines of working
code that a first-pass reachability scan would have reported as dead.

A genuine bonus from reading the table: `SUBCOMMANDS["db"] = SUBCOMMANDS["db-stats"]`
(`:472`) adds a `db` alias for `db-stats` — an undocumented convenience that the scan
would also have missed.

---

## Verified as sound — the secrets safety is real, and it is the restrictive case

`10p` noted this module is *"built with secrets safety as an explicit design property."*
Confirmed, with the enforcement point located:

```python
def read_env() -> Dict[str, str]:
    """Read whitelist-sanitized .env values. Secrets never leave this function."""
    ...
    if key in ENV_READ_ALLOWLIST:      # :68
        values[key] = val
```

**The allowlist is enforced at the read, not at the print.** A key not in
`ENV_READ_ALLOWLIST` (`:32-49`, a `frozenset` of 25 exact names — `BIG_BRAIN_MODEL`,
`SMALL_BRAIN_URL`, `BIG_BRAIN_GPU_LAYERS`, …) is never loaded into the dictionary at all,
so it cannot be printed by any downstream command, including a `--json` one. The comment at
`:76` states the intent precisely: *"Print allowlisted pairs. Any value we didn't allow
stays absent."*

**A second, independent layer sits behind it.** `pretty_env:75` applies
`re.compile(r"key|token|secret|password|passwd|api_key|apikey|auth", re.I)` and substitutes
`[REDACTED]`. So if someone later adds a misnamed-but-sensitive key to the allowlist, the
regex is the backstop that catches it. **Deny-by-default at the source, plus pattern-based
redaction at the output** — two layers that fail independently.

**This is the restrictive counterpart to `11k`'s AE-02.** `11k` recorded a tool-firewall
finding whose risk was a *permissive default* — a list that grants unless explicitly
withheld. Here the shape is inverted: a `frozenset` that grants only 25 enumerated keys, so
the 200+ other keys in the operator's `.env` — including `MRBOT_ENABLE_CRYPTO`,
`MRBOT_ENABLE_LIVE_TRADING`, and every `*_API_KEY` — are unreachable by construction.

**Endpoint probes stay localhost-only, as promised** (`:12-14`). `probe_models:91` builds
`http://127.0.0.1:{port}/v1/models` with a hardcoded loopback host and a bounded
`timeout_s=4.0`, and `:97-98` swallows every exception into `(False, "", [])` so an
unreachable brain server reports as *not running* rather than raising.

---

## Re-verification

**`10p` O-03 confirmed and root-caused (AR-01).** `10p`'s table recorded
`mrbot_cli.py | 501 | **nothing imports it**` and finding O-03 *"documents an invocation
path that does not exist."* Both hold; this pass adds the mechanism — the file was moved
under the restructure and the usage block was left behind.

**`10p` O-04 unaffected.** `cli_interface.py` (213 lines) was recorded as dead in the same
area. It is not in this file and this pass did not re-test it; it remains open.

**`10p`'s secrets-safety claim upheld.** The allowlist is enforced at `:68` and the
redaction regex at `:75`, so the property is structural rather than conventional.

**`11b` / device_registry unaffected.** `device_from_env` (AR-02) is the only overlap and
it is a 4-line `.env` lookup, not a detection path. `device_registry`'s hardware
enforcement — ARCH-ENG-115, ARCH-ENG-219, `_LAST_DETECT_ERROR` — is untouched, and the CLI's
`gpu_mem_info` (`:107-120`) is a display helper.

**`11p` / provider_manager unaffected.** `cmd_providers` reads `.env` keys through the
allowlist rather than calling `ProviderManager`, which is appropriate for a read-only CLI
that must work when the runtime is down. That is a deliberate separation, not a duplicate.

---

## Assessment

One dead four-line helper, one wrong docstring, and one scan limitation worth carrying
forward.

AR-01 is trivial to fix and worth fixing: a read-only inspection CLI is precisely what an
operator reaches for when something has gone wrong, and every command in its documentation
fails immediately. The root cause is benign — a restructure moved the file and the usage
block did not follow — which is why it is `low` rather than `med`. But `10p` could not
diagnose it from outside the file, and that is the argument for a depth pass: **the same
symptom ("nothing imports it") has a different cause than the area sweep could see, and only
reading the file against the tree's actual layout distinguished them.**

AR-02 is cleanup.

The scan limitation is the more broadly useful output. **Dict-valued dispatch is now the
tenth way a live reference can hide from a reachability scan**, and this instance was worth
266 lines. The sweep's standing rule — scans are a first pass, never a verdict — has now
been violated by ten distinct mechanisms, which is strong evidence that the rule should be
treated as a property of the method rather than a caveat on the results.

The allowlist is also worth holding up as the model for the findings still open. It grants
25 named keys and refuses everything else **at the point of reading**, with a second
redaction layer at the point of printing. That is what deny-by-default looks like when it is
done properly — and it is the opposite of AE-02's permissive list, `AN-02`'s documented-but-
unreachable cancellation token, and `AQ-01`'s structurally-incapable approval path.
