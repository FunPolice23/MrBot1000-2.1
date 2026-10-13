<!-- generated 53 files -->

### `agents/earning/__init__.py` — Canonical earning-domain services and adapters. (80L)


### `agents/earning/accounting.py` — Accounting projections for earning reports. (37L)

**Functions:**
- `accounting_projection(portfolio=..., accounting=..., lifecycle=...) -> dict` (L8) — Build verified/unverified revenue and expense fields for a report.


### `agents/earning/airdrop_claimer.py` — agents/airdrop_claimer.py — Simulate-then-confirm airdrop claims for MrBot1000. (215L)

**Classes:**
- `class ClaimPlan` (L22) — A simulated claim: what *would* happen, before any network action.
- `class AirdropClaimer` (L38) — Simulates airdrop claims; requires explicit confirmation to execute.
  - `__init__(session: requests.Session=None, evidence_store=None)` (L41)
  - `plan(airdrop: AirdropOpportunity) -> ClaimPlan` (L56) — Build a claim plan WITHOUT touching the network (pure simulation).
  - `is_safe_to_claim(airdrop: AirdropOpportunity) -> bool` (L84) — Determine if an airdrop is safe to auto-claim (heuristic only).
  - `_find_action_url(airdrop: AirdropOpportunity) -> Optional[str]` (L94) — Best-effort: extract the claim action URL from the claim page.
  - `claim(airdrop: AirdropOpportunity, confirm_cb: Optional[Callable[, ...) -> ClaimPlan` (L119) — Simulate, then execute ONLY if confirmed.
  - `claim_batch(airdrops: List[AirdropOpportunity], confirm_cb: Optional[Callable[[ClaimPlan],=None) -> dict` (L192) — Simulate/claim a batch. Without `confirm_cb`, only plans are produced


### `agents/earning/airdrop_scanner.py` — agents/airdrop_scanner.py — Crypto airdrop monitoring for MrBot1000. (330L)

**Classes:**
- `class AirdropOpportunity` (L28)
- `class AirdropScanner` (L45) — Scans for crypto airdrop opportunities from RSS feeds.
  - `__init__()` (L48)
  - `_parse_feed(feed_url: str)` (L96) — Parse an RSS/Atom feed, falling back to stdlib XML when feedparser is unavailable.
  - `_is_guide_article(title: str) -> bool` (L133) — True when a title is an explainer/roundup rather than a claimable drop.
  - `_rotate_window(items: list, page: int, size: int) -> list` (L139) — Return a rotating window over ``items`` that wraps around.
  - `scan_feeds(query: Optional[str]=None, page: int=1) -> List[AirdropOpportunity]` (L156) — Scan a page of the configured feeds for claimable airdrops.
  - `_is_airdrop_related(text: str) -> bool` (L189) — Return whether feed text is relevant to airdrop discovery.
  - `_parse_entry(entry: dict, combined_text: str) -> Optional[AirdropOpportunity]` (L194) — Convert a feed entry into a structured opportunity.
  - `_assess_risk(text: str, url: str) -> str` (L223) — Classify obvious airdrop scam indicators conservatively.
  - `_should_process(title: str) -> bool` (L238) — Check if this looks like an airdrop opportunity.
  - `_evaluate_opportunity(feed: str, url: str, title: str, description: str) -> Optional[AirdropOpportunity]` (L243) — Evaluate an opportunity and estimate its value.
  - `scan() -> List[AirdropOpportunity]` (L301) — Scan all feeds and return discovered opportunities.


### `agents/earning/backtesting.py` — agents/backtesting.py — Strategy backtesting engine (v2.1 Phase 2). (341L)

**Classes:**
- `class SignalType(Enum)` (L21)
- `class Trade` (L28) — Simulated trade.
- `class BacktestResult` (L40) — Results of a backtest run.
- `class Strategy` (L61) — Base class for trading strategies.
  - `generate_signal(data: Dict) -> SignalType` (L66) — Generate a trading signal from market data.
  - `get_parameters() -> Dict` (L70) — Get strategy parameters.
  - `set_parameters(params: Dict)` (L74) — Set strategy parameters.
- `class MovingAverageCrossover(Strategy)` (L79) — Moving Average Crossover strategy.
  - `__init__(fast_period: int=10, slow_period: int=30)` (L84)
  - `generate_signal(data: Dict) -> SignalType` (L88)
  - `get_parameters() -> Dict` (L108)
- `class RSIStrategy(Strategy)` (L112) — Relative Strength Index strategy.
  - `__init__(period: int=14, overbought: float=70, oversold: float=30)` (L117)
  - `generate_signal(data: Dict) -> SignalType` (L122)
  - `get_parameters() -> Dict` (L155)
- `class BacktestEngine` (L159) — Backtest trading strategies on historical data.
  - `__init__(initial_balance: float=10000.0, fee_pct: float=0.001)` (L162)
  - `run(strategy: Strategy, data: List[Dict], symbol: str='UNKNOWN') -> BacktestResult` (L167) — Run a backtest.
  - `compare_strategies() -> List[Dict]` (L292) — Compare all backtested strategies.
  - `get_best_strategy() -> Optional[BacktestResult]` (L311) — Get the best performing strategy by Sharpe ratio.
  - `generate_report(result: BacktestResult) -> str` (L317) — Generate a text report for a backtest result.


### `agents/earning/capabilities.py` — capability_registry.py — extensible capability taxonomy + system capability registry (v2.0.36e). (217L)

**Functions:**
- `get_default_registry() -> CapabilityRegistry` (L215)

**Classes:**
- `class CapabilityCategory(str, Enum)` (L26) — Seed taxonomy. The system stays extensible: any string token is a valid capability,
  - `values() -> List[str]` (L49)
- `class CapabilitySpec` (L54) — Authoritative description of ONE capability and what the system can do with it.
- `class CapabilityRegistry` (L75) — Single source of truth: which capabilities exist and what the system can do with each.
  - `__init__() -> None` (L81)
  - `register(spec: CapabilitySpec) -> None` (L86) — Register (or overwrite) a capability. Extensible by design.
  - `register_many(specs: List[CapabilitySpec]) -> None` (L90)
  - `get(name: str) -> Optional[CapabilitySpec]` (L95)
  - `all() -> List[CapabilitySpec]` (L101)
  - `by_category(category: CapabilityCategory) -> List[CapabilitySpec]` (L104)
  - `automatable() -> List[str]` (L107)
  - `_seed_defaults() -> None` (L114) — Seed the registry with the requested taxonomy AND the capabilities MrBot1000 can


### `agents/earning/capability.py` — agents/earning_capability.py — First real autonomous earning capability (v2.1 Phase 4). (303L)

**Classes:**
- `class EarningCapabilityResult` (L54) — Outcome of one earning-capability fulfillment attempt.
  - `is_approved() -> bool` (L71)
  - `to_dict() -> Dict[str, Any]` (L74)
- `class EarningCapabilityExecutor` (L95) — Deterministic, human-gated fulfillment of a single earning opportunity.
  - `__init__(portfolio: Any=None, lifecycle: Any=None, evidence_store: A, ...)` (L98)
  - `_job_id(opp: Any) -> str` (L113)
  - `_platform(opp: Any) -> str` (L116)
  - `_task_type(opp: Any) -> str` (L119)
  - `_requirements(opp: Any) -> List[str]` (L122)
  - `_gate_context(opp: Any) -> Dict[str, Any]` (L128)
  - `fulfill(opp: Any, producer: Producer, requirements: Optional[List[s, ...) -> EarningCapabilityResult` (L132) — Produce + validate + (human-gate) + locally-package an opportunity.
  - `_fail(result: EarningCapabilityResult, message: str) -> EarningCapabilityResult` (L234)
  - `_set_portfolio_status(opp_id: str, status: str, blocked_reason: str='', waiting_reason: str='') -> None` (L240)
  - `_record_lifecycle(opp_id: str, stage: str, note: str) -> None` (L260)
  - `_record_submission_evidence(opp: Any, opp_id: str, result: EarningCapabilityResult) -> str` (L271)


### `agents/earning/chain_verifier.py` — agents/chain_verifier.py — On-chain verification for airdrops (B3). (158L)

**Functions:**
- `read_balance(wm, wallet_name: str) -> Optional[WalletBalance]` (L48) — Safely read an on-chain balance. Returns None on any failure (no raise).
- `verify_eligibility(wm, wallet_name: str, airdrop=None, eligibility_fn: Optional[Callable[[str], bool]=None) -> EligibilityReport` (L62) — Confirm airdrop eligibility ON-CHAIN.
- `verify_claim_receipt(before: Optional[WalletBalance], after: Optional[WalletBala, ...) -> ReceiptReport` (L107) — Verify a claim actually delivered value, via on-chain balance delta.

