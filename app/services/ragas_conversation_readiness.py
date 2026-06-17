from __future__ import annotations

from typing import Any
from uuid import UUID

from app.api.schemas.evaluation import RagasConversationReadinessItem


def count_citations(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def conversation_readiness_items(
    conversation_ids: list[UUID],
    assistant_rows: list[tuple[UUID, Any]],
) -> list[RagasConversationReadinessItem]:
    by_conversation = {
        conversation_id: {
            "assistant_turns": 0,
            "evaluable_turns": 0,
            "citations_count": 0,
        }
        for conversation_id in conversation_ids
    }

    for conversation_id, citations in assistant_rows:
        current = by_conversation.get(conversation_id)
        if current is None:
            continue
        citations_count = count_citations(citations)
        current["assistant_turns"] += 1
        current["citations_count"] += citations_count
        if citations_count > 0:
            current["evaluable_turns"] += 1

    return [
        RagasConversationReadinessItem(
            conversation_id=conversation_id,
            assistant_turns=values["assistant_turns"],
            evaluable_turns=values["evaluable_turns"],
            citations_count=values["citations_count"],
            is_evaluable=values["evaluable_turns"] > 0,
        )
        for conversation_id, values in by_conversation.items()
    ]
