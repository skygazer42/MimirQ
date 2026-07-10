"""
Relation verification pass for KG extraction.

This is an optional second LLM pass designed to:
- drop unsupported / noisy relations (precision)
- normalize predicates to the allowlist (reduce 'unknown' and drift)
- ensure each relation has an evidence quote
"""


import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.rag.kg.extraction.relation_processor import normalize_predicate
from app.rag.kg.utils import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole

logger = get_logger("kg.extract.relation_verify")


def _clamp01(value: object, *, default: float) -> float:
    try:
        f = float(value)  # type: ignore[arg-type]
    except Exception:
        return float(default)
    if math.isnan(f):
        return float(default)
    return max(0.0, min(1.0, float(f)))


@dataclass(frozen=True)
class RelationCandidate:
    rid: str
    subject_id: str
    predicate: str
    object_id: str
    confidence: float = 0.5
    evidence_quote: str | None = None


class RelationVerifier:
    def __init__(self, llm_client: BaseLLMClient, *, allowed_predicates: Sequence[str] | None = None):
        self.llm_client = llm_client
        allow = [normalize_predicate(p) for p in (allowed_predicates or []) if str(p or "").strip()]
        self.allowed_predicates = set(allow)

    async def verify(
        self,
        *,
        text: str,
        candidates: Sequence[RelationCandidate],
        max_keep: int = 20,
    ) -> dict[str, Any]:
        clean_text = (text or "").strip()
        if not clean_text:
            return {"kept": []}

        cand_list = [c for c in (candidates or []) if str(getattr(c, "rid", "") or "").strip()]
        if not cand_list:
            return {"kept": []}

        lim = max(0, int(max_keep or 0))
        if lim <= 0:
            return {"kept": []}

        lines: list[str] = []
        for c in cand_list:
            rid = str(c.rid).strip()
            subj = str(c.subject_id).strip()
            obj = str(c.object_id).strip()
            pred = str(c.predicate or "").strip() or "unknown"
            evq = str(c.evidence_quote or "").strip()
            if not rid or not subj or not obj:
                continue
            if evq:
                evq = evq[:160]
                lines.append(f"{rid}: {subj} -[{pred}]-> {obj} | evidence: {evq}")
            else:
                lines.append(f"{rid}: {subj} -[{pred}]-> {obj}")

        if not lines:
            return {"kept": []}

        allowlist = sorted(self.allowed_predicates) if self.allowed_predicates else []
        allow_hint = ", ".join(allowlist[:200]) if allowlist else ""

        schema: dict[str, Any] = {
            "type": "object",
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
        try:
            raw = await self.llm_client.chat_with_schema(messages, response_schema=schema, temperature=0.2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Relation verify failed; returning no-op: %s", str(exc)[:200])
            return {"kept": []}

        kept_raw = raw.get("kept") if isinstance(raw, dict) else None
        if not isinstance(kept_raw, list):
            return {"kept": []}

        valid_rids = {str(c.rid).strip() for c in cand_list}

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in kept_raw:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("rid") or "").strip()
            if not rid or rid not in valid_rids or rid in seen:
                continue
            seen.add(rid)

            pred_in = str(item.get("predicate") or "").strip()
            pred = normalize_predicate(pred_in) if pred_in else ""
            if not pred:
                pred = "unknown"
            if self.allowed_predicates and pred not in self.allowed_predicates:
                # If verifier outputs a non-allowlisted predicate, drop it (avoid schema drift).
                continue

            evq = str(item.get("evidence_quote") or "").strip() or None
            out.append(
                {
                    "rid": rid,
                    "predicate": pred,
                    "confidence": _clamp01(item.get("confidence"), default=0.7),
                    "evidence_quote": (evq[:300] if evq else None),
                }
            )
            if len(out) >= lim:
                break

        return {"kept": out}


__all__ = ["RelationCandidate", "RelationVerifier"]