**Classes:**
- `class EligibilityReport` (L24)
- `class ReceiptReport` (L32)


### `agents/earning/defi_scanner.py` — agents/defi_scanner.py — DeFi yield farming scanner for MrBot1000. (148L)

**Classes:**
- `class DeFiOpportunity` (L13)
- `class DeFiScanner` (L28) — Scans DeFi protocols for yield opportunities.
  - `__init__()` (L46)
  - `scan_all() -> List[DeFiOpportunity]` (L53) — Scan all configured protocols.
  - `_scan_protocol(name: str, config: dict) -> List[DeFiOpportunity]` (L67)
  - `filter_by_risk(opportunities: List[DeFiOpportunity], max_risk: str='medium', **signals) -> List[DeFiOpportunity]` (L101)
  - `filter_by_min_tvl(opportunities: List[DeFiOpportunity], min_tvl_usd: float=1000) -> List[DeFiOpportunity]` (L115)
  - `screen_rug_pull(opportunities: List[DeFiOpportunity], **signals) -> tuple` (L124) — Screen opportunities for rug/pull risk. Returns (passed, results).


### `agents/earning/discoverer.py` — agents/earning_discoverer.py — Dynamic earning opportunity discovery. (467L)

**Classes:**
- `class EarningOpportunity` (L24) — A generic earning opportunity discovered from the web.
- `class EarningDiscoverer` (L40) — Discovers earning opportunities dynamically from various sources.
  - `__init__(min_amount: float=1.0, page: int=1)` (L73)
  - `discover_all() -> List[EarningOpportunity]` (L77) — Discover all earning opportunities from all sources.
  - `_discover_reddit() -> List[EarningOpportunity]` (L117) — Discover earning opportunities from Reddit.
  - `_reddit_json(url: str)` (L163) — Safe Reddit JSON fetch: returns parsed dict or None on any failure.
  - `_reddit_rss(url: str)` (L183) — Return Reddit RSS items in the JSON-shaped structure used above.
  - `_discover_twitter_crypto() -> List[EarningOpportunity]` (L203) — Discover crypto earning opportunities from Twitter/X.
  - `_discover_github_bounties() -> List[EarningOpportunity]` (L224) — Discover GitHub bug bounties and feature requests.
  - `_discover_discord_bots() -> List[EarningOpportunity]` (L303) — Discover earning opportunities from Discord bots.
  - `_discover_referral_programs() -> List[EarningOpportunity]` (L319) — Discover referral program opportunities.
  - `_discover_faucets() -> List[EarningOpportunity]` (L402) — Discover crypto faucet earning opportunities.
  - `_deduplicate(opps: List[EarningOpportunity]) -> List[EarningOpportunity]` (L450) — Remove duplicate opportunities.


### `agents/earning/discovery.py` — Application service for discovery orchestration in the earning domain. (79L)

**Classes:**
- `class EarningDiscoveryService` (L11) — Run built-in discovery and project results into the legacy pipeline API.
  - `__init__(memory=..., log_fn=..., legacy_type=..., sleep_fn=...) -> None` (L14)
  - `discover(sources: Optional[List[str]]=None, on_found: Optional[Calla, ...) -> List[Any]` (L27) — Discover, persist provenance, and return legacy opportunities.


### `agents/earning/economic_accounting.py` — agents/earning/economic_accounting.py — Unified Economic Accounting Layer (v2.0.36j). (536L)

**Functions:**
- `is_convertible(currency: str, rates: Optional[Dict[str, float]]=None) -> bool` (L196) — True iff `currency` has a known USD rate (ARCH-ENG-092).
- `_record_unconvertible(bucket: Dict[str, float], currency: str, amount: float) -> None` (L207) — Accumulate a native, unvalued amount into `bucket` keyed by currency.
- `to_usd(amount: float, currency: str, rates: Optional[Dict[str, float]]=None) -> float` (L218) — Convert an amount in `currency` to USD equivalent.

**Classes:**
- `class ExpenseCategory(str, Enum)` (L35)
- `class EconomicProfile` (L48) — Complete economic picture for one opportunity.
  - `to_dict() -> dict` (L117)
- `class EconomicAccounting` (L275) — Pure compute layer over EvidenceStore. No DB writes.
  - `__init__(evidence_store: Any, rates: Optional[Dict[str, float]]=None)` (L278)
  - `get_profile(opportunity_id: str, opportunity: Any=None, intel_verdict: , ...) -> EconomicProfile` (L284) — Build a complete EconomicProfile for an opportunity.
  - `aggregate(profiles: List[EconomicProfile]) -> Dict[str, Any]` (L415) — Aggregate metrics across multiple opportunities (for portfolio-level reporting).
  - `get_verified_revenue(opportunity_id: str) -> float` (L493) — Quick accessor: verified revenue for one opportunity.
  - `get_total_expenses(opportunity_id: str) -> float` (L512) — Quick accessor: total verified expenses for one opportunity.


### `agents/earning/economic_policy.py` — Typed economic predictions and deterministic decision policy. (265L)

**Functions:**
- `evaluate_prediction(prediction: EconomicPrediction, policy: DecisionPolicy, now, ...) -> DecisionResult` (L197) — Apply deterministic gates and thresholds without changing the prediction.

**Classes:**
- `class DecisionAction(str, Enum)` (L16)
- `class EconomicPrediction` (L24) — Versioned, range-friendly inputs for an economic decision.
  - `expected_net_value() -> float` (L80)
  - `productive_hours() -> float` (L92)
  - `expected_hourly_return() -> float` (L101)
  - `risk_adjusted_return() -> float` (L105)
  - `is_stale(now=..., max_age_seconds=...) -> bool` (L108)
  - `to_dict() -> dict[str, object]` (L114)
- `class DecisionPolicy` (L146) — Operator/runtime constraints applied to a prediction.
- `class DecisionResult` (L178)
  - `to_dict() -> dict[str, object]` (L186)


### `agents/earning/evaluation.py` — Provider-facing semantic scoring for earning opportunities. (150L)

**Functions:**
- `evaluate_opportunity(opportunity: Any, memory=..., log_fn=..., normalize_keep_alive=...) -> Any` (L16) — Apply model scores or a deterministic fallback to an opportunity.


### `agents/earning/evidence.py` — Evidence helpers used by earning lifecycle orchestration. (94L)

**Functions:**
- `build_manual_attestation(note: str, amount: float) -> Optional[dict]` (L8) — Build pending operator evidence; it is never affirmative verification.
- `_verification_level(verification: Any) -> Optional[int]` (L27) — Read the verification trust level (L0..L5) off a state's verification record.
- `is_affirmative_verification(state: Any) -> bool` (L54) — Return true only for VERIFIED/PARTIALLY_VERIFIED payment evidence that


### `agents/earning/execution.py` — Execution dispatch for earning opportunities. (45L)

**Functions:**
- `execute_opportunity(opportunity: Any, result_type=..., airdrop_fn=..., defi_fn=, ...) -> Any` (L8) — Route an opportunity to its guarded execution adapter.


### `agents/earning/executor.py` — agents/services/task_executor.py — Generalized Task Execution Framework engine (v2.0.36i). (385L)

**Classes:**
- `class StepStatus(str, Enum)` (L36)
- `class ExecutionContext` (L48) — Tracks state through the 14-step pipeline.
- `class ExecutionPlan` (L70) — Plan for executing a task.
  - `to_dict() -> dict` (L78)
- `class ExecutionResult` (L91) — Final result of execution.
  - `to_dict() -> dict` (L99)
