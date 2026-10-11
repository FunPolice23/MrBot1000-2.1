"""
agents/help_catalog.py — Static feature-help catalog for MrBot1000 v2.1 (v2.1).

A dependency-light, read-only catalog of the app's major features/controls so
that a help panel, in-app search box, or automation can answer "what does this
do?" without importing the GUI. Every entry is grounded in the real code:

    - Main-window tabs built from ``tab_specs`` in main.py:
    Management, Providers & GPU, Safety & Tools, Chat, Dialogue,
        Browse Root, Payments, Earnings,
    Settings, Live Logs, DB Stats.
  - GUI builders in gui/tab_builders.py (create_* methods) and widgets in
    gui/ (dual_brain_control.py, dialogue_tab.py, collaboration_tab.py,
    safety_tools_tab.py, chat_tab.py, model_switcher.py,
    dual_brain_control.py).
  - Worker / orchestration modules in agents/ (personas.py, dual_brain_*
    coordinator/runtime, big_brain.py, small_brain.py, gguf_meta.py, etc.)

This module is IMPORTABLE STANDALONE: stdlib only, no Qt, no project deps,
no import of gui/ or any agents module at import time. Keep it that way.

Exposed API
-----------
  FEATURES          : list[dict] — each dict has keys:
                        "feature"     short human name (str)
                        "category"    tab/subsystem label (str)
                        "description" 1-3 sentence summary (str)
                        "example"     one concrete usage sentence (str)
  lookup(keyword)   : list[dict] case-insensitive substring match across
                      feature/category/description; all entries if keyword is
                      empty/falsy. Always returns a (possibly empty) list.
  catalog_text()    : str readable plain-text rendering of every entry.
"""

from __future__ import annotations

from typing import List

# ─────────────────────────────────────────────────────────────────────────────
# Static feature catalog — grounded in real code (see descriptions for the
# module / method / control each entry maps to).
# ─────────────────────────────────────────────────────────────────────────────

