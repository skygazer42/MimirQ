"""
Skill processor: extract procedural "skills" (SOP-style know-how) from text chunks.

This complements event/entity extraction by capturing process knowledge:
- steps
- inputs / outputs
- tools
- tags
"""


import math
from typing import Any

from app.rag.kg.utils import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole

logger = get_logger("kg.extract.skills")


def _coerce_str_list(value: object, *, max_items: int = 50) -> list[str]:
    lim = max(0, int(max_items or 0))
    if lim <= 0:
        return []

    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parts = [p.strip() for p in text.splitlines()]
        out = [p for p in parts if p]
        if not out:
            out = [text]
        return out[:lim]

    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            s = str(item or "").strip()
            if not s:
                continue
            out.append(s)
            if len(out) >= lim:
                break
        return out

    # Fallback: coerce scalars to a single-item list.
    text = str(value).strip()
    if not text:
        return []
    return [text][:lim]


def _clamp01(value: object, *, default: float) -> float:
    try:
        f = float(value)  # type: ignore[arg-type]
    except Exception:
        return float(default)
    if math.isnan(f):
        return float(default)
    return max(0.0, min(1.0, float(f)))


class SkillProcessor:
    def __init__(self, llm_client: BaseLLMClient):
        self.llm_client = llm_client

    async def extract_skills(
        self,
        *,
        text: str,
        max_skills: int = 3,
    ) -> list[dict[str, Any]]:
        clean_text = (text or "").strip()
        if not clean_text:
            return []

        max_items = max(0, int(max_skills or 0))
        if max_items <= 0:
            return []

        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "category": {"type": "string"},
                            "summary": {"type": "string"},
                            "evidence_quote": {"type": "string"},
                            "steps": {"type": "array", "items": {"type": "string"}},
                            "inputs": {"type": "array", "items": {"type": "string"}},
                            "outputs": {"type": "array", "items": {"type": "string"}},
                            "tools": {"type": "array", "items": {"type": "string"}},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number"},
                        },
                        "required": ["name"],
                    },
                }
            },
        }

        prompt = (
            "Extract procedural skills (SOP-style know-how) from the text.\n"
            "Return JSON only.\n"
            f"Constraints:\n- Extract at most {max_items} skills.\n"
            "- Only include skills that are directly supported by the text.\n"
            "- Prefer concrete, executable steps.\n\n"
            "Evidence:\n"
            "- For each skill, include evidence_quote: an exact substring copied verbatim from the Text section.\n"
            "- evidence_quote MUST be copied verbatim (no paraphrase).\n"
            "- Keep evidence_quote short (prefer a single sentence/phrase, <= 240 chars).\n\n"
            "Optional fields:\n"
            "- category: a coarse category label (short phrase), e.g. Development / Data / AIGC / Science.\n\n"
            "Text:\n"
            f"{clean_text}\n"
        )

        messages = [LLMMessage(role=LLMRole.USER, content=prompt)]
        result = await self.llm_client.chat_with_schema(messages, response_schema=schema, temperature=0.2)

        raw_skills = result.get("skills") if isinstance(result, dict) else None
        if not isinstance(raw_skills, list) or not raw_skills:
            return []

        out: list[dict[str, Any]] = []
        for raw in raw_skills:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue

            category = str(raw.get("category") or "").strip() or None
            summary = str(raw.get("summary") or "").strip() or None
            evidence_quote = str(raw.get("evidence_quote") or "").strip() or None
            if evidence_quote and len(evidence_quote) > 240:
                evidence_quote = evidence_quote[:240]
            steps = _coerce_str_list(raw.get("steps"), max_items=30)
            inputs = _coerce_str_list(raw.get("inputs"), max_items=30)
            outputs = _coerce_str_list(raw.get("outputs"), max_items=30)
            tools = _coerce_str_list(raw.get("tools"), max_items=30)
            tags = _coerce_str_list(raw.get("tags"), max_items=30)

            out.append(
                {
                    "name": name,
                    "category": category,
                    "summary": summary,
                    "evidence_quote": evidence_quote,
                    "steps": steps,
                    "inputs": inputs,
                    "outputs": outputs,
                    "tools": tools,
                    "tags": tags,
                    "confidence": _clamp01(raw.get("confidence"), default=0.6),
                }
            )

            if len(out) >= max_items:
                break

        logger.info("Extracted %s skills", len(out))
        return out


__all__ = ["SkillProcessor"]