- `class TaskExecutor` (L111) — Drives the 14-step execution pipeline.
  - `__init__(portfolio: Any, capability_validator: Any, human_gate_manag, ...)` (L114)
  - `execute(task: Dict[str, Any], entry: Any) -> ExecutionResult` (L123) — Run the 14-step pipeline for a task.
  - `_step1_inspect_requirements(ctx: ExecutionContext) -> None` (L171) — Step 1: Inspect requirements. NEW → EVALUATING.
  - `_step2_identify_capabilities(ctx: ExecutionContext) -> None` (L186) — Step 2: Identify required capabilities.
  - `_step3_identify_tools(ctx: ExecutionContext) -> None` (L193) — Step 3: Identify available tools.
  - `_step4_determine_feasibility(ctx: ExecutionContext) -> None` (L204) — Step 4: Determine whether execution is possible. EVALUATING → QUALIFIED.
  - `_step5_create_plan(ctx: ExecutionContext) -> None` (L221) — Step 5: Create execution plan. QUALIFIED → RECOMMENDED.
  - `_step6_identify_human_actions(ctx: ExecutionContext) -> None` (L240) — Step 6: Identify required human actions. RECOMMENDED → AWAITING_APPROVAL.
  - `_step7_execute(ctx: ExecutionContext) -> None` (L252) — Step 7: Execute authorized operations. AWAITING_APPROVAL → READY → IN_PROGRESS.
  - `_step8_validate(ctx: ExecutionContext) -> None` (L262) — Step 8: Validate output. IN_PROGRESS.
  - `_step9_prepare_deliverables(ctx: ExecutionContext) -> None` (L273) — Step 9: Prepare deliverables. IN_PROGRESS → COMPLETED.
  - `_step10_submit(ctx: ExecutionContext) -> None` (L287) — Step 10: Submit through appropriate channel. COMPLETED → WAITING_EXTERNAL.
  - `_step11_wait(ctx: ExecutionContext) -> None` (L300) — Step 11: Wait for external acceptance/payment. WAITING_EXTERNAL → PAYMENT_PENDING.
  - `_step12_verify(ctx: ExecutionContext) -> None` (L307) — Step 12: Verify outcome. PAYMENT_PENDING.
  - `_step13_record_evidence(ctx: ExecutionContext) -> None` (L312) — Step 13: Record evidence. PAYMENT_PENDING.
  - `_step14_learn(ctx: ExecutionContext) -> None` (L324) — Step 14: Learn from result. PAYMENT_PENDING → PAID.
  - `_work_status_for_step(step: int) -> Any` (L333) — Map pipeline step to WorkStatus.
  - `_record_step(ctx: ExecutionContext, step: int, status: StepStatus, detail: str) -> None` (L347)
  - `_build_result(ctx: ExecutionContext, success: bool, status: str) -> ExecutionResult` (L358)
- `class ExecutionNotPossibleError(Exception)` (L373) — Raised when a task cannot be executed.


### `agents/earning/freelance_finder.py` — agents/freelance_finder.py — Real freelance opportunity hunter (v2.1 Path 1). (331L)

**Classes:**
- `class FreelanceOpportunity` (L24) — A real freelance opportunity found online.
- `class FreelanceFinder` (L37) — Find real freelance opportunities using web search.
  - `__init__(web: Optional[WebController]=None)` (L67)
  - `search(query: str, max_results: int=10, platforms: Optional[List[str]]=None) -> Dict[str, Any]` (L72) — Search for freelance opportunities.
  - `_search_platform(platform: str, query: str, max_results: int) -> List[FreelanceOpportunity]` (L107) — Search a specific platform.
  - `_search_targeted(query: str, max_results: int, search_terms: str, platform: str) -> List[FreelanceOpportunity]` (L134) — Search a marketplace family without pretending it has an API adapter.
  - `_search_upwork(query: str, max_results: int) -> List[FreelanceOpportunity]` (L152) — Search Upwork via web search.
  - `_search_fiverr(query: str, max_results: int) -> List[FreelanceOpportunity]` (L177) — Search Fiverr via web search.
  - `_search_reddit(query: str, max_results: int) -> List[FreelanceOpportunity]` (L202) — Search Reddit freelance subreddits.
  - `_search_prolific(query: str, max_results: int) -> List[FreelanceOpportunity]` (L228) — Search Prolific academic studies.
  - `_search_general(query: str, max_results: int) -> List[FreelanceOpportunity]` (L253) — General web search for freelance gigs.
  - `_extract_budget(text: str) -> str` (L278) — Extract budget info from text.
  - `_extract_skills(text: str) -> List[str]` (L294) — Extract skill keywords.
  - `_extract_time(text: str) -> str` (L307) — Extract time info.
  - `_opp_to_dict(opp: FreelanceOpportunity) -> Dict[str, Any]` (L320)


### `agents/earning/gas_estimator.py` — agents/gas_estimator.py — Gas-vs-value estimate for claims (B4). (62L)

**Functions:**
- `estimate_gas_usd(chain: str='ethereum', op_type: str='claim', override: Optional[float]=None) -> float` (L25) — Estimate the gas cost (USD) of an on-chain op.
- `gas_exceeds_value(gas_usd: float, expected_usd: float) -> bool` (L53) — True when the gas estimate is greater than the expected airdrop value.


### `agents/earning/goal_system.py` — agents/goal_system.py — Goal tracking for MrBot1000 earning tasks. (527L)

**Classes:**
- `class GoalStatus(str, Enum)` (L32)
- `class GoalPath(str, Enum)` (L39)
- `class EvidenceRow` (L50) — A single piece of verifiable proof for a goal.
  - `to_dict() -> Dict[str, Any]` (L68)
  - `from_dict(d: Dict[str, Any]) -> 'EvidenceRow'` (L82)
- `class Goal` (L97) — A single earning goal.
  - `progress_pct() -> float` (L120)
  - `is_overdue() -> bool` (L126)
  - `to_dict() -> Dict[str, Any]` (L131)
  - `from_dict(d: Dict[str, Any]) -> 'Goal'` (L149)
- `class GoalTracker` (L167) — Manages goals — create, update, add evidence, track progress.
  - `__init__(db_path: Optional[str]=None)` (L176)
  - `instance() -> 'GoalTracker'` (L190)
  - `_ensure_dir()` (L196)
  - `_connect()` (L201) — Return a sqlite3 connection using the shared in-memory
  - `_init_db()` (L210) — Create tables if they don't exist.
  - `create(goal: Goal) -> Goal` (L252) — Create a new goal.
  - `get(goal_id: str) -> Optional[Goal]` (L271) — Get a goal by ID.
  - `list_active() -> List[Goal]` (L282) — List all active goals.
  - `list_all() -> List[Goal]` (L291) — List all goals.
  - `update(goal: Goal) -> Goal` (L300) — Update a goal.
  - `delete(goal_id: str) -> bool` (L318) — Delete a goal.
  - `add_evidence(goal_id: str, evidence: EvidenceRow) -> EvidenceRow` (L328) — Add an evidence row to a goal and update current_usd.
  - `list_evidence(goal_id: str) -> List[EvidenceRow]` (L351) — List all evidence for a goal.
  - `add_earnings(goal_id: str, amount_usd: float, source: str='')` (L363) — Add verified earnings to a goal.
  - `check_completion(goal_id: str)` (L372) — Check if a goal is completed and update status.
  - `summary() -> Dict[str, Any]` (L386) — Return a summary dict for the GUI.
  - `process_event(event) -> None` (L416) — Process an event from the event logger and update relevant goals.
  - `_auto_match_event(event_type: str, source: str, details: Dict[str, Any])` (L451) — Try to auto-match an event to an active goal based on event type.
  - `_row_to_goal(row: sqlite3.Row) -> Goal` (L489)
  - `_row_to_evidence(row: sqlite3.Row) -> EvidenceRow` (L506)


### `agents/earning/got.py` — Graph-of-Thought planning for opportunity discovery and evaluation. (209L)

**Classes:**
- `class OpportunityGraphRank` (L26)
  - `recommendation() -> str` (L33)
  - `to_dict() -> dict` (L40)
- `class GraphBudget` (L51) — Hard limits for one bounded opportunity decision search.
- `class OpportunityGraphPlanner` (L66) — Build and rank a bounded GoT graph for evaluated opportunities.
  - `__init__(opportunities: Iterable[Any], evidence_by_id: Mapping[str, , ...)` (L69)
  - `_estimated_cost(opportunity: Any) -> float` (L86)
  - `_reject(opportunity: Any, reason: str) -> None` (L90)
  - `_load_candidates(opportunities: Iterable[Any]) -> None` (L96)
  - `_id(opportunity: Any) -> str` (L117)
  - `_build() -> None` (L120)
  - `_utility(opportunity: Any) -> float` (L161)
  - `rank() -> List[OpportunityGraphRank]` (L171)
  - `audit_summary() -> dict[str, Any]` (L193) — Return bounded-search metadata and compact rejected alternatives.


### `agents/earning/intelligence.py` — Deterministic intelligence evaluation for earning opportunities. (52L)

**Functions:**
- `evaluate_intelligence(opportunity: Any, memory=..., engine=..., log_fn=...) -> Any` (L14) — Attach and return the policy-backed intelligence result.


### `agents/earning/live_trading.py` — Live portfolio and trading service with deterministic risk controls. (616L)

**Functions:**
- `adapter_from_env(exchange_id: str) -> CcxtExchangeAdapter` (L606) — Create an adapter from exchange-specific environment variables.

