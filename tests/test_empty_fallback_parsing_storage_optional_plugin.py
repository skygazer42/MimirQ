from app.parsing.processors.support.recovery import _document_questions_enabled
from app.rag.kg.extraction_job_options import build_kg_extraction_job_options
from app.tasks.jobs import _kg_extraction_runtime


def test_kg_worker_keeps_the_frozen_absent_plugin_selection():
    frozen = build_kg_extraction_job_options(
        pipeline_hash=None,
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        extraction_backend="llm",
        kg_python_plugin=None,
        kg_python_params={},
        replace_existing=True,
        prune_orphan_entities=True,
        extract_relations=False,
        extract_skills=False,
    )

    runtime = _kg_extraction_runtime(effective=None, frozen_options=frozen)

    assert runtime["kg_python_plugin"] is None


def test_document_question_numeric_zero_disables_the_default_enabled_flag(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DOCUMENT_QUESTIONS_ENABLED", True)

    assert _document_questions_enabled({"document_questions_enabled": 0}) is False
    assert _document_questions_enabled({"document_questions_enabled": None}) is True
