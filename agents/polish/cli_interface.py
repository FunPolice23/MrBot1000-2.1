"""agents/polish/cli_interface.py — Phase 6: CLI Interface.

Command-line interface for MrBot1000, wrapping the core
subsystems with typed commands.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mrbot.polish.cli")


class CLIInterface:
    """Command-line interface for MrBot1000.

    Provides typed subcommands for each subsystem. Usage:
        python -m agents.polish.cli_interface --help
    """

    def __init__(self, registry=None, heartbeat=None, identity=None, audit=None):
        self.registry = registry
        self.heartbeat = heartbeat
        self.identity = identity
        self.audit = audit
        self.parser = self._build_parser()

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="mrbot",
            description="MrBot1000 2.0 — Autonomous Earning Agent",
        )
        sub = parser.add_subparsers(dest="command")

        # Agent commands
        agents_p = sub.add_parser("agents", help="List/inspect registered agents")
        agents_p.add_argument("action", nargs="?", choices=["list", "status"], default="list")

        # Heartbeat commands
        hb_p = sub.add_parser("heartbeat", help="Heartbeat status and control")
        hb_p.add_argument("action", nargs="?", choices=["status", "start", "stop"], default="status")
        hb_p.add_argument("--interval", type=float, default=60.0)

        # Identity commands
        id_p = sub.add_parser("identity", help="On-chain identity management")
        id_p.add_argument("action", nargs="?", choices=["card", "register", "verify"], default="card")
        id_p.add_argument("--name", default="MrBot1000")
        id_p.add_argument("--chain", default="ethereum")

        # Logging commands
        log_p = sub.add_parser("log", help="Audit log inspection")
        log_p.add_argument("action", nargs="?", choices=["tail", "clear", "export"], default="tail")
        log_p.add_argument("--severity", choices=["debug", "info", "warning", "error", "critical"])
        log_p.add_argument("--limit", type=int, default=20)
        log_p.add_argument("--output", default="")

        # Self-improvement commands
        si_p = sub.add_parser("learn", help="Self-improvement engine")
        si_p.add_argument("action", nargs="?", choices=["report", "reset"], default="report")

        # Self-test
        sub.add_parser("self-test", help="Run a quick self-test")

        return parser

    def run(self, args: Optional[List[str]] = None) -> Dict[str, Any]:
        """Parse and execute CLI arguments. Returns result dict."""
        parsed = self.parser.parse_args(args)
        cmd = parsed.command or "help"

        if cmd == "agents":
            return self._cmd_agents(parsed)
        if cmd == "heartbeat":
            return self._cmd_heartbeat(parsed)
        if cmd == "identity":
            return self._cmd_identity(parsed)
        if cmd == "log":
            return self._cmd_log(parsed)
        if cmd == "learn":
            return self._cmd_learn(parsed)
        if cmd == "self-test":
            return self._cmd_self_test(parsed)
        self.parser.print_help()
        return {"command": "help"}

    def _cmd_agents(self, args) -> Dict[str, Any]:
        if not self.registry:
            return {"error": "No agent registry configured"}
        if args.action == "list":
            agents = self.registry.get_all_agents()
            return {
                "agents": [
                    {"name": a.name, "role": a.role, "status": a.status}
                    for a in agents
                ]
            }
        if args.action == "status":
            health = self.registry.check_health()
            return health
        return {"error": f"Unknown agents action: {args.action}"}

    def _cmd_heartbeat(self, args) -> Dict[str, Any]:
        if not self.heartbeat:
            return {"error": "No heartbeat system configured"}
        if args.action == "status":
            return {
                "interval": self.heartbeat.interval,
                "tier": self.heartbeat.survival_tier.value,
                "running": self.heartbeat.running,
            }
        return {"error": f"Unknown heartbeat action: {args.action}"}

    def _cmd_identity(self, args) -> Dict[str, Any]:
        if not self.identity:
            return {"error": "No on-chain identity configured"}
        if args.action == "card":
            card = self.identity.generate_agent_card(
                name=args.name, description="MrBot1000 agent", capabilities=["scan", "propose"]
            )
            return card.to_dict()
        if args.action == "verify":
            return self.identity.verify(chain=args.chain)
        return {"error": f"Unknown identity action: {args.action}"}

    def _cmd_log(self, args) -> Dict[str, Any]:
        if not self.audit:
            return {"error": "No audit logger configured"}
        if args.action == "tail":
            sev = getattr(args, "severity", None)
            sev_enum = Severity(sev) if sev else None
            entries = self.audit.get_entries(severity=sev_enum, limit=args.limit)
            return {"entries": entries}
        if args.action == "clear":
            self.audit.clear()
            return {"status": "cleared"}
        if args.action == "export":
            entries = self.audit.get_entries(limit=args.limit)
            output = args.output or "audit_export.json"
            with open(output, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
            return {"status": f"exported to {output}"}
        return {"error": f"Unknown log action: {args.action}"}

    def _cmd_learn(self, args) -> Dict[str, Any]:
        return {"error": "Self-improvement engine not wired"}

    def _cmd_self_test(self, args) -> Dict[str, Any]:
        results = {}
        for name, mod in [
            ("heartbeat", __import__("agents.autonomy.heartbeat", fromlist=["HeartbeatSystem"])),
            ("self_improvement", __import__("agents.autonomy.self_improvement", fromlist=["SelfImprovementEngine"])),
            ("agent_registry", __import__("agents.autonomy.agent_registry", fromlist=["AgentRegistry"])),
            ("onchain_identity", __import__("agents.autonomy.onchain_identity", fromlist=["OnChainIdentity"])),
            ("logging", __import__("agents.polish.comprehensive_logging", fromlist=["AuditLogger"])),
        ]:
            try:
                results[name] = "OK"
            except Exception as e:
                results[name] = f"FAIL: {e}"
        return results


# Re-export for CLI entry point
from agents.polish.comprehensive_logging import Severity, AuditEvent, AuditLogger  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    cli = CLIInterface()
    result = cli.run(argv)
    print(json.dumps(result, indent=2, default=str))
    return 0


__all__ = ["CLIInterface", "Severity", "AuditEvent", "AuditLogger", "main"]