**Classes:**
- `class LiveTradingError(RuntimeError)` (L20) — Raised when a live-trading precondition fails.
- `class PortfolioSnapshot` (L25)
- `class MarketSnapshot` (L34)
- `class TradeIntent` (L44)
- `class RiskAssessment` (L58)
- `class TradingPolicy` (L66) — Hard limits for one exchange account.
- `class CcxtExchangeAdapter` (L85) — Optional ccxt adapter for real exchange reads and order submission.
  - `__init__(exchange_id: str, api_key: str='', secret: str='', password: str='', sandbox: bool=False)` (L88)
  - `fetch_balance() -> Dict[str, Any]` (L117)
  - `fetch_ticker(symbol: str) -> Dict[str, Any]` (L120)
  - `fetch_order_book(symbol: str) -> Dict[str, Any]` (L123)
  - `create_order(symbol: str, order_type: str, side: str, quantity: float, price: Optional[float]=None) -> Dict[str, Any]` (L126)
- `class LiveTradingService` (L131) — Live account reader and guarded order executor.
  - `__init__(adapter: Any=None, policy: Optional[TradingPolicy]=None, li, ...)` (L134)
  - `status() -> Dict[str, Any]` (L149)
  - `sync_portfolio() -> PortfolioSnapshot` (L158)
  - `fetch_market_snapshot(symbol: str) -> MarketSnapshot` (L178) — Build a risk input from fresh ticker and order-book data.
  - `assess_order(intent: TradeIntent, portfolio: PortfolioSnapshot, market: , ...) -> RiskAssessment` (L210)
  - `execute_order(intent: TradeIntent, assessment: RiskAssessment, approval_id: str='') -> Dict[str, Any]` (L300) — Submit one live order, or refuse.
  - `_reassess(intent: TradeIntent, approval_id: str='') -> RiskAssessment` (L360) — Re-derive the risk verdict from LIVE exchange state.
  - `_check_still_matches_what_was_approved(verdict: RiskAssessment, approval_id: str) -> None` (L392) — Refuse when live conditions no longer match the approved assessment.
  - `_require_approval_for(intent: TradeIntent, approval_id: str) -> None` (L434) — Fail closed unless a live APPROVED queue item names THIS order.
  - `_describe(d: Dict[str, Any]) -> str` (L471)
  - `_intent_differs(intent: TradeIntent, approved: Dict[str, Any]) -> bool` (L476) — Compare every field that changes what the exchange would receive.
  - `propose_order(intent: TradeIntent, assessment: RiskAssessment) -> Dict[str, Any]` (L510) — Create an approval item for an order that cannot be preapproved.
  - `_is_approved(approval_id: str) -> bool` (L529)
  - `_require_adapter() -> None` (L536)
  - `_book_levels(levels: Any) -> list[tuple[float, float]]` (L541)
  - `_validate_intent(intent: TradeIntent, market: MarketSnapshot) -> None` (L555)
  - `_split_symbol(symbol: str) -> tuple[str, str]` (L566)
  - `_usd_value(raw: Dict[str, Any], bucket: str, price_cache: Dict[str, float]) -> float` (L572)
  - `_fetch_asset_usd_price(asset: str) -> float` (L594)


### `agents/earning/microtask_earner.py` — agents/microtask_earner.py — Real micro-task earning path (v2.1 Path 2). (221L)

**Classes:**
- `class MicrotaskAttempt` (L27) — Record of a micro-task attempt.
- `class MicrotaskEarner` (L43) — Earn money by completing real micro-tasks.
  - `__init__(web: Optional[WebController]=None, workspace_root: str='')` (L46)
  - `find_gigs(platform: str='all', query: str='ai ml data labeling) -> List[MicrotaskGig]` (L52) — Find available micro-task gigs.
  - `accept_gig(gig: MicrotaskGig) -> MicrotaskAttempt` (L59) — Accept a gig and create workspace.
  - `work_on_gig(attempt: MicrotaskAttempt, instructions: str='') -> Dict[str, Any]` (L76) — Work on an accepted gig (platform-specific).
  - `_work_github_issue(attempt: MicrotaskAttempt, instructions: str) -> Dict[str, Any]` (L89) — Work on a GitHub issue: read requirements and prepare fix.
  - `_work_prolific_study(attempt: MicrotaskAttempt, instructions: str) -> Dict[str, Any]` (L126) — Prepare for a Prolific study.
  - `_work_remotask(attempt: MicrotaskAttempt, instructions: str) -> Dict[str, Any]` (L149) — Work on a Remotasks task.
  - `_work_generic(attempt: MicrotaskAttempt, instructions: str) -> Dict[str, Any]` (L169) — Generic micro-task work.
  - `submit_attempt(attempt: MicrotaskAttempt) -> Dict[str, Any]` (L184) — Submit a completed attempt.
  - `get_attempt(attempt_id: str) -> Optional[MicrotaskAttempt]` (L199) — Get attempt by ID.
  - `list_attempts(status: Optional[str]=None) -> List[MicrotaskAttempt]` (L203) — List attempts.
  - `get_status() -> Dict[str, Any]` (L210) — Get earner status.


### `agents/earning/moltbook_agent.py` — Moltbook agent identity onboarding. (401L)
> Phase E/F: real read+write client, api_key in vault, claim handoff.

**Functions:**
- `_safe_json(resp: Any) -> Any` (L389) — Best-effort JSON decode that never raises on an empty/odd body.

**Classes:**
- `class MoltbookRegistrationPlan` (L24) — A reviewable plan for an agent-owned Moltbook registration.
  - `ready() -> bool` (L36)
  - `to_dict() -> Dict[str, Any]` (L40)
- `class MoltbookAgentCapability` (L53) — Read, review, and optionally submit an agent-owned registration request.
  - `__init__(instruction_gate: Any, http_client: Any=None)` (L61)
  - `read_skill()` (L65)
  - `plan_registration(agent_name: str, description: str, skill_status: str='not_read') -> MoltbookRegistrationPlan` (L70)
  - `register(plan: MoltbookRegistrationPlan, capability_approved=...) -> Dict[str, Any]` (L82) — Register the agent, only after the capability has been approved.
  - `claim_status() -> Dict[str, Any]` (L139) — Check whether the agent has been claimed by its human.
  - `request_human_claim(plan: 'MoltbookRegistrationPlan', claim_url=..., verification_code=...) -> Dict[str, Any]` (L170) — Enqueue a human approval/notification carrying the claim instructions.
- `class MoltbookPoster` (L199) — Real read + write client for the Moltbook social network (Phase E).
  - `__init__(http_client: Any=None, api_key: str='', base_url: str=MOLTBOOK_API_BASE)` (L220)
  - `_key() -> Optional[str]` (L227)
  - `_auth_headers() -> Dict[str, str]` (L231)
  - `_offline(action: str) -> Dict[str, Any]` (L235)
  - `_require_key(action: str) -> Optional[Dict[str, Any]]` (L239)
  - `_verification(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]` (L246) — Surface a post/comment verification challenge if the API returned one.
  - `create_post(submolt_name: str, title: str, content: str='', url: str='', capability_approved=...) -> Dict[str, Any]` (L254) — Create a text/link post in a submolt. Requires capability approval.
  - `reply_to_post(post_id: str, content: str, parent_id: str='', capability_approved=...) -> Dict[str, Any]` (L288) — Comment on (or reply within) a post. Requires capability approval.
  - `upvote_post(post_id: str, capability_approved=...) -> Dict[str, Any]` (L318) — Upvote a post. Requires capability approval.
  - `upvote_comment(comment_id: str, capability_approved=...) -> Dict[str, Any]` (L324) — Upvote a comment. Requires capability approval.
  - `_vote(path: str, action: str, capability_approved=...) -> Dict[str, Any]` (L330)
  - `get_feed(sort: str='hot', limit: int=25, cursor: str='') -> Dict[str, Any]` (L346) — Read the post feed (hot/new/top/rising). Cursor-paginated.
  - `get_post(post_id: str) -> Dict[str, Any]` (L362)
  - `get_comments(post_id: str, sort: str='best', limit: int=35) -> Dict[str, Any]` (L374)


### `agents/earning/opportunity_adapters.py` — Adapters between the legacy earning pipeline model and canonical opportunities. (61L)

**Functions:**
- `canonical_to_legacy(canonical: Any, legacy_type: type) -> Any` (L15) — Convert a canonical opportunity to the pipeline's legacy shape.
- `legacy_to_canonical(legacy: Any) -> CanonicalOpportunity` (L38) — Convert the pipeline's legacy opportunity to the canonical shape.


### `agents/earning/opportunity_intelligence.py` — agents/opportunity_intelligence.py — Opportunity Intelligence Engine. (425L)

**Functions:**
- `_level(value_0_1: float, high: float=0.66, low: float=0.33) -> str` (L140) — Map a 0..1 value to high/medium/low.
- `_safe_div(a: float, b: float) -> float` (L149)

**Classes:**
- `class EvaluationConfig` (L36) — Tunable policy. All thresholds/weights live here, not hardcoded in logic.
- `class SemanticEstimate` (L76) — Optional semantic estimates the LLM MAY provide.
- `class EvaluationResult` (L97)
  - `to_dict() -> Dict[str, Any]` (L118)
