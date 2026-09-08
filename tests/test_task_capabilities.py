"""tests/test_task_capabilities.py — reusable Skill/Task capability framework (v2.0.36e).

Covers the user's required behavior:
- Task spec carries the 10 required fields (task_type, required_capabilities, inputs,
  expected_outputs, tools_required, estimated_effort, validation_method, human_required,
  execution_mode, payment_conditions).
- Extensible taxonomy (17 seed categories + OTHER; arbitrary new capabilities registerable).
- The LLM MAY determine semantic requirements (infer_task_requirements) but the DETERMINISTIC
  CapabilityValidator is authoritative.
- Verdicts: fully_automatable / partially_automatable / human_required / unsupported.
- Unsupported tasks MUST NOT appear executable (is_executable=False).
- Reuse existing skills/*.md (capability -> skill_file pointer).
- Integration: task_from_opportunity maps an Opportunity into a Task.
"""

import unittest

from agents.capability_registry import (
    CapabilityRegistry, CapabilityCategory, CapabilitySpec, DEFAULT_REGISTRY,
)
from agents.task_spec import (
    Task, TaskFeasibility, build_task, infer_task_requirements,
    task_from_opportunity, set_requirement_inferrer,
)
from agents.task_validator import CapabilityValidator


class TestTaxonomyExtensible(unittest.TestCase):
    def test_seed_categories_present(self):
        for c in ["READING", "WRITING", "EDITING", "RESEARCH", "DATA", "TRANSCRIPTION",
                  "CODING", "TESTING", "QA", "DOCUMENTS", "CONTENT", "WEB_RESEARCH",
                  "AUTOMATION", "ANALYSIS", "ADMINISTRATIVE", "CRYPTO", "OTHER"]:
            self.assertIn(c, CapabilityCategory.values())

    def test_registry_seeded_with_system_caps(self):
        r = CapabilityRegistry()
        self.assertIn("CODING", r)
        self.assertTrue(r.get("CODING").automatable)
        self.assertIn("TRANSCRIPTION", r)

    def test_taxonomy_extensible_via_register(self):
        r = CapabilityRegistry()
        r.register(CapabilitySpec("VOICEOVER", CapabilityCategory.OTHER,
                                  automatable=False, human_capable=True))
        self.assertIn("VOICEOVER", r)
        self.assertFalse(r.get("VOICEOVER").automatable)
        self.assertTrue(r.get("VOICEOVER").human_capable)

    def test_by_category_groups_coding_cluster(self):
        r = CapabilityRegistry()
        coding = {c.name for c in r.by_category(CapabilityCategory.CODING)}
        self.assertIn("CODING", coding)
        self.assertIn("DEBUGGING", coding)

    def test_skill_file_reuse_pointer(self):
        # Reuse existing skills/*.md rather than duplicating docs.
        r = CapabilityRegistry()
        self.assertEqual(r.get("READING").skill_file, "skills/document-qa.md")
        self.assertEqual(r.get("DOCUMENT_QA").skill_file, "skills/document-qa.md")


class TestTaskSpecFields(unittest.TestCase):
    def test_task_carries_ten_required_fields(self):
        t = Task(task_type="proofreading", required_capabilities=["READING", "EDITING"],
                 inputs=["doc.pdf"], expected_outputs=["proofed.pdf"],
                 tools_required=["filesystem.write"], estimated_effort=2.0,
                 validation_method="diff review", human_required=False,
                 execution_mode="automatic",
                 payment_conditions={"rate": "per_page"})
        for f in ("task_type", "required_capabilities", "inputs", "expected_outputs",
                  "tools_required", "estimated_effort", "validation_method",
                  "human_required", "execution_mode", "payment_conditions"):
            self.assertTrue(hasattr(t, f))
        self.assertEqual(t.payment_conditions["rate"], "per_page")

    def test_normalized_requirements_are_upper_and_unique(self):
        t = Task(required_capabilities=["coding", "CODING", "editing"])
        self.assertEqual(t.normalized_requirements(), ["CODING", "EDITING"])


class TestSemanticInference(unittest.TestCase):
    def test_proofread_maps_to_reading_editing_document_qa(self):
        caps = infer_task_requirements("Proofread 20 pages")
        self.assertIn("READING", caps)
        self.assertIn("EDITING", caps)
        self.assertIn("DOCUMENT_QA", caps)

    def test_fix_python_bug_maps_to_coding_debugging_testing(self):
        caps = infer_task_requirements("Fix Python bug in the parser")
        self.assertIn("CODING", caps)
        self.assertIn("DEBUGGING", caps)
        self.assertIn("TESTING", caps)

    def test_research_companies_maps_to_web_data_analysis(self):
        caps = infer_task_requirements("Research 30 companies and analyze the data")
        self.assertIn("WEB_RESEARCH", caps)
        self.assertIn("DATA", caps)
        self.assertIn("ANALYSIS", caps)

    def test_transcribe_maps_to_transcription(self):
        self.assertIn("TRANSCRIPTION", infer_task_requirements("Transcribe audio to text"))

    def test_build_task_infers_and_stores(self):
        t = build_task("proofreading", "Proofread 20 pages")
        self.assertEqual(t.task_type, "proofreading")
        self.assertTrue(t.required_capabilities)

    def test_llm_inferrer_is_optional_and_fails_safe(self):
        # Registering an LLM inferrer merges suggestions; lexicon still works if LLM raises.
        def boom(text):
            raise RuntimeError("llm down")
        set_requirement_inferrer(boom)
        caps = infer_task_requirements("Proofread a document")  # lexicon still returns results
        self.assertIn("READING", caps)
        set_requirement_inferrer(None)  # reset


