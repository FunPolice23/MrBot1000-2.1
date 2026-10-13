# Per-model recommended llama.cpp settings

MrBot1000 can suggest launch settings for the selected model. Recommendations
live in **`agents/providers/model_recommendations.py`** as a data table keyed by
model family, joined at runtime with capability detection.

## How it works

- `detect_model_family(path)` (from `agents/providers/model_profile.py`) maps the
  GGUF architecture / filename to a family (gemma, qwen3.6, glm, deepseek, …).
- `detect_mtp(path)` (from `agents/providers/model_capabilities.py`) confirms
  whether the model actually carries a Multi-Token-Prediction head.
- `recommend(path)` joins them and returns a dict: `context`, `gpu_layers`,
  `kv_cache`, `flash_attn`, `mtp` (only True when the family is MTP-typical AND
  the model has the head), `spec_draft_n_max`, plus a `notes` string and the
  detected `family`.

**Recommendations are defaults, never auto-applied.** The operator stays in
control; nothing changes a running brain without an explicit action.

## Current table (summary)

| Family | Context | GPU layers | KV | Flash | MTP | Notes |
|--------|---------|-----------|-----|-------|-----|-------|
| gemma (dense) | 8k | -1 (full) | f16 | auto | no | Full offload, modest context |
| gemma4 (MoE A4B/E) | 8k | -1 | q8_0 | on | no | q8_0 KV saves VRAM; experts may spill on 16 GB |
| qwen3 (dense) | 32k | -1 | q8_0 | on | no | Thinking model; not MTP in these quants |
| qwen3.6 (MoE A3B) | 32k | -1 | q8_0 | on | if head | Some 35B-A3B quants carry an MTP head |
| qwen3.8 (dense) | 32k | -1 | q8_0 | on | yes | MTP-capable |
| glm (MoE) | 32k | ~40 | q8_0 | on | no | Partial offload fits 16 GB; REAP-23B has no head |
| deepseek | 32k | -1 | q8_0 | on | if head | V3/R1 are MTP-native |
| nemotron | 32k | -1 | q8_0 | on | if head | 30B-A3B lines carry an MTP head |
| lfm (LFM2.5) | 32k | -1 | f16 | auto | no | Good CPU/RAM brain |
| phi (dense) | 16k | -1 | f16 | auto | no | Full offload |
| mistral (dense) | 32k | -1 | q8_0 | on | no | Full offload |
| *unknown* | 8k | -1 | f16 | auto | no | Safe generic fallback |

`gpu_layers` `-1` = auto/full offload, `0` = CPU, `N` = offload N layers.

## MoE vs dense guidance

- **Dense** models: full GPU offload (`gpu_layers=-1`), pick a KV type that fits
  your VRAM (f16 for headroom, q8_0 to stretch context).
- **MoE (A3B / A4B)**: active params are small, so full offload usually fits, but
  the *total* weights are large — on a 16 GB card use partial offload
  (`gpu_layers` ~40) and/or `q8_0` KV. Expert offload flags (`--n-cpu-moe`) are a
  future lever, not yet exposed.

## MTP (Multi-Token Prediction)

MTP predicts several tokens per forward pass for faster generation, but only on
models that carry an MTP head. The GUI greys the MTP toggle when the selected
model has no head (see `model_capabilities.detect_mtp`). When on, start with
`spec_draft_n_max = 3`.

## Extending the table

Add a family entry to `RECOMMENDATIONS` in
`agents/providers/model_recommendations.py`. Map any new GGUF architecture string
to a family in `ARCH_TO_FAMILY` (`agents/providers/model_profile.py`) so
detection picks it up. Keep values conservative and hardware-aware (single big
GPU + CPU/RAM pool). Add a test in `tests/providers/` asserting `recommend()`
returns sane values for the new family.
