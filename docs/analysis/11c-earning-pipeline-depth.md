# 11c — `app/earning_pipeline.py` depth pass (1,566 lines, 52 methods)

> **W-01 + W-02 RESOLVED in v2.1.125 (ARCH-ENG-285/286).** The 262-line parallel
> discovery island (`_discover_source` plus eight `_discover_*` handlers) is
> deleted; `run_discovery_cycle()` is the single scheduler-driven discovery
> stage. The three feature gates that lived only inside that island
> (`social_automation`, `airdrop_claiming`, `defi_scanning`) are now
> `is_enabled()` on the live `SocialSource`, `AirdropSource` and `DefiSource`,
> so a disabled flag actually stops the scan. The ARCH-ENG-212 DeFi structural
> test now targets the live `DefiSource` instead of the deleted call site.
>
> **LOW TIER CLOSED in v2.1.125.** W-04 (ARCH-ENG-254): six accessors with zero
> callers (`get_opportunity_stats`, `_db_execute`, `load_memory`,
> `build_workflow_plan`, `_legacy_to_canonical`, `get_platform_reputations`)
> are deleted, along with the never-imported `agents/services/workflow_planner.py`
> they kept alive. W-03 (ARCH-ENG-274): `search_opportunities_by_keyword` was
> dead, so the capability is now the read-only CLI command
> `mrbot-cli opportunities <keyword>` over `opportunity_memory`, and the dead
> pipeline wrapper is deleted rather than duplicated.
>

Depth-pass #3 of 83. The hub that F-01, O-01 and O-02 all route through.
**44 of 52 methods live — 8 dead**, and one of them is a 289-line dead island
carrying three feature-flag gates.

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| W-01 | **high** | **A 289-line parallel discovery implementation is dead, and three of its feature gates are inside it.** `_discover_source` (`:495`, 36 lines) is a complete source dispatcher with an allowlist and three `feature_enabled` gates. It is called by **nothing**. Its eight `_discover_*` handlers — `_discover_upwork` (33), `_discover_defi` (63), `_discover_dynamic` (25), `_discover_social` (23), `_discover_airdrops` (23), `_discover_fiverr` (21), `_discover_microtasks` (21), `_discover_content` (8) — are reachable **only from `_discover_source`**, so the whole island is transitively dead. The live path is entirely different: `discover()` (`:287`) → `self.discovery_service.discover()` → `agents/earning/discovery.py:49` → `BuiltinDiscoveryService` → `agents/discovery/discovery_port.py` → `DiscoveryEngine`. Two complete discovery implementations exist; `agents/discovery/` (assessed in `10f`) is the live one and this is the superseded one that was never retired — the same shape as `hardware_plan.py` (M-01) and `model_recommendations.py` (L-01). |
| W-02 | **high** | **Correction to `10d`: three of the eleven `feature_enabled()` call sites are inside the dead island, and `social_automation`'s *only* production gate is one of them.** In `10d` I recorded: *"The four flags that matter do gate behaviour… `self_improvement` (6), `airdrop_claiming` (2), `defi_scanning` (2), `social_automation` (1). These are real gates on real code paths."* The counts were right; **"on real code paths" was not.** Resolving each site to its enclosing definition: |

  | Flag | Site | Enclosing def | Live |
  |---|---|---|---|
  | `self_improvement` | `main.py:1617` | `_start_self_improve_monitor` | ✓ |
  | `self_improvement` | `composition_root.py:159` | module level | ✓ |
  | `self_improvement` | `self_improvement_commands.py:41/89/120` | `propose_code_patch` / `approve_and_apply` / `decline_patch` | ✓ |
  | `airdrop_claiming` | `agents/earning/tasks.py:18` | `execute_airdrop` | ✓ |
  | `defi_scanning` | `agents/earning/tasks.py:98` | `execute_defi` | ✓ |
  | **`social_automation`** | **`earning_pipeline.py:504`** | **`_discover_source`** | **DEAD** |
  | `airdrop_claiming` | `earning_pipeline.py:507` | `_discover_source` | DEAD |
  | `defi_scanning` | `earning_pipeline.py:510` | `_discover_source` | DEAD |

  So `airdrop_claiming` and `defi_scanning` survive — each has a second, live gate in `agents/earning/tasks.py` on the **execution** path. But **`social_automation` has no live gate at all.** It gates tab visibility (`main.py:1541`) and nothing else that runs. The error is the same one this sweep has made repeatedly and then corrected: I counted call sites without resolving whether the enclosing function was reachable. **A gate inside unreachable code is not a gate.** |
