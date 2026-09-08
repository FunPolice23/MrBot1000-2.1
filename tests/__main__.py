#!/usr/bin/env python3
"""
MrBot1000 Test Suite Runner

Usage:
    python -m tests                    # Run all tests
    python -m tests --list               # List available tests
    python -m tests --test <name>        # Run specific test
    python -m tests --run <test1> <test2>  # Run multiple tests by name
    python -m tests --category <cat>     # Run all tests in a category
"""
import sys
import os
import json
import argparse
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Test categories and their test functions
TEST_CATEGORIES = {
    'syntax': {
        'description': 'Syntax validation tests',
        'tests': ['check_syntax']
    },
    'import': {
        'description': 'Import verification tests',
        'tests': ['test_imports', 'test_httpx_dependency', 'test_analyst_worker', 'test_job_search', 'test_main']
    },
    'health': {
        'description': 'Health and functionality tests',
        'tests': ['test_analyst_metrics', 'test_job_evaluation']
    },
    'security': {
        'description': 'v2.0.22 security: instruction gate + trust boundary',
        'tests': ['test_instruction_gate', 'test_trust_boundary']
    },
    'section_c': {
        'description': 'Section C: platform safety & ToS (rate-limit, ramp, scraper resilience)',
        'tests': ['test_section_c']
    },
    'section_d': {
        'description': 'Section D: LLM quality & cost (proposal model role, A/B intros, cost-aware routing, circuit breaker)',
        'tests': ['test_section_d']
    },
    'section_e': {
        'description': 'Section E: GUI/perf — dense/MoE arch detection, per-role GPU offload, steady-stream, per-role memory',
        'tests': ['test_section_e']
    },
    'evidence': {
        'description': 'v2.0.34au: Evidence & Verification subsystem (domain, store, policy, integration, reconciliation, extensive scenarios)',
        'tests': ['test_evidence', 'test_evidence_integration', 'test_evidence_payout_path', 'test_evidence_audit_fixups', 'test_evidence_au']
    },
    'earning_memory': {
        'description': 'v2.0.35: Earning/Opportunity Learning Memory expansion (10 structured memory types, rich outcome/failure/success records, analytics with confidence+sample size)',
        'tests': ['test_earning_memory', 'test_earning_memory_au']
    },
    'learning_loop': {
        'description': 'v2.0.36d: Opportunity Learning Loop (prediction accuracy, recency weighting, 11 metrics, LearningLoop pipeline, LearningGovernor safety bounds)',
        'tests': ['test_learning_loop']
    },
    'task_capabilities': {
        'description': 'v2.0.36e: reusable Skill/Task capability framework (taxonomy, Task spec, deterministic CapabilityValidator)',
        'tests': ['test_task_capabilities']
    },
    'discovery_scheduler': {
        'description': 'v2.0.36f: dynamic opportunity discovery scheduler (history-driven source/category/strategy selection, exploration/exploitation, backoff, multi-origin strategy generation, provenance)',
        'tests': ['test_discovery_scheduler']
    },
    'search_strategy_memory': {
        'description': 'v2.0.36g: Search Strategy Memory (economic outcome tracking, usefulness optimization, cold-start-safe novel exploration, provenance->outcome wiring)',
        'tests': ['test_search_strategy_memory']
    },
    'opportunity_portfolio': {
        'description': 'v2.0.36h: Opportunity Portfolio & Work Queue (16-state WorkStatus, persistent queue, configurable QueuePolicy + CapacityConfig overcommit gates, lifecycle-authoritative transitions, next_action)',
        'tests': ['test_opportunity_portfolio']
    },
    'task_execution': {
        'description': 'v2.0.36i: Generalized Task Execution Framework (14-step pipeline, task-specific validators, human gates)',
        'tests': ['test_task_execution']
    },
    'economic_accounting': {
        'description': 'v2.0.36j: Unified Economic Accounting Layer (revenue/expense/profit, verified vs unverified, USD + crypto, ROI, prediction accuracy)',
        'tests': ['test_economic_accounting']
    },
    'autonomous_loop': {
        'description': 'v2.0.36k: Unified Autonomous Planning Loop (24-stage, provenance-preserving, truth-status tracking, structured explanations)',
        'tests': ['test_autonomous_loop']
    },
    'self_audit': {
        'description': 'v2.0.36j-T4: Self-Audit & Continuous-Improvement Layer (14 finding categories, structured recommendations, no security mutations)',
        'tests': ['test_self_audit']
    },
    'discovery': {
        'description': 'v2.0.34as: Generalized paid-opportunity discovery (structured model, pluggable sources, dedup, validation, web source)',
        'tests': ['test_opportunity_discovery']
    },
    'intelligence': {
        'description': 'v2.0.34at: Opportunity Intelligence Engine (24-factor expected-value model, cold-start neutral priors, explainable verdicts)',
        'tests': ['test_opportunity_intelligence']
    },
    'nvidia': {
        'description': 'v2.0.36: NVIDIA NIM support — provider registration, free/fallback model fetch, OpenAI-compatible streaming + reasoning capture',
        'tests': ['test_nvidia_nim']
    },
    'dual_brain_runtime': {
        'description': 'v2.1: canonical dual-brain runtime — role→GPU isolation, endpoint/model config, offline health, model switching',
        'tests': ['test_dual_brain_runtime']
    },
    'dual_brain_coordinator': {
        'description': 'v2.1: canonical cross-model collaboration — typed plan/research/review/execute handoff, durable MessageLog, cycle-safe',
        'tests': ['test_dual_brain_coordinator']
    },
    'autonomous_run_store': {
        'description': 'v2.1 Phase 3: durable autonomous-run ledger — persistence, restart recovery, idempotency, composition root',
        'tests': ['test_autonomous_run_store']
    },
    'earning_capability': {
        'description': 'v2.1 Phase 4: first real paper/human-gated earning capability — TaskWorkspace deliverable, deterministic validation, human gates, local submission, no fabricated payment',
        'tests': ['test_earning_capability']
    },
    'integration': {
        'description': 'Integration test bundles',
        'tests': ['run_full_suite', 'run_quick_check']
    }
}

