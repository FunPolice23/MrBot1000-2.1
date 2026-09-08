"""agents/cli_interface.py — Phase 6: CLI interface for MrBot1000 2.0.

Provides a Click-based CLI that mirrors the PySide6 GUI functionality,
allowing headless operation and scriptable automation.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import click

logger = logging.getLogger("mrbot.cli")


# ── State file ────────────────────────────────────────────────────

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cli_state.json")


@dataclass
class CLIState:
    """Persisted CLI state."""

    last_command: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)


def load_state(path: str = STATE_FILE) -> CLIState:
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CLIState(**data)
        except Exception:
            pass
    return CLIState()


def save_state(state: CLIState, path: str = STATE_FILE) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state.__dict__, f, indent=2)


# ── CLI Commands ──────────────────────────────────────────────────

@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.pass_context
def cli(ctx, verbose: bool):
    """MrBot1000 2.0 — Dual-Brain Autonomous Earning Agent.

    CLI interface for headless operation and scriptable automation.
    Mirrors the PySide6 GUI functionality.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    ctx.ensure_object(dict)
    ctx.obj["state"] = load_state()


@cli.command()
@click.pass_context
def status(ctx):
    """Show current system status."""
    state = ctx.obj["state"]
    click.echo("=== MrBot1000 2.0 Status ===")
    click.echo(f"Last command: {state.last_command or 'none'}")
    click.echo(f"Context keys: {list(state.context.keys())}")
    click.echo(f"History entries: {len(state.history)}")


@cli.command()
@click.option("--strategy", "-s", default="freelance_bidding", help="Strategy to use.")
@click.option("--platform", "-p", default="upwork", help="Platform to scan.")
@click.option("--query", "-q", default="", help="Search query.")
@click.pass_context
def scan(ctx, strategy: str, platform: str, query: str):
    """Scan for opportunities."""
    state = ctx.obj["state"]
    result = {
        "command": "scan",
        "strategy": strategy,
        "platform": platform,
        "query": query,
        "status": "executed",
    }
    state.last_command = "scan"
    state.context.update(result)
    state.history.append(result)
    save_state(state)
    click.echo(f"Scanned {platform} for '{query or 'all'}' using {strategy}")
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--id", "-i", required=True, help="Opportunity ID to evaluate.")
@click.option("--strategy", "-s", default="", help="Strategy to apply.")
@click.pass_context
def evaluate(ctx, id: str, strategy: str):
    """Evaluate an opportunity."""
    state = ctx.obj["state"]
    result = {
        "command": "evaluate",
        "opportunity_id": id,
        "strategy": strategy or "auto",
        "status": "pending_review",
    }
    state.last_command = "evaluate"
    state.context.update(result)
    state.history.append(result)
    save_state(state)
    click.echo(f"Evaluating opportunity {id} with strategy {result['strategy']}")
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--id", "-i", required=True, help="Opportunity ID to execute.")
@click.option("--dry-run", "-d", is_flag=True, default=False, help="Dry run without executing.")
@click.pass_context
def execute(ctx, id: str, dry_run: bool):
    """Execute an opportunity (human-gated)."""
    state = ctx.obj["state"]
    if dry_run:
        click.echo(f"[DRY-RUN] Would execute opportunity {id}")
    else:
        click.echo(f"Executing opportunity {id} — requires human approval gate")
    result = {
        "command": "execute",
        "opportunity_id": id,
        "dry_run": dry_run,
        "status": "pending_approval" if not dry_run else "dry_run",
    }
    state.last_command = "execute"
    state.context.update(result)
    state.history.append(result)
    save_state(state)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.pass_context
def wallet(ctx):
    """Show wallet status."""
    state = ctx.obj["state"]
    click.echo("=== Wallet Status ===")
    click.echo("SOL: not connected (simulated)")
    click.echo("ETH: not connected (simulated)")
    click.echo("USDC: not connected (simulated)")
    click.echo("Note: Set WALLET_PRIVATE_KEY env var for real operations.")


@cli.command()
@click.option("--chain", "-c", default="ethereum", help="Blockchain to register on.")
@click.option("--name", "-n", default="MrBot1000", help="Agent name.")
@click.option("--approved", "-a", is_flag=True, default=False, help="Explicit human approval.")
@click.pass_context
def register(ctx, chain: str, name: str, approved: bool):
    """Register on-chain identity (ERC-8004)."""
    from agents.autonomy.onchain_identity import OnChainIdentity

    identity = OnChainIdentity(wallet_addr="0xCLIDefault")
    card = identity.generate_agent_card(
        name=name,
        description="CLI-registered autonomous agent",
        capabilities=["scanning", "analysis", "proposal"],
    )
    result = identity.register(chain=chain, approved_by="human" if approved else None)
    click.echo(f"Agent card: {card.agent_id}")
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.pass_context
def history(ctx):
    """Show command history."""
    state = ctx.obj["state"]
    if not state.history:
        click.echo("No history yet.")
        return
    for i, entry in enumerate(state.history[-20:], 1):
        click.echo(f"{i}. {entry.get('command', '?')} — {entry.get('status', '?')}")


@cli.command()
@click.pass_context
def clear(ctx):
    """Clear CLI state and history."""
    state = ctx.obj["state"]
    state.last_command = ""
    state.context = {}
    state.history = []
    save_state(state)
    click.echo("CLI state cleared.")


# ── Entry Point ───────────────────────────────────────────────────

def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
