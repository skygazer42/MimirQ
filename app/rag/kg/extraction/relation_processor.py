"""
Relation processor: extract entity->entity relations ("triples") from chunk text.

Key goals:
- Constrain generation to candidate entities to reduce hallucinations.
- Normalize predicates against an allowlist (lightweight ontology v1).
- Return a compact, provenance-friendly payload to be persisted in `kg_relations`.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.rag.kg.utils import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole

logger = get_logger("kg.extract.relations")


_PRED_SAFE_RE = re.compile(r"[^a-z0-9_]+")

# Predicate synonyms -> canonical predicate keys.
#
# Rationale:
# - We keep the ontology allowlist compact.
# - LLMs often output semantically equivalent variants ("works at", "employed_by", ...).
# - Mapping them deterministically improves recall and reduces "unknown" drift without adding extra LLM calls.
_PREDICATE_SYNONYMS: dict[str, str] = {
    # identity / aliases
    "alias": "alias_of",
    "aliasof": "alias_of",
    "abbrev_of": "alias_of",
    "abbreviation_of": "alias_of",
    "synonym_of": "alias_of",
    # equivalence
    "sameas": "same_as",
    "equivalent_to": "same_as",
    "equivalentto": "same_as",
    # org / employment
    "worksat": "works_for",
    "works_at": "works_for",
    "employed_by": "works_for",
    "employedby": "works_for",
    "employer": "works_for",
    # location
    "locatedat": "located_in",
    "located_at": "located_in",
    "based_in": "located_in",
    "basedin": "located_in",
    # parts / membership
    "partof": "part_of",
    "haspart": "has_part",
    "memberof": "member_of",
    # software-ish
    "dependson": "depends_on",
    "dependsupon": "depends_on",
    "uses_tool": "uses",
    "utilizes": "uses",
}


def _normalize_predicate_key(value: str) -> str:
    """
    Normalize predicate keys to a stable snake_case-ish key (no synonym mapping).

    Examples:
    - "Works With" -> "works_with"
    - "located-in" -> "located_in"
    """
    text = (value or "").strip().casefold()
    text = re.sub(r"\s+", "_", text)
    text = text.replace("-", "_").replace(":", "_").replace("/", "_")
    text = _PRED_SAFE_RE.sub("", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def normalize_predicate(value: str) -> str:
    """
    Normalize + canonicalize a predicate key.

    This includes conservative synonym mapping to keep the stored ontology compact.
    """
    key = _normalize_predicate_key(value)
    mapped = _PREDICATE_SYNONYMS.get(key)
    return mapped or key or "unknown"


def _clamp01(value: object, *, default: float) -> float:
    try:
        f = float(value)  # type: ignore[arg-type]
    except Exception:
        return float(default)
    if math.isnan(f):
        return float(default)
    return max(0.0, min(1.0, float(f)))


@dataclass(frozen=True)
class CandidateEntity:
    """
    A single candidate entity visible to the relation extractor.

    `cid` should be a stable local id like "E1" to avoid string matching issues.
    """

    cid: str
    name: str
    type: str = "unknown"
    normalized_name: str = ""


class RelationProcessor:
    def __init__(
        self,
        llm_client: BaseLLMClient,
        *,
        allowed_predicates: Sequence[str] | None = None,
    ):
        self.llm_client = llm_client
        # Store normalized allowlist for fast membership checks.
        allow = [normalize_predicate(p) for p in (allowed_predicates or []) if str(p or "").strip()]
        self.allowed_predicates = set(allow)

    @staticmethod
    def _candidate_prompt_lines(candidates: Sequence[CandidateEntity]) -> list[str]:
        lines: list[str] = []
        for candidate in candidates:
            cid = str(getattr(candidate, "cid", "") or "").strip()
            if not cid:
                continue
            name = str(getattr(candidate, "name", "") or "").strip()
            if not name:
                continue
            etype = str(getattr(candidate, "type", "") or "unknown").strip() or "unknown"
            lines.append(f"{cid}: {name} ({etype})")
        return lines

    @staticmethod
    def _response_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject_id": {"type": "string"},
                            "predicate": {"type": "string"},
                            "object_id": {"type": "string"},
                            "confidence": {"type": "number"},
                            "qualifiers": {"type": "object"},
                            "evidence_quote": {"type": "string"},
                        },
                        "required": ["subject_id", "predicate", "object_id"],
                    },
                }
            },
        }

    @staticmethod
    def _normalize_relation(
        raw: dict[str, Any],
        *,
        valid_ids: set[str],
        allowed_predicates: set[str],
    ) -> dict[str, Any] | None:
        subj = str(raw.get("subject_id") or "").strip()
        obj = str(raw.get("object_id") or "").strip()
        pred_in = str(raw.get("predicate") or "").strip()
        if not subj or not obj or not pred_in:
            return None
        if subj not in valid_ids or obj not in valid_ids or subj == obj:
            return None

        pred_key = _normalize_predicate_key(pred_in)
        pred_norm = normalize_predicate(pred_in)
        pred_raw: str | None = pred_in if pred_norm != pred_key else None
        if allowed_predicates and pred_norm not in allowed_predicates:
            pred_raw = pred_in
            pred_norm = "unknown"

        return {
            "subject_id": subj,
            "predicate": pred_norm,
            "predicate_raw": pred_raw,
            "object_id": obj,
            "confidence": _clamp01(raw.get("confidence"), default=0.5),
            "qualifiers": raw.get("qualifiers") if isinstance(raw.get("qualifiers"), dict) else None,
            "evidence_quote": str(raw.get("evidence_quote") or "").strip() or None,
        }

    async def extract_relations(
        self,
        *,
        text: str,
        candidates: Sequence[CandidateEntity],
        max_relations: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Return normalized relation dicts:
        - subject_id (candidate cid)
        - predicate (normalized, allowlisted or "unknown")
        - predicate_raw (optional)
        - object_id (candidate cid)
        - confidence (0..1)
        - qualifiers (dict | None)
        """
        clean_text = (text or "").strip()
        if not clean_text:
            return []

        cand_list = list(candidates or [])
        if not cand_list:
            return []

        max_rels = max(0, int(max_relations or 0))
        if max_rels <= 0:
            return []

        cand_lines = self._candidate_prompt_lines(cand_list)
        if not cand_lines:
            return []

        allowlist = sorted(self.allowed_predicates) if self.allowed_predicates else []
        allow_hint = ", ".join(allowlist[:200]) if allowlist else ""

        prompt = (
            "Extract entity-to-entity relations (triples) from the text.\n"
            "Return JSON only.\n"
            "Constraints:\n"
            "- subject_id and object_id MUST be chosen from the candidate list ids.\n"
            "- Prefer using an allowed predicate when possible; do not invent new predicates.\n"
            '- If unsure about predicate, use "unknown".\n'
            "- Prefer concise, ontology-friendly predicate keys (snake_case).\n"
            '- If the text explicitly defines an alias/abbreviation/synonym (e.g. "X (Y)", "aka", "简称"), '
            'use predicate "alias_of".\n'
            "- For each relation, include evidence_quote: an exact substring from the text that "
            "supports the relation.\n"
            "- evidence_quote MUST be copied verbatim from the Text section (no paraphrase).\n"
            "- evidence_quote SHOULD include both the subject and object surface forms.\n"
            "- Keep evidence_quote short (prefer a single sentence/phrase, <= 240 chars).\n"
            f"- Allowed predicates (if applicable): {allow_hint}\n\n"
            "Candidates:\n"
            f"{chr(10).join(cand_lines)}\n\n"
            "Text:\n"
            f"{clean_text}\n"
        )

        messages = [LLMMessage(role=LLMRole.USER, content=prompt)]
        result = await self.llm_client.chat_with_schema(
            messages,
            response_schema=self._response_schema(),
            temperature=0.2,
        )

        rels_raw = result.get("relations") if isinstance(result, dict) else None
        if not isinstance(rels_raw, list):
            return []

        valid_ids = {c.cid for c in cand_list if str(getattr(c, "cid", "") or "").strip()}

        out: list[dict[str, Any]] = []
        for raw in rels_raw:
            if not isinstance(raw, dict):
                continue
            normalized = self._normalize_relation(
                raw,
                valid_ids=valid_ids,
                allowed_predicates=self.allowed_predicates,
            )
            if normalized is None:
                continue
            out.append(normalized)
            if len(out) >= max_rels:
                break

        logger.info("Extracted %s relations (candidates=%s)", len(out), len(cand_list))
        return out


__all__ = ["CandidateEntity", "RelationProcessor", "normalize_predicate"]