class TestValidatorVerdicts(unittest.TestCase):
    def setUp(self):
        self.v = CapabilityValidator()  # default registry, human_available=True

    def test_proofread_fully_automatable(self):
        f = self.v.validate(build_task("proofreading", "Proofread 20 pages"))
        self.assertEqual(f.verdict, "fully_automatable")
        self.assertTrue(f.is_executable)
        self.assertEqual(f.confidence, 1.0)

    def test_fix_python_fully_automatable(self):
        f = self.v.validate(build_task("bugfix", "Fix Python bug"))
        self.assertEqual(f.verdict, "fully_automatable")
        self.assertTrue(f.is_executable)

    def test_research_fully_automatable(self):
        f = self.v.validate(build_task("research", "Research 30 companies and analyze"))
        self.assertEqual(f.verdict, "fully_automatable")
        self.assertTrue(f.is_executable)

    def test_transcribe_human_required(self):
        f = self.v.validate(build_task("transcribe", "Transcribe audio recording"))
        self.assertEqual(f.verdict, "human_required")
        self.assertTrue(f.is_executable)
        self.assertIn("TRANSCRIPTION", f.human_only)

    def test_transcribe_without_human_is_unsupported(self):
        v = CapabilityValidator(human_available=False)
        f = v.validate(build_task("transcribe", "Transcribe audio recording"))
        self.assertEqual(f.verdict, "unsupported")
        self.assertFalse(f.is_executable)  # NOT executable

    def test_partially_automatable_mix(self):
        t = build_task("mixed", "Write code and transcribe the demo",
                       extra_capabilities=["CODING", "TRANSCRIPTION"])
        f = self.v.validate(t)
        self.assertEqual(f.verdict, "partially_automatable")
        self.assertTrue(f.is_executable)
        self.assertIn("CODING", f.automatable)
        self.assertIn("TRANSCRIPTION", f.human_only)

    def test_unsupported_capability_is_not_executable(self):
        reg = CapabilityRegistry()
        from agents.capability_registry import CapabilityCategory as CC
        reg.register(CapabilitySpec("MIND_READING", CC.OTHER, automatable=False, human_capable=False))
        v = CapabilityValidator(registry=reg)
        f = v.validate(build_task("x", "do mind reading", extra_capabilities=["MIND_READING"]))
        self.assertEqual(f.verdict, "unsupported")
        self.assertFalse(f.is_executable)
        self.assertIn("MIND_READING", f.unsupported_hard)

    def test_missing_capability_with_human_is_human_required(self):
        f = self.v.validate(build_task("z", "do quantum poetry", extra_capabilities=["QUANTUM_POETRY"]))
        self.assertEqual(f.verdict, "human_required")
        self.assertTrue(f.is_executable)
        self.assertIn("QUANTUM_POETRY", f.missing_system)

    def test_no_requirements_is_unsupported_not_executable(self):
        f = self.v.validate(Task(task_type="vague"))
        self.assertEqual(f.verdict, "unsupported")
        self.assertFalse(f.is_executable)

    def test_validator_writes_execution_mode_back(self):
        t = build_task("proofreading", "Proofread 20 pages")
        self.v.validate(t)
        self.assertEqual(t.execution_mode, "automatic")
        self.assertFalse(t.human_required)
        t2 = build_task("transcribe", "Transcribe audio")
        self.v.validate(t2)
        self.assertEqual(t2.execution_mode, "human_in_loop")
        self.assertTrue(t2.human_required)

    def test_classify_single_capability(self):
        self.assertEqual(self.v.classify("CODING"), "fully_automatable")
        self.assertEqual(self.v.classify("TRANSCRIPTION"), "human_required")
        self.assertEqual(self.v.classify("NOPE"), "unsupported")


class TestOpportunityIntegration(unittest.TestCase):
    def test_task_from_opportunity_maps_skills(self):
        from agents.opportunity_models import Opportunity
        o = Opportunity(opportunity_id="x", source="s", platform="p", title="Build scraper",
                        description="coding task", category="dev", task_type="web_scraping",
                        required_skills=["python"], estimated_effort=3.0)
        t = task_from_opportunity(o)
        self.assertIn("WEB_SCRAPING", t.required_capabilities)
        self.assertIn("PYTHON", t.required_capabilities)
        self.assertEqual(t.estimated_effort, 3.0)

    def test_opportunity_task_validates_against_registry(self):
        from agents.opportunity_models import Opportunity
        o = Opportunity(opportunity_id="x", source="s", platform="p", title="Write article",
                        description="content writing", category="writing", task_type="article",
                        required_skills=["writing"])
        t = task_from_opportunity(o)
        f = CapabilityValidator().validate(t)
        self.assertIn(f.verdict, ("fully_automatable", "partially_automatable", "human_required"))


class TestUnsupportedNeverExecutable(unittest.TestCase):
    """Explicit guard: the framework must never present an unsupported task as runnable."""

    def test_any_unsupported_verdict_has_false_executable(self):
        v = CapabilityValidator()
        # Force an unsupported verdict by disabling human and requiring a human-only cap.
        v_no_human = CapabilityValidator(human_available=False)
        f = v_no_human.validate(build_task("t", "Transcribe audio"))
        if f.verdict == "unsupported":
            self.assertFalse(f.is_executable)
        # And a genuine hard-unsupported case
        reg = CapabilityRegistry()
        from agents.capability_registry import CapabilityCategory as CC
        reg.register(CapabilitySpec("UNOBTANIUM", CC.OTHER, automatable=False, human_capable=False))
        f2 = CapabilityValidator(registry=reg).validate(
            build_task("u", "mine unobtanium", extra_capabilities=["UNOBTANIUM"]))
        self.assertEqual(f2.verdict, "unsupported")
        self.assertFalse(f2.is_executable)


if __name__ == "__main__":
    unittest.main()
