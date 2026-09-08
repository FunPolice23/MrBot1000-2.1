"""tests/test_task_execution.py — Generalized Task Execution Framework (v2.0.36i)."""

import os
import tempfile
import time
import unittest

from agents.task_validators import (
    ValidationReport,
    CodingValidator,
    WritingValidator,
    ResearchValidator,
    DataValidator,
    TranscriptionValidator,
    DocumentValidator,
    get_validator,
    VALIDATOR_REGISTRY,
)
from agents.human_gates import HumanGateType, HumanGateRecord, HumanGateManager
from agents.task_executor import (
    TaskExecutor, ExecutionContext, ExecutionPlan, ExecutionResult,
    StepStatus, ExecutionNotPossibleError,
)
from agents.opportunity_portfolio import (
    PortfolioEntry, WorkStatus, OpportunityPortfolio,
)
from agents.capability_registry import CapabilityRegistry, CapabilitySpec, get_default_registry


class TestValidators(unittest.TestCase):
    """Task-specific deterministic validators."""

    # ── Coding ──────────────────────────────────────────────────────────────

    def test_coding_validator_pass(self):
        output = {
            "code": "def hello():\n    return 'world'\n",
            "tests": "def test_hello():\n    assert hello() == 'world'\n",
            "test_passed": True,
        }
        v = CodingValidator()
        report = v.validate(task={}, output=output, context={})
        self.assertIsInstance(report, ValidationReport)
        self.assertTrue(report.passed)
        self.assertEqual(report.validator_type, "coding")

    def test_coding_validator_fail_no_tests(self):
        output = {"code": "def hello():\n    return 'world'\n"}
        report = CodingValidator().validate(task={}, output=output, context={})
        self.assertFalse(report.passed)

    # ── Writing ─────────────────────────────────────────────────────────────

    def test_writing_validator_pass(self):
        output = {
            "text": "# Title\n\n## Introduction\n\nThis is a well-structured document with enough words to pass the minimum length requirement for the writing validator test. It contains multiple sentences and covers several topics in depth to ensure the word count is well above fifty words total.\n\n## Requirements\n\nRequirement one is addressed in detail here. Requirement two is also covered.\n\n## Conclusion\n\nDone with the document.",
            "requirements": ["requirement one", "requirement two"],
        }
        report = WritingValidator().validate(task={}, output=output, context={})
        self.assertTrue(report.passed)

    def test_writing_validator_fail_too_short(self):
        output = {"text": "Short."}
        report = WritingValidator().validate(task={}, output=output, context={})
        self.assertFalse(report.passed)

    # ── Research ────────────────────────────────────────────────────────────

    def test_research_validator_pass(self):
        output = {
            "sources": [
                {"url": "https://wikipedia.org/a", "title": "Source A"},
                {"url": "https://example.com/b", "title": "Source B"},
                {"url": "https://wikipedia.org/c", "title": "Source C"},
            ],
            "claims": [
                {"text": "Claim 1", "source": "https://wikipedia.org/a"},
                {"text": "Claim 2", "source": "https://example.com/b"},
            ],
        }
        report = ResearchValidator().validate(task={}, output=output, context={})
        self.assertTrue(report.passed)

    def test_research_validator_fail_no_sources(self):
        output = {"claims": [{"text": "Claim without source"}]}
        report = ResearchValidator().validate(task={}, output=output, context={})
        self.assertFalse(report.passed)

    # ── Data ────────────────────────────────────────────────────────────────

    def test_data_validator_pass(self):
        output = {
            "schema": {"name": "str", "age": "int"},
            "rows": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}],
        }
        report = DataValidator().validate(task={}, output=output, context={})
        self.assertTrue(report.passed)

    def test_data_validator_fail_empty(self):
        output = {"schema": {"name": "str"}, "rows": []}
        report = DataValidator().validate(task={}, output=output, context={})
        self.assertFalse(report.passed)

    # ── Transcription ───────────────────────────────────────────────────────

    def test_transcription_validator_pass(self):
        output = {
            "format": "srt",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello"},
                {"start": 1.0, "end": 2.0, "text": "World"},
            ],
        }
        report = TranscriptionValidator().validate(task={}, output=output, context={})
        self.assertTrue(report.passed)

    def test_transcription_validator_fail_overlap(self):
        output = {
            "format": "srt",
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "Hello"},
                {"start": 1.0, "end": 3.0, "text": "World"},
            ],
        }
        report = TranscriptionValidator().validate(task={}, output=output, context={})
        self.assertFalse(report.passed)

    # ── Document ────────────────────────────────────────────────────────────

    def test_document_validator_pass(self):
        output = {
            "fields": {"title": "T", "author": "A", "date": "2024-01-01", "summary": "S"},
            "required_fields": ["title", "author", "date", "summary"],
            "sections": ["Introduction", "Body", "Conclusion"],
        }
        report = DocumentValidator().validate(task={}, output=output, context={})
        self.assertTrue(report.passed)

    def test_document_validator_fail_missing_field(self):
        output = {
            "fields": {"title": "T"},
            "required_fields": ["title", "author", "date"],
        }
        report = DocumentValidator().validate(task={}, output=output, context={})
        self.assertFalse(report.passed)

    # ── Registry ────────────────────────────────────────────────────────────

    def test_get_validator_coding(self):
        v = get_validator("coding")
        self.assertIsInstance(v, CodingValidator)

    def test_get_validator_writing(self):
        v = get_validator("writing")
        self.assertIsInstance(v, WritingValidator)

    def test_get_validator_unknown_fallback(self):
        v = get_validator("unknown_task_type")
        self.assertIsInstance(v, WritingValidator)  # fallback

    def test_validator_registry_has_all_types(self):
        expected = {"coding", "writing", "research", "data", "transcription", "document"}
        self.assertTrue(expected.issubset(set(VALIDATOR_REGISTRY.keys())))


