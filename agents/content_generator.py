"""
agents/content_generator.py — Content generation for earning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .base_worker import WorkerAgent


class ContentGenerator:
    """Generates content for crypto projects that pay in tokens."""

    def __init__(self, worker: WorkerAgent):
        self.worker = worker

    def draft_blog_post(self, topic: str,
                          keywords: List[str] = None,
                          tone: str = "professional") -> str:
        prompt = (
            f"Write a {tone} blog post about: {topic}\n"
            f"Keywords to include: {', '.join(keywords or [])}\n"
            f"Length: 500-800 words.\n"
            f"Include a clear introduction, body with subheadings, "
            f"and conclusion.\n"
            f"Focus on providing genuine value, not promotional fluff."
        )
        return self.worker.llm(
            system="You are a technical content writer.",
            user=prompt,
        )

    def draft_social_post(self, topic: str,
                            platform: str = "twitter",
                            tone: str = "engaging") -> str:
        prompt = (
            f"Write a {platform} post about: {topic}\n"
            f"Tone: {tone}\n"
            f"Include relevant hashtags.\n"
            f"Max 280 characters for Twitter, 150 words for other "
            f"platforms."
        )
        return self.worker.llm(
            system="You are a social media content writer.",
            user=prompt,
        )

    def draft_github_contribution(self, repo_url: str,
                                    issue_number: int = None) -> str:
        issue_part = (
            f"Issue #{issue_number}" if issue_number
            else "General contribution"
        )
        prompt = (
            f"Draft a professional GitHub contribution for: "
            f"{repo_url}\n{issue_part}\n"
            f"Include: what was changed, why it matters, and any "
            f"relevant context."
        )
        return self.worker.llm(
            system="You are a technical writer for open source.",
            user=prompt,
        )

    def find_content_opportunities(self) -> List[dict]:
        return [
            {
                "platform": "Mirror.xyz",
                "type": "blog",
                "pay": "crypto",
                "description": "Publish articles and earn crypto tokens",
            },
            {
                "platform": "Hive",
                "type": "blog",
                "pay": "crypto",
                "description": "Write and earn HIVE tokens",
            },
            {
                "platform": "Lens Protocol",
                "type": "social",
                "pay": "crypto",
                "description": "Create content and earn on Farcaster/Lens",
            },
            {
                "platform": "Gitcoin",
                "type": "github",
                "pay": "crypto",
                "description": "Contribute to open source and earn grants",
            },
            {
                "platform": "BountyBoard",
                "type": "github",
                "pay": "crypto",
                "description": "Find bounties for crypto project contributions",
            },
        ]