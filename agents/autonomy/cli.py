"""agents/autonomy/cli.py — Phase 6: CLI interface for MrBot1000 2.0.

Minimal CLI built on argparse (stdlib) — no external deps.
Designed for Windows 11 25H2: runs as a console app alongside
the PySide6 GUI, or standalone for headless operation.

Commands:
    earning run          Run a full earning cycle (Paths 1-4)
    earning status       Show current earning state
    heartbeat start      Start the heartbeat system
    heartbeat status     Show current tier and credits
    agents list          List registered agents
    agents register      Register a new agent
    identity card        Generate an on-chain agent card
    identity verify      Verify on-chain identity
    self-improve status  Show learning state
    self-improve run     Run a self-improvement pass
    help                 Show this help
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mrbot.cli")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ── earning ──────────────────────────────────────────────────────────

def cmd_earning_run(sources: Optional[str], max_risk: str) -> int:
    """Run a full earning cycle."""
    from agents.earning_capability import EarningCapability

    src_list = None if sources == "all" else sources.split(",")
    cap = EarningCapability()
    print(f"[earning] Running cycle: sources={src_list or 'all'}, max_risk={max_risk}")
    result = cap.run_full_cycle(sources=src_list, max_risk=max_risk)
    print(f"[earning] Cycle complete: {result.get('message', 'done')}")
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_earning_status() -> int:
    """Show current earning state."""
    from agents.earning_capability import EarningCapability
    cap = EarningCapability()
    state = cap.get_state()
    print("[earning] Current state:")
    print(json.dumps(state, indent=2, default=str))
    return 0


# ── heartbeat ────────────────────────────────────────────────────────

def cmd_heartbeat_start(interval: float, credit_getter: str) -> int:
    """Start the heartbeat system."""
    from agents.autonomy.heartbeat import HeartbeatSystem

    getter = _resolve_credit_getter(credit_getter)
    hb = HeartbeatSystem(interval=interval, credit_getter=getter)
    print(f"[heartbeat] Starting (interval={interval}s, credits={getter()})")

    async def run():
        await hb.run(max_ticks=10)  # limited for CLI

    asyncio.run(run())
    hb.stop()
    print("[heartbeat] Stopped (10 ticks max)")
    return 0


def cmd_heartbeat_status(credit_getter: str) -> int:
    """Show current tier and credits."""
    from agents.autonomy.heartbeat import CreditMonitor, SurvivalTier

    getter = _resolve_credit_getter(credit_getter)
    cm = CreditMonitor(getter=getter)

    async def check():
        return await cm.check()

    snap = asyncio.run(check())
    print(f"[heartbeat] Credits: {snap.credits:.2f}")
    print(f"[heartbeat] Tier: {snap.tier.value}")
    return 0


def _resolve_credit_getter(spec: str):
    """Resolve a credit getter from a spec string.

    Format: "fixed:<amount>" or "env:<VAR>" or "mock"
    """
    if spec.startswith("fixed:"):
        val = float(spec.split(":", 1)[1])
        return lambda: val
    if spec.startswith("env:"):
        var = spec.split(":", 1)[1]
        return lambda: float(os.environ.get(var, "0"))
    return lambda: 999.0  # default mock


# ── agents ───────────────────────────────────────────────────────────

def cmd_agents_list() -> int:
    """List registered agents."""
    from agents.autonomy.agent_registry import AgentRegistry

    reg = AgentRegistry()
    agents = reg.get_all_agents()
    if not agents:
        print("[agents] No agents registered")
        return 0
    print(f"[agents] {len(agents)} registered:")
    for a in agents:
        print(f"  {a.name} ({a.role}) — {a.status} — {a.tasks_completed} done")
    return 0


def cmd_agents_register(name: str, role: str, capabilities: str) -> int:
    """Register a new agent."""
    from agents.autonomy.agent_registry import AgentRegistry, CapabilitySpec, CapabilityCategory

    reg = AgentRegistry()
    cap_list = []
    for cap_name in capabilities.split(","):
        cap_list.append(CapabilitySpec(
            category=CapabilityCategory.SCANNING,
            name=cap_name.strip(),
        ))
    agent = reg.register(name=name, role=role, capabilities=cap_list)
    print(f"[agents] Registered: {agent.name} ({agent.agent_id})")
    return 0


# ── identity ─────────────────────────────────────────────────────────

def cmd_identity_card(name: str, description: str, capabilities: str, endpoint: str) -> int:
    """Generate an on-chain agent card."""
    from agents.autonomy.onchain_identity import OnChainIdentity

    id_ = OnChainIdentity()
    card = id_.generate_agent_card(
        name=name,
        description=description,
        capabilities=capabilities.split(","),
        endpoint=endpoint,
    )
    print(f"[identity] Agent card generated:")
    print(json.dumps(card.to_dict(), indent=2))
    return 0


def cmd_identity_verify() -> int:
    """Verify on-chain identity."""
    from agents.autonomy.onchain_identity import OnChainIdentity

    id_ = OnChainIdentity()
    result = id_.verify()
    print(f"[identity] Verification:")
    print(json.dumps(result, indent=2))
    return 0


# ── self-improvement ─────────────────────────────────────────────────

def cmd_self_improve_status() -> int:
    """Show learning state."""
    from agents.autonomy.self_improvement import SelfImprovementEngine

    engine = SelfImprovementEngine()
    rec = engine.get_recommendation()
    print("[self-improve] State:")
    print(f"  Total outcomes: {engine.state.total_outcomes}")
    print(f"  Overall success rate: {engine.state.overall_success_rate:.1%}")
    print(f"  Net ROI: {engine.state.net_roi:.2%}")
    print(f"  Preferred strategies: {[s['strategy'] for s in rec.get('preferred_strategies', [])]}")
    return 0


def cmd_self_improve_run() -> int:
    """Run a self-improvement pass."""
    from agents.autonomy.self_improvement import SelfImprovementEngine, OutcomeRecord, Outcome

    engine = SelfImprovementEngine()
    # Simulate a few outcomes for the pass
    engine.record_outcome(OutcomeRecord(
        opportunity_id="cli-1", strategy="freelance_bidding", platform="upwork",
        outcome=Outcome.SUCCESS.value, revenue=100.0, cost=5.0,
        tags=["data"], timestamp=datetime.now().timestamp(),
    ))
    rec = engine.get_recommendation()
    print("[self-improve] Pass complete:")
    print(f"  Outcomes: {engine.state.total_outcomes}")
    print(f"  Success rate: {engine.state.overall_success_rate:.1%}")
    return 0


# ── main ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrbot",
        description="MrBot1000 2.0 CLI — autonomous earning agent control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mrbot earning run --sources all --max-risk low
  mrbot heartbeat start --interval 60 --credit-getter fixed:500
  mrbot agents list
  mrbot identity card --name "MrBot1000" --description "Autonomous agent"
  mrbot self-improve status
        """,
    )
    sub = parser.add_subparsers(dest="command")

    # earning
    earn = sub.add_parser("earning", help="Earning cycle controls")
    earn_sub = earn.add_subparsers(dest="sub")
    earn_run = earn_sub.add_parser("run", help="Run a full earning cycle")
    earn_run.add_argument("--sources", default="all", help="Comma-separated sources or 'all'")
    earn_run.add_argument("--max-risk", default="low", help="Max risk level")
    earn_status = earn_sub.add_parser("status", help="Show earning state")

    # heartbeat
    hb = sub.add_parser("heartbeat", help="Heartbeat system controls")
    hb_sub = hb.add_subparsers(dest="sub")
    hb_start = hb_sub.add_parser("start", help="Start heartbeat")
    hb_start.add_argument("--interval", type=float, default=60.0, help="Tick interval in seconds")
    hb_start.add_argument("--credit-getter", default="mock", help="Credit source: fixed:N, env:VAR, mock")
    hb_status = hb_sub.add_parser("status", help="Show heartbeat status")
    hb_status.add_argument("--credit-getter", default="mock", help="Credit source")

    # agents
    agents = sub.add_parser("agents", help="Agent registry controls")
    agents_sub = agents.add_subparsers(dest="sub")
    agents_list = agents_sub.add_parser("list", help="List registered agents")
    agents_reg = agents_sub.add_parser("register", help="Register a new agent")
    agents_reg.add_argument("--name", required=True, help="Agent name")
    agents_reg.add_argument("--role", required=True, help="Agent role")
    agents_reg.add_argument("--capabilities", default="scanning", help="Comma-separated capabilities")

    # identity
    id_ = sub.add_parser("identity", help="On-chain identity controls")
    id_sub = id_.add_subparsers(dest="sub")
    id_card = id_sub.add_parser("card", help="Generate agent card")
    id_card.add_argument("--name", required=True, help="Agent name")
    id_card.add_argument("--description", default="", help="Agent description")
    id_card.add_argument("--capabilities", default="scanning", help="Comma-separated capabilities")
    id_card.add_argument("--endpoint", default="", help="Agent endpoint")
    id_verify = id_sub.add_parser("verify", help="Verify on-chain identity")

    # self-improve
    si = sub.add_parser("self-improve", help="Self-improvement engine controls")
    si_sub = si.add_subparsers(dest="sub")
    si_status = si_sub.add_parser("status", help="Show learning state")
    si_run = si_sub.add_parser("run", help="Run a self-improvement pass")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "earning":
        if args.sub == "run":
            return cmd_earning_run(sources=args.sources, max_risk=args.max_risk)
        if args.sub == "status":
            return cmd_earning_status()
        parser.print_help()
        return 1

    if args.command == "heartbeat":
        if args.sub == "start":
            return cmd_heartbeat_start(interval=args.interval, credit_getter=args.credit_getter)
        if args.sub == "status":
            return cmd_heartbeat_status(credit_getter=args.credit_getter)
        parser.print_help()
        return 1

    if args.command == "agents":
        if args.sub == "list":
            return cmd_agents_list()
        if args.sub == "register":
            return cmd_agents_register(name=args.name, role=args.role, capabilities=args.capabilities)
        parser.print_help()
        return 1

    if args.command == "identity":
        if args.sub == "card":
            return cmd_identity_card(name=args.name, description=args.description, capabilities=args.capabilities, endpoint=args.endpoint)
        if args.sub == "verify":
            return cmd_identity_verify()
        parser.print_help()
        return 1

    if args.command == "self-improve":
        if args.sub == "status":
            return cmd_self_improve_status()
        if args.sub == "run":
            return cmd_self_improve_run()
        parser.print_help()
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
