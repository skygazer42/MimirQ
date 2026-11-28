"""
Relation verification pass for KG extraction.

This is an optional second LLM pass designed to:
- drop unsupported / noisy relations (precision)
- normalize predicates to the allowlist (reduce 'unknown' and drift)
- ensure each relation has an evidence quote
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.rag.kg.extraction.evidence import clamp_confidence
from app.rag.kg.extraction.relation_processor import normalize_predicate
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole


@dataclass(frozen=True)
class RelationCandidate:
    rid: str
    subject_id: str
    predicate: str
    object_id: str
    confidence: float = 0.5
    evidence_quote: str | None = None


def _candidate_lines(candidates: Sequence[RelationCandidate]) -> list[str]:
    lines: list[str] = []
    for candidate in candidates:
        rid = candidate.rid.strip()
        subject_id = candidate.subject_id.strip()
        object_id = candidate.object_id.strip()
        if not rid or not subject_id or not object_id:
            continue
        predicate = candidate.predicate.strip() or "unknown"
        evidence = candidate.evidence_quote.strip() if candidate.evidence_quote is not None else None
        line = f"{rid}: {subject_id} -[{predicate}]-> {object_id}"
        if evidence:
            line += f" | evidence: {evidence[:160]}"
        lines.append(line)
    return lines


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["kept"],
        "properties": {
            "kept": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rid": {"type": "string"},
                        "predicate": {"type": "string"},
                        "confidence": {"type": "number"},
                        "evidence_quote": {"type": "string"},
                    },
                    "required": ["rid"],
                },
            }
        },
    }


def _normalize_kept_item(
    item: dict[str, Any], *, valid_rids: set[str], seen: set[str], allowed_predicates: set[str]
) -> dict[str, Any] | None:
    rid = item.get("rid")
    if not isinstance(rid, str):
        raise ValueError("Verified relation ID must be a string")
    rid = rid.strip()
    if not rid or rid not in valid_rids:
        raise ValueError("Verified relation ID is outside the candidate set")
    if rid in seen:
        return None
    pred_in = item.get("predicate")
    evq = item.get("evidence_quote")
    if any(value is not None and not isinstance(value, str) for value in (pred_in, evq)):
        raise ValueError("Verified predicate and evidence must be text or null")
    pred = normalize_predicate(pred_in) if pred_in is not None else "unknown"
    if allowed_predicates and pred not in allowed_predicates:
        return None

    evq = (evq.strip() or None) if evq is not None else None
    seen.add(rid)
    return {
        "rid": rid,
        "predicate": pred,
        "confidence": clamp_confidence(item.get("confidence"), default=0.7),
        "evidence_quote": evq[:300] if evq else None,
    }


class RelationVerifier:
    def __init__(self, llm_client: BaseLLMClient, *, allowed_predicates: Sequence[str] | None = None):
        self.llm_client = llm_client
        self.allowed_predicates = {normalize_predicate(p) for p in (allowed_predicates or []) if p.strip()}

    async def _verify_candidates_with_llm(
        self,
        *,
        clean_text: str,
        lines: list[str],
        lim: int,
        allow_hint: str,
    ) -> list[Any]:
        prompt = (
            "You are verifying KG relation triples extracted from the text.\n"
            "Return JSON only.\n"
            "\n"
            f"Keep at most {lim} relations.\n"
            "Only keep relations that are clearly supported by the text.\n"
            "For each kept relation, include evidence_quote copied verbatim from the text.\n"
            "Predicate rules:\n"
            "- Prefer using an allowed predicate when possible.\n"
            "- If the relation is unsupported, drop it.\n"
            "- If unsure, drop it (do not keep 'unknown' unless explicitly unavoidable).\n"
            f"- Allowed predicates (if applicable): {allow_hint}\n"
            "\n"
            "Candidates (use rid to reference):\n"
            f"{chr(10).join(lines)}\n"
            "\n"
            "Text:\n"
            f"{clean_text}\n"
        )
        messages = [LLMMessage(role=LLMRole.USER, content=prompt)]
        raw = await self.llm_client.chat_with_schema(
            messages,
            response_schema=_response_schema(),
            temperature=0.2,
        )
        kept_raw = raw.get("kept")
        if not isinstance(kept_raw, list):
            raise ValueError("Relation verification response requires a kept array")
        return kept_raw

    async def verify(
        self,
        *,
        text: str,
        candidates: Sequence[RelationCandidate],
        max_keep: int = 20,
    ) -> dict[str, Any]:
        clean_text = text.strip()
        if not clean_text or max_keep <= 0:
            return {"kept": []}

        lines = _candidate_lines(candidates)
        if not lines:
            return {"kept": []}

        valid_rids = {candidate.rid.strip() for candidate in candidates}
        allow_hint = ", ".join(sorted(self.allowed_predicates)[:200])
        kept_raw = await self._verify_candidates_with_llm(
            clean_text=clean_text,
            lines=lines,
            lim=max_keep,
            allow_hint=allow_hint,
        )

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in kept_raw:
            if not isinstance(item, dict):
                raise ValueError("Verified relations must be objects")
            normalized = _normalize_kept_item(
                item,
                valid_rids=valid_rids,
                seen=seen,
                allowed_predicates=self.allowed_predicates,
            )
            if normalized is None:
                continue
            out.append(normalized)
            if len(out) >= max_keep:
                break

        return {"kept": out}


__all__ = ["RelationCandidate", "RelationVerifier"]