# Get all individual test names (excluding bundle tests)
ALL_TESTS = [t for cat in TEST_CATEGORIES.values() for t in cat['tests'] if not t.startswith('run_')]

RESULTS_DIR = Path(__file__).parent / 'test_results'
RESULTS_FILE = RESULTS_DIR / f'test_run_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'

# Results storage
_results = {
    'timestamp': datetime.now().isoformat(),
    'tests_run': [],
    'passed': [],
    'failed': [],
    'errors': []
}


def ensure_results_dir():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def list_tests():
    print("Available test categories and tests:")
    print("=" * 60)
    for category, info in TEST_CATEGORIES.items():
        print(f"\n  [{category.upper()}] {info['description']}")
        for test in info['tests']:
            builtin = " (runs other tests)" if test.startswith('run_') else ""
            print(f"    • {test}{builtin}")
    print()
    print("Examples:")
    print("  python -m tests                    # Run all tests")
    print("  python -m tests --test check_syntax  # Run single test")
    print("  python -m tests --category syntax  # Run all syntax tests")
    print("  python -m tests --run check_syntax test_imports  # Run multiple tests")
    print()


def get_all_test_names():
    """Get all runnable test names (excluding bundle tests)"""
    return ALL_TESTS.copy() + ['run_full_suite', 'run_quick_check']


