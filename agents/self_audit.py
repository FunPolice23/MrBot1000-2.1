"""agents/self_audit.py — Self-Audit & Continuous-Improvement Layer (v2.0.36j-T4).

Identifies repeated failures, prediction errors, bad strategies, poor platforms/categories/task types,
low-performing variants, high-cost workflows, human intervention patterns, execution failures,
stale providers, stale categories, security problems, and documentation drift.

Produces structured improvement recommendations with: observation, evidence, confidence,
recommended change, expected benefit, expected risk, affected components, test requirements.

SAFETY CONSTRAINTS (non-negotiable):
- Does NOT automatically change security policies.
- Does NOT automatically weaken approval requirements.
- Does NOT automatically modify TrustBoundary.
- Does NOT automatically execute code modifications.
- Proposed code changes must continue through the existing validation/security pipeline.
- Learns operational strategies without changing safety constraints.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Finding category ───────────────────────────────────────────────────────────

class AuditCategory(str, Enum):
    REPEATED_FAILURES = "repeated_failures"
    PREDICTION_ERRORS = "prediction_errors"
    BAD_STRATEGIES = "bad_strategies"
    POOR_PLATFORMS = "poor_platforms"
    POOR_CATEGORIES = "poor_categories"
    POOR_TASK_TYPES = "poor_task_types"
    LOW_PERFORMING_VARIANTS = "low_performing_variants"
    HIGH_COST_WORKFLOWS = "high_cost_workflows"
    HUMAN_INTERVENTION = "human_intervention"
    EXECUTION_FAILURES = "execution_failures"
    STALE_PROVIDERS = "stale_providers"
    STALE_CATEGORIES = "stale_categories"
    SECURITY_PROBLEMS = "security_problems"
    DOCUMENTATION_DRIFT = "documentation_drift"


# ── Severity ───────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Audit finding ──────────────────────────────────────────────────────────────

@dataclass
class AuditFinding:
    """A structured improvement recommendation."""
    category: AuditCategory
    severity: Severity
    observation: str
    evidence: Dict[str, Any]
    confidence: float                       # 0..1
    recommended_change: str
    expected_benefit: str
    expected_risk: str
    affected_components: List[str]
    test_requirements: List[str]
    opportunity_id: str = ""
    platform: str = ""
    category_value: str = ""
    strategy_id: str = ""
    metric_value: float = 0.0
    metric_threshold: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "observation": self.observation,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "recommended_change": self.recommended_change,
            "expected_benefit": self.expected_benefit,
            "expected_risk": self.expected_risk,
            "affected_components": self.affected_components,
            "test_requirements": self.test_requirements,
            "opportunity_id": self.opportunity_id,
            "platform": self.platform,
            "category_value": self.category_value,
            "strategy_id": self.strategy_id,
            "metric_value": self.metric_value,
            "metric_threshold": self.metric_threshold,
            "created_at": self.created_at,
        }


# ── Audit report ───────────────────────────────────────────────────────────────

@dataclass
class AuditReport:
    """Complete audit results."""
    findings: List[AuditFinding] = field(default_factory=list)
    audited_at: float = field(default_factory=time.time)
    total_opportunities: int = 0
    total_platforms: int = 0
    total_strategies: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    def by_category(self, cat: AuditCategory) -> List[AuditFinding]:
        return [f for f in self.findings if f.category == cat]

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "audited_at": self.audited_at,
            "total_findings": len(self.findings),
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "total_opportunities": self.total_opportunities,
            "total_platforms": self.total_platforms,
            "total_strategies": self.total_strategies,
        }


# ── Self-audit engine ──────────────────────────────────────────────────────────

class SelfAuditEngine:
    """Analyzes engine data to produce improvement recommendations. Pure analysis — no mutations."""

    def __init__(self, memory: Any, evidence_store: Any = None, accounting: Any = None,
                 config: Optional[Dict] = None):
        self.memory = memory
        self.evidence_store = evidence_store
        self.accounting = accounting
        self.config = config or {}

        # Configurable thresholds
        self.min_sample_size = self.config.get("min_sample_size", 3)
        self.poor_acceptance_threshold = self.config.get("poor_acceptance_threshold", 0.1)
        self.bad_strategy_threshold = self.config.get("bad_strategy_threshold", 0.2)
        self.high_cost_ratio = self.config.get("high_cost_ratio", 0.5)
        self.stale_days = self.config.get("stale_days", 30)
        self.human_intervention_threshold = self.config.get("human_intervention_threshold", 0.3)

    # ── Main entry ─────────────────────────────────────────────────────────────

    def run_audit(self) -> AuditReport:
        """Run the full self-audit and return a report."""
        report = AuditReport()

        self._audit_repeated_failures(report)
        self._audit_prediction_errors(report)
        self._audit_bad_strategies(report)
        self._audit_poor_platforms(report)
        self._audit_poor_categories(report)
        self._audit_poor_task_types(report)
        self._audit_low_performing_variants(report)
        self._audit_high_cost_workflows(report)
        self._audit_human_intervention(report)
        self._audit_execution_failures(report)
        self._audit_stale_providers(report)
        self._audit_stale_categories(report)
        self._audit_security_problems(report)
        self._audit_documentation_drift(report)

        return report

    # ── 1. Repeated failures ──────────────────────────────────────────────────

    def _audit_repeated_failures(self, report: AuditReport) -> None:
        """Identify opportunities with repeated failure patterns."""
        platforms = self._get_all_platforms()
        report.total_platforms = len(platforms)

        for platform in platforms:
            rep = self.memory.get_platform_reputation(platform)
            if rep is None:
                continue
            total = rep.get("total", 0)
            if total < self.min_sample_size:
                continue
            failed = rep.get("failed", 0)
            failure_rate = failed / total if total > 0 else 0.0

            if failure_rate >= 0.7 and total >= 5:
                report.findings.append(AuditFinding(
                    category=AuditCategory.REPEATED_FAILURES,
                    severity=Severity.HIGH if failure_rate >= 0.8 else Severity.MEDIUM,
                    observation=f"Platform '{platform}' has a {failure_rate:.0%} failure rate ({failed}/{total} attempts).",
                    evidence={"platform": platform, "failure_rate": failure_rate,
                              "total_attempts": total, "failed": failed},
                    confidence=min(1.0, total / 10.0),
                    recommended_change=f"Reduce attempt rate for platform '{platform}'; investigate failure root cause before further submissions.",
                    expected_benefit="Reduce wasted effort and cost from repeated failures.",
                    expected_risk="May miss legitimate opportunities on this platform.",
                    affected_components=["earning_pipeline", "discovery_scheduler", "reputation_memory"],
                    test_requirements=["Verify failure rate calculation matches raw outcomes",
                                       "Check that reducing attempts does not block legitimate opportunities"],
                    platform=platform,
                    metric_value=failure_rate,
                    metric_threshold=0.7,
                ))

    # ── 2. Prediction errors ─────────────────────────────────────────────────

    def _audit_prediction_errors(self, report: AuditReport) -> None:
        """Identify systematic prediction errors."""
        accuracy = self.memory.get_prediction_accuracy("global", "global")
        if accuracy:
            sample_size = accuracy.get("sample_size", 0)
            if sample_size >= self.min_sample_size:
                rev_error = abs(accuracy.get("revenue_error_pct", 0.0))
                if rev_error > 0.5:
                    report.findings.append(AuditFinding(
                        category=AuditCategory.PREDICTION_ERRORS,
                        severity=Severity.HIGH if rev_error > 1.0 else Severity.MEDIUM,
                        observation=f"Revenue predictions have a {rev_error:.0%} average error (sample={sample_size}).",
                        evidence=accuracy,
                        confidence=min(1.0, sample_size / 20.0),
                        recommended_change="Recalibrate expected-value model weights or add new prediction features.",
                        expected_benefit="More accurate opportunity evaluation and prioritization.",
                        expected_risk="Overcorrection may introduce new biases.",
                        affected_components=["opportunity_intelligence", "earning_memory"],
                        test_requirements=["Back-test new calibration against historical outcomes",
                                           "Verify error decreases on holdout sample"],
                        metric_value=rev_error,
                        metric_threshold=0.5,
                    ))

        # Per-dimension prediction errors
        for dim in ("category", "platform", "task_type"):
            try:
                metrics_list = self.memory.compute_all_metrics(dim)
                for m in metrics_list:
                    if m.sample_size >= self.min_sample_size:
                        eva = abs(m.expected_vs_actual_return - 1.0)
                        if eva > 0.5:
                            report.findings.append(AuditFinding(
                                category=AuditCategory.PREDICTION_ERRORS,
                                severity=Severity.MEDIUM,
                                observation=f"{dim} '{m.value}' has {eva:.0%} expected-vs-actual return deviation.",
                                evidence={"dim": dim, "value": m.value, "expected_vs_actual": m.expected_vs_actual_return,
                                          "sample_size": m.sample_size},
                                confidence=min(1.0, m.sample_size / 20.0),
                                recommended_change=f"Review prediction accuracy for {dim} '{m.value}'; consider separate model calibration.",
                                expected_benefit="Better per-category/platform/task-type prioritization.",
                                expected_risk="Fragmented calibration may overfit to small samples.",
                                affected_components=["opportunity_intelligence"],
                                test_requirements=["Verify per-dimension metrics are statistically significant"],
                                category_value=m.value,
                                metric_value=eva,
                                metric_threshold=0.5,
                            ))
            except Exception:
                pass

    # ── 3. Bad strategies ────────────────────────────────────────────────────

    def _audit_bad_strategies(self, report: AuditReport) -> None:
        """Identify search strategies with poor performance."""
        try:
            # Query the database directly for worst strategies
            conn = sqlite3.connect(self.memory.db_path)
            rows = conn.execute(
                """SELECT strategy_id, used_count, result_count, useful_result_count,
                          completed, paid, net_revenue, duplicate_count
                   FROM search_strategy WHERE used_count >= ?""",
                (self.min_sample_size,)
            ).fetchall()
            conn.close()

            strategies = []
            for row in rows:
                sid, used, result_count, useful, completed, paid, net_rev, dups = row
                used = int(used or 0)
                result_count = int(result_count or 0)
                useful = int(useful or 0)
                completed = int(completed or 0)
                paid = int(paid or 0)
                net_rev = float(net_rev or 0.0)
                dups = int(dups or 0)
                # Compute usefulness (same formula as earning_memory._strategy_usefulness)
                usefulness = (net_rev + 10.0 * useful + 20.0 * completed + 30.0 * paid - 5.0 * dups) / max(used, 1)
                strategies.append({
                    "strategy_id": sid, "used_count": used, "usefulness": usefulness,
                    "result_count": result_count, "useful_result_count": useful,
                    "completed": completed, "paid": paid, "net_revenue": net_rev,
                })
            report.total_strategies = len(strategies)

            for s in strategies:
                if s["usefulness"] < self.bad_strategy_threshold:
                    report.findings.append(AuditFinding(
                        category=AuditCategory.BAD_STRATEGIES,
                        severity=Severity.MEDIUM,
                        observation=f"Search strategy '{s['strategy_id']}' has low usefulness ({s['usefulness']:.2f}) after {s['used_count']} uses.",
                        evidence=s,
                        confidence=min(1.0, s['used_count'] / 10.0),
                        recommended_change=f"Deprecate or replace strategy '{s['strategy_id']}'; shift budget to higher-usefulness alternatives.",
                        expected_benefit="Higher-quality opportunity discovery per search.",
                        expected_risk="May lose niche opportunities that only this strategy finds.",
                        affected_components=["discovery_scheduler", "search_strategy_memory"],
                        test_requirements=["A/B test replacement strategy against current one",
                                           "Monitor discovery quality after deprecation"],
                        strategy_id=s['strategy_id'],
                        metric_value=s['usefulness'],
                        metric_threshold=self.bad_strategy_threshold,
                    ))
        except Exception:
            pass

    # ── 4. Poor platforms ────────────────────────────────────────────────────

    def _audit_poor_platforms(self, report: AuditReport) -> None:
        """Identify platforms with consistently poor outcomes."""
        platforms = self._get_all_platforms()
        for platform in platforms:
            rep = self.memory.get_platform_reputation(platform)
            if rep is None:
                continue
            total = rep.get("total", 0)
            if total < self.min_sample_size:
                continue
            success_rate = rep.get("success_rate", 0.0)
            if success_rate < self.poor_acceptance_threshold:
                report.findings.append(AuditFinding(
                    category=AuditCategory.POOR_PLATFORMS,
                    severity=Severity.HIGH if total >= 10 else Severity.MEDIUM,
                    observation=f"Platform '{platform}' has only {success_rate:.0%} acceptance rate over {total} attempts.",
                    evidence=rep,
                    confidence=min(1.0, total / 15.0),
                    recommended_change=f"Reduce attempt volume for '{platform}'; investigate platform-specific failure causes.",
                    expected_benefit="Reduce wasted effort on low-yield platforms.",
                    expected_risk="May miss platform-specific opportunities that require persistence.",
                    affected_components=["discovery_scheduler", "platform_throttle", "reputation_memory"],
                    test_requirements=["Verify acceptance rate includes all attempt types",
                                       "Confirm reduction does not block high-value niche opportunities"],
                    platform=platform,
                    metric_value=success_rate,
                    metric_threshold=self.poor_acceptance_threshold,
                ))

    # ── 5. Poor categories ───────────────────────────────────────────────────

    def _audit_poor_categories(self, report: AuditReport) -> None:
        """Identify opportunity categories with poor performance."""
        try:
            all_metrics = self.memory.compute_all_metrics("category")
            for m in all_metrics:
                if m.sample_size < self.min_sample_size:
                    continue
                if m.acceptance_rate < self.poor_acceptance_threshold and m.sample_size >= 5:
                    report.findings.append(AuditFinding(
                        category=AuditCategory.POOR_CATEGORIES,
                        severity=Severity.MEDIUM,
                        observation=f"Category '{m.value}' has {m.acceptance_rate:.0%} acceptance rate (sample={m.sample_size}).",
                        evidence={"acceptance_rate": m.acceptance_rate, "avg_revenue": m.average_revenue,
                                  "avg_net_profit": m.average_net_profit, "sample_size": m.sample_size},
                        confidence=min(1.0, m.sample_size / 15.0),
                        recommended_change=f"Reduce priority for category '{m.value}'; investigate root causes (pricing, competition, fit).",
                        expected_benefit="Better resource allocation toward high-performing categories.",
                        expected_risk="May miss category-specific improvements that could raise acceptance.",
                        affected_components=["opportunity_intelligence", "discovery_scheduler"],
                        test_requirements=["Verify category classification is accurate",
                                           "Monitor category performance after priority adjustment"],
                        category_value=m.value,
                        metric_value=m.acceptance_rate,
                        metric_threshold=self.poor_acceptance_threshold,
                    ))
        except Exception:
            pass

    # ── 6. Poor task types ───────────────────────────────────────────────────

    def _audit_poor_task_types(self, report: AuditReport) -> None:
        """Identify task types with poor performance."""
        try:
            all_metrics = self.memory.compute_all_metrics("task_type")
            for m in all_metrics:
                if m.sample_size < self.min_sample_size:
                    continue
                # Poor net hourly return despite decent acceptance
                if m.acceptance_rate >= 0.3 and m.average_hourly_return < 10.0 and m.sample_size >= 5:
                    report.findings.append(AuditFinding(
                        category=AuditCategory.POOR_TASK_TYPES,
                        severity=Severity.MEDIUM,
                        observation=f"Task type '{m.value}' has excellent acceptance ({m.acceptance_rate:.0%}) but poor net hourly return (${m.average_hourly_return:.2f}/hr).",
                        evidence={"acceptance_rate": m.acceptance_rate, "avg_hourly_return": m.average_hourly_return,
                                  "avg_effort_hours": m.average_effort_hours, "sample_size": m.sample_size},
                        confidence=min(1.0, m.sample_size / 15.0),
                        recommended_change=f"Investigate effort estimation for '{m.value}'; consider pricing adjustments or workflow optimization.",
                        expected_benefit="Improve net hourly return for accepted work.",
                        expected_risk="Raising prices may reduce acceptance rate.",
                        affected_components=["opportunity_intelligence", "task_executor"],
                        test_requirements=["Track hourly return after pricing/workflow changes",
                                           "Monitor acceptance rate for regression"],
                        category_value=m.value,
                        metric_value=m.average_hourly_return,
                        metric_threshold=10.0,
                    ))
        except Exception:
            pass

    # ── 7. Low-performing variants ───────────────────────────────────────────

    def _audit_low_performing_variants(self, report: AuditReport) -> None:
        """Identify low-performing proposal variants."""
        try:
            variants = self.memory.get_successful_patterns("proposal_variant", min_confidence=0.0)
            if not variants:
                return
            for v in variants:
                rate = v.get("success_rate", 0.0)
                total = v.get("total", 0)
                if total >= self.min_sample_size and rate < 0.15:
                    report.findings.append(AuditFinding(
                        category=AuditCategory.LOW_PERFORMING_VARIANTS,
                        severity=Severity.MEDIUM,
                        observation=f"Proposal variant '{v.get('pattern_value', '?')}' has only {rate:.0%} acceptance rate (sample={total}).",
                        evidence=v,
                        confidence=min(1.0, total / 15.0),
                        recommended_change=f"Deprecate or revise proposal variant '{v.get('pattern_value', '?')}'; test higher-performing alternatives.",
                        expected_benefit="Higher acceptance rates through better proposal variants.",
                        expected_risk="New variants may not generalize across platforms/categories.",
                        affected_components=["content_generator", "proposal_generator"],
                        test_requirements=["A/B test new variant against deprecated one",
                                           "Verify improvement is consistent across platforms"],
                        category_value=v.get("pattern_value", ""),
                        metric_value=rate,
                        metric_threshold=0.15,
                    ))
        except Exception:
            pass

    # ── 8. High-cost workflows ───────────────────────────────────────────────

    def _audit_high_cost_workflows(self, report: AuditReport) -> None:
        """Identify workflows where costs exceed expected profit."""
        if self.accounting is None:
            return
        try:
            opp_ids = self._get_all_opportunity_ids()
            for opp_id in opp_ids:
                try:
                    profile = self.accounting.get_profile(opp_id)
                    if profile.realized_expense > 0 and profile.expected_value > 0:
                        cost_ratio = profile.realized_expense / max(profile.expected_value, 0.01)
                        if cost_ratio > self.high_cost_ratio:
                            report.findings.append(AuditFinding(
                                category=AuditCategory.HIGH_COST_WORKFLOWS,
                                severity=Severity.HIGH if cost_ratio > 1.0 else Severity.MEDIUM,
                                observation=f"Opportunity '{opp_id}' has costs ({profile.realized_expense:.2f}) exceeding {cost_ratio:.0%} of expected value ({profile.expected_value:.2f}).",
                                evidence={"opportunity_id": opp_id, "realized_expense": profile.realized_expense,
                                          "expected_value": profile.expected_value, "cost_ratio": cost_ratio,
                                          "expenses": profile.expenses},
                                confidence=0.8,
                                recommended_change=f"Review cost structure for '{opp_id}'; optimize LLM usage, reduce unnecessary API calls, or renegotiate platform fees.",
                                expected_benefit="Improve net profitability per opportunity.",
                                expected_risk="Cost-cutting may reduce deliverable quality or acceptance rate.",
                                affected_components=["task_executor", "economic_accounting"],
                                test_requirements=["Verify cost reduction does not reduce acceptance rate",
                                                   "Track net profit after optimization"],
                                opportunity_id=opp_id,
                                metric_value=cost_ratio,
                                metric_threshold=self.high_cost_ratio,
                            ))
                except Exception:
                    continue
        except Exception:
            pass

    # ── 9. Human intervention ────────────────────────────────────────────────

    def _audit_human_intervention(self, report: AuditReport) -> None:
        """Identify opportunities with recurring human intervention requirements."""
        try:
            portfolio = getattr(self.memory, 'portfolio', None)
            if portfolio is None:
                return
            all_entries = portfolio.load_all()
            human_required = [e for e in all_entries if getattr(e, 'work_status', None) and
                              e.work_status.value == 'awaiting_approval']
            total = len(all_entries)
            if total > 0:
                human_rate = len(human_required) / total
                if human_rate > self.human_intervention_threshold:
                    report.findings.append(AuditFinding(
                        category=AuditCategory.HUMAN_INTERVENTION,
                        severity=Severity.MEDIUM,
                        observation=f"{len(human_required)}/{total} opportunities ({human_rate:.0%}) require human approval.",
                        evidence={"awaiting_approval": len(human_required), "total": total, "human_rate": human_rate},
                        confidence=min(1.0, total / 20.0),
                        recommended_change="Review human gate triggers; automate gates that have consistent clearance patterns (e.g., payments under threshold).",
                        expected_benefit="Faster execution for low-risk operations.",
                        expected_risk="May automate a gate that should remain manual.",
                        affected_components=["human_gates", "task_executor"],
                        test_requirements=["Verify automated gates maintain security boundaries",
                                           "Monitor for incorrectly auto-cleared gates"],
                        metric_value=human_rate,
                        metric_threshold=self.human_intervention_threshold,
                    ))
        except Exception:
            pass

    # ── 10. Execution failures ───────────────────────────────────────────────

    def _audit_execution_failures(self, report: AuditReport) -> None:
        """Identify opportunities stuck in BLOCKED or FAILED states."""
        try:
            portfolio = getattr(self.memory, 'portfolio', None)
            if portfolio is None:
                return
            all_entries = portfolio.load_all()
            blocked = [e for e in all_entries if getattr(e, 'work_status', None) and
                       e.work_status.value in ('blocked', 'failed', 'rejected')]
            for entry in blocked:
                report.findings.append(AuditFinding(
                    category=AuditCategory.EXECUTION_FAILURES,
                    severity=Severity.LOW,
                    observation=f"Opportunity '{entry.opportunity_id}' is in state '{entry.work_status.value}'.",
                    evidence={"opportunity_id": entry.opportunity_id, "status": entry.work_status.value},
                    confidence=0.7,
                    recommended_change=f"Review and resolve '{entry.opportunity_id}'; either retry with fixes or mark abandoned.",
                    expected_benefit="Clean up stale blocked/failed opportunities.",
                    expected_risk="Retry may fail again if root cause not addressed.",
                    affected_components=["task_executor", "opportunity_portfolio"],
                    test_requirements=["Verify resolution does not re-introduce the failure"],
                    opportunity_id=entry.opportunity_id,
                ))
        except Exception:
            pass

    # ── 11. Stale providers ──────────────────────────────────────────────────

    def _audit_stale_providers(self, report: AuditReport) -> None:
        """Identify providers that have not produced results recently."""
        platforms = self._get_all_platforms()
        now = time.time()
        stale_cutoff = now - (self.stale_days * 86400)

        for platform in platforms:
            rep = self.memory.get_platform_reputation(platform)
            if rep is None:
                continue
            last_attempt = rep.get("last_attempt", 0)
            total = rep.get("total", 0)
            if total > 0 and last_attempt > 0 and last_attempt < stale_cutoff:
                days_stale = (now - last_attempt) / 86400
                report.findings.append(AuditFinding(
                    category=AuditCategory.STALE_PROVIDERS,
                    severity=Severity.LOW,
                    observation=f"Provider '{platform}' has not produced results in {days_stale:.0f} days.",
                    evidence={"platform": platform, "last_attempt": last_attempt, "days_stale": days_stale},
                    confidence=0.6,
                    recommended_change=f"Consider removing or reducing weight for stale provider '{platform}'.",
                    expected_benefit="Reduce wasted discovery budget on inactive providers.",
                    expected_risk="Provider may become active again seasonally.",
                    affected_components=["discovery_scheduler", "discovery_sources"],
                    test_requirements=["Verify provider inactivity before removal"],
                    platform=platform,
                    metric_value=days_stale,
                    metric_threshold=self.stale_days,
                ))

    # ── 12. Stale categories ─────────────────────────────────────────────────

    def _audit_stale_categories(self, report: AuditReport) -> None:
        """Identify opportunity categories with no recent activity."""
        try:
            all_metrics = self.memory.compute_all_metrics("category")
            now = time.time()
            for m in all_metrics:
                last_active = getattr(m, 'last_active', 0)
                if m.sample_size >= self.min_sample_size and last_active > 0:
                    days_stale = (now - last_active) / 86400
                    if days_stale > self.stale_days:
                        report.findings.append(AuditFinding(
                            category=AuditCategory.STALE_CATEGORIES,
                            severity=Severity.LOW,
                            observation=f"Category '{m.value}' has had no new opportunities in {days_stale:.0f} days.",
                            evidence={"category": m.value, "days_stale": days_stale, "last_active": last_active},
                            confidence=0.6,
                            recommended_change=f"Consider deprioritizing category '{m.value}' until new opportunities appear.",
                            expected_benefit="Focus discovery on active categories.",
                            expected_risk="Category may have seasonal or cyclical availability.",
                            affected_components=["discovery_scheduler", "opportunity_intelligence"],
                            test_requirements=["Monitor for category re-activation"],
                            category_value=m.value,
                            metric_value=days_stale,
                            metric_threshold=self.stale_days,
                        ))
        except Exception:
            pass

    # ── 13. Security problems ────────────────────────────────────────────────

    def _audit_security_problems(self, report: AuditReport) -> None:
        """Identify potential security concerns."""
        try:
            wallet_mgr = getattr(self.memory, 'wallet_manager', None)
            if wallet_mgr:
                failed_ops = getattr(wallet_mgr, 'failed_operations', [])
                for op in failed_ops:
                    report.findings.append(AuditFinding(
                        category=AuditCategory.SECURITY_PROBLEMS,
                        severity=Severity.HIGH,
                        observation=f"Wallet operation failed validation: {op.get('description', 'unknown')}.",
                        evidence=op,
                        confidence=0.9,
                        recommended_change="Review wallet operation validation rules; investigate root cause of failure.",
                        expected_benefit="Ensure wallet security constraints are working correctly.",
                        expected_risk="May reveal a bug in validation logic that blocks legitimate operations.",
                        affected_components=["wallet_manager", "security_policy"],
                        test_requirements=["Verify validation rules are correct",
                                           "Test that legitimate operations are not blocked"],
                    ))
        except Exception:
            pass

    # ── 14. Documentation drift ──────────────────────────────────────────────

    def _audit_documentation_drift(self, report: AuditReport) -> None:
        """Identify documentation that may have drifted from implementation."""
        try:
            import re
            improvements_path = os.path.join(os.path.dirname(__file__), "..", "IMPROVEMENTS.md")
            if os.path.exists(improvements_path):
                content = open(improvements_path, encoding="utf-8").read()
                completed = len(re.findall(r'\| H\d+ .* \| Complete \|', content))
                versions = len(re.findall(r'## \[\d+\.\d+\.\d+[a-z]\]', content))
                if completed > 0 and versions > 0:
                    ratio = completed / max(versions, 1)
                    if ratio > 15:
                        report.findings.append(AuditFinding(
                            category=AuditCategory.DOCUMENTATION_DRIFT,
                            severity=Severity.LOW,
                            observation=f"IMPROVEMENTS.md has {completed} completed items but only {versions} version entries (ratio {ratio:.1f}:1).",
                            evidence={"completed": completed, "versions": versions, "ratio": ratio},
                            confidence=0.5,
                            recommended_change="Review IMPROVEMENTS.md for stale entries; rotate completed items to CHANGELOG.",
                            expected_benefit="Accurate, up-to-date improvement tracking.",
                            expected_risk="Historical data loss if items are removed carelessly.",
                            affected_components=["IMPROVEMENTS.md", "documentation"],
                            test_requirements=["Verify all completed items have corresponding code"],
                            metric_value=ratio,
                            metric_threshold=15.0,
                        ))
        except Exception:
            pass

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_all_platforms(self) -> List[str]:
        """Get all platform names from memory."""
        try:
            conn = sqlite3.connect(self.memory.db_path)
            rows = conn.execute("SELECT DISTINCT platform FROM reputation_memory").fetchall()
            conn.close()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []

    def _get_all_opportunity_ids(self) -> List[str]:
        """Get all opportunity IDs from memory."""
        try:
            conn = sqlite3.connect(self.memory.db_path)
            rows = conn.execute("SELECT DISTINCT id FROM opportunities").fetchall()
            conn.close()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []


__all__ = [
    "AuditCategory",
    "Severity",
    "AuditFinding",
    "AuditReport",
    "SelfAuditEngine",
]
