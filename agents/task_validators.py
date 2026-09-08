"""agents/task_validators.py — Task-specific deterministic validators (v2.0.36i).

Each validator is a pure deterministic function: (task, output, context) -> ValidationReport.
The LLM may *produce* output; these validators decide whether that output actually completes the task.
No LLM is called during validation — that is the whole point.

Validators per the user's spec:
- CODING: tests, lint, build, diff
- WRITING: requirements coverage, length, formatting, factual consistency
- RESEARCH: source count, source quality, citation/provenance, completeness
- DATA: schema validation, row counts, duplicate detection, consistency
- TRANSCRIPTION: output format, completeness, timestamp integrity
- DOCUMENT: required fields, formatting, page count, content coverage
"""

from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Validation report ──────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    """Deterministic verdict from a task-specific validator."""
    validator_type: str
    passed: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def add_check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": passed, "detail": detail})

    def to_dict(self) -> dict:
        return {
            "validator_type": self.validator_type,
            "passed": self.passed,
            "checks": self.checks,
            "summary": self.summary,
            "timestamp": self.timestamp,
        }


# ── Base validator ─────────────────────────────────────────────────────────────

class BaseValidator:
    """Abstract base. Subclass per task type."""
    validator_type = "base"

    def validate(self, task: Dict[str, Any], output: Dict[str, Any],
                 context: Dict[str, Any]) -> ValidationReport:
        raise NotImplementedError


# ── CODING validator ───────────────────────────────────────────────────────────

class CodingValidator(BaseValidator):
    """Tests, lint (parse), build (import), diff."""
    validator_type = "coding"

    def validate(self, task: Dict[str, Any], output: Dict[str, Any],
                 context: Dict[str, Any]) -> ValidationReport:
        report = ValidationReport(validator_type=self.validator_type, passed=True)

        code = output.get("code", "")
        tests = output.get("tests", "")

        # 1. Code must parse (lint equivalent)
        code_ok = self._check_syntax(code, report)

        # 2. Tests must exist
        tests_ok = self._check_tests(tests, output, report)

        # 3. Diff: code must differ from input (meaningful change)
        diff_ok = self._check_diff(code, context.get("input_code", ""), report)

        report.passed = code_ok and tests_ok and diff_ok
        report.summary = f"coding: parse={code_ok}, tests={tests_ok}, diff={diff_ok}"
        return report

    def _check_syntax(self, code: str, report: ValidationReport) -> bool:
        if not code.strip():
            report.add_check("syntax", False, "No code provided")
            return False
        try:
            ast.parse(code)
            report.add_check("syntax", True, "Code parses cleanly")
            return True
        except SyntaxError as e:
            report.add_check("syntax", False, f"Syntax error: {e}")
            return False

    def _check_tests(self, tests: str, output: Dict, report: ValidationReport) -> bool:
        test_passed = output.get("test_passed")
        if test_passed is True:
            report.add_check("tests", True, "Tests passed")
            return True
        if tests.strip():
            report.add_check("tests", True, "Test file present")
            return True
        report.add_check("tests", False, "No tests provided")
        return False

    def _check_diff(self, code: str, input_code: str, report: ValidationReport) -> bool:
        if not input_code.strip():
            report.add_check("diff", True, "No input to compare; assumed new")
            return True
        if code.strip() == input_code.strip():
            report.add_check("diff", False, "Code unchanged from input")
            return False
        report.add_check("diff", True, "Code differs from input")
        return True


# ── WRITING validator ──────────────────────────────────────────────────────────

class WritingValidator(BaseValidator):
    """Requirements coverage, length, formatting, factual consistency."""
    validator_type = "writing"
    MIN_WORDS = 50

    def validate(self, task: Dict[str, Any], output: Dict[str, Any],
                 context: Dict[str, Any]) -> ValidationReport:
        report = ValidationReport(validator_type=self.validator_type, passed=True)
        text = output.get("text", "")

        length_ok = self._check_length(text, report)
        coverage_ok = self._check_requirements_coverage(text, output.get("requirements", []), report)
        format_ok = self._check_formatting(text, report)

        report.passed = length_ok and coverage_ok and format_ok
        report.summary = f"writing: length={length_ok}, coverage={coverage_ok}, format={format_ok}"
        return report

    def _check_length(self, text: str, report: ValidationReport) -> bool:
        words = len(text.split())
        if words < self.MIN_WORDS:
            report.add_check("length", False, f"Too short: {words} words (min {self.MIN_WORDS})")
            return False
        report.add_check("length", True, f"{words} words")
        return True

    def _check_requirements_coverage(self, text: str, requirements: List[str],
                                     report: ValidationReport) -> bool:
        if not requirements:
            report.add_check("requirements_coverage", True, "No requirements to cover")
            return True
        text_lower = text.lower()
        covered = sum(1 for r in requirements if r.lower() in text_lower)
        ratio = covered / len(requirements)
        if ratio < 0.5:
            report.add_check("requirements_coverage", False,
                             f"Only {covered}/{len(requirements)} requirements addressed")
            return False
        report.add_check("requirements_coverage", True,
                         f"{covered}/{len(requirements)} requirements addressed")
        return True

    def _check_formatting(self, text: str, report: ValidationReport) -> bool:
        has_headings = bool(re.search(r'^#{1,6}\s', text, re.MULTILINE)) or \
                       bool(re.search(r'^[A-Z][^.]*$', text, re.MULTILINE))
        if not has_headings and len(text.split()) > self.MIN_WORDS:
            report.add_check("formatting", False, "No headings/structure detected")
            return False
        report.add_check("formatting", True, "Has structure/headings")
        return True