def run_test(test_name: str) -> tuple:
    """Run a single test by name. Returns (success, message)."""
    if test_name == 'check_syntax':
        return test_syntax()
    elif test_name == 'test_imports':
        return test_imports()
    elif test_name == 'test_analyst_worker':
        return test_analyst_worker()
    elif test_name == 'test_httpx_dependency':
        return test_httpx_dependency()
    elif test_name == 'test_job_search':
        return test_job_search()
    elif test_name == 'test_main':
        return test_main()
    elif test_name == 'test_analyst_metrics':
        return test_analyst_metrics()
    elif test_name == 'test_job_evaluation':
        return test_job_evaluation()
    elif test_name == 'test_instruction_gate':
        return test_instruction_gate()
    elif test_name == 'test_trust_boundary':
        return test_trust_boundary()
    elif test_name == 'test_section_c':
        return run_unittest_file("test_section_c.py")
    elif test_name == 'test_section_d':
        return run_unittest_file("test_section_d.py")
    elif test_name == 'test_section_e':
        return run_unittest_file("test_section_e.py")
    elif test_name == 'test_evidence_audit_fixups':
        return run_unittest_file("test_evidence_audit_fixups.py")
    elif test_name == 'test_opportunity_discovery':
        return run_unittest_file("test_opportunity_discovery.py")
    elif test_name == 'test_opportunity_intelligence':
        return run_unittest_file("test_opportunity_intelligence.py")
    elif test_name == 'test_nvidia_nim':
        return run_unittest_file("test_nvidia_nim.py")
    elif test_name == 'test_dual_brain_runtime':
        return run_unittest_file("test_dual_brain_runtime.py")
    elif test_name == 'test_dual_brain_coordinator':
        return run_unittest_file("test_dual_brain_coordinator.py")
    elif test_name == 'test_autonomous_run_store':
        return run_unittest_file("test_autonomous_run_store.py")
    elif test_name == 'test_earning_capability':
        return run_unittest_file("test_earning_capability.py")
    elif test_name == 'test_evidence_integration':
        return run_unittest_file("test_evidence_integration.py")
    elif test_name == 'test_evidence':
        return run_unittest_file("test_evidence.py")
    elif test_name == 'test_evidence_payout_path':
        return run_unittest_file("test_evidence_payout_path.py")
    elif test_name == 'test_evidence_au':
        return run_unittest_file("test_evidence_au.py")
    elif test_name == 'test_earning_memory':
        return run_unittest_file("test_earning_memory.py")
    elif test_name == 'test_earning_memory_au':
        return run_unittest_file("test_earning_memory_au.py")
    elif test_name == 'test_learning_loop':
        return run_unittest_file("test_learning_loop.py")
    elif test_name == 'test_task_capabilities':
        return run_unittest_file("test_task_capabilities.py")
    elif test_name == 'test_discovery_scheduler':
        return run_unittest_file("test_discovery_scheduler.py")
    elif test_name == 'test_search_strategy_memory':
        return run_unittest_file("test_search_strategy_memory.py")
    elif test_name == 'test_opportunity_portfolio':
        return run_unittest_file("test_opportunity_portfolio.py")
    elif test_name == 'test_task_execution':
        return run_unittest_file("test_task_execution.py")
    elif test_name == 'test_economic_accounting':
        return run_unittest_file("test_economic_accounting.py")
    elif test_name == 'test_autonomous_loop':
        return run_unittest_file("test_autonomous_loop.py")
    elif test_name == 'test_self_audit':
        return run_unittest_file("test_self_audit.py")
    elif test_name == 'run_quick_check':
        return run_tests(['check_syntax', 'test_imports', 'test_analyst_worker'])
    elif test_name == 'run_full_suite':
        return run_tests(ALL_TESTS)
    else:
        return False, f"Unknown test: {test_name}"


# ── Individual Test Functions ─────────────────────────────────────────────

