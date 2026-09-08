# Agent implementations for MrBot1000
# Note: Agents are imported directly in main.py and manager.py
# using from agents.<module> import <class> syntax

from .airdrop_scanner import AirdropScanner, AirdropOpportunity
from .base_worker import WorkerAgent
from .job_search_worker import JobSearchWorker
from .shared_context import SharedContext
from .social_earning_platform import SocialEarningPlatform

__all__ = [
    'WorkerAgent',
    'JobSearchWorker',
    'SharedContext',
    'AirdropScanner',
    'AirdropOpportunity',
    'SocialEarningPlatform',
]
