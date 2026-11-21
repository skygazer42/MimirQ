"""
Entity verification pass for KG extraction.

This is an optional second LLM pass designed to:
- reduce noisy entities (precision)
- correct entity types/descriptions
- optionally add alias_of edges between candidates (fragmentation reduction)

All outputs are gated by deterministic evidence checks in the caller.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.rag.kg.extraction.evidence import clamp_confidence
from app.rag.kg.extraction.parser import normalize_entity_type
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole


def _empty_verify_result() -> dict[str, list[dict[str, Any]]]:
    return {"kept": [], "aliases": []}


def _build_candidate_lines(candidates: Sequence["EntityCandidate"]) -> list[str]:
    lines: list[str] = []
    for candidate in candidates:
        cid = candidate.cid.strip()
        name = candidate.name.strip()
        if not cid or not name:
            continue
        etype = candidate.type.strip() or "unknown"
        desc = candidate.description.strip()
        if desc:
            lines.append(f"{cid}: {name} ({etype}) - {desc[:120]}")
            continue
        lines.append(f"{cid}: {name} ({etype})")
    return lines


def _entity_verification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["kept"],
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


def _build_verification_prompt(
    *,
    clean_text: str,
    candidate_lines: list[str],
    keep_limit: int,
    alias_limit: int,
) -> str:
    return (
        "You are cleaning and verifying entity candidates for a Knowledge Graph (KG) extraction pipeline.\n"
        "Return JSON only.\n"
        "\n"
        "Rules:\n"
        f"- Keep at most {keep_limit} entities.\n"
        "- Only keep entities that are clearly supported by the text.\n"
        "- Prefer specific named entities over generic concepts (avoid keeping stopwords like "
        "'system', 'method' unless truly central).\n"
        "- You may correct the entity type and description.\n"
        "- For each kept entity, include evidence_quote: an exact substring copied verbatim from the text.\n"
        "- If you identify explicit aliases/abbreviations/synonyms among the candidates, add up "
        f"to {alias_limit} alias edges.\n"
        "- For each alias edge, include evidence_quote copied verbatim from the text.\n"
        "- alias_id and canonical_id MUST refer to candidate ids.\n"
        "\n"
        "Candidates:\n"
        f"{chr(10).join(candidate_lines)}\n"
        "\n"
        "Text:\n"
        f"{clean_text}\n"
    )


def _sanitize_kept_entities(items: object, *, valid_ids: set[str], keep_limit: int) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    if not isinstance(items, list):
        raise ValueError("Entity verification response requires a kept array")

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Entity verification kept items must be objects")
        cid = item.get("id")
        if not isinstance(cid, str):
            raise ValueError("Verified entity IDs must be strings")
        cid = cid.strip()
        if not cid or cid not in valid_ids:
            raise ValueError("Verified entity ID is outside the candidate set")
        if cid in seen_ids:
            continue
        desc = item.get("description")
        evidence_quote = item.get("evidence_quote")
        entity_type = item.get("type")
        if any(value is not None and not isinstance(value, str) for value in (desc, evidence_quote, entity_type)):
            raise ValueError("Verified entity text fields must be strings or null")
        desc = (desc.strip() or None) if desc is not None else None
        evidence_quote = (evidence_quote.strip() or None) if evidence_quote is not None else None
        seen_ids.add(cid)
        kept.append(
            {
                "id": cid,
                "type": normalize_entity_type(entity_type if entity_type is not None else "unknown"),
                "description": desc[:400] if desc else None,
                "evidence_quote": evidence_quote[:300] if evidence_quote else None,
                "confidence": clamp_confidence(item.get("confidence"), default=0.7),
            }
        )
        if len(kept) >= keep_limit:
            break
    return kept


def _sanitize_aliases(
    items: object,
    *,
    valid_ids: set[str],
    alias_limit: int,
) -> list[dict[str, Any]]:
    aliases: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    if alias_limit <= 0 or items is None:
        return aliases
    if not isinstance(items, list):
        raise ValueError("Entity verification aliases must be an array or null")

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Verified aliases must be objects")
        alias_id = item.get("alias_id")
        canonical_id = item.get("canonical_id")
        if not isinstance(alias_id, str) or not isinstance(canonical_id, str):
            raise ValueError("Verified alias IDs must be strings")
        alias_id = alias_id.strip()
        canonical_id = canonical_id.strip()
        if not alias_id or not canonical_id or alias_id == canonical_id:
            continue
        if alias_id not in valid_ids or canonical_id not in valid_ids:
            raise ValueError("Verified alias ID is outside the candidate set")
        pair = (alias_id, canonical_id)
        if pair in seen_pairs:
            continue
        evidence_quote = item.get("evidence_quote")
        if evidence_quote is not None and not isinstance(evidence_quote, str):
            raise ValueError("Verified alias evidence must be text or null")
        evidence_quote = (evidence_quote.strip() or None) if evidence_quote is not None else None
        seen_pairs.add(pair)
        aliases.append(
            {
                "alias_id": alias_id,
                "canonical_id": canonical_id,
                "evidence_quote": evidence_quote[:300] if evidence_quote else None,
                "confidence": clamp_confidence(item.get("confidence"), default=0.9),
            }
        )
        if len(aliases) >= alias_limit:
            break
    return aliases


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
        clean_text = text.strip()
        if not clean_text or max_keep <= 0:
            return _empty_verify_result()

        cand_lines = _build_candidate_lines(candidates)
        if not cand_lines:
            return _empty_verify_result()

        valid_ids = {candidate.cid.strip() for candidate in candidates}
        alias_limit = max(0, max_alias_edges)
        messages = [
            LLMMessage(
                role=LLMRole.USER,
                content=_build_verification_prompt(
                    clean_text=clean_text,
                    candidate_lines=cand_lines,
                    keep_limit=max_keep,
                    alias_limit=alias_limit,
                ),
            )
        ]
        raw = await self.llm_client.chat_with_schema(
            messages,
            response_schema=_entity_verification_schema(),
            temperature=0.2,
        )
        return {
            "kept": _sanitize_kept_entities(
                raw.get("kept"),
                valid_ids=valid_ids,
                keep_limit=max_keep,
            ),
            "aliases": _sanitize_aliases(
                raw.get("aliases"),
                valid_ids=valid_ids,
                alias_limit=alias_limit,
            ),
        }


__all__ = ["EntityCandidate", "EntityVerifier"]
