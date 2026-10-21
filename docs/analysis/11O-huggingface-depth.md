# 11O — `agents/providers/huggingface_models.py` depth pass (557 lines, 33 functions)

Depth-pass #41 of 83. **0 dead of 33 — no findings.** The module that downloads multi-GB GGUF
files from the internet, and the most thoroughly defended single function in the depth pass.

---

## Structure

```
L   23-30    ProviderInstallTarget   L   72-124  HuggingFaceModelService (5 methods)
L   52-68    GGUFArtifact (1 method) L  205-444  HuggingFaceModelService (15 methods)
L  127-556  12 module functions
```

Docstring: *"Hugging Face GGUF discovery and safe download helpers."*

Largest: `download_artifact` (95), `inspect` (70), `search` (27), `_summary_model` (27),
`provider_install_targets` (16), `_artifact_from_sibling` (15).

---

## Findings

**None.** All 33 are live. Two observations recorded below rather than as findings.

---

## `download_artifact` — twelve defences, in the right order

This function downloads a file that will be several gigabytes, from a URL derived from a
repo id, into a directory the operator chose. Each of the obvious failure modes is handled,
and the *order* is what makes it good rather than merely thorough.

**1. The destination cannot escape.** `:461`:
```python
target = destination / Path(artifact.name).name
```
`Path(...).name` discards every directory component, so `../../.ssh/authorized_keys` becomes
`authorized_keys` — written inside `destination` or not at all. **Path traversal is closed by
construction, not by a check**, which is `11B`'s *"a type is a guarantee; a validator is a
promise"* applied to a filesystem path.

**2. The URL is trusted-host-only, checked twice — before and after the redirect.**
`:459` validates `artifact.download_url` before the request; `:481` validates
`response.url` *inside* the response block. `_https_url:127-134`:

```python
host = (parsed.hostname or "").lower().rstrip(".")
trusted = host == "huggingface.co" or host.endswith(".huggingface.co") or host.endswith(".hf.co")
if parsed.scheme != "https" or not trusted:
    raise ValueError("Hugging Face requests must use a trusted HTTPS host")
```

Three details worth crediting: the `.hf.co` suffix is what permits HF's **signed CDN redirect
hosts** without allowing arbitrary domains; `parsed.hostname` is used rather than a substring
match on the URL, so `evil.com/?x=huggingface.co` cannot pass; and `.lower().rstrip(".")`
defeats both case tricks and the trailing-root-dot form (`huggingface.co.`).

**3. A resume cannot splice two different models together.** `:464-474`: the `.part` file's
companion `.json` records `{url, size, sha256}`, and if it does not match the artifact being
downloaded exactly, both files are deleted and the download restarts. Without this, an
interrupted 4 GB download of model A resumed as model B would produce a corrupt file with a
valid-looking name.

**4. Resume only proceeds if the server agrees.** `:479-486`: a `Range` header is sent, and if
`existing > 0` but the response is not `206`, the partial is discarded rather than appended to.
Appending a full response to an existing partial is the classic way to produce a file of the
right length and entirely wrong contents.

**5. Size is checked before, at entry, and during.** `:477-478` pre-flight against free disk;
`:489-492` against the response's declared total; `:510-514` on every chunk written, closing
the handle and cleaning up before raising. Three separate checks because a server can lie at
any of those points.

**6. Disk space is re-checked during the download.** `:516-519`, every 16 MiB:
```python
if completed - checked_space_at >= 16 * 1024 * 1024:
    if total and free_space(destination) < max(total - completed, 0):
        raise OSError("Free storage became insufficient during download")
```
A pre-flight check cannot catch a disk that fills because something *else* started writing.
This is the `11G` `_can_write` discipline applied to a transfer in flight — and given that
`11G`'s quota exists precisely because this machine's page cache is contended by a local GGUF
model, it is the right check to have.

**7. The hash is verified before publication.** `:534-542` streams SHA-256 over the completed
file and deletes both artefacts on mismatch. **And publication is atomic** (`:543`
`os.replace(partial, target)`) — so a consumer never observes a partially-written file under
the real name.

**8. The state file is removed only after success** (`:544`) — it is a resume record, not a
success marker, so a crash before `os.replace` leaves a resumable partial.

**9. Cancellation is checked twice per iteration** (`:501-506`), before the write and again
around the pause loop, so a cancel during a 1 MiB chunk wait is honoured promptly rather than
after the next chunk boundary.

**10. Progress reporting degrades rather than fails.** `:528-531` catches `TypeError` and
retries with the two-argument form — so a caller that wrote `progress(done, total)` instead of
`progress(done, total, speed)` still gets updates instead of an exception mid-download.

---

## Two observations, recorded rather than filed

**The hash is optional.** `:534` is `if artifact.sha256:` — when HuggingFace publishes no hash
for an artifact, the file is still published, unverified. The size checks bound how wrong it
can be, and the host allowlist bounds who could serve it, so the residual risk is a truncated
or corrupt file atomically appearing under its real name. Worth one line in the fix list
(*"verify what you can; say plainly when you could not"*) rather than a code change.

