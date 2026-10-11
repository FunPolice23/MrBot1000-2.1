"""
agents/reputation.py — Reputation tracking system (v2.1 Phase 2).

Tracks agent reputation across all platforms:
- Per-platform metrics (success rate, total earnings, task count)
- Overall reputation score
- Badge system for achievements
- Work history/portfolio
- Verification of completed work
"""

import time
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class BadgeTier(Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"
    DIAMOND = "diamond"


@dataclass
class Badge:
    """Achievement badge."""
    id: str
    name: str
    description: str
    tier: BadgeTier
    icon: str
    earned_at: float
    criteria: str


@dataclass
class PlatformMetrics:
    """Metrics for a single platform."""
    platform: str
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    rejected_tasks: int = 0
    total_earnings: float = 0.0
    verified_earnings: float = 0.0
    total_costs: float = 0.0
    average_rating: float = 0.0
    ratings_count: int = 0
    first_task_at: float = 0.0
    last_task_at: float = 0.0
    
    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.successful_tasks / self.total_tasks
    
    @property
    def net_earnings(self) -> float:
        return self.total_earnings - self.total_costs

    @property
    def verified_net_earnings(self) -> float:
        return self.verified_earnings - self.total_costs
    
    @property
    def roi(self) -> float:
        if self.total_costs == 0:
            return 0.0
        return (self.total_earnings - self.total_costs) / self.total_costs * 100

    @property
    def verified_roi(self) -> float:
        if self.total_costs == 0:
            return 0.0
        return (self.verified_earnings - self.total_costs) / self.total_costs * 100


@dataclass
class WorkRecord:
    """Record of a completed task."""
    task_id: str
    platform: str
    title: str
    description: str
    category: str
    status: str  # completed, failed, rejected
    payout: float
    costs: float
    rating: float = 0.0
    feedback: str = ""
    completed_at: float = 0.0
    verified: bool = False
    verification_ref: str = ""


class ReputationTracker:
    """Track and manage agent reputation across platforms."""
    
    def __init__(self, state_path: str = ""):
        self.state_path = state_path or os.path.join(
            os.path.expanduser("~"), ".mrbot1000", "reputation.json"
        )
        self._platforms: Dict[str, PlatformMetrics] = {}
        self._work_history: List[WorkRecord] = []
        self._badges: List[Badge] = []
        
        # Load persisted state
        self._load()
    
    def _load(self):
        """Load reputation state from disk."""
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path) as f:
                    data = json.load(f)
                
                for platform, metrics in data.get("platforms", {}).items():
                    self._platforms[platform] = PlatformMetrics(**metrics)
                
                for record in data.get("work_history", []):
                    self._work_history.append(WorkRecord(**record))
                
                for badge_data in data.get("badges", []):
                    badge_data["tier"] = BadgeTier(badge_data["tier"])
                    self._badges.append(Badge(**badge_data))
            except Exception:
                pass
    
    def _save(self):
        """Save reputation state to disk."""
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            
            data = {
                "platforms": {
                    name: metrics.__dict__
                    for name, metrics in self._platforms.items()
                },
                "work_history": [r.__dict__ for r in self._work_history[-100:]],  # Keep last 100
                "badges": [
                    {**b.__dict__, "tier": b.tier.value}
                    for b in self._badges
                ],
                "saved_at": time.time(),
            }
            
            with open(self.state_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
    
    def record_work(self, record: WorkRecord):
        """Record completed work."""
        # Update platform metrics
        if record.platform not in self._platforms:
            self._platforms[record.platform] = PlatformMetrics(platform=record.platform)
        
        metrics = self._platforms[record.platform]
        metrics.total_tasks += 1
        metrics.last_task_at = record.completed_at
        
        if metrics.first_task_at == 0:
            metrics.first_task_at = record.completed_at
        
        if record.status == "completed":
            metrics.successful_tasks += 1
            metrics.total_earnings += record.payout
            if record.verified:
                metrics.verified_earnings += record.payout
        elif record.status == "failed":
            metrics.failed_tasks += 1
        elif record.status == "rejected":
            metrics.rejected_tasks += 1
        
        metrics.total_costs += record.costs
        
        # Update rating
        if record.rating > 0:
            total_rating = metrics.average_rating * metrics.ratings_count + record.rating
            metrics.ratings_count += 1
            metrics.average_rating = total_rating / metrics.ratings_count
        
        # Add to history
        self._work_history.append(record)
        
        # Check for new badges
        self._check_badges()
        
        # Save state
        self._save()
    
    def get_platform_metrics(self, platform: str) -> Optional[PlatformMetrics]:
        """Get metrics for a specific platform."""
        return self._platforms.get(platform)
    
    def get_all_metrics(self) -> Dict[str, PlatformMetrics]:
        """Get all platform metrics."""
        return dict(self._platforms)
    
    def get_overall_metrics(self) -> Dict:
        """Get overall aggregated metrics."""
        total_tasks = sum(m.total_tasks for m in self._platforms.values())
        successful = sum(m.successful_tasks for m in self._platforms.values())
        failed = sum(m.failed_tasks for m in self._platforms.values())
        earnings = sum(m.total_earnings for m in self._platforms.values())
        costs = sum(m.total_costs for m in self._platforms.values())
        verified_earnings = sum(m.verified_earnings for m in self._platforms.values())
        
        return {
            "total_tasks": total_tasks,
            "successful_tasks": successful,
            "failed_tasks": failed,
            "success_rate": successful / total_tasks if total_tasks > 0 else 0,
            "total_earnings": earnings,
            "recorded_earnings": earnings,
            "verified_earnings": verified_earnings,
            "unverified_completed_records": sum(
                1 for r in self._work_history
                if r.status == "completed" and not r.verified
            ),
            "total_costs": costs,
            "net_earnings": earnings - costs,
            "verified_net_earnings": verified_earnings - costs,
            "roi": ((earnings - costs) / costs * 100) if costs > 0 else 0,
            "platforms_count": len(self._platforms),
            "badges_count": len(self._badges),
        }
    
    def get_badges(self) -> List[Badge]:
        """Get all earned badges."""
        return list(self._badges)
    
    def get_work_history(self, limit: int = 20) -> List[WorkRecord]:
        """Get recent work history."""
        return self._work_history[-limit:]
    
    def get_portfolio(self) -> Dict:
        """Get work portfolio summary."""
        categories: Dict[str, int] = {}
        for record in self._work_history:
            if record.status == "completed":
                categories[record.category] = categories.get(record.category, 0) + 1
        
        return {
            "total_completed": sum(1 for r in self._work_history if r.status == "completed"),
            "categories": categories,
            "platforms": list(self._platforms.keys()),
            "top_platform": max(
                self._platforms.items(),
                key=lambda x: x[1].verified_earnings,
                default=(None, None)
            )[0],
        }
    
    def _check_badges(self):
        """Check and award new badges."""
        metrics = self.get_overall_metrics()
        earned_ids = {b.id for b in self._badges}
        
        badges_to_check = [
            ("first_task", "First Steps", "Complete your first task", BadgeTier.BRONZE, "🎯",
             metrics["total_tasks"] >= 1),
            ("ten_tasks", "Getting Started", "Complete 10 tasks", BadgeTier.BRONZE, "🔟",
             metrics["total_tasks"] >= 10),
            ("fifty_tasks", "Veteran", "Complete 50 tasks", BadgeTier.SILVER, "50️⃣",
             metrics["total_tasks"] >= 50),
            ("hundred_tasks", "Centurion", "Complete 100 tasks", BadgeTier.GOLD, "💯",
             metrics["total_tasks"] >= 100),
            ("high_success", "Reliable", "Achieve 90%+ success rate", BadgeTier.SILVER, "⭐",
             metrics["success_rate"] >= 0.9 and metrics["total_tasks"] >= 10),
            ("earner_100", "Earner", "Earn $100+ (verified)", BadgeTier.BRONZE, "$",
             metrics["verified_earnings"] >= 100),
            ("earner_1000", "High Earner", "Earn $1,000+", BadgeTier.GOLD, "$$$",
             metrics["verified_earnings"] >= 1000),
            ("multi_platform", "Multi-Platform", "Work on 3+ platforms", BadgeTier.SILVER, "🌐",
             metrics["platforms_count"] >= 3),
            ("roi_positive", "Profitable", "Achieve positive ROI", BadgeTier.GOLD, "📈",
             metrics["verified_net_earnings"] > 0 and metrics["verified_earnings"] > 0),
            ("verified_pro", "Verified Pro", "Get 10+ verified completions", BadgeTier.PLATINUM, "✅",
             sum(1 for r in self._work_history if r.verified) >= 10),
        ]
        
        for badge_id, name, desc, tier, icon, criteria in badges_to_check:
            if badge_id not in earned_ids and criteria:
                self._badges.append(Badge(
                    id=badge_id,
                    name=name,
                    description=desc,
                    tier=tier,
                    icon=icon,
                    earned_at=time.time(),
                    criteria=desc,
                ))
    
    def get_reputation_score(self) -> float:
        """Calculate overall reputation score (0-100)."""
        metrics = self.get_overall_metrics()
        
        if metrics["total_tasks"] == 0:
            return 0.0
        
        # Components
        success_score = metrics["success_rate"] * 40  # 40 points max
        volume_score = min(metrics["total_tasks"] / 100, 1.0) * 20  # 20 points max
        roi_score = min(max(
            metrics["verified_net_earnings"] / metrics["total_costs"] * 100
            if metrics["total_costs"] > 0 else 0,
            0,
        ) / 100, 1.0) * 20  # 20 points max
        diversity_score = min(metrics["platforms_count"] / 5, 1.0) * 10  # 10 points max
        badge_score = min(metrics["badges_count"] / 10, 1.0) * 10  # 10 points max
        
        return success_score + volume_score + roi_score + diversity_score + badge_score
