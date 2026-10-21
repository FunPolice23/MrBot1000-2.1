# 10r — `gui/` (part 1: structure and reachability)

38 scripts, 21,772 lines — the largest area in the repository, and the largest
files in it (`dialogue_tab.py` at 4,398 lines is the single biggest file in the
project). This first pass establishes the reachability picture across the whole
package. Substance analysis of the three giants continues.

---

## Structure

| File | Lines | File | Lines |
|---|---:|---|---:|
| `tabs/dialogue_tab.py` | 4398 | `tabs/earning_tab.py` | 590 |
| `builders/tab_feature_builders.py` | 3898 | `tabs/model_library_tab.py` | 506 |
| `widgets/dual_brain_control.py` | 3804 | `tabs/earning_insights.py` | 503 |
| `workers/provider_lifecycle_backend.py` | 1771 | `tabs/chat_tab.py` | 492 |
| `widgets/provider_config_widget.py` | 972 | `tabs/management_tab.py` | 380 |
| `workers/brain_launch_worker.py` | 744 | `tabs/analytics_tab.py` | 299 |
| `tabs/safety_tools_tab.py` | 623 | `panels/approval_panel.py` | 285 |
| | | `panels/registration_panel.py` | 271 |
| `widgets/brain_control_row.py` | 270 | `widgets/brain_roster_panel.py` | 244 |
| `widgets/brain_settings_row.py` | 237 | `tabs/payments_tab.py` | 240 |
| `tabs/collaboration_tab.py` | 183 | `builders/tab_lifecycle.py` | 138 |
| `builders/tab_workers.py` | 132 | `widgets/performance.py` | 121 |
| `panels/help_dialog.py` | 121 | `theme_ui_state.py` | 109 |
| `widgets/web_nav_bus.py` | 96 | `builders/refresh_coordinator.py` | 78 |
| `workers/db_query_worker.py` | 68 | `widgets/persona_naming.py` | 59 |
| `workers/provider_workers.py` | 57 | `builders/tab_builders.py` | 53 |
| `panels/dialogue_log.py` | 25 | 5 × `__init__.py` | 5 |

---

## Findings

| ID | Sev | Finding |
|---|---|---|
| Q-01 | info | **Zero dead modules across all 38 files** — the best-wired area in the repository, alongside `agents/safety/`. This took **seven** distinct import-form blind spots to establish, and the false readings were severe: an early pass flagged **12** files dead, including `tab_feature_builders.py` (3,898 lines) and `provider_lifecycle_backend.py` (1,771). The first error was subpackage paths (`gui.tabs.dialogue_tab` has `tabs.` between `gui.` and the module); the second, in the corrected pass, was `from gui import theme_ui_state` — a from-package import of a *module* rather than a name. `main.py:3447` uses exactly that form. Both readings were obviously wrong on inspection (`main.py` plainly builds the tabs), which is the only reason they were caught. |
| Q-02 | info | **`dialogue_tab.py`: 4 dead methods of 88.** `DialogueTab._clean_model_response` (`:565`), `_dialogue_model_blocked` (`:576`), `_log_dialogue_turn` (`:885`) and `DialogueWorker._safe_fallback_response` (`:3691`) — all small (9–28 lines), all with zero tests. **84 of 88 are live.** For the largest class in the repository that is a strong result, and it stands in direct contrast to `Workshop` (23 of 47 dead) and `EarningMemory` (15 of 74 dead). |
| Q-03 | info | **`dialogue_log.py` is wired; its would-be wrapper is not.** `panels/dialogue_log.py` (25 lines) exports `_append_dialogue_log` — a *"Module-level best-effort JSONL writer for per-turn dialogue records"*, appending one JSON line to `logs/dialogue_YYYYMMDD.log` with failures *"silently ignored so the dialogue tab never breaks"*. It **is** called, at three sites in `dialogue_tab.py` (`:36`, `:279`, `:910`). The dead `DialogueTab._log_dialogue_turn` is the method wrapper that those direct calls superseded. Recorded so the dead method is not mistaken for a logging gap — the logging works. |
| Q-04 | info | **Three files carry 12,100 of the area's 21,772 lines**, and `DialogueTab` is a single 3,304-line class with 79 methods (`dialogue_tab.py:233-3537`). `dual_brain_control.py` (3,804) and `tab_feature_builders.py` (3,898) have no docstring at all. A structural observation rather than a defect, but it is where D-01's inert crypto toggle (`tab_feature_builders.py:2464`) and H-01's demo-only quality gate both surface to the operator. |

---

## Architecture — verified

`main.py` reaches the entire GUI through **two** imports:

```python
main.py:207   from gui.builders.tab_builders import TabBuildersMixin
main.py:2992  from gui.widgets.brain_roster_panel import save_roster_from
```

`TabBuildersMixin` (`builders/tab_builders.py`, 53 lines) is the facade, and it
delegates to the large builder modules. That is why most `gui/` files show zero
*outside* consumers and are reached transitively — which is also why a
reachability scan keyed on direct imports misreads them, and why intra-package
reachability from the facade is what full production reachability looks like here.

`dialogue_tab.py`'s structure is coherent despite its size:

```
L   49  class _WorkerCancelled          (cancellation sentinel)
L   61  def   _decision_signature
L  192  def   _is_empty_model_response
L  201  def   _is_transport_error_text
L  224  def   _is_empty_response_text
L  233  class DialogueTab               -> ends L3537   (79 methods, 3304 lines)
L 3540 class DialogueWorker             -> ends L4398   (9 methods, 859 lines)
```

The four module-level helpers are response-validity predicates, which reads as
deliberate separation of the honesty checks from the tab class rather than
accumulation.

---

## Assessment

`gui/` is the healthiest package in the repository by reachability. Every file is
live, the largest class wires 84 of its 88 methods, and the package has a
single clean entry point through one 53-line mixin.

The Q-01 methodology note is the substantive output. A sweep of this area with a
conventional import-pattern grep would have reported **twelve** dead files
totalling roughly 12,000 lines and would have been wrong about the three largest
components of the operator-facing application. It was only caught because
`main.py` obviously builds the tabs, which is a contradiction visible without any
tooling. That is now the seventh import form this codebase has used to defeat a
reachability scan:

1. direct absolute import
2. dict-valued dispatch (`agents/core`)
3. return types used by attribute access (`agents/earning`)
4. relative import (`agents/earning`, `agents/providers`)
5. package-facade re-export (`agents/providers`)
6. `from pkg import module as alias` (`agents/runtime`)
7. subpackage paths and `from pkg import module` (`gui/`)

Every one of these produced a *candidate* that then required checking, and every
check caught it. None would survive as a verdict, and on an area of this size the
cost of not checking would have been severe.

Substance analysis of `dialogue_tab.py`, `tab_feature_builders.py` and
`dual_brain_control.py` — the 12,100 lines where D-01 and H-01 reach the
operator — is the next step, not yet done.