- `class OpportunityIntelligenceEngine` (L155) — Deterministic expected-value evaluator over structured opportunities.
  - `__init__(config: Optional[EvaluationConfig]=None)` (L158)
  - `_history_rate(memory, method: str, key: str)` (L163) — Return (success_rate, total_samples, confidence) for a history series.
  - `evaluate(opportunity: Opportunity, memory=None, estimates: Optional[SemanticEstimate]=None) -> EvaluationResult` (L187)
  - `_rationale(verdict: str, ev: float, conf: float, scam: float, risk_unsafe: bool) -> str` (L417)


### `agents/earning/opportunity_lifecycle.py` — agents/earning/opportunity_lifecycle.py — Opportunity lifecycle automation (967L)

**Functions:**
- `get_lifecycle_tracker() -> OpportunityLifecycleTracker` (L949) — Get or create the global lifecycle tracker.
- `initialize_lifecycle_export(research_folder: str=None)` (L957) — Initialize export paths for research folder integration.

**Classes:**
- `class LifecycleEvent` (L38)
- `class OpportunityState` (L49)
- `class OpportunityLifecycleTracker` (L64) — Automated lifecycle tracker with smart transitions and scheduling.
  - `__init__(callback: Callable=None, evidence_store=None, learning_loop, ...)` (L87)
  - `start(opportunity: Any) -> OpportunityState` (L107) — Start tracking a new opportunity.
  - `get_state(opportunity_id: str) -> Dict` (L120) — Get current state as dict for serialization.
  - `get_all_states() -> List[Dict]` (L148) — Get all opportunity states.
  - `get_queued_opportunities() -> List[OpportunityState]` (L152) — Get opportunities ready for auto-application.
  - `get_active_opportunities() -> List[OpportunityState]` (L162) — Get opportunities that need attention.
  - `promote_to_applied(opportunity_id: str, reason: str='') -> OpportunityState` (L171) — Auto-transition from queued to applied.
  - `promote_to_submitted(opportunity_id: str, work_complete: bool=True) -> OpportunityState` (L180) — Auto-transition from applied/in_progress to submitted.
  - `scheduler_check(current_time: float=None) -> List[Dict]` (L194) — Run scheduler check - returns list of actions to take.
  - `process_scheduled_actions(actions: List[Dict]) -> List[Dict]` (L235) — Execute scheduled actions and return results.
  - `rank_by_value_effort(limit: int=10) -> List[tuple]` (L257) — Rank opportunities by value/effort ratio. Returns [(state, score), ...].
  - `get_top_opportunities(k: int=3) -> List[OpportunityState]` (L285) — Get top K opportunities by value/effort ratio.
  - `mark_researched(opportunity_id: str, note: str='') -> OpportunityState` (L292)
  - `mark_queued(opportunity_id: str, score: float=0.5, note: str='') -> OpportunityState` (L297)
  - `mark_applied(opportunity_id: str, note: str='') -> OpportunityState` (L304)
  - `mark_in_progress(opportunity_id: str, note: str='') -> OpportunityState` (L310)
  - `mark_submitted(opportunity_id: str, note: str='', amount: float=0.0, evidence=None) -> OpportunityState` (L315) — v2.0.34aq: if an Evidence is supplied (e.g. platform_submission), record it in the
  - `mark_paid_verified(opportunity_id: str, amount: float=0.0, evidence=None) -> OpportunityState` (L336) — v2.0.34aq: accepts a legacy VerificationEvidence dict OR a new Evidence.
  - `reconcile_evidence(opportunity_id: str, evidence_id: str, reconciler: str='ope, ...) -> Optional[Evidence]` (L453) — v2.0.34au: promote a non-affirmative (CONFLICTED/REJECTED/UNVERIFIED) evidence to
  - `mark_paid(opportunity_id: str, amount: float=0.0, note: str='') -> OpportunityState` (L503) — DEPRECATED (A2): self-reported payout. Now delegates to the verifier
  - `mark_failed(opportunity_id: str, note: str='') -> OpportunityState` (L518)
  - `mark_rejected(opportunity_id: str, reason: str='') -> OpportunityState` (L528)
  - `mark_final_outcome(opportunity_id: str, outcome_state=..., platform=..., categ, ...) -> Optional['LearningDelta']` (L534) — v2.0.36d: feed a final outcome into the Opportunity Learning Loop.
  - `_ensure(opportunity_id: str) -> OpportunityState` (L614)
  - `_transition(state: OpportunityState, stage: str, note: str, amount: float=0.0, source: str='system') -> bool` (L619) — Attempt a stage transition. Returns True iff the stage actually moved.
  - `_mark_paid(state: OpportunityState, note: str, amount: float, verification, source: str='verifier') -> bool` (L642) — Flip a state to `paid` THROUGH the state machine (ARCH-ENG-062).
  - `_route_to(start: str, target: str) -> List[str]` (L692) — Shortest legal stage path `start` -> `target`, excluding `start` itself.
  - `_persist() -> None` (L719) — Write all lifecycle states to the JSON state file (best-effort).
  - `_recover_from_disk() -> None` (L734) — Load previously-persisted states so a restart does not lose the
  - `_append(state: OpportunityState, stage: str, note: str, amount: flo, ...) -> None` (L771)
  - `_event_to_dict(event: LifecycleEvent) -> Dict` (L787)
  - `_notify(event_type: str, opportunity_id: str, state: OpportunityState)` (L797) — Notify callback if one was registered.
  - `verified_revenue_usd() -> float` (L820) — A2: sum of `last_amount` for states whose payout was VERIFIED.
  - `_is_verified_evidence(ev: Optional[Dict]) -> bool` (L835) — True iff a stored verification dict proves an INDEPENDENT payment.
  - `unverified_payouts() -> List[str]` (L864) — A2: opportunity ids with a payout attempt that was NOT verified.
  - `export_queued_jobs(path: str=None) -> str` (L880) — Export queued jobs to JSON file for research folder integration.
  - `export_analytics_report(path: str=None) -> str` (L906) — Export analytics summary to JSON file.


### `agents/earning/opportunity_models.py` — agents/opportunity_models.py — Generalized paid-opportunity model + taxonomy. (299L)

**Functions:**
- `classify_category(text: str) -> str` (L78) — Best-effort canonical category from free text. Falls back to 'other'.
- `validate_opportunity(o: Opportunity) -> ValidationResult` (L168) — Deterministic VALIDATION of a discovered listing (never uses the LLM).

**Classes:**
- `class Opportunity` (L93) — Structured representation of a discovered paid/rewarded opportunity.
  - `identity_key() -> str` (L139) — Normalized identity for cross-source dedup (not just id).
  - `to_dict() -> dict` (L151)
  - `from_dict(d: dict) -> 'Opportunity'` (L155)
- `class ValidationResult` (L161)
- `class OpportunitySource(ABC)` (L201) — A pluggable discovery source. Subclass and register with DiscoveryEngine.
  - `discover() -> List[Opportunity]` (L207) — Return discovered opportunities. Must NOT invent from LLM text.
  - `is_enabled() -> bool` (L211)
- `class BaseOpportunitySource(OpportunitySource)` (L215) — Convenience base: subclasses implement `_discover()`; provenance is coerced.
  - `discover(query: Optional[str]=None, categories: Optional[List[str]]=None, page: int=1) -> List[Opportunity]` (L228)
  - `_discover(query: Optional[str]=None, categories: Optional[List[str]]=None) -> List[Opportunity]` (L246)
- `class OpportunityDeduplicator` (L251) — Normalized identity fingerprinting across sources.
  - `__init__()` (L254)
  - `seen(o: Opportunity) -> bool` (L257)
  - `add(o: Opportunity) -> None` (L260)
  - `filter(opps: List[Opportunity]) -> List[Opportunity]` (L263)
  - `reset() -> None` (L271)
- `class OpportunityRegistry` (L275) — Holds registered sources and runs them with failure isolation.
  - `__init__()` (L278)
  - `register(src: OpportunitySource) -> None` (L281)
  - `sources() -> List[OpportunitySource]` (L284)
  - `run_all()` (L287) — Return (results, errors). A failing source is isolated (errors[name]).


### `agents/earning/opportunity_portfolio.py` — agents/opportunity_portfolio.py — persistent Opportunity Portfolio & Work Queue (v2.0.36h). (786L)

**Functions:**
- `canonical_portfolio_path() -> str` (L24) — Return the ONE canonical portfolio database path for the whole app.
- `resolve_next_action(entry: PortfolioEntry) -> tuple` (L744) — Deterministic (action, reason) for a portfolio entry based on its WorkStatus.
- `apply_next(portfolio: OpportunityPortfolio, entry: PortfolioEntry, now: float, **ctx) -> PortfolioEntry` (L754) — Advance an entry to its next logical WorkStatus based on its current status.