def test_syntax() -> tuple:
    """Validate Python syntax for all modified files"""
    import py_compile
    
    files = [
        PROJECT_ROOT / 'manager.py',
        PROJECT_ROOT / 'main.py',
        PROJECT_ROOT / 'agents/analyst_worker.py',
        PROJECT_ROOT / 'agents/job_search_worker.py',
        PROJECT_ROOT / 'agents/summarizer.py',
        PROJECT_ROOT / 'agents/base_worker.py',
    ]
    
    failed = []
    for f in files:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            failed.append(f"{Path(f).name}: {e}")
    
    if failed:
        return False, f"Syntax errors:\n" + "\n".join(f"  ✗ {e}" for e in failed)
    return True, "All files passed syntax validation"


def test_imports() -> tuple:
    """Verify core modules can be imported"""
    try:
        import agents.base_worker
        from agents.job_search_worker import JobSearchWorker
    except Exception as e:
        return False, f"Import error: {e}"
    
    return True, "All core imports successful"


def test_httpx_dependency() -> tuple:
    """Verify httpx and dependent modules import in a cold environment."""
    try:
        import httpx
        import agents.social_earning_platform
        import earning_pipeline
    except Exception as e:
        return False, f"httpx/dependency import error: {e}"

    return True, "httpx dependency imports are healthy"


def test_main() -> tuple:
    """Verify main.py can be imported and ManagerThread has required methods"""
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'  # Avoid GUI issues
    
    try:
        if 'main' in sys.modules:
            del sys.modules['main']
        if 'manager' in sys.modules:
            del sys.modules['manager']
        
        from main import MainWindow
        from manager import ManagerThread
        
        # Verify required methods exist
        required_methods = ['set_summarizer', 'register_worker', 'get_free_worker']
        missing = [m for m in required_methods if not hasattr(ManagerThread, m)]
        
        if missing:
            return False, f"Missing methods: {', '.join(missing)}"
        
        return True, "MainWindow and ManagerThread imported successfully"
    except Exception as e:
        import traceback
        return False, f"Import error: {e}"


def run_unittest_file(filename: str) -> tuple:
    """Run a unittest-style test file from the tests/ directory."""
    import unittest
    path = os.path.join(os.path.dirname(__file__), filename)
    if not os.path.exists(path):
        return False, f"Test file not found: {filename}"
    suite = unittest.TestLoader().discover(
        start_dir=os.path.dirname(path), pattern=filename)
    res = unittest.TextTestRunner(verbosity=0).run(suite)
    if res.wasSuccessful():
        return True, f"{filename}: {res.testsRun} tests passed"
    failures = [str(f[1]) for f in res.failures] + [str(e[1]) for e in res.errors]
    return False, f"{filename}: {len(failures)} failure(s)\n" + "\n".join(failures[:5])


def test_instruction_gate() -> tuple:
    """v2.0.22: instruction provenance gate (quarantine/allow/block)."""
    return run_unittest_file("test_instruction_gate.py")


def test_trust_boundary() -> tuple:
    """v2.0.22: high-trust action boundary + platform adapter shape."""
    return run_unittest_file("test_trust_boundary.py")


def test_analyst_worker() -> tuple:
    """Verify AnalystWorker can be instantiated"""
    try:
        from agents.analyst_worker import AnalystWorker
        worker = AnalystWorker(api_key="", log_signal=lambda x: None)
        return True, "AnalystWorker instantiated successfully"
    except Exception as e:
        return False, f"AnalystWorker error: {e}"


def test_job_search() -> tuple:
    """Verify JobSearchWorker can be instantiated"""
    try:
        from agents.job_search_worker import JobSearchWorker
        worker = JobSearchWorker(api_key="", log_signal=lambda x: None)
        return True, "JobSearchWorker instantiated successfully"
    except Exception as e:
        return False, f"JobSearchWorker error: {e}"