**The redirect check happens after the connection.** `:481` runs inside the `with requests.get(...)`
block, so the connection to the redirect target has already been made; `requests` follows
redirects internally unless `allow_redirects=False`. **The guard therefore prevents *trusting*
the response body from an untrusted host, not *contacting* it.** For a desktop app talking to a
fixed three-host allowlist, that is proportionate — and validating after the fact is the
standard mitigation when the HTTP client owns redirect following. Noted for completeness rather
than as a finding.

---

## Verified as sound

**`_parse_params:142-149` prefers the authoritative field over pattern matching** — it looks for
`number of parameters` / `parameter count` first and only falls back to a `(\d+\.?\d*)[bB]`
regex, and takes `max()` of the matches. The same hierarchy `11F`'s `OUTCOME_STATES` and `11N`'s
family profiles use: **explicit declaration beats inference, and inference takes the most
favourable reading rather than the first.**

**`_parse_context:152-155` matches two spellings** (`context length` and
`max_position_embeddings`) — because HF metadata and model cards use different vocabularies for
the same fact. `11D`'s `OUTCOME_STATES` instinct again: two names, one meaning, deliberately
both handled.

**Every parser returns `Optional`/`None` rather than a default.** `_parse_params`,
`_parse_context`, `_parse_quantization` (returns `"unknown"`), `_architecture` (returns
`"unknown"`), `_is_moe` (returns `Optional[bool]`). **Unknown is represented as unknown** — the
`11w` `_stated_usd` discipline (`0.0` means UNKNOWN, never a guess) applied to model metadata.

**`_is_moe` returns `Optional[bool]`, not `False`** — and that tri-state matters, because
`11D`'s device panel and `11N`'s profile table both treat MoE as a capability with a
configuration consequence (`--n-cpu-moe`). Collapsing "unknown" into "not MoE" would silently
select the wrong CPU-offload strategy.

**`_artifact_from_sibling` (15 lines) and `_summary_model` (27 lines)** are separate
transformations rather than one function returning everything, so the install-target listing
and the search summary can be produced independently.

**`provider_install_targets` (16 lines)** returns structured `ProviderInstallTarget` values
rather than shell strings — so `11x`'s `command_argv` parsing has typed input to work with,
and no caller has to escape anything.

**`free_space` is a module function, not a method** — so the disk check in `download_artifact` is
testable without constructing a service, and the same check could be reused by the workshop
quota's sibling in `11G`.

---

## Re-verification

**`11G` / `11v` consistent.** The `16 * 1024 * 1024` re-check at `:516` is the same discipline as
`workshop.py:_can_write`'s dual-limit check and `live_trading`'s fail-closed ordering. Three
independent money/resource surfaces, one habit.

**`11N` extended.** `model_profile.py` reads family from GGUF metadata; this module *produces*
that metadata. `_architecture:167-172` and `_is_moe:175` are the upstream sources for
`FAMILY_PROFILES`' family and MoE fields — and both propagate unknownness rather than guessing,
which is why the downstream table can trust them.

**`11x` consistent.** `provider_install_targets` returning typed objects is what lets
`11x`'s `_exec_*` paths avoid string-escaping entirely; the download helper is the upstream
half of that discipline.

**`11B` / `11I` unaffected.** Nothing here touches model configuration or adapters; this is
acquisition only.

---

## Assessment

Zero dead of thirty-three, and no findings — which for a module handling untrusted network
input and multi-gigabyte writes is the expected and welcome result.

**`download_artifact` is the best-defended single function in the depth pass**, and the reason
is structural rather than exhaustive. Three of its twelve defences make the failure
*unrepresentable* rather than merely checked: `Path(...).name` cannot traverse, the host
allowlist cannot be widened by a crafted URL string, and `os.replace` cannot expose a partial
file. The other nine are checks, and each one is placed where the corresponding claim can still
be false.

**The one thing worth carrying into the fix list is the optional hash** — not as a bug, but as
an instance of a pattern the codebase already reasons about elsewhere. When HF publishes no
`sha256`, the download completes and the file is published with no integrity claim made and no
indication to the operator that one was unavailable. `11R`'s AJ-02 restated demand — *"report
insufficient data rather than no problems found"* — applies here in miniature: an unverified
download is fine, an unverified download that *looks* verified is not. Since the file lands
in a models directory where it will be loaded without further checking, a one-line note at
publication time ("installed without checksum verification") would close it.

**At 41 of 83 files swept, the pattern across the depth pass is worth restating once more
before the remaining files.** Of the 41 modules examined, the ones with findings fall into
exactly three classes: **a missing last hop** (the recurring defect, ~20 instances), **the same
decision expressed N times with N answers** (`11v`'s parsers, `11N`'s regexes, `11L`'s catalog),
and **a correct mechanism carrying wrong content** (`AK-01`, `BB-01`, `BD-04`). Modules with
none of the three — like this one, like `11t`'s approval queue, like `11E`'s dual-brain control
— are not absent of care; they are simply where the care landed.