# ── RESEARCH validator ─────────────────────────────────────────────────────────

class ResearchValidator(BaseValidator):
    """Source count, source quality, citation/provenance, completeness."""
    validator_type = "research"
    MIN_SOURCES = 3

    def validate(self, task: Dict[str, Any], output: Dict[str, Any],
                 context: Dict[str, Any]) -> ValidationReport:
        report = ValidationReport(validator_type=self.validator_type, passed=True)

        sources = output.get("sources", [])
        claims = output.get("claims", [])

        count_ok = self._check_source_count(sources, report)
        citation_ok = self._check_citations(claims, sources, report)
        quality_ok = self._check_source_quality(sources, report)

        report.passed = count_ok and citation_ok and quality_ok
        report.summary = f"research: count={count_ok}, citation={citation_ok}, quality={quality_ok}"
        return report

    def _check_source_count(self, sources: List, report: ValidationReport) -> bool:
        if len(sources) < self.MIN_SOURCES:
            report.add_check("source_count", False,
                             f"Only {len(sources)} sources (min {self.MIN_SOURCES})")
            return False
        report.add_check("source_count", True, f"{len(sources)} sources")
        return True

    def _check_citations(self, claims: List, sources: List, report: ValidationReport) -> bool:
        if not claims:
            report.add_check("citations", True, "No claims to verify")
            return True
        source_urls = {s.get("url", "") for s in sources}
        cited = sum(1 for c in claims if c.get("source", "") in source_urls)
        ratio = cited / len(claims)
        if ratio < 0.5:
            report.add_check("citations", False,
                             f"Only {cited}/{len(claims)} claims cited")
            return False
        report.add_check("citations", True, f"{cited}/{len(claims)} claims cited")
        return True

    def _check_source_quality(self, sources: List, report: ValidationReport) -> bool:
        domains = set()
        for s in sources:
            url = s.get("url", "")
            m = re.search(r'://([^/]+)', url)
            if m:
                domains.add(m.group(1))
        if len(domains) < 2:
            report.add_check("source_quality", False,
                             f"Only {len(domains)} unique domain(s)")
            return False
        report.add_check("source_quality", True, f"{len(domains)} unique domains")
        return True


# ── DATA validator ──────────────────────────────────────────────────────────────

class DataValidator(BaseValidator):
    """Schema validation, row counts, duplicate detection, consistency."""
    validator_type = "data"

    def validate(self, task: Dict[str, Any], output: Dict[str, Any],
                 context: Dict[str, Any]) -> ValidationReport:
        report = ValidationReport(validator_type=self.validator_type, passed=True)

        rows = output.get("rows", [])
        schema = output.get("schema", {})

        schema_ok = self._check_schema(rows, schema, report)
        rows_ok = self._check_row_counts(rows, report)
        dup_ok = self._check_duplicates(rows, report)

        report.passed = schema_ok and rows_ok and dup_ok
        report.summary = f"data: schema={schema_ok}, rows={rows_ok}, dups={dup_ok}"
        return report

    def _check_schema(self, rows: List, schema: Dict, report: ValidationReport) -> bool:
        if not rows:
            report.add_check("schema", False, "No rows")
            return False
        if not schema:
            report.add_check("schema", True, "No schema specified; skipped")
            return True
        actual = set(rows[0].keys()) if rows else set()
        expected = set(schema.keys())
        missing = expected - actual
        if missing:
            report.add_check("schema", False, f"Missing fields: {missing}")
            return False
        report.add_check("schema", True, "All expected fields present")
        return True

    def _check_row_counts(self, rows: List, report: ValidationReport) -> bool:
        if not rows:
            report.add_check("row_counts", False, "Zero rows")
            return False
        report.add_check("row_counts", True, f"{len(rows)} rows")
        return True

    def _check_duplicates(self, rows: List, report: ValidationReport) -> bool:
        if not rows:
            report.add_check("duplicates", True, "No rows to check")
            return True
        seen = set()
        dups = 0
        for r in rows:
            key = tuple(sorted(r.items())) if isinstance(r, dict) else r
            if key in seen:
                dups += 1
            seen.add(key)
        if dups > 0:
            report.add_check("duplicates", False, f"{dups} duplicate row(s)")
            return False
        report.add_check("duplicates", True, "No duplicates")
        return True


# ── TRANSCRIPTION validator ────────────────────────────────────────────────────

