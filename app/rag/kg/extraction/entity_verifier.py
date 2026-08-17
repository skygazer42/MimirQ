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


def _empty_verify_result() -> dict[str, list[dict[str, Any]]]:
    return {"kept": [], "aliases": []}


def _verified_candidate_ids(candidates: Sequence["EntityCandidate"]) -> set[str]:
    return {
        str(candidate.cid).strip()
        for candidate in (candidates or [])
        if str(getattr(candidate, "cid", "") or "").strip()
    }


def _build_candidate_lines(candidates: Sequence["EntityCandidate"]) -> list[str]:
    lines: list[str] = []
    for candidate in candidates:
        cid = str(candidate.cid).strip()
        name = str(candidate.name or "").strip()
        if not cid or not name:
            continue
        etype = str(candidate.type or "unknown").strip() or "unknown"
        desc = str(candidate.description or "").strip()
        if desc:
            lines.append(f"{cid}: {name} ({etype}) - {desc[:120]}")
            continue
        lines.append(f"{cid}: {name} ({etype})")
    return lines


def _entity_verification_schema() -> dict[str, Any]:
    return {
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


def _sanitize_kept_entities(
    parser: EntityValueParser,
    items: object,
    *,
    valid_ids: set[str],
    keep_limit: int,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    if not isinstance(items, list):
        return kept

    for item in items:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if not cid or cid not in valid_ids or cid in seen_ids:
            continue
        seen_ids.add(cid)
        desc = str(item.get("description") or "").strip() or None
        evidence_quote = str(item.get("evidence_quote") or "").strip() or None
        kept.append(
            {
                "id": cid,
                "type": parser.normalize_type(str(item.get("type") or "unknown")),
                "description": desc[:400] if desc else None,
                "evidence_quote": evidence_quote[:300] if evidence_quote else None,
                "confidence": _clamp01(item.get("confidence"), default=0.7),
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
    if alias_limit <= 0 or not isinstance(items, list):
        return aliases

    for item in items:
        if not isinstance(item, dict):
            continue
        alias_id = str(item.get("alias_id") or "").strip()
        canonical_id = str(item.get("canonical_id") or "").strip()
        if not alias_id or not canonical_id or alias_id == canonical_id:
            continue
        if alias_id not in valid_ids or canonical_id not in valid_ids:
            continue
        pair = (alias_id, canonical_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        evidence_quote = str(item.get("evidence_quote") or "").strip() or None
        aliases.append(
            {
                "alias_id": alias_id,
                "canonical_id": canonical_id,
                "evidence_quote": evidence_quote[:300] if evidence_quote else None,
                "confidence": _clamp01(item.get("confidence"), default=0.9),
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
            return _empty_verify_result()

        cand_list = [c for c in (candidates or []) if str(getattr(c, "cid", "") or "").strip()]
        if not cand_list:
            return _empty_verify_result()

        keep_lim = max(0, int(max_keep or 0))
        if keep_lim <= 0:
            return _empty_verify_result()

        alias_lim = max(0, int(max_alias_edges or 0))
        cand_lines = _build_candidate_lines(cand_list)
        if not cand_lines:
            return _empty_verify_result()

        messages = [
            LLMMessage(
                role=LLMRole.USER,
                content=_build_verification_prompt(
                    clean_text=clean_text,
                    candidate_lines=cand_lines,
                    keep_limit=keep_lim,
                    alias_limit=alias_lim,
                ),
            )
        ]
        try:
            raw = await self.llm_client.chat_with_schema(
                messages,
                response_schema=_entity_verification_schema(),
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Entity verify failed; returning no-op: %s", str(exc)[:200])
            return _empty_verify_result()

        valid_ids = _verified_candidate_ids(cand_list)
        payload = raw if isinstance(raw, dict) else {}
        return {
            "kept": _sanitize_kept_entities(
                self.parser,
                payload.get("kept"),
                valid_ids=valid_ids,
                keep_limit=keep_lim,
            ),
            "aliases": _sanitize_aliases(
                payload.get("aliases"),
                valid_ids=valid_ids,
                alias_limit=alias_lim,
            ),
        }


__all__ = ["EntityCandidate", "EntityVerifier"]
