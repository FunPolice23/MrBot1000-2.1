"""
mrbot_cli — read-only CLI for inspecting a live or offline MrBot1000 runtime.

Usage examples:
    python -m agents.mrbot_cli providers           # brain servers + .env config
    python -m agents.mrbot_cli providers --json    # same, as JSON
    python -m agents.mrbot_cli models              # what llama-server reports on each port
    python -m agents.mrbot_cli dialogue            # current DialogueTab state (offline file read)
    python -m agents.mrbot_cli db-stats           # SQLite portfolio summary
    python -m agents.mrbot_cli health              # one-line pass/fail per subsystem

Secrets safety:
    Never prints full credential values. Endpoint URLs are public localhost
    addresses and may be printed. All .env reads are whitelisted by key prefix.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"

# Keys allowed to be read and printed by this CLI.
ENV_READ_ALLOWLIST = frozenset({
    "BIG_BRAIN_MODEL", "SMALL_BRAIN_MODEL",
    "BIG_BRAIN_URL", "SMALL_BRAIN_URL",
    "BIG_BRAIN_PORT", "SMALL_BRAIN_PORT",
    "BIG_BRAIN_DEVICE", "SMALL_BRAIN_DEVICE",
    "BIG_BRAIN_PROVIDER", "SMALL_BRAIN_PROVIDER",
    "ACTIVE_LOCAL_PROVIDER", "ACTIVE_CLOUD_PROVIDER",
    "BIG_BRAIN_CONTEXT", "SMALL_BRAIN_CONTEXT",
    "BIG_BRAIN_TEMPERATURE", "SMALL_BRAIN_TEMPERATURE",
    "BIG_BRAIN_MAX_TOKENS", "SMALL_BRAIN_MAX_TOKENS",
    "BIG_BRAIN_GPU_LAYERS", "SMALL_BRAIN_GPU_LAYERS",
    "BIG_BRAIN_THREADS", "SMALL_BRAIN_THREADS",
    "BIG_BRAIN_BATCH", "SMALL_BRAIN_BATCH",
    "BIG_BRAIN_KV_CACHE", "SMALL_BRAIN_KV_CACHE",
    "BIG_BRAIN_SPLIT_MODE", "SMALL_BRAIN_SPLIT_MODE",
    "BIG_BRAIN_ENABLED", "SMALL_BRAIN_ENABLED",
    "BIG_BRAIN_NAME", "SMALL_BRAIN_NAME",
})


# ── .env reading ──────────────────────────────────────────────────────────────

def read_env() -> Dict[str, str]:
    """Read whitelist-sanitized .env values. Secrets never leave this function."""
    values: Dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'").strip()
        if key in ENV_READ_ALLOWLIST:
            values[key] = val
    return values


def pretty_env(env: Dict[str, str]) -> str:
    lines: List[str] = ["[MrBot1000 .env — sanitized, secrets redacted]"]
    redacted = re.compile(r"key|token|secret|password|passwd|api_key|apikey|auth", re.I)
    # Print allowlisted pairs. Any value we didn't allow stays absent.
    for k in sorted(env):
        v = env[k]
        flag = ""
        if redacted.search(k):
            v = "[REDACTED]"
        lines.append(f"  {k:28} = {v}")
    return "\n".join(lines)


# ── llama-server probes ───────────────────────────────────────────────────────

def probe_models(port: int, timeout_s: float = 4.0) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """Return (is_running, model_id_or_empty, raw_entries)."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode())
            entries = data.get("data", [])
            primary = entries[0].get("id", "") if entries else ""
            return True, primary, entries
    except Exception as exc:
        return False, "", []


def device_from_env(env: Dict[str, str], which: str) -> str:
    key = f"{which}_BRAIN_DEVICE"
    val = env.get(key, "")
    return val if val else "0" if which == "BIG" else "1"


def gpu_mem_info() -> Dict[str, str]:
    """Best-effort GPU memory from nvidia-smi, per device index."""
    out: Dict[str, str] = {}
    try:
        proc = os.popen("nvidia-smi --query-gpu=index,memory.used --format=csv,noheader 2>/dev/null")
        raw = proc.read().strip()
        proc.close()
        for line in raw.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].endswith("MiB"):
                out[parts[0]] = parts[1]
    except Exception:
        pass
    return out


# ── providers subcommand ──────────────────────────────────────────────────────

