"""Source conversation, message and run IDs for the Dify HTTP turn adapter."""

from app.api.schemas.integrations import DifyConversationTurnRequest
from app.services.dify_integration.common import _first_nonempty_str, _uuid_or_none


def _dify_turn_source_conversation_id(body: DifyConversationTurnRequest) -> str | None:
    body_conversation_id = body.conversation_id
    non_uuid_body_conversation_id = None
    if body_conversation_id is not None and _uuid_or_none(body_conversation_id) is None:
        non_uuid_body_conversation_id = str(body_conversation_id).strip()
    return _first_nonempty_str(
        body.source_conversation_id,
        body.dify_conversation_id,
        non_uuid_body_conversation_id,
    )


def _dify_turn_source_message_id(body: DifyConversationTurnRequest) -> str | None:
    return _first_nonempty_str(body.source_message_id, body.dify_message_id)


def _dify_turn_source_run_id(body: DifyConversationTurnRequest) -> str | None:
    return _first_nonempty_str(body.source_run_id, body.dify_workflow_run_id)


__all__ = [
    "_dify_turn_source_conversation_id",
    "_dify_turn_source_message_id",
    "_dify_turn_source_run_id",
]
