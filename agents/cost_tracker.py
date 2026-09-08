"""
agents/cost_tracker.py — Comprehensive cost tracking and spend caps (v2.1 Phase 1).

Tracks LLM spending across all providers with:
- Daily/weekly/monthly spend caps
- Per-model cost tracking
- Spend forecasting
- Budget alerts
- Automatic provider switching when caps are hit
"""

import time
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta


# ── Cost Configuration ────────────────────────────────────────────────────

@dataclass
class CostConfig:
    """Cost tracking configuration."""
    daily_cap_usd: float = 10.0
    weekly_cap_usd: float = 50.0
    monthly_cap_usd: float = 150.0
    alert_threshold_pct: float = 0.80  # Alert at 80% of cap
    auto_switch_to_local: bool = True  # Switch to local when cap hit
    track_per_model: bool = True
    track_per_platform: bool = True
    state_path: str = ""
    
    @classmethod
    def load(cls, path: str = "") -> "CostConfig":
        """Load config from file."""
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            return cls(**data)
        return cls()
    
    def save(self, path: str = ""):
        """Save config to file."""
        path = path or self.state_path
        if path:
            with open(path, "w") as f:
                json.dump(self.__dict__, f, indent=2)


# ── Spend Record ──────────────────────────────────────────────────────────

@dataclass
class SpendRecord:
    """Single spend record."""
    timestamp: float
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    platform: str = ""  # Which platform triggered the call
    purpose: str = ""  # What the call was for
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "platform": self.platform,
            "purpose": self.purpose,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SpendRecord":
        return cls(**data)


# ── Cost Tracker ──────────────────────────────────────────────────────────