def cmd_providers(args):
    env = read_env()
    big_port = int(env.get("BIG_BRAIN_PORT", "1234"))
    small_port = int(env.get("SMALL_BRAIN_PORT", "1235"))
    big_model_env = env.get("BIG_BRAIN_MODEL", "")
    small_model_env = env.get("SMALL_BRAIN_MODEL", "")

    big_running, big_id, big_entries = probe_models(big_port)
    small_running, small_id, small_entries = probe_models(small_port)
    gpu = gpu_mem_info()

    rows = []
    for label, port, env_model, running, server_id, device_key in [
        ("Big Brain (Edward)", big_port, big_model_env, big_running, big_id, "BIG"),
        ("Small Brain (Jacob)", small_port, small_model_env, small_running, small_id, "SMALL"),
    ]:
        device = env.get(f"{device_key}_BRAIN_DEVICE", "")
        gpu_mem = gpu.get(device, "n/a")
        if running:
            match = "MATCH" if env_model and env_model in server_id else "MISMATCH"
            rows.append(
                f"\n  {label}\n"
                f"    port        : {port}\n"
                f"    device      : CUDA{device}  (GPU mem: {gpu_mem})\n"
                f"    running     : YES\n"
                f"    env .model  : {env_model or '(empty)'}\n"
                f"    server id   : {server_id}\n"
                f"    match       : {match}"
            )
        else:
            rows.append(
                f"\n  {label}\n"
                f"    port        : {port}\n"
                f"    device      : CUDA{device}\n"
                f"    running     : NO  (nothing listening on this port)\n"
                f"    env .model  : {env_model or '(empty)'}\n"
            )

    lines = [
        f"\n{'='*60}",
        " MrBot1000 — Providers & GPU State",
        f"{'='*60}",
        "",
        pretty_env(env),
    ] + rows + [
        "",
        f"llama-server binary : D:\\\\llama.cpp\\\\llama-server.exe",
        f"mode               : dual-instance (two separate processes)",
        "",
    ]
    text = "\n".join(lines)

    if args.json:
        summary = {
            "big_brain": {
                "port": big_port,
                "device": env.get("BIG_BRAIN_DEVICE", ""),
                "env_model": big_model_env,
                "running": big_running,
                "server_model": big_id,
                "match": bool(big_running and big_model_env and big_model_env in big_id),
                "gpu_mem": gpu.get(env.get("BIG_BRAIN_DEVICE", ""), "n/a"),
            },
            "small_brain": {
                "port": small_port,
                "device": env.get("SMALL_BRAIN_DEVICE", ""),
                "env_model": small_model_env,
                "running": small_running,
                "server_model": small_id,
                "match": bool(small_running and small_model_env and small_model_env in small_id),
                "gpu_mem": gpu.get(env.get("SMALL_BRAIN_DEVICE", ""), "n/a"),
            },
            "env_sanitized": env,
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    print(text)


# ── models subcommand ─────────────────────────────────────────────────────────

def cmd_models(args):
    env = read_env()
    big_port = int(env.get("BIG_BRAIN_PORT", "1234"))
    small_port = int(env.get("SMALL_BRAIN_PORT", "1235"))

    big_run, big_id, big_entries = probe_models(big_port, timeout_s=args.timeout)
    small_run, small_id, small_entries = probe_models(small_port, timeout_s=args.timeout)

    lines = [f"\n{'='*60}", " llama-server /v1/models", f"{'='*60}", ""]

    for label, port, running, server_id, entries in [
        ("Big Brain (1234)", big_port, big_run, big_id, big_entries),
        ("Small Brain (1235)", small_port, small_run, small_id, small_entries),
    ]:
        lines.append(f"\n  {label}")
        if running:
            lines.append(f"    loaded model : {server_id}")
            lines.append(f"    total models : {len(entries)}")
            for e in entries:
                mid = e.get("id", "")
                lines.append(f"      - {mid}")
        else:
            lines.append("    running      : NO")

    if args.json:
        payload = {
            "big": {"running": big_run, "primary_id": big_id, "count": len(big_entries), "entries": big_entries},
            "small": {"running": small_run, "primary_id": small_id, "count": len(small_entries), "entries": small_entries},
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print("\n".join(lines))


# ── dialogue subcommand (offline snapshot, no GUI dependency) ────────────────

def cmd_dialogue(args):
    """Read the most recent DialogueTab state from the SQLite evidence store.

    This does NOT require the GUI to be running. If no DB is found, prints a
    clear message and exits 0 (not an error — just no data yet).
    """
    db_paths = [
        REPO_ROOT / "mrbot_state.db",
        REPO_ROOT / "mrbot.db",
        REPO_ROOT / "data" / "mrbot.db",
    ]
    db_path: Optional[Path] = None
    for candidate in db_paths:
        if candidate.exists():
            db_path = candidate
            break

    if db_path is None:
        print("\n  No local SQLite DB found at the usual locations.")
        print(f"  Checked: {', '.join(str(p) for p in db_paths)}")
        print("  Start the GUI or run a discovery cycle to produce a DB first.\n")
        return

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Try common schema shapes; fall back gracefully if a table is missing.
        def rows(sql: str):
            try:
                return cur.execute(sql).fetchall()
            except sqlite3.OperationalError as exc:
                return []

        opportunities = rows(
            "SELECT COUNT(*) AS c, COALESCE(SUM(expected_value), 0) AS v "
            "FROM opportunities WHERE status IS NOT 'rejected'"
        )
        opp_count = opp_count or 0
        opp_value = opp_value or 0.0
        try:
            opp_count = int(opp_count)
            opp_value = float(opp_value)
        except Exception:
            opp_count, opp_value = 0, 0.0

        last_opps = rows(
            "SELECT id, source, title, expected_value, status "
            "FROM opportunities ORDER BY created_at DESC LIMIT 5"
        )

        action_rows = rows(
            "SELECT action, COUNT(*) AS c FROM actions GROUP BY action ORDER BY c DESC LIMIT 8"
        )

        print(f"\n{'='*60}")
        print(" MrBot1000 — Dialogue / Opportunity Snapshot")
        print(f"{'='*60}")
        print(f"\n  DB        : {db_path}")
        print(f"  Opps      : {opp_count} open/seen")
        print(f"  Exp. value: {opp_value:.4f} (sum of expected_value)")

        if last_opps:
            print("\n  Recent opportunities:")
            for row in last_opps:
                src = (row["source"] or "?")[:16]
                status = (row["status"] or "?")[:12]
                val = f"{row['expected_value']:.4f}" if row["expected_value"] else "-"
                title = (row["title"] or "(untitled)")[:40]
                print(f"    [{src:16}] [{status:12}] {val:>8}  {title}")

        if action_rows:
            print("\n  Recent actions:")
            for row in action_rows:
                print(f"    {row['action']}  x{row['c']}")
        else:
            print("\n  No action rows found in schema.")

        conn.close()
    except Exception as exc:
        print(f"\n  Failed to read DB: {exc}\n")

    if args.json:
        # Re-run quickly as JSON for machine consumers.
        pass


# ── db-stats subcommand (mirrors the GUI DB Stats panel) ─────────────────────

def cmd_db_stats(args):
    db_paths = [
        REPO_ROOT / "mrbot_state.db",
        REPO_ROOT / "mrbot.db",
        REPO_ROOT / "data" / "mrbot.db",
    ]
    db_path: Optional[Path] = None
    for candidate in db_paths:
        if candidate.exists():
            db_path = candidate
            break

    if db_path is None:
        print("\n  No local SQLite DB found.\n")
        return

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        def one(sql: str, default: Any = None) -> Any:
            try:
                row = cur.execute(sql).fetchone()
                return row[0] if row else default
            except sqlite3.OperationalError:
                return default

        total_calls = one("SELECT COUNT(*) FROM chat_messages")
        total_tokens = one("SELECT COALESCE(SUM(tokens_used), 0) FROM chat_messages")
        errors = one("SELECT COUNT(*) FROM chat_messages WHERE error IS NOT NULL")
        successes = one("SELECT COUNT(*) FROM chat_messages WHERE error IS NULL AND content IS NOT NULL AND content != ''")
        pending = one("SELECT COUNT(*) FROM pending_tasks")
        completed = one("SELECT COUNT(*) FROM actions WHERE result IS NOT NULL")

        print(f"\n{'='*60}")
        print(" MrBot1000 — DB Stats")
        print(f"{'='*60}")
        print(f"\n  DB path      : {db_path}")
        print(f"  Chat msgs    : {total_calls}")
        print(f"  Tokens used  : {total_tokens}")
        print(f"  Errors       : {errors}")
        print(f"  Successes    : {successes}")
        print(f"  Pending tasks: {pending}")
        print(f"  Completed    : {completed}")
        print(f"  DB size      : {db_path.stat().st_size:,} bytes")
    except Exception as exc:
        print(f"\n  Failed to read DB: {exc}\n")


# ── logs subcommand (tail recent llama-server log files) ─────────────────────

def cmd_logs(args):
    import tempfile
    log_names = ["mrbot-big-llama-server.log", "mrbot-small-llama-server.log", "mrbot-dual-brain-crash.log"]
    tmp = Path(tempfile.gettempdir())
    found = {name: tmp / name for name in log_names if (tmp / name).exists()}
    if not found:
        print("\n  No recent llama-server logs in %TEMP%.\n")
        return

    tail = args.tail
    lines: List[str] = []
    for name, path in found.items():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            body = text.splitlines()[-tail:]
        except OSError:
            body = [f"<unreadable: {path}>"]
        lines.append(f"\n--- {name} ({path.parent.name}/{path.name}) ---")
        lines.extend(body)

    print("\n".join(lines))


# ── health subcommand (one-line summary) ──────────────────────────────────────

def cmd_health(args):
    env = read_env()
    big_run, big_id, _ = probe_models(int(env.get("BIG_BRAIN_PORT", "1234")), timeout_s=3.0)
    small_run, small_id, _ = probe_models(int(env.get("SMALL_BRAIN_PORT", "1235")), timeout_s=3.0)
    import sqlite3
    db_exists = any((REPO_ROOT / p).exists() for p in ["mrbot_state.db", "mrbot.db", "data/mrbot.db"])

    checks = [
        (".env", bool(env)),
        ("Big Brain", big_run),
        ("Small Brain", small_run),
        ("SQLite DB", db_exists),
    ]
    all_ok = all(ok for _, ok in checks)
    status = "OK" if all_ok else "DEGRADED"
    print(f"\n  MrBot1000 health: {status}")
    for name, ok in checks:
        mark = "✓" if ok else "✗"
        print(f"    {mark} {name}")
    print()


# ── CLI wiring ────────────────────────────────────────────────────────────────

SUBCOMMANDS: Dict[str, Dict[str, Any]] = {
    "providers": {
        "func": cmd_providers,
        "help": "Show configured brain endpoints, loaded models, and .env state (sanitized).",
        "args": lambda p: p.add_argument("--json", action="store_true",
                                         help="Output as JSON instead of a table."),
    },
    "models": {
        "func": cmd_models,
        "help": "Query each llama-server port for its loaded model and full model list.",
        "args": lambda p: [p.add_argument("--timeout", type=float, default=4.0,
                                          help="Seconds to wait per port probe (default 4)."),
                           p.add_argument("--json", action="store_true",
                                          help="Output as JSON.")][0],  # side effects only
    },
    "dialogue": {
        "func": cmd_dialogue,
        "help": "Read the latest Dialogue/opportunity snapshot from the local SQLite DB (no GUI needed).",
        "args": lambda p: None,
    },
    "db-stats": {
        "func": cmd_db_stats,
        "help": "Mirror the GUI DB Stats panel: msg counts, token totals, errors, pending/completed.",
        "args": lambda p: None,
    },
    "logs": {
        "func": cmd_logs,
        "help": "Tail the recent llama-server launch logs from %TEMP%.",
        "args": lambda p: p.add_argument("--tail", type=int, default=40,
                                         help="Lines to show per log file (default 40)."),
    },
    "health": {
        "func": cmd_health,
        "help": "One-line summary: .env, both servers, and SQLite DB presence.",
        "args": lambda p: None,
    },
}
SUBCOMMANDS["db"] = SUBCOMMANDS["db-stats"]  # alias


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mrbot-cli",
        description="Read-only CLI for inspecting a MrBot1000 runtime. "
                    "No secrets are printed; endpoint probes stay localhost-only.",
    )
    sub = parser.add_subparsers(dest="command")
    for name, spec in SUBCOMMANDS.items():
        p = sub.add_parser(name, help=spec["help"])
        if spec["args"] is not None:
            spec["args"](p)
        p.set_defaults(func=spec["func"])

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        args.func(args)
        return 0
    except Exception as exc:
        print(f"mrbot-cli: error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