class TestHumanGates(unittest.TestCase):
    """Human-in-the-loop gate manager."""

    def test_detects_payment_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t1", "description": "Submit invoice for payment"}
        gates = mgr.assess(task, {})
        self.assertTrue(any(g.gate_type == HumanGateType.PAYMENTS for g in gates))

    def test_detects_contracts_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t2", "description": "Sign the contract and NDA"}
        gates = mgr.assess(task, {})
        self.assertTrue(any(g.gate_type == HumanGateType.CONTRACTS for g in gates))

    def test_detects_signatures_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t3", "description": "Signature required on document"}
        gates = mgr.assess(task, {})
        self.assertTrue(any(g.gate_type == HumanGateType.SIGNATURES for g in gates))

    def test_detects_identity_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t4", "description": "KYC identity verification needed"}
        gates = mgr.assess(task, {})
        self.assertTrue(any(g.gate_type == HumanGateType.IDENTITY_VERIFICATION for g in gates))

    def test_detects_sensitive_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t5", "description": "Handle sensitive personal data"}
        gates = mgr.assess(task, {})
        self.assertTrue(any(g.gate_type == HumanGateType.SENSITIVE_INFORMATION for g in gates))

    def test_detects_irreversible_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t6", "description": "Delete the production database"}
        gates = mgr.assess(task, {})
        self.assertTrue(any(g.gate_type == HumanGateType.IRREVERSIBLE_ACTION for g in gates))

    def test_detects_captcha_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t7", "description": "Solve captcha to proceed"}
        gates = mgr.assess(task, {})
        self.assertTrue(any(g.gate_type == HumanGateType.CAPTCHA for g in gates))

    def test_detects_platform_manual_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t8", "description": "Manual platform-specific interview"}
        gates = mgr.assess(task, {})
        self.assertTrue(any(g.gate_type == HumanGateType.PLATFORM_MANUAL for g in gates))

    def test_requires_human_true(self):
        mgr = HumanGateManager()
        task = {"task_id": "t9", "description": "Payment processing"}
        self.assertTrue(mgr.requires_human(task, {}))

    def test_requires_human_false(self):
        mgr = HumanGateManager()
        task = {"task_id": "t10", "description": "Write a simple blog post"}
        self.assertFalse(mgr.requires_human(task, {}))

    def test_clear_gate(self):
        mgr = HumanGateManager()
        task = {"task_id": "t11", "description": "Payment required"}
        mgr.assess(task, {})
        self.assertTrue(mgr.clear_gate("t11", HumanGateType.PAYMENTS, "approved by user"))
        self.assertTrue(mgr.all_cleared("t11"))

    def test_pending_gates(self):
        mgr = HumanGateManager()
        task = {"task_id": "t12", "description": "Payment and signature required"}
        mgr.assess(task, {})
        pending = mgr.get_pending_gates("t12")
        self.assertEqual(len(pending), 2)
        mgr.clear_gate("t12", HumanGateType.PAYMENTS)
        self.assertEqual(len(mgr.get_pending_gates("t12")), 1)

    def test_no_gates_for_simple_task(self):
        mgr = HumanGateManager()
        task = {"task_id": "t13", "description": "Write a simple blog post about Python"}
        gates = mgr.assess(task, {})
        self.assertEqual(len(gates), 0)