class CostTracker:
    """Track and limit LLM spending."""
    
    def __init__(self, config: CostConfig = None):
        self.config = config or CostConfig()
        self._records: List[SpendRecord] = []
        self._alerts: List[dict] = []
        
        # Load persisted state
        if self.config.state_path and os.path.exists(self.config.state_path):
            self._load_state()
    
    def _load_state(self):
        """Load spend records from disk."""
        try:
            with open(self.config.state_path) as f:
                data = json.load(f)
                self._records = [SpendRecord.from_dict(r) for r in data.get("records", [])]
                self._alerts = data.get("alerts", [])
        except Exception:
            pass
    
    def _save_state(self):
        """Persist spend records to disk."""
        if self.config.state_path:
            try:
                data = {
                    "records": [r.to_dict() for r in self._records],
                    "alerts": self._alerts,
                    "saved_at": time.time(),
                }
                with open(self.config.state_path, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
    
    def record_spend(self, model: str, provider: str, prompt_tokens: int,
                     completion_tokens: int, cost_usd: float, platform: str = "",
                     purpose: str = ""):
        """Record a spend event."""
        record = SpendRecord(
            timestamp=time.time(),
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            platform=platform,
            purpose=purpose,
        )
        self._records.append(record)
        self._save_state()
        
        # Check for alerts
        self._check_alerts()
    
    def get_spend(self, days: int = 1) -> float:
        """Get total spend in the last N days."""
        cutoff = time.time() - (days * 86400)
        return sum(r.cost_usd for r in self._records if r.timestamp >= cutoff)
    
    def get_spend_by_model(self, days: int = 1) -> Dict[str, float]:
        """Get spend breakdown by model."""
        cutoff = time.time() - (days * 86400)
        by_model: Dict[str, float] = {}
        for r in self._records:
            if r.timestamp >= cutoff:
                by_model[r.model] = by_model.get(r.model, 0) + r.cost_usd
        return by_model
    
    def get_spend_by_provider(self, days: int = 1) -> Dict[str, float]:
        """Get spend breakdown by provider."""
        cutoff = time.time() - (days * 86400)
        by_provider: Dict[str, float] = {}
        for r in self._records:
            if r.timestamp >= cutoff:
                by_provider[r.provider] = by_provider.get(r.provider, 0) + r.cost_usd
        return by_provider
    
    def get_spend_by_platform(self, days: int = 1) -> Dict[str, float]:
        """Get spend breakdown by platform."""
        cutoff = time.time() - (days * 86400)
        by_platform: Dict[str, float] = {}
        for r in self._records:
            if r.timestamp >= cutoff and r.platform:
                by_platform[r.platform] = by_platform.get(r.platform, 0) + r.cost_usd
        return by_platform
    
    def check_cap(self, period: str = "daily") -> Tuple[bool, float, float]:
        """
        Check if a spend cap is exceeded.
        
        Returns: (exceeded, current_spend, cap_amount)
        """
        if period == "daily":
            spend = self.get_spend(days=1)
            cap = self.config.daily_cap_usd
        elif period == "weekly":
            spend = self.get_spend(days=7)
            cap = self.config.weekly_cap_usd
        elif period == "monthly":
            spend = self.get_spend(days=30)
            cap = self.config.monthly_cap_usd
        else:
            return False, 0.0, 0.0
        
        return spend >= cap, spend, cap
    
    def get_remaining_budget(self, period: str = "daily") -> float:
        """Get remaining budget for a period."""
        _, spend, cap = self.check_cap(period)
        return max(0, cap - spend)
    
    def should_allow_call(self, estimated_cost: float, period: str = "daily") -> bool:
        """Check if a call should be allowed based on budget."""
        _, spend, cap = self.check_cap(period)
        return (spend + estimated_cost) <= cap
    
    def get_forecast(self, days: int = 7) -> Dict[str, float]:
        """Forecast future spend based on recent history."""
        daily_avg = self.get_spend(days=min(days, 7)) / min(days, 7)
        return {
            "daily_avg": daily_avg,
            "weekly_forecast": daily_avg * 7,
            "monthly_forecast": daily_avg * 30,
        }
    
    def get_alerts(self) -> List[dict]:
        """Get active alerts."""
        return list(self._alerts)
    
    def clear_alerts(self):
        """Clear all alerts."""
        self._alerts = []
        self._save_state()
    
    def _check_alerts(self):
        """Check for budget alerts."""
        alerts = []
        
        # Daily alert
        exceeded, spend, cap = self.check_cap("daily")
        if exceeded:
            alerts.append({
                "level": "critical",
                "period": "daily",
                "message": f"Daily cap exceeded: ${spend:.2f} / ${cap:.2f}",
                "timestamp": time.time(),
            })
        elif spend >= cap * self.config.alert_threshold_pct:
            alerts.append({
                "level": "warning",
                "period": "daily",
                "message": f"Daily budget at {spend/cap*100:.0f}%: ${spend:.2f} / ${cap:.2f}",
                "timestamp": time.time(),
            })
        
        # Weekly alert
        exceeded, spend, cap = self.check_cap("weekly")
        if exceeded:
            alerts.append({
                "level": "critical",
                "period": "weekly",
                "message": f"Weekly cap exceeded: ${spend:.2f} / ${cap:.2f}",
                "timestamp": time.time(),
            })
        elif spend >= cap * self.config.alert_threshold_pct:
            alerts.append({
                "level": "warning",
                "period": "weekly",
                "message": f"Weekly budget at {spend/cap*100:.0f}%: ${spend:.2f} / ${cap:.2f}",
                "timestamp": time.time(),
            })
        
        # Monthly alert
        exceeded, spend, cap = self.check_cap("monthly")
        if exceeded:
            alerts.append({
                "level": "critical",
                "period": "monthly",
                "message": f"Monthly cap exceeded: ${spend:.2f} / ${cap:.2f}",
                "timestamp": time.time(),
            })
        elif spend >= cap * self.config.alert_threshold_pct:
            alerts.append({
                "level": "warning",
                "period": "monthly",
                "message": f"Monthly budget at {spend/cap*100:.0f}%: ${spend:.2f} / ${cap:.2f}",
                "timestamp": time.time(),
            })
        
        self._alerts = alerts
    
    def get_status(self) -> dict:
        """Get comprehensive cost status."""
        daily_exceeded, daily_spend, daily_cap = self.check_cap("daily")
        weekly_exceeded, weekly_spend, weekly_cap = self.check_cap("weekly")
        monthly_exceeded, monthly_spend, monthly_cap = self.check_cap("monthly")
        
        return {
            "daily": {
                "spend": round(daily_spend, 4),
                "cap": daily_cap,
                "remaining": round(max(0, daily_cap - daily_spend), 4),
                "exceeded": daily_exceeded,
                "pct": (daily_spend / daily_cap * 100) if daily_cap > 0 else 0,
            },
            "weekly": {
                "spend": round(weekly_spend, 4),
                "cap": weekly_cap,
                "remaining": round(max(0, weekly_cap - weekly_spend), 4),
                "exceeded": weekly_exceeded,
                "pct": (weekly_spend / weekly_cap * 100) if weekly_cap > 0 else 0,
            },
            "monthly": {
                "spend": round(monthly_spend, 4),
                "cap": monthly_cap,
                "remaining": round(max(0, monthly_cap - monthly_spend), 4),
                "exceeded": monthly_exceeded,
                "pct": (monthly_spend / monthly_cap * 100) if monthly_cap > 0 else 0,
            },
            "by_model": self.get_spend_by_model(days=1),
            "by_provider": self.get_spend_by_provider(days=1),
            "by_platform": self.get_spend_by_platform(days=1),
            "forecast": self.get_forecast(),
            "alerts": self.get_alerts(),
        }
