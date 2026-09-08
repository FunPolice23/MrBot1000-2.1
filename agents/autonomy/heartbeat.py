"""agents/autonomy/heartbeat.py — Phase 5: Heartbeat System (from Automaton).

Continuous operation heartbeat that monitors credit level, adjusts survival
tier, and runs tier-appropriate tasks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("mrbot.autonomy.heartbeat")


# ── Thresholds ──────────────────────────────────────────────────────────────

CRITICAL_THRESHOLD = 0.0   # credits at or below 0 → CRITICAL
WARNING_THRESHOLD  = 10.0  # credits below this → REDUCED
FULL_THRESHOLD     = 50.0  # credits above this → FULL


# ── Survival tiers ──────────────────────────────────────────────────────────

class SurvivalTier(Enum):
    FULL = "full"
    REDUCED = "reduced"
    LOW = "low"
    CRITICAL = "critical"


@dataclass
class CreditSnapshot:
    credits: float = 0.0
    tier: SurvivalTier = SurvivalTier.FULL
    checked_at: float = 0.0


@dataclass
class HeartbeatRecord:
    tick: int = 0
    tier: SurvivalTier = SurvivalTier.FULL
    credits: float = 0.0
    tasks_run: int = 0
    errors: int = 0
    duration_s: float = 0.0


class CreditMonitor:
    """Monitors available credits / balance and reports snapshots.

    Pluggable: supply a callable ``getter`` that returns a float, or rely on
    the default stub (returns 9999 so the system is FULL by default).
    """

    def __init__(self, getter: Optional[Callable[[], float]] = None):
        self._getter = getter or (lambda: 9999.0)
        self._history: List[CreditSnapshot] = []

    async def check(self) -> CreditSnapshot:
        try:
            val = float(self._getter())
        except Exception as e:
            logger.warning("CreditMonitor.check failed: %s — using 0", e)
            val = 0.0
        snap = CreditSnapshot(
            credits=val,
            tier=self._classify(val),
            checked_at=time.time(),
        )
        self._history.append(snap)
        return snap

    @staticmethod
    def _classify(credits: float) -> SurvivalTier:
        if credits <= 0:
            return SurvivalTier.CRITICAL
        if credits < CRITICAL_THRESHOLD:
            return SurvivalTier.LOW
        if credits < WARNING_THRESHOLD:
            return SurvivalTier.REDUCED
        return SurvivalTier.FULL

    @property
    def history(self) -> List[CreditSnapshot]:
        return list(self._history)


class HeartbeatSystem:
    """Continuous operation heartbeat.

    ``run()`` loops every ``interval`` seconds, checks credit, adjusts tier,
    and dispatches tier-appropriate tasks.  Set ``running`` to False from
    another coroutine to stop gracefully.
    """

    def __init__(
        self,
        interval: float = 300.0,
        credit_getter: Optional[Callable[[], float]] = None,
        on_tick: Optional[Callable[[HeartbeatRecord], Any]] = None,
    ):
        self.interval = interval
        self.credit_monitor = CreditMonitor(getter=credit_getter)
        self.survival_tier = SurvivalTier.FULL
        self.running = False
        self._tick = 0
        self._on_tick = on_tick
        self.history: List[HeartbeatRecord] = []

    async def run(self, max_ticks: Optional[int] = None) -> List[HeartbeatRecord]:
        """Main heartbeat loop.

        Args:
            max_ticks: Stop after this many iterations (None = forever).
        """
        self.running = True
        self._tick = 0
        logger.info("Heartbeat started (interval=%.0fs)", self.interval)

        while self.running:
            tick_start = time.time()
            self._tick += 1
            errors = 0
            tasks_run = 0

            try:
                snap = await self.credit_monitor.check()
                self.survival_tier = snap.tier
                tasks_run = await self._run_tier_tasks(snap)
            except Exception as e:
                logger.error("Heartbeat tick %d error: %s", self._tick, e)
                errors += 1

            duration = time.time() - tick_start
            record = HeartbeatRecord(
                tick=self._tick,
                tier=self.survival_tier,
                credits=self.credit_monitor.history[-1].credits
                if self.credit_monitor.history
                else 0.0,
                tasks_run=tasks_run,
                errors=errors,
                duration_s=duration,
            )
            self.history.append(record)
            if self._on_tick:
                try:
                    self._on_tick(record)
                except Exception:
                    pass

            if max_ticks and self._tick >= max_ticks:
                break

            await asyncio.sleep(self.interval)

        self.running = False
        logger.info("Heartbeat stopped after %d ticks", self._tick)
        return list(self.history)

    def stop(self) -> None:
        self.running = False

    async def _run_tier_tasks(self, snap: CreditSnapshot) -> int:
        """Run tasks appropriate for the current survival tier.

        Returns number of tasks executed.
        """
        if snap.tier == SurvivalTier.FULL:
            return await self._run_full_tasks()
        if snap.tier == SurvivalTier.REDUCED:
            return await self._run_reduced_tasks()
        if snap.tier == SurvivalTier.LOW:
            return await self._run_low_tasks()
        # CRITICAL: halt all operations, alert human
        logger.critical("CRITICAL tier — halting all tasks, alerting human")
        return 0

    async def _run_full_tasks(self) -> int:
        """All features active, full scanning."""
        logger.debug("FULL tier tasks")
        return 1

    async def _run_reduced_tasks(self) -> int:
        """Reduced scanning, cheaper models."""
        logger.debug("REDUCED tier tasks")
        return 1

    async def _run_low_tasks(self) -> int:
        """Minimal scanning, local only."""
        logger.debug("LOW tier tasks")
        return 1


__all__ = [
    "SurvivalTier",
    "CreditSnapshot",
    "HeartbeatRecord",
    "CreditMonitor",
    "HeartbeatSystem",
    "CRITICAL_THRESHOLD",
    "WARNING_THRESHOLD",
    "FULL_THRESHOLD",
]
