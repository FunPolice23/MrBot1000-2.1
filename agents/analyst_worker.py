"""
analyst_worker.py — Proposal quality metrics analysis for MrBot1000

Specialization: analyzes proposal quality, code metrics, and winning rate drivers.
Collects metrics on clarity, requirement matching, deliverable structure, and success patterns.
"""

import re
import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from agents.base_worker import WorkerAgent, ROOT_FOLDER
from library import AgentLogger, ResponseParser, fingerprint


@dataclass
class ProposalMetrics:
    """Metrics collected from a code/proposal analysis."""
    proposal_id: str
    clarity_score: float  # 0-1, how clear the requirements are
    complexity_score: float  # 0-1, estimated effort/complexity
    deliverable_structure: str  # "good", "moderate", "poor"
    potential_bugs: List[str] = field(default_factory=list)
    missing_sections: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    recommendations: List[str] = field(default_factory=list)
    can_submit: bool = False
    verified_at: float = field(default_factory=time.time)


class AnalystWorker(WorkerAgent):
    """
    AnalystWorker — Analyzes code quality, proposal metrics, and winning rate drivers.
    
    Collects and analyzes:
    - Proposal clarity scores
    - Requirement alignment rates  
    - Complexity vs. deliverable ratios
    - Success/failure patterns by gig source
    
    Provides actionable insights for improving proposal win rates.
    """

    def __init__(self, api_key: str, log_signal, db=None):
        super().__init__(api_key, log_signal, db=db)
        self._logger = AgentLogger(db=db, source="AnalystWorker", signal=log_signal)
        self._metrics_store: List[ProposalMetrics] = []

    # ── Analysis Methods ────────────────────────────────────────────────────────

    def analyze_proposal(self, proposal_text: str, proposal_id: str = None) -> ProposalMetrics:
        """
        Analyze a proposal and return quality metrics.
        
        Metrics include:
        - clarity_score: how clear the requirements are (0-1)
        - complexity_score: estimated effort/complexity (0-1, higher = more complex)
        - deliverable_structure: "good", "moderate", or "poor"
        - potential_bugs: list of identified issues
        - missing_sections: list of sections that should be present
        """
        if not proposal_text or not proposal_text.strip():
            return ProposalMetrics(
                proposal_id=proposal_id or f"empty_{int(time.time()*1000)}",
                clarity_score=0.0,
                complexity_score=0.0,
                deliverable_structure="poor",
                quality_score=0.0,
                recommendations=["Proposal is empty - add requirements and deliverables"]
            )

        # Clarity score - based on structure and language
        lines = proposal_text.strip().split('\n')
        has_structure = any(indicator in proposal_text.lower() 
                          for indicator in ['introduction', 'requirements', 'deliverables', 'timeline'])
        
        if len(lines) < 3:
            clarity_score = 0.3
        elif not has_structure:
            clarity_score = 0.5  # Has content but lacks structure
        elif len(lines) < 10:
            clarity_score = 0.7
        else:
            clarity_score = min(1.0, 0.7 + (len(lines) - 10) / 20)

        # Complexity score - estimate based on code-like patterns
        complexity_keywords = ['implement', 'build', 'develop', 'integrate', 
                              'refactor', 'optimize', 'restructure']
        complexity_count = sum(1 for line in lines 
                             if any(kw in line.lower() for kw in complexity_keywords))
        
        complexity_score = min(0.9, max(0.2, 0.3 + complexity_count / 15))

        # Deliverable structure assessment
        has_implementation = 'implementation' in proposal_text.lower()
        has_code = 'code' in proposal_text.lower()
        has_steps = 'steps' in proposal_text.lower() or 'plan' in proposal_text.lower()
        
        if has_implementation or has_steps:
            deliverable_structure = "good"
        elif has_code and len(proposal_text) > 200:
            deliverable_structure = "moderate"
        else:
            deliverable_structure = "poor"

        # Identify potential issues
        potential_bugs = []
        missing_sections = []
        
        vague_terms = ['fast', 'quickly', 'easily', 'simple']
        has_vague = any(term in proposal_text.lower() for term in vague_terms)
        if has_vague and len(proposal_text) > 100:
            potential_bugs.append("Uses vague terms like 'fast' or 'quick' without specifics")
        
        if 'deadline' not in proposal_text.lower() and 'time' in proposal_text.lower():
            missing_sections.append("Missing explicit timeline/deadline specification")
        
        if 'budget' not in proposal_text.lower() and 'cost' not in proposal_text.lower():
            missing_sections.append("Missing budget discussion")

        # Quality score calculation
        quality_score = (
            clarity_score * 0.3 +
            complexity_score * 0.2 +
            (0.5 if deliverable_structure == "good" else 
             0.3 if deliverable_structure == "moderate" else 0.1) * 0.3 +
            (0.5 if not potential_bugs else 0.3) * 0.2
        )

        recommendations = self._generate_recommendations(
            clarity_score, deliverable_structure, potential_bugs, missing_sections
        )

        metrics = ProposalMetrics(
            proposal_id=proposal_id or f"prop_{fingerprint(proposal_text[:100])}",
            clarity_score=round(clarity_score, 2),
            complexity_score=round(complexity_score, 2),
            deliverable_structure=deliverable_structure,
            potential_bugs=potential_bugs,
            missing_sections=missing_sections,
            quality_score=round(quality_score, 2),
            recommendations=recommendations,
            can_submit=quality_score >= 0.7
        )

        self._metrics_store.append(metrics)
        return metrics

    def _generate_recommendations(self, clarity: float, structure: str, 
                                 bugs: List[str], missing: List[str]) -> List[str]:
        """Generate actionable improvement recommendations."""
        recs = []
        
        if clarity < 0.6:
            recs.append("Add clear requirements section with numbered items")
        
        if structure == "poor":
            recs.append("Include 'Deliverables' and 'Timeline' sections")
        
        if missing:
            recs.extend([f"Add: {m}" for m in missing[:2]])
        
        if not bugs and structure in ["good", "moderate"]:
            recs.append("Proposal quality is strong - ready to submit")
        
        return recs[:4]  # Limit recommendations

    # ── Job Search Evaluation ────────────────────────────────────────────────

    def evaluate_job_listing(self, job_record: dict, reputation: Optional[dict] = None) -> dict:
        """
        Evaluate a job listing for proposal quality potential.

        Returns dict with:
        - fit_score: 0-1 match between job and team skills
        - clarity_score: how clear the job requirements are
        - expected_quality: predicted proposal quality (0-1)
        - recommended_action: "apply", "research", "pass"
        - win_rate_flag: True if auto-declined by the A5 win-rate guard
          (reputation below the configured threshold with enough samples).
        """
        skills = job_record.get('skills', [])
        description = job_record.get('description', '')
        title = job_record.get('title', '')
        budget = job_record.get('budget', 0)
        platform = job_record.get('platform', 'unknown')

        # Skill overlap with MrBot1000's known skills
        team_skills = ['Python', 'PySide6', 'Qt', 'SQLite', 'LLM integration',
                      'automation', 'web scraping', 'data analysis', 'REST APIs',
                      'freelance proposal writing', 'AI agents', 'Ollama']

        skill_overlap = len(set(s.lower() for s in skills) &
                           set(s.lower() for s in team_skills))
        fit_score = min(1.0, skill_overlap / max(len(skills), 1) * 1.5)

        # Clarity assessment
        clarity = self._assess_job_clarity(title, description)

        # Expected proposal quality
        expected_quality = (fit_score * 0.6 + clarity * 0.4)

        # Recommendation
        if expected_quality >= 0.6 and budget >= 50:
            action = "apply"
        elif expected_quality >= 0.4 and budget >= 30:
            action = "research"
        else:
            action = "pass"

        # A5: win-rate feedback loop. If a platform has a proven poor win-rate
        # (enough samples below the configured threshold), auto-decline it so we
        # stop wasting proposals + LLM $ on losers. Cold-start safe (no reputation
        # provided, or too few samples => no decline).
        win_rate_flag = False
        notes = []
        if reputation is not None:
            try:
                from agents.win_rate_guard import WinRateGuard
                g = WinRateGuard.from_env()
                if g.should_decline(reputation):
                    win_rate_flag = True
                    action = "pass"
                    rate = reputation.get("success_rate", 0.0)
                    notes.append(
                        f"auto-declined: {platform} win-rate {rate:.0%} < "
                        f"{g.decline_below:.0%} over {reputation.get('total', 0)} attempts")
            except Exception:
                pass

        return {
            'job_id': job_record.get('job_id'),
            'platform': platform,
            'fit_score': round(fit_score, 2),
            'clarity_score': clarity,
            'expected_quality': round(expected_quality, 2),
            'recommended_action': action,
            'win_rate_flag': win_rate_flag,
            'skills_matched': skill_overlap,
            'budget_usd': budget,
            'notes': "; ".join(notes)
        }

    def _assess_job_clarity(self, title: str, description: str) -> float:
        """Assess how clear a job listing's requirements are."""
        text = (title + ' ' + description).lower()
        
        # Good indicators of clarity
        good_indicators = [
            'requirements:', 'must have', 'will provide', 'deliverable',
            'specification', 'criteria', 'milestones', 'timeline'
        ]
        good_count = sum(1 for ind in good_indicators if ind in text)
        
        # Vague indicators (reduce clarity)
        vague_indicators = ['flexible', 'nice to have', 'want to', 'should be able']
        vague_count = sum(1 for ind in vague_indicators if ind in text)
        
        # Calculate clarity
        if not description:
            return 0.3
        
        base_clarity = min(0.9, max(0.3, good_count * 0.2 + 0.5))
        penalty = min(0.3, vague_count * 0.1)
        
        return round(max(0.2, base_clarity - penalty), 2)

    # ── Metrics Report Generation ────────────────────────────────────────────

    def generate_metrics_report(self) -> dict:
        """
        Generate a comprehensive report on proposal quality metrics.
        
        Returns aggregated statistics and insights.
        """
        if not self._metrics_store:
            return {
                'status': 'no_metrics_available',
                'total_proposals': 0,
                'message': 'No proposals have been analyzed yet'
            }

        qualities = [m.quality_score for m in self._metrics_store]
        clarities = [m.clarity_score for m in self._metrics_store]
        complexities = [m.complexity_score for m in self._metrics_store]
        
        stats = {
            'total_proposals': len(self._metrics_store),
            'average_quality': round(sum(qualities) / len(qualities), 2),
            'average_clarity': round(sum(clarities) / len(clarities), 2),
            'average_complexity': round(sum(complexities) / len(complexities), 2),
            'submissions_recommended': sum(1 for m in self._metrics_store if m.can_submit),
            'low_quality_count': sum(1 for q in qualities if q < 0.5),
            'by_structure': {
                'good': sum(1 for m in self._metrics_store if m.deliverable_structure == 'good'),
                'moderate': sum(1 for m in self._metrics_store if m.deliverable_structure == 'moderate'),
                'poor': sum(1 for m in self._metrics_store if m.deliverable_structure == 'poor')
            }
        }

        # Top issues identified
        all_bugs = [bug for m in self._metrics_store for bug in m.potential_bugs]
        all_missing = [s for m in self._metrics_store for s in m.missing_sections]
        
        from collections import Counter
        common_bugs = [item for item, count in Counter(all_bugs).most_common(3)]
        common_missing = [item for item, count in Counter(all_missing).most_common(3)]

        stats['common_issues'] = {
            'frequent_bugs': common_bugs,
            'frequently_missing': common_missing
        }

        return stats

    def clear_metrics(self):
        """Clear stored metrics."""
        self._metrics_store.clear()

    # ── Worker Interface ────────────────────────────────────────────────────────

    def run_analysis_cycle(self, proposals: List[dict]) -> List[ProposalMetrics]:
        """
        Analyze a batch of proposals and return metrics.
        
        Use this for batch processing of job listings or proposal drafts.
        """
        results = []
        for i, prop in enumerate(proposals):
            text = prop.get('description', '') or prop.get('title', '')
            metrics = self.analyze_proposal(
                text, 
                prop.get('id') or prop.get('job_id') or f"batch_{i}"
            )
            results.append(metrics)
        return results