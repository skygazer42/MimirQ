"""
Entity verification pass for KG extraction.

This is an optional second LLM pass designed to:
- reduce noisy entities (precision)
- correct entity types/descriptions
- optionally add alias_of edges between candidates (fragmentation reduction)

All outputs are gated by deterministic evidence checks in the caller.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.kg.utils import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole

logger = get_logger("kg.extract.entity_verify")


def _clamp01(value: object, *, default: float) -> float:
    try:
        f = float(value)  # type: ignore[arg-type]
    except Exception:
        return float(default)
    if math.isnan(f):
        return float(default)
    return max(0.0, min(1.0, float(f)))


@dataclass(frozen=True)
class EntityCandidate:
    cid: str
    name: str
    type: str = "unknown"
    description: str = ""
    evidence_quote: str | None = None


class EntityVerifier:
    def __init__(self, llm_client: BaseLLMClient):
        self.llm_client = llm_client
        self.parser = EntityValueParser()

    async def verify(
        self,
        *,
        text: str,
        candidates: Sequence[EntityCandidate],
        max_keep: int = 30,
        max_alias_edges: int = 10,
    ) -> dict[str, Any]:
        """
        Return a sanitized payload:
        - kept: [{id, type, description, evidence_quote, confidence}]
        - aliases: [{alias_id, canonical_id, confidence, evidence_quote}]
        """
        clean_text = (text or "").strip()
        if not clean_text:
            return {"kept": [], "aliases": []}

        cand_list = [c for c in (candidates or []) if str(getattr(c, "cid", "") or "").strip()]
        if not cand_list:
            return {"kept": [], "aliases": []}

        keep_lim = max(0, int(max_keep or 0))
        if keep_lim <= 0:
            return {"kept": [], "aliases": []}

        alias_lim = max(0, int(max_alias_edges or 0))

        # Keep the prompt compact and deterministic: id + name + type (+ short desc).
        cand_lines: list[str] = []
        for c in cand_list:
            cid = str(c.cid).strip()
            name = str(c.name or "").strip()
            if not cid or not name:
                continue
            etype = str(c.type or "unknown").strip() or "unknown"
            desc = str(c.description or "").strip()
            if desc:
                desc = desc[:120]
                cand_lines.append(f"{cid}: {name} ({etype}) - {desc}")
            else:
                cand_lines.append(f"{cid}: {name} ({etype})")

        if not cand_lines:
            return {"kept": [], "aliases": []}

        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "kept": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "type": {"type": "string"},
                            "description": {"type": "string"},
                            "confidence": {"type": "number"},
                            "evidence_quote": {"type": "string"},
                        },
                        "required": ["id"],
                    },
                },
                "aliases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "alias_id": {"type": "string"},
                            "canonical_id": {"type": "string"},
                            "confidence": {"type": "number"},
                            "evidence_quote": {"type": "string"},
                        },
                        "required": ["alias_id", "canonical_id"],
                    },
                },
            },
        }

        prompt = (
            "You are cleaning and verifying entity candidates for a Knowledge Graph (KG) extraction pipeline.\n"
            "Return JSON only.\n"
            "\n"
            "Rules:\n"
            f"- Keep at most {keep_lim} entities.\n"
            "- Only keep entities that are clearly supported by the text.\n"
            "- Prefer specific named entities over generic concepts (avoid keeping stopwords like "
            "'system', 'method' unless truly central).\n"
            "- You may correct the entity type and description.\n"
            "- For each kept entity, include evidence_quote: an exact substring copied verbatim from the text.\n"
            "- If you identify explicit aliases/abbreviations/synonyms among the candidates, add up "
            f"to {alias_lim} alias edges.\n"
            "- For each alias edge, include evidence_quote copied verbatim from the text.\n"
            "- alias_id and canonical_id MUST refer to candidate ids.\n"
            "\n"
            "Candidates:\n"
            f"{chr(10).join(cand_lines)}\n"
            "\n"
            "Text:\n"
            f"{clean_text}\n"
        )

        messages = [LLMMessage(role=LLMRole.USER, content=prompt)]
        try:
            raw = await self.llm_client.chat_with_schema(messages, response_schema=schema, temperature=0.2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Entity verify failed; returning no-op: %s", str(exc)[:200])
            return {"kept": [], "aliases": []}

        kept_raw = raw.get("kept") if isinstance(raw, dict) else None
        aliases_raw = raw.get("aliases") if isinstance(raw, dict) else None

        valid_ids = {str(c.cid).strip() for c in cand_list if str(getattr(c, "cid", "") or "").strip()}

        kept: list[dict[str, Any]] = []
        seen_keep: set[str] = set()
        if isinstance(kept_raw, list):
            for item in kept_raw:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("id") or "").strip()
                if not cid or cid not in valid_ids or cid in seen_keep:
                    continue
                seen_keep.add(cid)

                etype = self.parser.normalize_type(str(item.get("type") or "unknown"))
                desc = str(item.get("description") or "").strip() or None
                evq = str(item.get("evidence_quote") or "").strip() or None
                kept.append(
                    {
                        "id": cid,
                        "type": etype,
                        "description": (desc[:400] if desc else None),
                        "evidence_quote": (evq[:300] if evq else None),
                        "confidence": _clamp01(item.get("confidence"), default=0.7),
                    }
                )
                if len(kept) >= keep_lim:
                    break

        aliases: list[dict[str, Any]] = []
        seen_alias: set[tuple[str, str]] = set()
        if alias_lim > 0 and isinstance(aliases_raw, list):
            for item in aliases_raw:
                if not isinstance(item, dict):
                    continue
                a = str(item.get("alias_id") or "").strip()
                c = str(item.get("canonical_id") or "").strip()
                if not a or not c or a == c:
                    continue
                if a not in valid_ids or c not in valid_ids:
                    continue
                key = (a, c)
                if key in seen_alias:
                    continue
                seen_alias.add(key)

                evq = str(item.get("evidence_quote") or "").strip() or None
                aliases.append(
                    {
                        "alias_id": a,
                        "canonical_id": c,
                        "evidence_quote": (evq[:300] if evq else None),
                        "confidence": _clamp01(item.get("confidence"), default=0.9),
                    }
                )
                if len(aliases) >= alias_lim:
                    break

        return {"kept": kept, "aliases": aliases}


__all__ = ["EntityCandidate", "EntityVerifier"]