class TestExecutor(unittest.TestCase):
    """14-step execution pipeline."""

    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "portfolio.db")
        self.portfolio = OpportunityPortfolio(db_path=self.db_path)
        self.registry = get_default_registry()
        # Ensure CODING is automatable; human NOT available so unsupported = truly unsupported
        from agents.task_validator import CapabilityValidator
        self.validator = CapabilityValidator(self.registry, human_available=False)
        self.gate_mgr = HumanGateManager()
        self.executor = TaskExecutor(self.portfolio, self.validator, self.gate_mgr)

    def _make_entry(self, opp_id="opp-1"):
        entry = PortfolioEntry(opportunity_id=opp_id, work_status=WorkStatus.NEW)
        self.portfolio.add(entry)
        return entry

    def test_full_pipeline_pass(self):
        """Full 14-step pipeline for a coding task with valid output."""
        task = {
            "task_id": "code-1",
            "task_type": "coding",
            "required_capabilities": ["CODING"],
            "description": "Write a Python function",
            "validation_method": "tests",
            "output": {
                "code": "def hello():\n    return 'world'\n",
                "tests": "def test_hello():\n    assert hello() == 'world'\n",
                "test_passed": True,
            },
        }
        entry = self._make_entry("code-1")
        result = self.executor.execute(task, entry)
        self.assertTrue(result.success)
        self.assertEqual(result.final_status, "paid")
        self.assertGreaterEqual(result.completed_steps, 10)

    def test_pipeline_stops_at_human_gate(self):
        """Pipeline stops at step 6 when human gate detected."""
        task = {
            "task_id": "pay-1",
            "task_type": "coding",
            "required_capabilities": ["CODING"],
            "description": "Submit payment for $500",
        }
        entry = self._make_entry("pay-1")
        result = self.executor.execute(task, entry)
        self.assertFalse(result.success)
        self.assertEqual(result.final_status, "awaiting_approval")

    def test_pipeline_validation_failure(self):
        """Pipeline fails at step 8 when validation fails."""
        task = {
            "task_id": "code-2",
            "task_type": "coding",
            "required_capabilities": ["CODING"],
            "description": "Write a Python function",
            "output": {
                "code": "",  # empty — fails syntax check
            },
        }
        entry = self._make_entry("code-2")
        result = self.executor.execute(task, entry)
        self.assertFalse(result.success)

    def test_pipeline_not_executable(self):
        """Pipeline fails when capability validator says unsupported."""
        task = {
            "task_id": "code-3",
            "task_type": "coding",
            "required_capabilities": ["UNICORN_MAGIC"],
            "description": "Do something impossible",
        }
        entry = self._make_entry("code-3")
        result = self.executor.execute(task, entry)
        self.assertFalse(result.success)
        self.assertEqual(result.final_status, "failed")

    def test_execution_context_audit(self):
        """ExecutionContext records all steps."""
        task = {
            "task_id": "code-4",
            "task_type": "coding",
            "required_capabilities": ["CODING"],
            "description": "Write a function",
            "output": {
                "code": "def f():\n    return 1\n",
                "tests": "def test_f():\n    assert f() == 1\n",
                "test_passed": True,
            },
        }
        entry = self._make_entry("code-4")
        result = self.executor.execute(task, entry)
        ctx = result.context
        self.assertEqual(ctx.current_step, 14)
        self.assertIsNotNone(ctx.capability_verdict)
        self.assertIsNotNone(ctx.validation_report)
        self.assertGreater(len(ctx.step_results), 5)


if __name__ == "__main__":
    unittest.main()
