# ═══════════════════════════════════════════════════════════════════════════
# PROGRAM KNOWLEDGE BASE — v2.1
# ═══════════════════════════════════════════════════════════════════════════
# PURPOSE: Both brains understand what MrBot1000 is, how it works,
#          and can access persistent memory that grows over time.
#
# TO REMOVE: Delete this file and remove imports from agents/big_brain.py
#            and agents/small_brain.py
# ═══════════════════════════════════════════════════════════════════════════

import os
import sys
import json
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "dual_brain.db"


class ProgramKnowledge:
    """Static knowledge about MrBot1000 that both brains need."""
    
    PROGRAM_NAME = "MrBot1000"
    PROGRAM_VERSION = "2.1"
    PROGRAM_PURPOSE = "AI-Powered Online Income & Crypto Opportunity Engine"
    
    CORE_IDENTITY = """
    MrBot1000 is a local-first AI system that discovers, analyzes, and executes
    online earning opportunities. It runs entirely on the user's hardware with
    no cloud dependencies. The system uses two AI brains working together:
    
    - Small Brain (fast, 4B parameters): Handles casual chat, quick tasks,
      pre-filtering opportunities, and relays complex work to Big Brain.
      Runs on GTX 1660 Super (6 GB) via Ollama.
    
    - Big Brain (smart, 14B-27B parameters): Handles deep analysis, complex
      reasoning, multi-step planning, coding, and verification.
      Runs on RTX 5060 Ti (16 GB) via LM Studio.
    
    The human operator is the final decision-maker. Both brains assist,
    advise, and execute tasks, but the human approves all actions.
    """
    
    CORE_CAPABILITIES = """
    MrBot1000 can:
    1. Discover earning opportunities (freelance, microtasks, airdrops, etc.)
    2. Analyze opportunities for payout, risk, and time estimate
    3. Detect scams and flag suspicious offers
    4. Generate proposals and cover letters
    5. Track opportunities through their lifecycle
    6. Execute safe, repeatable actions (form filling, claims)
    7. Learn from outcomes to improve future decisions
    8. Manage multiple income streams simultaneously
    """
    
    SAFETY_RULES = """
    CRITICAL SAFETY CONSTRAINTS:
    1. No illegal activities (click fraud, fake reviews, identity theft)
    2. Respect robots.txt and rate limits on all platforms
    3. Human must approve: spending money, signing contracts, sharing sensitive data
    4. Use dedicated low-balance wallet for crypto actions
    5. Simulate smart contract calls before executing
    6. Never share user data with third parties
    7. All high-risk actions require explicit human confirmation
    """
    
    ARCHITECTURE = """
    SYSTEM ARCHITECTURE:
    - GUI: PySide6 desktop application with tabbed interface
    - Data: SQLite databases (agent.db, earning.db, job_search.db)
    - AI: Dual-brain setup (Ollama + LM Studio)
    - Discovery: RSS feeds, Reddit, web scraping, platform APIs
    - Execution: Playwright browser automation, API clients
    - Learning: Outcome tracking, reputation database, memory system
    
    FILE STRUCTURE:
    - main.py: Main application window and tab management
    - agents/: Worker agents for discovery, analysis, execution
    - gui/: UI components (chat_tab, dialogue_tab, dual_brain_control)
    - prompts/: System prompts for both brains
    - scripts/: Startup scripts for Ollama and LM Studio
    """
    
    USER_PREFERENCES = """
    USER PROFILE:
    - Skills: Python, web scraping
    - Availability: 4 hours/day
    - Payment preference: USD (no crypto)
    - Platform avoidlist: Fiverr (high fees)
    - Risk tolerance: Medium
    - Goals: Earn $500/week online
    """