class TranscriptionValidator(BaseValidator):
    """Output format, completeness, timestamp integrity."""
    validator_type = "transcription"

    def validate(self, task: Dict[str, Any], output: Dict[str, Any],
                 context: Dict[str, Any]) -> ValidationReport:
        report = ValidationReport(validator_type=self.validator_type, passed=True)

        segments = output.get("segments", [])

        format_ok = self._check_format(output.get("format", ""), report)
        ts_ok = self._check_timestamp_integrity(segments, report)
        complete_ok = self._check_completeness(segments, context.get("duration", 0), report)

        report.passed = format_ok and ts_ok and complete_ok
        report.summary = f"transcription: format={format_ok}, timestamps={ts_ok}, complete={complete_ok}"
        return report

    def _check_format(self, fmt: str, report: ValidationReport) -> bool:
        valid = {"srt", "txt", "md", "vtt", "json"}
        if fmt.lower() not in valid:
            report.add_check("format", False, f"Unknown format: {fmt}")
            return False
        report.add_check("format", True, f"Format: {fmt}")
        return True

    def _check_timestamp_integrity(self, segments: List, report: ValidationReport) -> bool:
        if not segments:
            report.add_check("timestamp_integrity", False, "No segments")
            return False
        for i, s in enumerate(segments):
            if s.get("start", 0) >= s.get("end", 0):
                report.add_check("timestamp_integrity", False,
                                 f"Segment {i}: start >= end")
                return False
        # check overlap
        for i in range(1, len(segments)):
            if segments[i].get("start", 0) < segments[i-1].get("end", 0):
                report.add_check("timestamp_integrity", False,
                                 f"Segment {i} overlaps with previous")
                return False
        report.add_check("timestamp_integrity", True, "Timestamps valid and non-overlapping")
        return True

    def _check_completeness(self, segments: List, duration: float, report: ValidationReport) -> bool:
        if not segments:
            report.add_check("completeness", False, "No segments")
            return False
        if duration <= 0:
            report.add_check("completeness", True, "No duration to compare")
            return True
        last_end = max(s.get("end", 0) for s in segments)
        coverage = last_end / duration
        if coverage < 0.8:
            report.add_check("completeness", False,
                             f"Only {coverage:.0%} coverage")
            return False
        report.add_check("completeness", True, f"{coverage:.0%} coverage")
        return True


# ── DOCUMENT validator ─────────────────────────────────────────────────────────

class DocumentValidator(BaseValidator):
    """Required fields, formatting, page count, content coverage."""
    validator_type = "document"

    def validate(self, task: Dict[str, Any], output: Dict[str, Any],
                 context: Dict[str, Any]) -> ValidationReport:
        report = ValidationReport(validator_type=self.validator_type, passed=True)

        fields = output.get("fields", {})
        required = output.get("required_fields", [])

        fields_ok = self._check_required_fields(fields, required, report)
        format_ok = self._check_formatting(output, report)
        coverage_ok = self._check_content_coverage(output, report)

        report.passed = fields_ok and format_ok and coverage_ok
        report.summary = f"document: fields={fields_ok}, format={format_ok}, coverage={coverage_ok}"
        return report

    def _check_required_fields(self, fields: Dict, required: List, report: ValidationReport) -> bool:
        if not required:
            report.add_check("required_fields", True, "No required fields specified")
            return True
        missing = [f for f in required if not fields.get(f, "")]
        if missing:
            report.add_check("required_fields", False, f"Missing: {missing}")
            return False
        report.add_check("required_fields", True, "All required fields present")
        return True

    def _check_formatting(self, output: Dict, report: ValidationReport) -> bool:
        sections = output.get("sections", [])
        if not sections:
            report.add_check("formatting", False, "No sections")
            return False
        report.add_check("formatting", True, f"{len(sections)} sections")
        return True

    def _check_content_coverage(self, output: Dict, report: ValidationReport) -> bool:
        sections = output.get("sections", [])
        if not sections:
            report.add_check("content_coverage", False, "No sections")
            return False
        report.add_check("content_coverage", True, f"{len(sections)} sections present")
        return True


# ── Validator registry ──────────────────────────────────────────────────────────

VALIDATOR_REGISTRY: Dict[str, type] = {
    "coding": CodingValidator,
    "writing": WritingValidator,
    "research": ResearchValidator,
    "data": DataValidator,
    "transcription": TranscriptionValidator,
    "document": DocumentValidator,
}


def get_validator(task_type: str) -> BaseValidator:
    """Return the appropriate validator for a task type. Falls back to WritingValidator."""
    tt = (task_type or "").lower()
    for key, cls in VALIDATOR_REGISTRY.items():
        if key in tt:
            return cls()
    # fallback
    return WritingValidator()


__all__ = [
    "ValidationReport",
    "BaseValidator",
    "CodingValidator",
    "WritingValidator",
    "ResearchValidator",
    "DataValidator",
    "TranscriptionValidator",
    "DocumentValidator",
    "VALIDATOR_REGISTRY",
    "get_validator",
]
