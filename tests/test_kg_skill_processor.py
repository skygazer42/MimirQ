from __future__ import annotations

import asyncio

import pytest


class _FakeLLM:
    def __init__(self, payload):  # noqa: ANN001
        self._payload = payload

    async def chat_with_schema(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await asyncio.sleep(0)  # Sonar S7503
        return self._payload


@pytest.mark.asyncio
async def test_skill_processor_accepts_empty_list() -> None:
    from app.rag.kg.extraction.skill_processor import SkillProcessor

    proc = SkillProcessor(_FakeLLM({"skills": []}))
    out = await proc.extract_skills(text="No procedural content here.", max_skills=3)
    assert out == []


@pytest.mark.asyncio
async def test_skill_processor_coerces_steps_to_list() -> None:
    from app.rag.kg.extraction.skill_processor import SkillProcessor

    proc = SkillProcessor(
        _FakeLLM(
            {
                "skills": [
                    {
                        "name": "Setup Python venv",
                        "summary": "Create and activate a virtual environment.",
                        "steps": "python -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt",
                        "inputs": "requirements.txt",
                        "outputs": [".venv"],
                        "tools": ["python", "pip"],
                        "tags": ["python", "environment"],
                    }
                ]
            }
        )
    )

    out = await proc.extract_skills(text="...", max_skills=3)
    assert len(out) == 1
    assert out[0]["name"] == "Setup Python venv"
    assert out[0]["steps"] == [
        "python -m venv .venv",
        "source .venv/bin/activate",
        "pip install -r requirements.txt",
    ]
    assert out[0]["inputs"] == ["requirements.txt"]


@pytest.mark.asyncio
async def test_skill_processor_passes_through_category() -> None:
    from app.rag.kg.extraction.skill_processor import SkillProcessor

    proc = SkillProcessor(
        _FakeLLM(
            {
                "skills": [
                    {
                        "name": "Setup Python venv",
                        "category": "Development",
                        "summary": "Create and activate a virtual environment.",
                        "steps": ["python -m venv .venv"],
                        "tags": ["python", "environment"],
                    }
                ]
            }
        )
    )

    out = await proc.extract_skills(text="...", max_skills=3)
    assert len(out) == 1
    assert out[0].get("category") == "Development"


@pytest.mark.asyncio
async def test_skill_processor_passes_through_evidence_quote() -> None:
    from app.rag.kg.extraction.skill_processor import SkillProcessor

    proc = SkillProcessor(
        _FakeLLM(
            {
                "skills": [
                    {
                        "name": "Setup Python venv",
                        "evidence_quote": "python -m venv .venv",
                    }
                ]
            }
        )
    )

    out = await proc.extract_skills(text="...", max_skills=3)
    assert len(out) == 1
    assert out[0].get("evidence_quote") == "python -m venv .venv"