FEATURES: List[dict] = [
    # ── Management tab (create_management_tab, main.py dashboard) ───────────
    {
        "feature": "Management Control Center",
        "category": "Management",
        "description":
            "The startup dashboard and 13-tab app home (built eagerly at launch). "
            "Offers Agent Controls, Pipeline Controls, and Interface groups. "
            "Maps to create_management_tab() and the first entry of tab_specs in main.py.",
        "example": "Open Management on launch and press 'Run Earning Cycle' to start discovery.",
    },
    {
        "feature": "Pause / Resume Manager",
        "category": "Management",
        "description":
            "Toggles the autonomous agent manager loop on and off via _toggle_pause(). "
            "While paused, the manager's scheduled agent work and heartbeat are suspended.",
        "example": "Pause the manager before editing .env so no background job runs mid-edit.",
    },
    {
        "feature": "Run Earning Cycle",
        "category": "Management",
        "description":
            "Runs a full earning discovery -> evaluate -> execute cycle off the GUI thread "
            "(PipelineWorker) using the selected source and max-risk filter. Maps to "
            "_run_earning_cycle() / run_full_cycle().",
        "example": "Select source 'all' and press 'Run Earning Cycle' to scan for new opportunities.",
    },
    {
        "feature": "Force Self-Improvement",
        "category": "Management",
        "description":
            "Triggers force_safe_improve() to kick off a guarded self-improvement pass of the "
            "agent's own reasoning/skills rather than waiting for the scheduled cadence.",
        "example": "Press 'Force Self-Improvement' right after a model change to regenerate skill notes.",
    },
    {
        "feature": "Force Research Re-scan",
        "category": "Management",
        "description":
            "Runs force_research_rescan() to re-scan configured research/discovery sources now "
            "instead of waiting for the next scheduled discovery sweep.",
        "example": "Press 'Force Research Re-scan' after adding a new discovery source.",
    },

    # ── Providers & GPU tab (create_providers_gpu_tab + DualBrainControl) ────
    {
        "feature": "Unified Providers & GPU panel",
        "category": "Providers & GPU",
        "description":
            "A single DualBrainControl widget managing both llama.cpp brains, the canonical "
            "DualBrainRuntime, model dropdowns, per-brain llama.cpp settings, and start/stop "
            "of the llama-server endpoints. Replaces the old LlamaManager + DualBrainControl split.",
        "example": "Use the Providers & GPU tab to start both brains and verify endpoint/model state.",
    },
    {
        "feature": "VRAM-affinity warn-but-allow guard",
        "category": "Providers & GPU",
        "description":
            "Before starting a brain, _check_vram_affinity() queries the target GPU's free VRAM "
            "(via nvidia-smi) and estimates the model's VRAM need (gguf_meta.estimate_vram_gb). "
            "If the model clearly exceeds free VRAM it shows a warning asking you to confirm an "
            "overflow-to-SYSTEM-RAM spill is intended — it never routes across PCIe to the other "
            "GPU (cross-GPU spill is structurally disabled). You may click 'Start anyway'.",
        "example": "Loading a large .gguf onto the 6 GB 1660 Super prompts you before overflowing to RAM.",
    },
    {
        "feature": "Per-brain llama.cpp model dropdowns",
        "category": "Providers & GPU",
        "description":
            "Each brain (Big/Small) has a model combo populated from _discover_gguf_models() plus "
            "the running llama-server's model list. _restart_brain_with() swaps the model and "
            "restarts that brain's server without touching the other GPU.",
        "example": "Pick a different .gguf for the Small Brain dropdown and confirm to hot-swap it.",
    },
    {
        "feature": "Per-brain llama.cpp settings",
        "category": "Providers & GPU",
        "description":
            "Independent ctx-size, threads, GPU layers (split), batch, and KV-cache settings for "
            "each brain, written back to env (BIG_BRAIN_*/SMALL_BRAIN_*). Includes ctx size "
            "spins (range 2048-131072) and -1=auto GPU-layer spins. Maps to the sb_/bb_*_spin "
            "controls and _apply_llama_settings() in dual_brain_control.py.",
        "example": "Lower the Small Brain ctx-size and threads to fit a model on its 6 GB card.",
    },
    {
        "feature": "Big Brain / Small Brain start & stop",
        "category": "Providers & GPU",
        "description":
            "Start and force-stop handlers for each brain's llama-server on its own configured "
            "port. Stop acts on whatever is listening on the port even if the panel did not "
            "start it (leftover from a prior run), guarding against recursion.",
        "example": "Press Stop on the Small Brain to clear a stale llama-server before relaunching.",
    },
    {
        "feature": "GGUF metadata & VRAM estimation",
        "category": "Providers & GPU",
        "description":
            "Reads .gguf header metadata (agents/gguf_meta.py) to estimate weights + KV-cache "
            "VRAM for the current context. Used by the VRAM guard and by the model tooltips.",
        "example": "Hover a model to see its estimated VRAM footprint for your current ctx size.",
    },

    # ── Safety & Tools tab (safety_tools_tab.py) ────────────────────────────
    {
        "feature": "Safety & Tools tab",
        "category": "Safety & Tools",
        "description":
            "A surface for agent safety gates and helper tools (human gates, safety checks, "
            "utility tooling). Built by SafetyToolsTab in gui/safety_tools_tab.py via "
            "create_safety_tools_tab().",
        "example": "Open Safety & Tools to review and configure the safety gate settings.",
    },
    {
        "feature": "Human approval gates",
        "category": "Safety & Tools",
        "description":
            "Agents' human_gates.py gates that require explicit human confirmation before "
            "high-risk actions (money, contracts, submissions) execute, mirroring the "
            "Navigator persona's rule to never auto-execute high-risk work.",
        "example": "A high-payout Upwork submission pauses until you click Submit in the gate dialog.",
    },

    # ── Chat tab (create_chat_tab + chat_tab.py) ────────────────────────────
    {
        "feature": "Chat tab (human conversation)",
        "category": "Chat",
        "description":
            "Chat surface for conversing with the agent (chat_tab.py, chat_router). Sends your "
            "message to the configured chat model and streams the reply in a normal Q&A thread.",
        "example": "Type a question in the Chat tab and press Enter to get an answer.",
    },

    # ── Dialogue tab (create_dialogue_tab + dialogue_tab.py) ────────────────
    {
        "feature": "Dialogue tab (Big Brain <-> Small Brain)",
        "category": "Dialogue",
        "description":
            "A two-model conversation surface (dialogue_tab.py). One brain responds to the "
            "other's reply; inference runs in a background DialogueWorker so the GUI never "
            "freezes. Adapted to the Driver/Navigator persona framing.",
        "example": "Open Dialogue and let Driver and Navigator debate a goal before you act.",
    },
    {
        "feature": "Auto-step dialogue",
        "category": "Dialogue",
        "description":
            "auto_step() advances the dialogue one exchange at a time (default cap of 10 "
            "auto-steps). Runs sequentially so overlapping inference threads that once raced "
            "on shared history cannot stack. Button shows 'Stop' while running.",
        "example": "Press the Auto-Step button to watch the brains take turns, stopping at the cap.",
    },
    {
        "feature": "Live continuous dialogue",
        "category": "Dialogue",
        "description":
            "The 'Live' toggle (live()/stop_live()) runs a continuous Big Brain <-> Small Brain "
            "dialogue until you press Stop. Each response is generated off the GUI thread.",
        "example": "Press Live to let the two brains deliberate continuously while you monitor.",
    },
    {
        "feature": "Single-step dialogue",
        "category": "Dialogue",
        "description":
            "single_step() runs exactly one exchange from the current speaker and stops, so you "
            "can drive the conversation one turn at a time.",
        "example": "Click once to get a single reply from the active brain and inspect it.",
    },

    # ── Persona system (agents/personas.py) ─────────────────────────────────
    {
        "feature": "Persona system (Driver & Navigator)",
        "category": "Personas",
        "description":
            "Two named identities in agents/personas.py replacing the generic robot framing. "
            "Driver (ambitious strategist, bias-to-act) binds to the Big Brain; Navigator "
            "(cautious risk-checker) binds to the Small Brain. Each persona carries identity, "
            "strengths, guardrails, and pulls real memory/personality context, and builds a "
            "system prompt via Persona.build_system_prompt().",
        "example": "Driver proposes the plan and Navigator vetoes it before high-risk execution.",
    },
    {
        "feature": "Persona memory & personality hooks",
        "category": "Personas",
        "description":
            "Each Persona reads live traits from the shared PersonalityEngine and memory context "
            "from the KnowledgeContext/MemoryDatabase by its db key (big_brain/small_brain), so "
            "the identity is grounded in real stored history, not decoration.",
        "example": "The persona's prompt includes its recent memories when a new goal starts.",
    },
    {
        "feature": "persona_for_key / persona_for_brain_role resolution",
        "category": "Personas",
        "description":
            "Helpers map a brain role or string key ('driver'/'big_brain'/BIG, etc.) to the "
            "matching Persona so the Dialogue/coordinator prepend the right system prompt.",
        "example": "A coordinator maps BrainRole.BIG to the Driver persona before inference.",
    },

    # ── Dual-brain runtime / coordinator / management memory ────────────────
    {
        "feature": "Canonical DualBrainRuntime",
        "category": "Providers & GPU / Collaboration",
        "description":
            "DualBrainRuntime.from_env() is the single canonical runtime contract (endpoint, "
            "model, device) shared across the Providers & GPU panel and Dialogue, "
            "and the brain adapters, so every tab observes the same configuration.",
        "example": "Changing the model in Providers & GPU is reflected in the Collaboration run monitor.",
    },
    {
        "feature": "DualBrainCoordinator collaboration protocol",
        "category": "Dialogue / Management",
        "description":
            "agents/dual_brain_coordinator.py orchestrates a multi-stage Driver/Navigator "
            "collaboration with a run ledger and per-run status, logging messages via "
            "MessageLog to dual_brain_messages.db.",
        "example": "The coordinator logs each Driver->Navigator exchange as a stage of a run.",
    },
    {
        "feature": "Management memory and stream telemetry",
        "category": "Management",
        "description":
            "Management exposes the useful legacy memory databases and live stream health "
            "telemetry without requiring a separate tab. Chat and CEO memory can be refreshed "
            "or cleared explicitly.",
        "example": "Open Management to inspect memory status and stream health.",
    },

    # ── Payments / Earnings / wallet (create_payments_tab/earnings_tab) ─────
    {
        "feature": "Payments tab",
        "category": "Payments",
        "description":
            "Handles payout verification for opportunities. Verifies a payout with a wallet "
            "address or transaction reference; unverifiable payouts are logged as 'submitted' "
            "for the audit trail rather than silently marked verified.",
        "example": "Enter an opportunity id and a tx reference, then press Verify to check the payout.",
    },
    {
        "feature": "Earnings tab",
        "category": "Earnings",
        "description":
            "Dashboard of earnings/portfolio data (create_earnings_tab) over the earning "
            "database, surfacing opportunities, pipeline results, and outcome accounting.",
        "example": "Open Earnings to review the current opportunity portfolio and cycle results.",
    },
    {
        "feature": "Wallet & crypto management",
        "category": "Earnings",
        "description":
            "Wallet address handling and crypto helpers (agents/wallet_manager.py, "
            "wallet_crypto.py) for receiving/payout tracking on the earnings side.",
        "example": "Set your wallet address in the Earnings tab so payouts can be attributed.",
    },

    # ── Settings / Logs / DB stats / file browse ────────────────────────────
    {
        "feature": "Settings tab (per-provider roles)",
        "category": "Settings",
        "description":
            "create_settings_tab() lets you enable/disable each LLM provider per role "
            "('Both', 'Main only', 'Chat only', 'Disabled') plus assorted MRBOT_FX_* toggles. "
            "Seeded from environment variables on open.",
        "example": "Disable the Chat role of a provider while keeping it for the Main agent.",
    },
    {
        "feature": "Ollama/llama.cpp model dropdown refresh",
        "category": "Settings",
        "description":
            "The Ollama model dropdowns auto-refresh the first time Settings opens and via the "
            "Refresh button, querying llama-server for available models so you don't have to "
            "click Refresh manually.",
        "example": "Open Settings once and the dropdowns auto-populate from the running server.",
    },
    {
        "feature": "Live Logs tab",
        "category": "Live Logs",
        "description":
            "create_logs_tab() shows the running application log stream (agent, pipeline, LLM "
            "activity) as it happens, useful for watching background runs.",
        "example": "Watch the Live Logs tab while a Collaboration run executes.",
    },
    {
        "feature": "DB Stats tab",
        "category": "DB Stats",
        "description":
            "create_db_stats_tab() reports database statistics (row counts / sizes) across the "
            "agent, earning, and dual-brain stores for a health snapshot.",
        "example": "Open DB Stats to confirm the earning and message databases are growing normally.",
    },
    {
        "feature": "Browse Root / file browser tab",
        "category": "Browse Root",
        "description":
            "A file-browser surface (create_file_browser_tab) rooted at the project directory "
            "for inspecting files and outputs without leaving the app.",
        "example": "Browse Root to locate a saved proposal draft before it is submitted.",
    },

    # ── Help catalog itself ─────────────────────────────────────────────────
    {
        "feature": "Feature help catalog",
        "category": "Help",
        "description":
            "This static catalog (agents/help_catalog.py): a stdlib-only FEATURES list with "
            "feature/category/description/example for ~25+ real features, plus lookup() for "
            "keyword search and catalog_text() for a plain-text render. No Qt, no project deps.",
        "example": "Call help_catalog.lookup('vram') to list all VRAM-related features.",
    },

    # ── Advanced llama.cpp flags (v2.1.9) ───────────────────────────────────
    # One entry per control in Providers & GPU -> "Advanced llama.cpp Flags".
    # Every flag is OPTIONAL: leaving a control at its "(default)" / unset value
    # adds no flag, so llama-server keeps its own default.
    {
        "feature": "Advanced llama.cpp Flags panel",
        "category": "Providers & GPU",
        "description":
            "Per-brain group in Providers & GPU holding 23 optional llama-server flags "
            "(performance, MoE offload, samplers, reasoning, vision). Each control maps to "
            "exactly one flag. A control left at its '(default)' / unset value adds NO flag, "
            "so the launch command is unchanged until you opt in. Changes apply on the next "
            "brain restart (Stop then Start). Saved to .env as <BIG|SMALL>_BRAIN_*.",
        "example": "Open Providers & GPU, set 'MoE Layers on CPU' to 20 for the Big Brain, press Save Local Provider Settings, then restart the Big Brain.",
    },
    {
        "feature": "Flag: Flash Attention (--flash-attn)",
        "category": "Providers & GPU",
        "description":
            "Uses the fused attention kernel: faster generation and lower memory use on "
            "supported cards. 'auto' lets llama.cpp decide (its own default); 'on' forces it; "
            "'off' disables it. Usually a free win on modern GPUs.",
        "example": "Set Flash Attn to 'on' and restart the brain; if generation errors, switch back to 'auto'.",
    },
    {
        "feature": "Flag: Cache Reuse (--cache-reuse)",
        "category": "Providers & GPU",
        "description":
            "Minimum chunk size for reusing a KV prefix across requests via KV shifting. "
            "Big win in Dialogue, where every turn resends a long shared prefix. 0 = off. "
            "Note: llama.cpp ignores this when a vision model (mmproj) is loaded.",
        "example": "Set Cache Reuse to 256 to speed up long Dialogue sessions.",
    },
    {
        "feature": "Flag: Context Checkpoints (--ctx-checkpoints)",
        "category": "Providers & GPU",
        "description":
            "Maximum number of context checkpoints kept per slot. Lets llama.cpp rewind to a "
            "recent checkpoint instead of re-processing the whole prompt, which keeps long "
            "conversations coherent. Higher uses more memory.",
        "example": "Set Ctx Checkpoints to 8 for long multi-turn conversations.",
    },
    {
        "feature": "Flag: KV cache in system RAM (--no-kv-offload)",
        "category": "Providers & GPU",
        "description":
            "Checked = the KV cache stays in system RAM instead of VRAM, freeing GPU memory "
            "for model weights. Useful when a model only just fits. Unchecked adds no flag, so "
            "llama.cpp keeps KV offload enabled (its default).",
        "example": "If a model fails to load for lack of VRAM, tick 'Keep KV cache in system RAM'.",
    },
    {
        "feature": "Flag: MoE experts on CPU (--n-cpu-moe)",
        "category": "Providers & GPU",
        "description":
            "Keeps the Mixture-of-Experts weights of the FIRST N layers in system RAM. This is "
            "the main lever that fits a large MoE model (e.g. a 35B-A3B) onto a smaller card: "
            "expert weights are the bulk of a MoE model and are used sparsely. 0 = off.",
        "example": "On a 16GB card, try MoE Layers on CPU = 20, then raise or lower until the model loads and speed is acceptable.",
    },
    {
        "feature": "Flag: Dense FFN on CPU (--n-cpu-ffn)",
        "category": "Providers & GPU",
        "description":
            "Keeps the dense feed-forward weights of the FIRST N layers in system RAM. Applies "
            "to the non-expert (dense) part of the network, so it helps dense models as well as "
            "MoE. 0 = off.",
        "example": "Set Dense FFN on CPU = 10 to shave VRAM from a dense model.",
    },
    {
        "feature": "Flag: All MoE experts on CPU (--cpu-moe)",
        "category": "Providers & GPU",
        "description":
            "Puts EVERY MoE expert weight in system RAM. Smallest possible VRAM footprint and "
            "the slowest option, but it can run a model that would otherwise not fit at all.",
        "example": "Tick 'All MoE weights on CPU' as a last resort for a very large MoE model.",
    },
    {
        "feature": "Flag: Top-K sampling (--top-k)",
        "category": "Providers & GPU",
        "description":
            "Keeps only the K most likely tokens at each step. Lower = more focused and "
            "deterministic; higher = more varied. llama.cpp's own default is 40; unset adds no flag.",
        "example": "Set Top-K to 40 for balanced output, or 20 for more focused answers.",
    },
    {
        "feature": "Flag: Top-P sampling (--top-p)",
        "category": "Providers & GPU",
        "description":
            "Nucleus sampling: keeps the smallest set of tokens whose probabilities sum to P. "
            "0.9-0.95 is typical; 1.0 disables it. Unset adds no flag (llama.cpp default 0.95).",
        "example": "Set Top-P to 0.9 to trim unlikely tokens.",
    },
    {
        "feature": "Flag: Min-P sampling (--min-p)",
        "category": "Providers & GPU",
        "description":
            "Drops tokens whose probability is below a fraction of the most likely token. "
            "Adapts to how confident the model is, so it tends to give better quality than "
            "top-p alone. 0 = disabled; a common setting is 0.05.",
        "example": "Set Min-P to 0.05 for a good quality/creativity balance.",
    },
    {
        "feature": "Flag: Repeat Penalty (--repeat-penalty)",
        "category": "Providers & GPU",
        "description":
            "Penalises tokens that already appeared recently, discouraging repetition. "
            "1.0 = disabled (llama.cpp default). Too high makes text incoherent, so stay low.",
        "example": "Set Repeat Penalty to 1.1 if replies start repeating phrases.",
    },
    {
        "feature": "Flag: Presence Penalty (--presence-penalty)",
        "category": "Providers & GPU",
        "description":
            "Flat penalty applied once to any token that has already appeared, which pushes the "
            "model toward new topics. 0.0 = disabled.",
        "example": "Set Presence Penalty to 0.2 to encourage fresh wording.",
    },
    {
        "feature": "Flag: Frequency Penalty (--frequency-penalty)",
        "category": "Providers & GPU",
        "description":
            "Penalty that grows with how OFTEN a token has appeared, so it targets the most "
            "over-used words. 0.0 = disabled.",
        "example": "Set Frequency Penalty to 0.2 when one phrase keeps dominating.",
    },
    {
        "feature": "Flag: DRY sampler (--dry-multiplier and friends)",
        "category": "Providers & GPU",
        "description":
            "DRY (Don't Repeat Yourself) directly suppresses repeated SEQUENCES of tokens, not "
            "just single tokens — it is the sampler purpose-built to break loops. Multiplier "
            "0 = off. Sub-controls: DRY Base (llama.cpp default 1.75), DRY Allowed Len (how long "
            "a repeat may be before penalising, default 2) and DRY Penalty Last-N (how many "
            "tokens to look back over, default 64).",
        "example": "Set DRY Multiplier to 0.8 when the two brains start echoing each other.",
    },
    {
        "feature": "Flag: XTC sampler (--xtc-probability)",
        "category": "Providers & GPU",
        "description":
            "XTC (eXclude Top Choices) removes the most obvious 'boring' tokens with the given "
            "probability, which raises variety and can pull a conversation out of a rut. "
            "0 = off. XTC Threshold (default 0.1; 1.0 disables) controls how aggressively.",
        "example": "Set XTC Probability to 0.5 to make the personas less predictable.",
    },
    {
        "feature": "Flag: Reasoning Budget (--reasoning-budget)",
        "category": "Providers & GPU",
        "description":
            "Token budget for a thinking model's reasoning: -1 = unrestricted, 0 = end thinking "
            "immediately, N = cap it at N tokens. Capping it stops a thinking model from burning "
            "the whole context before answering.",
        "example": "Set Reasoning Budget to 1024 to keep a thinking model's deliberations short.",
    },
    {
        "feature": "Flag: Reasoning Format (--reasoning-format)",
        "category": "Providers & GPU",
        "description":
            "Controls how thought tags are parsed and returned: 'none' leaves thoughts inline in "
            "the message content, 'auto' extracts them, and the 'deepseek' variants match that "
            "family's tag layout.",
        "example": "Set Reasoning Format to 'auto' so thinking stays out of the visible reply.",
    },
    {
        "feature": "Flag: Vision projector / mmproj (--mmproj)",
        "category": "Providers & GPU",
        "description":
            "Path to a companion mmproj-*.gguf file that gives a text model the ability to see "
            "images. Leave EMPTY when the model has vision built into its own GGUF (many newer "
            "vision models do) or is text-only — an empty field adds no flag. The 'Auto' button "
            "looks for an mmproj-*.gguf beside the selected model and tells you if there is none.",
        "example": "Pick a gemma-4 model, press Auto to fill in mmproj-gemma-4-E4B-it-BF16.gguf, then restart.",
    },
    {
        "feature": "Flag: Projector on CPU (--no-mmproj-offload)",
        "category": "Providers & GPU",
        "description":
            "Checked = the vision projector stays in system RAM instead of VRAM, saving a little "
            "GPU memory when images are used. Unchecked adds no flag (llama.cpp default).",
        "example": "Tick 'Keep projector on CPU' if vision pushes the model over your VRAM budget.",
    },
]


def lookup(keyword: str = "") -> List[dict]:
    """Return catalog entries matching keyword (case-insensitive substring).

    Matches against feature name, category, and description. Empty / None /
    whitespace keyword returns the full catalog. Always returns a list.
    """
    kw = (keyword or "").strip().lower()
    if not kw:
        return list(FEATURES)
    hits = []
    for entry in FEATURES:
        haystack = " ".join([
            str(entry.get("feature", "")),
            str(entry.get("category", "")),
            str(entry.get("description", "")),
        ]).lower()
        if kw in haystack:
            hits.append(entry)
    return hits


def catalog_text() -> str:
    """Return a readable plain-text rendering of every catalog entry."""
    lines = ["MrBot1000 v2.1 — Feature Help Catalog", "=" * 42]
    for i, entry in enumerate(FEATURES, 1):
        lines.append("")
        lines.append(f"[{i}] {entry.get('feature')}   ({entry.get('category')})")
        lines.append(f"    {entry.get('description')}")
        example = entry.get("example")
        if example:
            lines.append(f"    Example: {example}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    print(catalog_text())
    print(f"\n--- {len(FEATURES)} features indexed ---")
