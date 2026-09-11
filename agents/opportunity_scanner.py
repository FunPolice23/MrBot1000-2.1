"""
agents/opportunity_scanner.py — Background opportunity scanner daemon (v2.1 Phase 1).

Continuously scans all configured platforms for opportunities:
- Runs as a background thread
- Polls platforms at configurable intervals
- Scores and filters opportunities
- Stores in database for review
- Alerts on high-value finds
"""

import time
import threading
import logging
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field

from agents.platforms import create_all_adapters, PlatformAdapter
from agents.opportunity_models import Opportunity, OpportunitySource
from agents.opportunity_intelligence import OpportunityIntelligenceEngine

logger = logging.getLogger(__name__)


@dataclass
class ScannerConfig:
    """Scanner configuration."""
    enabled: bool = True
    scan_interval_seconds: int = 300  # 5 minutes
    platforms: List[str] = field(default_factory=lambda: ["upwork", "fiverr", "github"])
    min_score: float = 0.5
    max_results_per_scan: int = 50
    auto_research: bool = True
    alert_on_high_value: bool = True
    high_value_threshold: float = 100.0


class OpportunityScanner:
    """Background daemon that continuously scans for opportunities."""
    
    def __init__(self, config: ScannerConfig = None, db=None, 
                 intelligence: OpportunityIntelligenceEngine = None):
        self.config = config or ScannerConfig()
        self.db = db
        self.intelligence = intelligence or OpportunityIntelligenceEngine()
        
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._adapters: Dict[str, PlatformAdapter] = {}
        self._last_scan: float = 0
        self._scan_count: int = 0
        self._total_found: int = 0
        self._callbacks: List[Callable] = []
    
    def register_callback(self, callback: Callable):
        """Register a callback for new opportunities."""
        self._callbacks.append(callback)
    
    def start(self):
        """Start the scanner daemon."""
        if self._running:
            return
        
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Opportunity scanner started")
    
    def stop(self):
        """Stop the scanner daemon."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning("Opportunity scanner did not stop within 10 seconds")
            else:
                self._thread = None
        logger.info("Opportunity scanner stopped")
    
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running
    
    def get_status(self) -> dict:
        """Get scanner status."""
        return {
            "running": self._running,
            "last_scan": self._last_scan,
            "scan_count": self._scan_count,
            "total_found": self._total_found,
            "platforms": list(self._adapters.keys()),
            "interval": self.config.scan_interval_seconds,
        }
    
    def scan_now(self) -> List[Opportunity]:
        """Run an immediate scan."""
        return self._scan_all()
    
    def _run(self):
        """Main scanner loop."""
        while self._running:
            try:
                self._scan_all()
                self._scan_count += 1
                self._last_scan = time.time()
            except Exception as e:
                logger.error(f"Scan error: {e}")
            
            # Wait for next scan
            self._stop_event.wait(max(0, self.config.scan_interval_seconds))
    
    def _scan_all(self) -> List[Opportunity]:
        """Scan all configured platforms."""
        opportunities = []
        
        for platform_name in self.config.platforms:
            try:
                adapter = self._get_adapter(platform_name)
                if adapter and adapter.enabled:
                    platform_opps = self._scan_platform(adapter, platform_name)
                    opportunities.extend(platform_opps)
            except Exception as e:
                logger.warning(f"Failed to scan {platform_name}: {e}")
        
        # Score and filter
        scored = self._score_opportunities(opportunities)
        filtered = [o for o in scored if o.score >= self.config.min_score]
        
        # Store in database
        if self.db:
            for opp in filtered:
                self.db.store_opportunity(opp)
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(filtered)
            except Exception as e:
                logger.warning(f"Callback error: {e}")
        
        self._total_found += len(filtered)
        return filtered
    
    def _get_adapter(self, platform_name: str) -> Optional[PlatformAdapter]:
        """Get or create adapter for a platform."""
        if platform_name not in self._adapters:
            try:
                from agents.instruction_gate import InstructionGate
                from agents.trust_boundary import TrustBoundary
                
                gate = InstructionGate()
                boundary = TrustBoundary()
                
                from agents.platforms import create_adapter
                adapter = create_adapter(platform_name, gate, boundary)
                if adapter:
                    adapter.enabled = True  # Enable for scanning
                self._adapters[platform_name] = adapter
            except Exception as e:
                logger.warning(f"Failed to create adapter for {platform_name}: {e}")
                return None
        
        return self._adapters.get(platform_name)
    
    def _scan_platform(self, adapter: PlatformAdapter, platform_name: str) -> List[Opportunity]:
        """Scan a single platform for opportunities."""
        opportunities = []
        
        try:
            if platform_name == "upwork":
                result = adapter.execute_action("search_jobs", {"query": "", "limit": 20})
                if result.get("ok"):
                    for job in result.get("opportunities", []):
                        opp = Opportunity(
                            title=job.get("title", ""),
                            description=job.get("description", ""),
                            url=job.get("url", ""),
                            source="upwork",
                            category="freeling",
                            budget_usd=float(job.get("budget", {}).get("amount", 0)),
                        )
                        opportunities.append(opp)
            
            elif platform_name == "fiverr":
                result = adapter.execute_action("search_gigs", {"query": "", "limit": 20})
                if result.get("ok"):
                    for gig in result.get("opportunities", []):
                        opp = Opportunity(
                            title=gig.get("title", ""),
                            description=gig.get("description", ""),
                            url=gig.get("url", ""),
                            source="fiverr",
                            category="freelance",
                            budget_usd=float(gig.get("budget", {}).get("amount", 0)),
                        )
                        opportunities.append(opp)
            
            elif platform_name == "github":
                result = adapter.execute_action("search_issues", {
                    "labels": ["bounty", "help wanted"],
                    "limit": 20,
                })
                if result.get("ok"):
                    for issue in result.get("opportunities", []):
                        opp = Opportunity(
                            title=issue.get("title", ""),
                            description=issue.get("description", ""),
                            url=issue.get("url", ""),
                            source="github",
                            category="open_source_bounty",
                            budget_usd=0,  # GitHub issues don't always have bounties
                        )
                        opportunities.append(opp)
            
            elif platform_name == "prolific":
                result = adapter.execute_action("search_studies", {"limit": 20})
                if result.get("ok"):
                    for study in result.get("opportunities", []):
                        opp = Opportunity(
                            title=study.get("title", ""),
                            description=study.get("description", ""),
                            url=study.get("url", ""),
                            source="prolific",
                            category="paid_study",
                            budget_usd=float(study.get("reward", 0)),
                        )
                        opportunities.append(opp)
        
        except Exception as e:
            logger.warning(f"Error scanning {platform_name}: {e}")
        
        return opportunities
    
    def _score_opportunities(self, opportunities: List[Opportunity]) -> List[Opportunity]:
        """Score opportunities using intelligence engine."""
        for opp in opportunities:
            opp.score = self.intelligence.evaluate(opp).get("score", 0)
        return opportunities
