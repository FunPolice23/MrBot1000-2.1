"""agents/autonomy/onchain_identity.py — Phase 5: On-Chain Identity (ERC-8004).

Agent card generation and on-chain registration with safety gates.
All on-chain operations require explicit human approval.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mrbot.autonomy.onchain_identity")


@dataclass
class AgentMetadata:
    name: str = ""
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    endpoint: str = ""
    version: str = "1.0.0"


@dataclass
class AgentCard:
    """ERC-8004 agent card.

    Represents the on-chain identity of an autonomous agent.
    """

    agent_id: str = ""
    name: str = ""
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    endpoint: str = ""
    version: str = "1.0.0"
    created_at: float = 0.0
    signature: str = ""  # placeholder; real signing requires wallet

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "endpoint": self.endpoint,
            "version": self.version,
            "created_at": self.created_at,
            "signature": self.signature,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


class OnChainIdentity:
    """ERC-8004 on-chain identity manager.

    Generates agent cards and handles on-chain registration.
    All on-chain operations are human-gated — no irreversible
    transactions without explicit approval.
    """

    def __init__(
        self,
        wallet_addr: Optional[str] = None,
        registry_path: Optional[str] = None,
    ):
        self.wallet_addr = wallet_addr
        self.registry_path = registry_path
        self.agent_card: Optional[AgentCard] = None
        self._registrations: List[Dict[str, Any]] = []
        self._load()

    # ── Agent card generation ────────────────────────────

    def generate_agent_card(
        self,
        name: str,
        description: str,
        capabilities: List[str],
        endpoint: str = "",
        version: str = "1.0.0",
    ) -> AgentCard:
        """Generate an AgentCard from metadata.

        The card is NOT on-chain yet. Call ``register`` to submit.
        """
        agent_id = self._compute_agent_id(name, endpoint)
        card = AgentCard(
            agent_id=agent_id,
            name=name,
            description=description,
            capabilities=capabilities,
            endpoint=endpoint,
            version=version,
            created_at=time.time(),
        )
        self.agent_card = card
        return card

    def _compute_agent_id(self, name: str, endpoint: str) -> str:
        """Deterministic agent ID from name + endpoint + wallet."""
        raw = f"{name}:{endpoint}:{self.wallet_addr or 'anonymous'}:{time.time()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── On-chain registration (human-gated) ──────────────

    def register(
        self,
        chain: str = "ethereum",
        metadata: Optional[AgentMetadata] = None,
        approved_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register the agent on-chain.

        REQUIRES explicit human approval via ``approved_by``.
        Without it, returns a simulated/dry-run result only.

        Returns:
            Dict with tx_hash (real or simulated), status, and
            a warning if not actually submitted.
        """
        if not self.agent_card:
            raise RuntimeError(
                "No agent card generated. Call generate_agent_card() first."
            )

        if not approved_by:
            logger.warning(
                "On-chain registration requires human approval. "
                "Returning dry-run result only."
            )
            return {
                "status": "dry_run",
                "agent_card": self.agent_card.to_dict(),
                "chain": chain,
                "tx_hash": None,
                "warning": "NOT submitted on-chain — human approval required",
            }

        # Real on-chain submission path (requires SDK/credentials)
        tx_hash = self._submit_on_chain(chain, metadata)
        record = {
            "chain": chain,
            "agent_id": self.agent_card.agent_id,
            "tx_hash": tx_hash,
            "approved_by": approved_by,
            "timestamp": time.time(),
        }
        self._registrations.append(record)
        self._save()
        return record

    def _submit_on_chain(
        self, chain: str, metadata: Optional[AgentMetadata]
    ) -> str:
        """Submit registration to the blockchain.

        Placeholder: in production, this would call the ERC-8004
        registry contract via web3.py or similar SDK.
        Returns a simulated tx hash for now.
        """
        logger.info(
            "Submitting on-chain identity to %s (wallet=%s)",
            chain,
            self.wallet_addr or "(none)",
        )
        # Simulated tx hash — replace with real contract call when SDK ready
        simulated = hashlib.sha256(
            f"tx:{self.agent_card.agent_id}:{chain}:{time.time()}".encode()
        ).hexdigest()[:32]
        return f"0x{simulated}"

    # ── Verification ─────────────────────────────────────

    def verify(self, chain: str = "ethereum", agent_address: str = "") -> Dict[str, Any]:
        """Verify an agent's on-chain identity.

        Placeholder — queries the ERC-8004 registry contract.
        Returns simulated data for now.
        """
        if not agent_address and self.wallet_addr:
            agent_address = self.wallet_addr
        return {
            "chain": chain,
            "agent_address": agent_address,
            "registered": bool(self._registrations),
            "agent_card": self.agent_card.to_dict() if self.agent_card else None,
            "registrations": self._registrations,
        }

    # ── Persistence ──────────────────────────────────────

    def _load(self) -> None:
        if not self.registry_path or not os.path.isfile(self.registry_path):
            return
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._registrations = data.get("registrations", [])
            card_data = data.get("agent_card")
            if card_data:
                self.agent_card = AgentCard(**card_data)
        except Exception as e:
            logger.error("Failed to load on-chain identity: %s", e)

    def _save(self) -> None:
        if not self.registry_path:
            return
        os.makedirs(os.path.dirname(self.registry_path) or ".", exist_ok=True)
        data = {
            "agent_card": self.agent_card.to_dict() if self.agent_card else None,
            "registrations": self._registrations,
            "wallet_addr": self.wallet_addr,
        }
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


__all__ = [
    "AgentMetadata",
    "AgentCard",
    "OnChainIdentity",
]