def test_analyst_metrics() -> tuple:
    """Test AnalystWorker proposal analysis functionality"""
    try:
        from agents.analyst_worker import AnalystWorker
        worker = AnalystWorker(api_key="", log_signal=lambda x: None)
        
        # Test proposal
        test_prop = "Requirements: Build chatbot. Deliverables: Code. Timeline: 4 weeks."
        metrics = worker.analyze_proposal(test_prop, "test")
        
        if not (0 <= metrics.quality_score <= 1):
            return False, f"Invalid quality score: {metrics.quality_score}"
        
        return True, f"Proposal analysis OK (quality={metrics.quality_score})"
    except Exception as e:
        return False, f"Analyst metrics error: {e}"


def test_job_evaluation() -> tuple:
    """Test job listing evaluation"""
    try:
        from agents.analyst_worker import AnalystWorker
        worker = AnalystWorker(api_key="", log_signal=lambda x: None)
        
        test_job = {
            "job_id": "test_job",
            "title": "Build AI Chatbot",
            "description": "Need Python dev",
            "budget": 500,
            "skills": ["Python"],
            "url": "https://example.com"
        }
        result = worker.evaluate_job_listing(test_job)
        
        if 'recommended_action' not in result:
            return False, "Missing recommended_action in result"
        
        return True, f"Job evaluation OK (action={result['recommended_action']})"
    except Exception as e:
        return False, f"Job evaluation error: {e}"


def run_tests(test_list: list) -> tuple:
    """Run multiple tests and collect results"""
    passed = []
    failed = []
    errors = []
    
    for test_name in test_list:
        success, msg = run_test(test_name)
        _results['tests_run'].append(test_name)
        
        if success:
            passed.append(test_name)
            print(f"  ✅ {test_name}: {msg}")
        else:
            failed.append(test_name)
            error_msg = f"{test_name}: {msg}"
            errors.append(error_msg)
            print(f"  ❌ {test_name}: {msg}")
    
    # Update results
    _results['passed'].extend(passed)
    _results['failed'].extend(failed)
    _results['errors'].extend(errors)
    
    if failed:
        return False, f"{len(failed)} test(s) failed: " + "; ".join(failed)
    return True, f"All {len(passed)} tests passed"


def run_category(category: str) -> tuple:
    """Run all tests in a category"""
    if category not in TEST_CATEGORIES:
        return False, f"Unknown category: {category}"
    
    tests = TEST_CATEGORIES[category]['tests']
    return run_tests(tests)


def save_results():
    """Save test results to JSON file"""
    ensure_results_dir()
    
    # Update timestamp for the save
    _results['timestamp'] = datetime.now().isoformat()
    
    with open(RESULTS_FILE, 'w') as f:
        json.dump(_results, f, indent=2)
    
    print(f"\n📁 Results saved to: {RESULTS_FILE}")
    print(f"   Summary: {len(_results['passed'])} passed, {len(_results['failed'])} failed")


def main():
    parser = argparse.ArgumentParser(description='MrBot1000 Test Suite')
    parser.add_argument('--list', action='store_true', help='List available tests')
    parser.add_argument('--test', type=str, help='Run specific test')
    parser.add_argument('--run', nargs='+', choices=get_all_test_names(),
                        help='Run specific tests by name (can specify multiple)')
    parser.add_argument('--category', type=str, choices=list(TEST_CATEGORIES.keys()),
                        help='Run all tests in a category')
    parser.add_argument('--all', action='store_true', help='Run all individual tests')
    
    args = parser.parse_args()
    
    ensure_results_dir()
    
    if args.list:
        list_tests()
        return 0
    
    # Determine which tests to run
    if args.test:
        tests_to_run = [args.test]
    elif args.run:
        tests_to_run = args.run
    elif args.category:
        tests_to_run = TEST_CATEGORIES[args.category]['tests']
    elif args.all:
        tests_to_run = ALL_TESTS
    else:
        # Default: run all individual tests
        tests_to_run = ALL_TESTS
    
    print(f"Running {len(tests_to_run)} test(s)...\n")
    
    success, msg = run_tests(tests_to_run)
    print(f"\n{msg}")
    
    save_results()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())