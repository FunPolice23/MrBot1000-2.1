# MrBot1000 2.1 — Dual-Brain AI Earning Agent

A local-first, human-gated AI agent that helps you earn money across multiple paths:
freelance, micro-tasks, crypto, bounties, and trading.

## 🧠 Dual-Brain Architecture

- **Marcus (Big Brain)** — 7B-14B model on primary GPU (strategy, deep reasoning, writing)
- **Alex (Small Brain)** — 1.5B-3B model on secondary GPU (chat, review, fast responses)
- Both collaborate on tasks, catch each other's mistakes, and require human approval for real-money actions

## 🚀 Quick Start

1. Clone the repo
2. Copy `.env.example` to `.env` and fill in your API keys
3. Install dependencies: `pip install -r requirements.txt`
4. Start llama.cpp with your models
5. Run: `python main.py`

## 📁 Project Structure

```
MrBot1000_2.0/
├── main.py                 # Application entry point
├── agents/                 # AI agent logic
│   ├── big_brain.py        # Primary reasoning engine
│   ├── small_brain.py      # Secondary chat/review engine
│   ├── earning_pipeline.py # Multi-path earning orchestrator
│   ├── goal_system.py      # Goal tracking
│   ├── event_logger.py     # Hash-chained audit ledger
│   ├── alerting.py         # Real-time alerting rules
│   └── ...
├── gui/                    # PySide6 desktop interface
│   ├── dual_brain_control.py
│   ├── earning_tab.py
│   ├── analytics_tab.py
│   └── ...
├── prompts/                # System prompts for each brain
├── skills/                 # Agent skill definitions
├── scripts/                # Launch scripts (llama.cpp, LM Studio)
├── tests/                  # Test suite
├── requirements.txt        # Python dependencies
└── README.md
```

## 🛡️ Safety First

- **Every real-money action requires explicit human approval**
- **Cost caps** prevent runaway LLM spending
- **Hash-chained audit ledger** for tamper-evident records
- **Survival tiers** reduce spending when credits are low

## 📊 Earning Paths

| Path | Description | Status |
|------|-------------|--------|
| Freelance | Upwork/Fiverr proposal writing | ✅ |
| Micro-tasks | Prolific/DataAnnotation | ✅ |
| Crypto | On-chain payments | ✅ |
| Bounty | GitHub/Gitcoin bounties | 🔜 |
| Trading | Paper → Live trading | 🔜 |
| Content | Content marketing | 🔜 |

## 📜 License

See LICENSE file for details.

## 🤝 Contributing

PRs welcome! See CONTRIBUTING.md for guidelines.