**Classes:**
- `class IllegalTransitionError(Exception)` (L39) — Raided when a WorkStatus or lifecycle transition is invalid.
- `class WorkStatus(str, Enum)` (L45) — Portfolio-level work status. Richer than the lifecycle stage vocabulary.
  - `is_terminal() -> bool` (L70)
- `class WorkStatusConfig` (L83) — Maps WorkStatus → lifecycle stage and defines valid WorkStatus transitions.
- `class PortfolioEntry` (L169) — A single opportunity in the portfolio with enriched portfolio-level fields.
  - `to_dict() -> dict` (L196)
  - `from_dict(d: dict) -> 'PortfolioEntry'` (L202)
- `class OpportunityPortfolio` (L210) — Persistent portfolio of opportunities with WorkStatus transitions.
  - `__init__(db_path: str, lifecycle: Any=None)` (L219)
  - `_init_db() -> None` (L227)
  - `_row_to_entry(row: tuple) -> PortfolioEntry` (L261) — Convert a DB row (matching the column order in _init_db) to a PortfolioEntry.
  - `add(entry: PortfolioEntry) -> None` (L297) — Insert or replace a portfolio entry.
  - `get(opportunity_id: str) -> Optional[PortfolioEntry]` (L323) — Get a single entry by ID.
  - `update(entry: PortfolioEntry) -> None` (L335) — Update an existing entry (same as add — INSERT OR REPLACE).
  - `remove(opportunity_id: str) -> None` (L339) — Delete an entry.
  - `list_all() -> List[PortfolioEntry]` (L346) — List all entries.
  - `list_work(status: Optional[WorkStatus]=None) -> List[PortfolioEntry]` (L353) — List entries, optionally filtered by WorkStatus.
  - `count_by_status() -> Dict[str, int]` (L365) — Count entries per work status.
  - `load_all() -> List[PortfolioEntry]` (L377) — Load all entries (for recovery after restart). Alias for list_all.
  - `transition_work_status(opportunity_id: str, new_status: WorkStatus, **ctx) -> PortfolioEntry` (L383) — Transition an entry to a new WorkStatus.
  - `_delegate_to_lifecycle(opportunity_id: str, old_status: WorkStatus, new_status: Wo, ...) -> None` (L416) — Delegate a lifecycle-affecting move to the injected lifecycle tracker.
  - `_lifecycle_path(start: str, goal: str) -> List[str]` (L452) — Find the shortest chain of lifecycle stages from start to goal using BFS over
  - `_apply_lifecycle_stage(opportunity_id: str, lifecycle_stage: str, **ctx) -> None` (L473) — Apply a single lifecycle stage via the tracker's mark methods.
- `class QueuePolicy` (L507) — Configurable prioritization policy.
  - `score(entry: PortfolioEntry, now: float) -> float` (L530) — Compute a priority score for an entry (higher = more attractive).
  - `_deadline_urgency(deadline: float, now: float) -> float` (L552) — 1.0 if due within 24h, decaying to 0.0 if >14d or no deadline.
- `class CapacityConfig` (L570) — Configurable overcommit limits. Hard gates: select_next skips any entry exceeding a limit.
- `class WorkQueue` (L582) — Prioritized selection with hard overcommit enforcement.
  - `__init__(portfolio: OpportunityPortfolio, policy: QueuePolicy, capacity: CapacityConfig)` (L589)
  - `compute_scores(now: float) -> List[tuple]` (L597) — Compute policy_score for every non-terminal entry. Returns [(entry, score)].
  - `prioritized(now: float) -> List[PortfolioEntry]` (L603) — Return non-terminal entries sorted by policy_score descending (the queue order).
  - `_current_counts(now: float) -> Dict[str, Any]` (L611) — Snapshot current utilization across all capacity dimensions.
  - `would_exceed_capacity(entry: PortfolioEntry, counts: Dict[str, Any]) -> Optional[str]` (L634) — Check if adding `entry` to active work would exceed any capacity limit.
  - `select_next(now: float, limit: Optional[int]=None) -> List[PortfolioEntry]` (L663) — Select the next batch to act on, respecting capacity.
  - `_projected_counts(counts: Dict[str, Any], entry: PortfolioEntry) -> Dict[str, Any]` (L682) — Return a copy of counts with `entry` consumed (for selection tracking).
  - `get_blocked() -> List[PortfolioEntry]` (L701) — Return BLOCKED entries with their blocked_reason.
  - `summary(now: float) -> Dict[str, Any]` (L705) — Summary dict: counts by status + exposure + remaining capacity.


### `agents/earning/paper_trading.py` — agents/paper_trading.py — Paper trading engine for safe strategy validation (v2.1 Phase 1). (390L)

**Classes:**
- `class OrderType(Enum)` (L22)
- `class OrderSide(Enum)` (L28)
- `class Order` (L34) — Simulated order.
- `class Position` (L51) — Portfolio position.
- `class Trade` (L62) — Completed trade.
- `class PaperTradingEngine` (L73) — Paper trading engine with virtual portfolio.
  - `__init__(initial_balance: float=10000.0, config_path: str='', audit_path: str='')` (L78)
  - `_load_audit_log() -> None` (L117)
  - `_audit(event: str, **details) -> None` (L129)
  - `get_equity() -> float` (L146) — Calculate total equity (cash + positions).
  - `get_position(symbol: str) -> Optional[Position]` (L151) — Get position for a symbol.
  - `get_all_positions() -> List[Position]` (L155) — Get all positions.
  - `update_price(symbol: str, price: float)` (L159) — Update current price for a symbol.
  - `place_order(symbol: str, side: OrderSide, quantity: float, order_type: , ...) -> Optional[Order]` (L171) — Place an order.
  - `cancel_order(order_id: str) -> bool` (L224) — Cancel a pending order.
  - `_execute_order(order: Order)` (L232) — Execute an order.
  - `_check_limit_orders(symbol: str, price: float)` (L302) — Check and execute limit orders.
  - `get_performance() -> Dict` (L320) — Get performance metrics.
  - `get_report() -> str` (L367) — Generate a text performance report.


### `agents/earning/payment.py` — Payment-side earning services. (41L)

**Functions:**
- `record_realized_gas(db_path=..., chain=..., usd=..., note=...) -> None` (L8) — Record realized blockchain gas without allowing ledger errors to escape.
- `total_realized_gas(db_path=...) -> float` (L27) — Read realized gas for reporting; unavailable ledgers contribute zero.


### `agents/earning/payment_evidence.py` — Shared payment-evidence vocabulary. (41L)


### `agents/earning/payout_verifier.py` — agents/payout_verifier.py — Verify that a payout actually happened (A2). (140L)

**Classes:**
- `class VerificationEvidence` (L23)
  - `summary() -> str` (L33)
- `class PayoutVerifier` (L40) — Produce VerificationEvidence from a real payment source (or operator input).
  - `verify_crypto(wallet_manager, wallet_name: str, expected_usd: float, befo, ...) -> VerificationEvidence` (L44) — Verify a crypto payout against wallet balance.
  - `verify_manual(expected_usd: float, reference: str) -> VerificationEvidence` (L118) — Human-attested payout. Verified only if a non-empty reference exists.
  - `verify_api(expected_usd: float, statement_ref: str) -> VerificationEvidence` (L134) — Stub: real API statement parsing lands when an account is connected.


### `agents/earning/platform_submitter.py` — agents/platform_submitter.py — Human-gated platform submission wrapper (v2.1 Path 1). (320L)

**Classes:**
- `class SubmissionRecord` (L25) — Record of a submission attempt.
  - `to_dict() -> Dict[str, Any]` (L38)
- `class PlatformSubmitter` (L53) — Submit to freelance platforms with human approval gates.
  - `__init__(safety_guard: Optional[SafetyGuard]=None, evidence_dir: str='')` (L56)
  - `_ensure_evidence_dir()` (L63)
  - `register_platform(name: str, adapter: Any)` (L69) — Register a platform adapter.
  - `get_platform(name: str) -> Optional[Any]` (L73) — Get a registered platform adapter.
  - `prepare_submission(platform: str, opportunity: Dict[str, Any], proposal_text: , ...) -> SubmissionRecord` (L77) — Prepare a submission package and queue for human approval.
  - `request_approval(record: SubmissionRecord) -> Dict[str, Any]` (L115) — Request human approval for a submission.
  - `submit_if_approved(record: SubmissionRecord) -> Dict[str, Any]` (L180) — Submit a record the human has actually approved.
  - `submit(record: SubmissionRecord) -> Dict[str, Any]` (L258) — Submit an approved record via platform adapter.
  - `get_record(record_id: str) -> Optional[SubmissionRecord]` (L297) — Get submission record by ID.
  - `list_records(status: Optional[str]=None) -> List[SubmissionRecord]` (L301) — List submission records.
  - `get_status() -> Dict[str, Any]` (L308) — Get submitter status.