class MemoryDatabase:
    """Persistent memory storage for both brains."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize the database tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    source TEXT DEFAULT 'conversation',
                    tags TEXT DEFAULT '',
                    expires_at TEXT
                );
                
                CREATE TABLE IF NOT EXISTS personality_traits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brain TEXT NOT NULL,
                    trait TEXT NOT NULL,
                    value REAL DEFAULT 0.5,
                    last_updated TEXT NOT NULL,
                    UNIQUE(brain, trait)
                );
                
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    outcome TEXT,
                    success INTEGER,
                    lesson TEXT
                );
                
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    brain TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    context TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
                CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
                CREATE INDEX IF NOT EXISTS idx_conversations_brain ON conversations(brain);
                CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp);
            """)
    
    def add_memory(self, category: str, title: str, content: str,
                   importance: float = 0.5, source: str = "conversation",
                   tags: str = "", expires_days: int = None):
        """Add a new memory."""
        expires_at = None
        if expires_days:
            expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO memories (timestamp, category, title, content, importance, source, tags, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), category, title, content, importance, source, tags, expires_at))
    
    def get_memories(self, category: str = None, limit: int = 10,
                     min_importance: float = 0.0) -> List[Dict]:
        """Retrieve memories, optionally filtered by category."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM memories WHERE importance >= ?"
            params = [min_importance]
            
            if category:
                query += " AND category = ?"
                params.append(category)
            
            query += " ORDER BY importance DESC, timestamp DESC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
    
    def search_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """Search memories by content."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM memories 
                WHERE content LIKE ? OR title LIKE ? OR tags LIKE ?
                ORDER BY importance DESC, timestamp DESC LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
            return [dict(row) for row in rows]
    
    def log_conversation(self, brain: str, role: str, message: str, context: str = ""):
        """Log a conversation turn."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO conversations (timestamp, brain, role, message, context)
                VALUES (?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), brain, role, message, context))
    
    def get_conversation_history(self, brain: str, limit: int = 20) -> List[Dict]:
        """Get recent conversation history for a brain."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM conversations 
                WHERE brain = ? 
                ORDER BY timestamp DESC LIMIT ?
            """, (brain, limit)).fetchall()
            return [dict(row) for row in rows]
    
    def update_personality(self, brain: str, trait: str, value: float):
        """Update a personality trait for a brain."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO personality_traits (brain, trait, value, last_updated)
                VALUES (?, ?, ?, ?)
            """, (brain, trait, max(0.0, min(1.0, value)), datetime.now().isoformat()))
    
    def get_personality(self, brain: str) -> Dict[str, float]:
        """Get all personality traits for a brain."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT trait, value FROM personality_traits WHERE brain = ?
            """, (brain,)).fetchall()
            return {row["trait"]: row["value"] for row in rows}
    
    def log_decision(self, decision: str, outcome: str = None, success: int = None, lesson: str = ""):
        """Log a decision and its outcome for learning."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO decisions (timestamp, decision, outcome, success, lesson)
                VALUES (?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), decision, outcome, success, lesson))
    
    def get_lessons(self, limit: int = 10) -> List[Dict]:
        """Get recent lessons learned from decisions."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM decisions 
                WHERE lesson IS NOT NULL AND lesson != ''
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]


class PersonalityEngine:
    """Dynamic personality system that evolves based on interactions."""
    
    TRAIT_DEFINITIONS = {
        "friendliness": "How warm and approachable the brain is",
        "assertiveness": "How confidently the brain makes recommendations",
        "caution": "How carefully the brain evaluates risks",
        "creativity": "How creatively the brain approaches problems",
        "detail_orientation": "How much detail the brain provides",
        "humor": "How much humor the brain uses",
        "proactivity": "How proactively the brain suggests opportunities",
        "skepticism": "How skeptical the brain is of too-good-to-be-true offers",
        "empathy": "How well the brain understands user frustrations",
        "efficiency": "How concise vs thorough the brain is"
    }
    
    def __init__(self, db: MemoryDatabase):
        self.db = db
    
    def get_system_prompt_addon(self, brain: str) -> str:
        """Generate a personality addon for the system prompt."""
        traits = self.db.get_personality(brain)
        
        if not traits:
            return ""
        
        # Find dominant traits (top 3)
        sorted_traits = sorted(traits.items(), key=lambda x: x[1], reverse=True)
        dominant = sorted_traits[:3]
        
        addon = "\n\n## YOUR PERSONALITY\n"
        addon += "Your personality has evolved based on interactions:\n"
        
        for trait, value in dominant:
            if value > 0.7:
                level = "very high"
            elif value > 0.5:
                level = "high"
            elif value > 0.3:
                level = "moderate"
            else:
                level = "low"
            
            addon += f"- {trait.replace('_', ' ').title()}: {level}\n"
        
        addon += "\nAdapt your communication style accordingly.\n"
        
        return addon
    
    def evolve_from_interaction(self, brain: str, user_message: str, response: str):
        """Evolve personality based on interaction patterns."""
        # Simple heuristic-based evolution
        # In a real system, this could use another LLM call to analyze the interaction
        
        # If user asks direct questions, increase efficiency
        if len(user_message) < 50:
            self._adjust_trait(brain, "efficiency", 0.05)
        
        # If response is long, decrease efficiency slightly
        if len(response) > 1000:
            self._adjust_trait(brain, "efficiency", -0.02)
        
        # If user asks about risks, increase caution
        if any(word in user_message.lower() for word in ["risk", "safe", "scam", "trust"]):
            self._adjust_trait(brain, "caution", 0.03)
        
        # If user asks for opportunities, increase proactivity
        if any(word in user_message.lower() for word in ["find", "opportunity", "earn", "money", "gig"]):
            self._adjust_trait(brain, "proactivity", 0.03)
    
    def _adjust_trait(self, brain: str, trait: str, delta: float):
        """Adjust a personality trait."""
        traits = self.db.get_personality(brain)
        current = traits.get(trait, 0.5)
        new_value = max(0.0, min(1.0, current + delta))
        self.db.update_personality(brain, trait, new_value)


# ═══════════════════════════════════════════════════════════════════════════
# KNOWLEDGE CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════════════════
class KnowledgeContext:
    """Builds context from knowledge base and memory for injection into prompts."""
    
    def __init__(self, db: MemoryDatabase):
        self.db = db
    
    def build_context(self, brain: str, query: str = "") -> str:
        """Build a context string for the given brain and query."""
        context_parts = []
        
        # Add program knowledge
        context_parts.append(f"# {ProgramKnowledge.PROGRAM_NAME} v{ProgramKnowledge.PROGRAM_VERSION}")
        context_parts.append(ProgramKnowledge.CORE_IDENTITY)
        
        # Add relevant memories
        if query:
            memories = self.db.search_memories(query, limit=5)
        else:
            memories = self.db.get_memories(limit=5, min_importance=0.5)
        
        if memories:
            context_parts.append("\n## RELEVANT MEMORIES")
            for mem in memories:
                context_parts.append(f"- [{mem['category']}] {mem['title']}: {mem['content'][:200]}")
        
        # Add lessons learned
        lessons = self.db.get_lessons(limit=3)
        if lessons:
            context_parts.append("\n## LESSONS LEARNED")
            for lesson in lessons:
                context_parts.append(f"- {lesson['lesson'][:200]}")
        
        # Add recent conversation history
        history = self.db.get_conversation_history(brain, limit=5)
        if history:
            context_parts.append("\n## RECENT CONVERSATION")
            for h in reversed(history):
                context_parts.append(f"{h['role']}: {h['message'][:100]}")

        # Domain state is read-only and bounded so both brains can reason from
        # the same live workspace without gaining a second action pathway.
        try:
            from agents.workspace_context import build_workspace_context
            context_parts.append(build_workspace_context())
        except Exception:
            pass
        
        return "\n".join(context_parts)


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCES
# ═══════════════════════════════════════════════════════════════════════════
_db = None
_personality = None
_knowledge = None

def get_database() -> MemoryDatabase:
    """Get or create the memory database singleton."""
    global _db
    if _db is None:
        _db = MemoryDatabase()
    return _db

def get_personality_engine() -> PersonalityEngine:
    """Get or create the personality engine singleton."""
    global _personality
    if _personality is None:
        _personality = PersonalityEngine(get_database())
    return _personality

def get_knowledge_context() -> KnowledgeContext:
    """Get or create the knowledge context singleton."""
    global _knowledge
    if _knowledge is None:
        _knowledge = KnowledgeContext(get_database())
    return _knowledge
