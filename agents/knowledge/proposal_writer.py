"""
agents/proposal_writer.py — Proposal/cover letter writer for freelance gigs (v2.1 Path 1).

Generates tailored proposals from opportunity descriptions.
Does NOT submit — only produces draft text for human review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProposalDraft:
    """A generated proposal draft."""
    opportunity_id: str
    platform: str
    title: str
    body: str
    skills_matched: List[str] = field(default_factory=list)
    estimated_bid: str = ""
    status: str = "draft"
    raw: Dict = field(default_factory=dict)


class ProposalWriter:
    """Write tailored proposals for freelance opportunities."""

    def __init__(self, persona_name: str = "Jacob"):
        self.persona_name = persona_name

    def write(self, opportunity: Dict[str, Any], tone: str = "professional") -> ProposalDraft:
        """Write a proposal for an opportunity."""
        title = opportunity.get("title", "")
        description = opportunity.get("description", "")
        platform = opportunity.get("platform", "unknown")
        skills = opportunity.get("skills", [])
        budget = opportunity.get("budget", "")

        body = self._generate_body(title, description, skills, tone)
        bid = self._estimate_bid(budget, description)

        return ProposalDraft(
            opportunity_id=opportunity.get("url", ""),
            platform=platform,
            title=title,
            body=body,
            skills_matched=skills[:5],
            estimated_bid=bid,
            raw=opportunity,
        )

    def _generate_body(self, title: str, description: str, skills: List[str], tone: str) -> str:
        """Generate proposal body."""
        intro = self._pick_intro(tone)
        skill_line = self._pick_skill_line(skills)
        evidence = self._pick_evidence(skills)
        close = self._pick_close(tone)

        paragraphs = []
        if intro:
            paragraphs.append(intro)
        paragraphs.append(f"I read your post: \"{title}\".")
        paragraphs.append(f"{skill_line}.")
        if evidence:
            paragraphs.append(f"{evidence}")
        paragraphs.append(f"{close}.")
        return "\n\n".join(paragraphs)

    def _pick_intro(self, tone: str) -> str:
        if tone == "casual":
            return "Hey — quick note on this."
        elif tone == "formal":
            return "Dear Hiring Manager,"
        return "Hi there, I reviewed your posting."

    def _pick_skill_line(self, skills: List[str]) -> str:
        if skills:
            return f"This aligns with my work in: {', '.join(skills[:3])}"
        return "I can deliver this cleanly and on time."

    def _pick_evidence(self, skills: List[str]) -> str:
        if not skills:
            return ""
        if "python" in skills or "automation" in skills:
            return "Recent similar work involved Python automation and reliable delivery."
        if "writing" in skills or "research" in skills:
            return "I focus on clear writing and sourced research with fast turnaround."
        return "I can adapt quickly to the specific requirements here."

    def _pick_close(self, tone: str) -> str:
        if tone == "casual":
            return "Let me know if you want examples or a quick call"
        return "Happy to share examples or answer questions before you decide."

    @staticmethod
    def _estimate_bid(budget: str, description: str) -> str:
        """Estimate a reasonable bid."""
        if not budget or budget == "Not specified":
            return "TBD / rate-based"
        # Extract numbers from budget text
        nums = re.findall(r'[\d,]+', budget)
        if nums:
            try:
                val = float(nums[0].replace(",", ""))
                if val < 50:
                    return f"${val:.0f}"
                elif val < 500:
                    return f"${val:.0f}-${val*1.2:.0f}"
                else:
                    return f"${val:.0f} or fixed-price"
            except ValueError:
                pass
        return "TBD"

    def batch_write(self, opportunities: List[Dict[str, Any]], tone: str = "professional") -> List[ProposalDraft]:
        """Write proposals for multiple opportunities."""
        return [self.write(opp, tone) for opp in opportunities]