### `agents/earning/platform_throttle.py` — Platform rate-limiting (v2.0.34q, Section C1). (122L)

**Functions:**
- `_env_rate(platform: str) -> Optional[float]` (L55) — Read RATE_<PLATFORM> (calls/sec) from env, validating it's a sane float.
- `get_throttle() -> PlatformThrottle` (L115)

**Classes:**
- `class PlatformThrottle` (L70) — Holds one TokenBucket per platform and acquires tokens before calls.
  - `__init__() -> None` (L73)
  - `_bucket(platform: str) -> TokenBucket` (L77)
  - `acquire(platform: str, tokens: float=1.0) -> None` (L94) — Block until one token is available for ``platform``.
  - `reset() -> None` (L104) — Drop all buckets (used in tests / config reload).


### `agents/earning/portfolio.py` — Portfolio projection for evaluated earning opportunities. (86L)

**Functions:**
- `sync_to_portfolio(opportunity: Any, portfolio=..., log_fn=...) -> None` (L8) — Create or update the portfolio projection for one opportunity.


### `agents/earning/proposal.py` — Safety-gated proposal submission orchestration. (182L)

**Functions:**
- `submit_gig_proposal(opportunity: Any, draft: str, result_type=..., reviewer=..., ...) -> Any` (L8) — Submit a proposal through review, human/ramp, and evidence gates.


### `agents/earning/ranking.py` — Graph-based ranking for evaluated earning opportunities. (83L)
> Phase C: optional strategy_feedback param applies clamped multiplier on top of GoT rank.

**Functions:**
- `rank_opportunities(opportunities: List[Any], evidence_store=..., log_fn=..., strategy_feedback=...) -> Tuple[List[Any], Any, list]` (L10) — Attach graph ranks and return opportunities in ranked order.


### `agents/earning/real_crypto_operator.py` — agents/real_crypto_operator.py — Human-gated real crypto payment operator (v2.1 Path 3). (114L)

**Classes:**
- `class RealCryptoOperator` (L26) — Human-gated real crypto payment operator.
  - `__init__(wallet_manager, safety_guard: Optional[SafetyGuard]=None)` (L29)
  - `propose_payment(from_address: str, to_address: str, amount: float, currency: str, chain, memo: str='') -> Dict[str, Any]` (L34) — Propose a payment for human approval.
  - `confirm_and_send(request_id: str, rpc_url: str='', private_key: str='') -> Dict[str, Any]` (L86) — Confirm approval and attempt real send if configured.
  - `get_pending() -> List[Dict[str, Any]]` (L107) — Get pending payment requests.
  - `get_status() -> Dict[str, Any]` (L112)


### `agents/earning/reputation.py` — agents/reputation.py — Reputation tracking system (v2.1 Phase 2). (319L)

**Classes:**
- `class BadgeTier(Enum)` (L20)
- `class Badge` (L29) — Achievement badge.
- `class PlatformMetrics` (L41) — Metrics for a single platform.
  - `success_rate() -> float` (L57)
  - `net_earnings() -> float` (L63)
  - `verified_net_earnings() -> float` (L67)
  - `roi() -> float` (L71)
  - `verified_roi() -> float` (L77)
- `class WorkRecord` (L84) — Record of a completed task.
- `class ReputationTracker` (L101) — Track and manage agent reputation across platforms.
  - `__init__(state_path: str='')` (L104)
  - `_load()` (L115) — Load reputation state from disk.
  - `_save()` (L134) — Save reputation state to disk.
  - `record_work(record: WorkRecord)` (L157) — Record completed work.
  - `get_platform_metrics(platform: str) -> Optional[PlatformMetrics]` (L197) — Get metrics for a specific platform.
  - `get_all_metrics() -> Dict[str, PlatformMetrics]` (L201) — Get all platform metrics.
  - `get_overall_metrics() -> Dict` (L205) — Get overall aggregated metrics.
  - `get_badges() -> List[Badge]` (L234) — Get all earned badges.
  - `get_work_history(limit: int=20) -> List[WorkRecord]` (L238) — Get recent work history.
  - `get_portfolio() -> Dict` (L242) — Get work portfolio summary.
  - `_check_badges()` (L260) — Check and award new badges.
  - `get_reputation_score() -> float` (L300) — Calculate overall reputation score (0-100).


### `agents/earning/router.py` — Task router — classifies tasks and selects specialization + tools. (123L)

**Functions:**
- `classify_task(text: str) -> str` (L93) — Classify a task by its primary type.
- `get_tools_for_task(task_type: str) -> List[Dict]` (L107) — Get tool definitions appropriate for the task type.
- `get_specialization_prompt(task_type: str) -> str` (L114) — Get the system prompt addon for a task type.
- `get_all_tools() -> List[Dict]` (L119) — Get all available tool definitions.


### `agents/earning/rug_screen.py` — agents/rug_screen.py — DeFi rug/pull screening (B5). (107L)

**Functions:**
- `_level_from(flags: List[str], fails: List[str]) -> str` (L34)
- `screen_opportunity(opp, contract_age_days=..., audit_verified=..., tvl_history, ...) -> RugScreenResult` (L42) — Screen one DeFi opportunity for rug/pull risk.

**Classes:**
- `class RugScreenResult` (L28)


### `agents/earning/social_earning_platform.py` — agents/social_earning_platform.py — Social layer & alternative earning sources. (355L)
> Phase A added _scan_remote_job_boards (WeWorkRemotely RSS).

**Classes:**
- `class SocialOpportunity` (L24) — Represents an opportunity from social platforms.
- `class SocialEarningPlatform` (L41) — Scans social platforms for earning opportunities.
  - `__init__()` (L44)
  - `discover_all(page: int=1, query: Optional[str]=None) -> List[SocialOpportunity]` (L51) — Discover opportunities from all social sources.
  - `_scan_reddit_jobs(page: int=1, query: Optional[str]=None) -> List[SocialOpportunity]` (L103) — Scan Reddit r/forhire, r/freelance, r/jobbit.
  - `_scan_twitter_jobs() -> List[SocialOpportunity]` (L171) — Scan Twitter for micro-jobs and freelance posts.
  - `_scan_linkedin_jobs() -> List[SocialOpportunity]` (L185) — Scan LinkedIn job posts via public RSS.
  - `_scan_forum_jobs() -> List[SocialOpportunity]` (L248) — Scan community forums for jobs.
  - `_scan_remote_job_boards(page: int=1, query: Optional[str]=None) -> List[SocialOpportunity]` (L264) — Scan remote-job boards that publish public RSS (WeWorkRemotely).
  - `scan_reddit_jobs() -> List[SocialOpportunity]` (L337) — Public method for Reddit scanning.
  - `scan_twitter_jobs() -> List[SocialOpportunity]` (L341) — Public method for Twitter scanning.


### `agents/earning/social_writer_factory.py` — Build the confirmed social writer for the social_post tool (Phase E). (83L)
> build_moltbook_writer registered via set_social_writer (Phase E).

**Functions:**
- `build_moltbook_writer() -> Optional[Callable[[dict], str]]` (L20) — Return a social_post writer backed by a real MoltbookPoster, or None.


### `agents/earning/spec.py` — task_spec.py — Task specification + deterministic semantic requirement inference (v2.0.36e). (195L)

**Functions:**
- `set_requirement_inferrer(fn) -> None` (L125) — Optionally plug an LLM in for richer semantic mapping. The validator still decides feasibility.
- `infer_task_requirements(text: str) -> List[str]` (L131) — Map natural-language text -> required capability tokens.
- `build_task(task_type: str, description: str='', title=..., source=...,, ...) -> Task` (L152) — Convenience constructor: optionally infer required capabilities from the description.
- `task_from_opportunity(opp, registry=None) -> Task` (L170) — Map an existing earning `Opportunity` into a reusable Task (reuse, not duplicate).

**Classes:**
- `class Task` (L22) — A reusable, capability-described unit of work.
  - `normalized_requirements() -> List[str]` (L46)
- `class TaskFeasibility` (L51) — Authoritative output of the deterministic capability validator.
  - `to_dict() -> dict` (L64)


### `agents/earning/strategy_feedback.py` — Strategy feedback — close the autonomous-learning outcome loop (Phase C). (155L)
> Read-only aggregator; advisory only; cold-start safe (>=3 runs); total_paid from paid=1 only.