| W-03 | low | **`search_opportunities_by_keyword` (`:1546`, 11 lines) is dead**, which matters because `ALLOW_WEB_DISCOVERY=True` in `.env:358` (F-04) — the operator has web discovery enabled, and the only keyword-driven entry point to it is unreachable. Web discovery does run, via `WebDiscoverySource` in `discovery_sources.py:468` and the fixed seed feeds; only the *targeted* keyword search is unwired. |
| W-04 | low | **Five further dead methods, all small accessors:** `get_opportunity_stats` (`:1558`, 9L), `_db_execute` (`:261`, 8L), `load_memory` (`:1387`, 7L), `build_workflow_plan` (`:1535`, 6L), `_legacy_to_canonical` (`:474`, 4L), `get_platform_reputations` (`:1403`, 3L). `build_workflow_plan` makes **`agents/services/workflow_planner.py` transitively dead** — the only thing `earning_pipeline.py` imported from it, and its sole consumer. |

---

## Re-verification of earlier findings

**F-01 confirmed unchanged.** `run_discovery_cycle` (`:332-375`) remains the only
caller of `DiscoveryScheduler.tick()` and remains uncalled;
`run_autonomous_loop` (`:1337-1383`) remains uncalled. The live path is still
`run_full_cycle` (`:1300-1335`), and `discover()` still writes outcomes to the
scheduler at `:318`/`:322` and calls `mark_searched` at `:327` — recording into
state nothing consumes.

**G-05 confirmed.** Nothing in this file drives `LiveTradingService`.

**O-02 / `10q` confirmed.** `LearningLoop` is genuinely constructed at `:139-140`.

**W-01 partly explains `10h`'s G-05 framing**: the per-source discovery handlers
that would have reached airdrop and DeFi are dead, so the only live airdrop/DeFi
gates are the *execution* ones in `tasks.py`.

---

## Verified as sound

**`EarningPipeline.__init__` (`:111-200`) wires the hub correctly.** It constructs
`DiscoveryScheduler` (`:157`) from `agents/discovery/discovery_strategies.py:156`,
`EvidenceStore` (`:135`) on AgentDB's evidence table, and `LearningLoop`
(`:139-140`). Those are the three subsystems this sweep has separately verified as
live, and the hub is what connects them.

**`discover()` (`:272-330`) delegates cleanly** to the port/adapter boundary rather
than reimplementing discovery, which is why `agents/discovery/` could be assessed as
the single live implementation.

**`mark_paid_verified` is used at three sites** (`:1436`, `:1489`) plus `main.py:1813`,
matching the ARCH-ENG-043 payout design verified in `10h`.

---

## Assessment

44 of 52 live is a good result for a 1,456-line class, and the hub is correctly
wired to the three subsystems that matter.

W-01 and W-02 are the same finding seen from two sides, and together they are the
most consequential result of the depth pass so far. A parallel 289-line discovery
implementation sits beside the live one, and because it is where three of the seven
feature gates were written, one of them — `social_automation` — has lost its only
live enforcement.

This also sharpens D-01. That finding said the crypto toggle controls nothing. The
deeper truth is that **the gates which *are* live are scattered and thin**
(`tasks.py`'s two execution-path checks, five `self_improvement` sites, two
tab-visibility dicts), while a coherent gate layer exists in a dead method. That
reads less like seven independent oversights and more like one refactor —
`discovery()` moving to the port boundary — that left the old implementation in
place, gates and all.

W-02 is a correction to a claim I made and published in `10d`. The counting method
was sound and I applied it; I simply did not resolve the enclosing definitions,
which is the step that would have caught it. Recorded here rather than quietly
amended, because the earlier document should be read with this one.