**Classes:**
- `class PlatformStats` (L28) — Aggregated outcome statistics for one platform.
  - `success_rate() -> float` (L38)
  - `paid_rate() -> float` (L42)
  - `avg_payout() -> float` (L46)
  - `to_dict() -> Dict[str, Any]` (L49)
- `class StrategyFeedback` (L70) — Aggregate autonomous-run outcomes into per-platform statistics.
  - `__init__(run_store: Any, platform_resolver: Optional[Callable[[str], str]]=None, min_runs=...)` (L73)
  - `platform_stats(limit: int=500) -> Dict[str, PlatformStats]` (L81) — Aggregate recent runs into {platform: PlatformStats}.
  - `_recent_runs(limit: int) -> List[Dict[str, Any]]` (L109) — Read recent runs from the store, tolerating either list_runs() or a
  - `ranking_adjustment(platform: str, stats: Optional[Dict[str, PlatformSta=None) -> float` (L122) — Multiplier for a platform's rank, in [_MIN_ADJUST, _MAX_ADJUST].
  - `summary_lines(stats: Optional[Dict[str, PlatformSta=None) -> List[str]` (L142) — Human-readable per-platform summary for the Autonomous-Learning tab.


### `agents/earning/submission.py` — Submission-ramp bookkeeping for earning proposals. (21L)

**Functions:**
- `record_ramp_submission(opportunity: Any, memory=...) -> None` (L8) — Record an attempt without crediting a win.


### `agents/earning/submission_ramp.py` — Human-in-the-loop submission ramp (v2.0.34r, Section C2). (185L)

**Functions:**
- `_env_int(name: str, default: int) -> int` (L31)
- `_env_float(name: str, default: float) -> float` (L42)
- `get_ramp(memory=None) -> SubmissionRamp` (L167)
- `set_ramp_memory(memory) -> None` (L178) — Wire an EarningMemory instance into the singleton (call at startup).

**Classes:**
- `class SubmissionRamp` (L55) — Per-platform count-based human-confirmation ramp.
  - `__init__(memory=None, min_submissions: Optional[int]=None, win_rate_, ...)` (L58)
  - `_platform_key(platform: str) -> str` (L72)
  - `_reputation(platform: str) -> dict` (L75)
  - `requires_human(platform: str, ai_policy: str='ai_allowed') -> bool` (L84) — True => a human confirmation is required before submitting.
  - `record_outcome(platform: str, accepted: bool) -> None` (L111) — DEPRECATED (H39 fix, v2.0.34u): do NOT use for the submit-time call —
  - `record_submission(platform: str) -> None` (L120) — Record a proposal *submission* (not an acceptance). Bumps the attempt
  - `record_accept(platform: str, revenue: float=0.0) -> None` (L131) — Record a *real* acceptance/win (proposal was paid/accepted).
  - `record_reject(platform: str) -> None` (L140) — Record a *real* rejection/loss (proposal was rejected/failed).
  - `status(platform: str, ai_policy: str='ai_allowed') -> dict` (L149)


### `agents/earning/tasks.py` — Source-specific earning task adapters. (146L)

**Functions:**
- `execute_airdrop(opportunity: Any, result_type=..., evidence_store=..., claimer_factory=...) -> Any` (L10) — Plan an airdrop claim; real claiming remains human-gated.
- `execute_defi(opportunity: Any, result_type=...) -> Any` (L97)
- `execute_microtask(opportunity: Any, result_type=...) -> Any` (L113)
- `execute_simple(opportunity: Any, result_type=..., memory=...) -> Any` (L122)


### `agents/earning/validator.py` — task_validator.py — DETERMINISTIC capability validator (v2.0.36e). (156L)

**Classes:**
- `class CapabilityValidator` (L31) — Deterministic feasibility gate backed by a CapabilityRegistry.
  - `__init__(registry: Optional[CapabilityRegistry]=None, human_available: bool=True) -> None` (L34)
  - `set_human_available(available: bool) -> None` (L39)
  - `validate(task: Task) -> TaskFeasibility` (L43)
  - `_apply_to_task(task: Task, f: TaskFeasibility) -> None` (L135) — Write the authoritative execution mode / human_required back onto the task
  - `classify(capability: str) -> str` (L147)


### `agents/earning/validators.py` — agents/task_validators.py — Task-specific deterministic validators (v2.0.36i). (441L)

**Functions:**
- `get_validator(task_type: str) -> BaseValidator` (L419) — Return the appropriate validator for a task type. Falls back to WritingValidator.

**Classes:**
- `class ValidationReport` (L28) — Deterministic verdict from a task-specific validator.
  - `add_check(name: str, passed: bool, detail: str='') -> None` (L36)
  - `to_dict() -> dict` (L39)
- `class BaseValidator` (L51) — Abstract base. Subclass per task type.
  - `validate(task: Dict[str, Any], output: Dict[str, Any], context: Dict[str, Any]) -> ValidationReport` (L55)
- `class CodingValidator(BaseValidator)` (L62) — Tests, lint (parse), build (import), diff.
  - `validate(task: Dict[str, Any], output: Dict[str, Any], context: Dict[str, Any]) -> ValidationReport` (L66)
  - `_check_syntax(code: str, report: ValidationReport) -> bool` (L86)
  - `_check_tests(tests: str, output: Dict, report: ValidationReport) -> bool` (L98)
  - `_check_diff(code: str, input_code: str, report: ValidationReport) -> bool` (L109)
- `class WritingValidator(BaseValidator)` (L122) — Requirements coverage, length, formatting, factual consistency.
  - `validate(task: Dict[str, Any], output: Dict[str, Any], context: Dict[str, Any]) -> ValidationReport` (L127)
  - `_check_length(text: str, report: ValidationReport) -> bool` (L140)
  - `_check_requirements_coverage(text: str, requirements: List[str], report: ValidationReport) -> bool` (L148)
  - `_check_formatting(text: str, report: ValidationReport) -> bool` (L164)
- `class ResearchValidator(BaseValidator)` (L176) — Source count, source quality, citation/provenance, completeness.
  - `validate(task: Dict[str, Any], output: Dict[str, Any], context: Dict[str, Any]) -> ValidationReport` (L181)
  - `_check_source_count(sources: List, report: ValidationReport) -> bool` (L196)
  - `_check_citations(claims: List, sources: List, report: ValidationReport) -> bool` (L204)
  - `_check_source_quality(sources: List, report: ValidationReport) -> bool` (L218)
- `class DataValidator(BaseValidator)` (L235) — Schema validation, row counts, duplicate detection, consistency.
  - `validate(task: Dict[str, Any], output: Dict[str, Any], context: Dict[str, Any]) -> ValidationReport` (L239)
  - `_check_schema(rows: List, schema: Dict, report: ValidationReport) -> bool` (L254)
  - `_check_row_counts(rows: List, report: ValidationReport) -> bool` (L270)
  - `_check_duplicates(rows: List, report: ValidationReport) -> bool` (L277)
- `class TranscriptionValidator(BaseValidator)` (L297) — Output format, completeness, timestamp integrity.
  - `validate(task: Dict[str, Any], output: Dict[str, Any], context: Dict[str, Any]) -> ValidationReport` (L301)
  - `_check_format(fmt: str, report: ValidationReport) -> bool` (L315)
  - `_check_timestamp_integrity(segments: List, report: ValidationReport) -> bool` (L323)
  - `_check_completeness(segments: List, duration: float, report: ValidationReport) -> bool` (L341)
- `class DocumentValidator(BaseValidator)` (L360) — Required fields, formatting, page count, content coverage.
  - `validate(task: Dict[str, Any], output: Dict[str, Any], context: Dict[str, Any]) -> ValidationReport` (L364)
  - `_check_required_fields(fields: Dict, required: List, report: ValidationReport) -> bool` (L379)
  - `_check_formatting(output: Dict, report: ValidationReport) -> bool` (L390)
  - `_check_content_coverage(output: Dict, report: ValidationReport) -> bool` (L398)


### `agents/earning/win_rate_guard.py` — agents/win_rate_guard.py — Auto-decline platforms below a win-rate threshold (A5). (75L)

**Classes:**
- `class WinRateGuard` (L15) — Decline a platform when its win-rate is below `decline_below` AND it has at
  - `__init__(decline_below: float=0.2, min_samples: int=5)` (L19)
  - `from_env(env_key: str='WINRATE_DECLINE_BEL) -> 'WinRateGuard'` (L30) — Read `decline_below` from an env value expressed as a PERCENT (e.g. "20").
  - `_rate_and_total(reputation: dict) -> tuple` (L40) — Return (success_rate, total) from a reputation dict, tolerating shapes.
  - `should_decline(reputation: dict) -> bool` (L58) — True iff the platform has enough samples AND its win-rate is below threshold.
  - `status(reputation: dict) -> dict` (L65)

