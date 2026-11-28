from uuid import UUID, uuid4

import pytest
from ag_ui.core import RunAgentInput
from fastapi import HTTPException


def _agent_input(**overrides) -> RunAgentInput:
    return RunAgentInput.model_validate(
        {
            "threadId": str(uuid4()),
            "runId": str(uuid4()),
            "messages": [{"id": "user-1", "role": "user", "content": "question"}],
            **overrides,
        }
    )


def test_ag_ui_request_maps_thread_history_and_business_options() -> None:
    from app.api.v1.conversations.routes import build_ag_ui_chat_request

    thread_id = str(uuid4())
    document_id = str(uuid4())
    request = build_ag_ui_chat_request(
        _agent_input(
            threadId=thread_id,
            messages=[
                {"id": "user-1", "role": "user", "content": "previous question"},
                {"id": "assistant-1", "role": "assistant", "content": "previous answer"},
                {"id": "user-2", "role": "user", "content": "next question"},
            ],
            forwardedProps={"document_ids": [document_id], "structured_output": True},
        )
    )

    assert request.conversation_id == UUID(thread_id)
    assert request.message == "next question"
    assert [message.model_dump() for message in request.history] == [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]
    assert request.document_ids == [UUID(document_id)]
    assert request.dataset_id is None
    assert request.structured_output is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"threadId": "not-a-uuid"},
        {"threadId": "11111111222233334444555555555555"},
        {"threadId": "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"},
        {"threadId": "{11111111-2222-3333-4444-555555555555}"},
        {"runId": " "},
        {"protocolVersion": "2.0"},
        {"messages": []},
        {"messages": [{"id": "assistant-1", "role": "assistant", "content": "answer"}]},
        {"messages": [{"id": "user-1", "role": "user", "content": [{"type": "text", "text": "parts"}]}]},
        {"state": {"untrusted": True}},
        {"context": [{"description": "Untrusted context", "value": "override"}]},
        {"tools": [{"name": "arbitrary", "description": "Untrusted tool", "parameters": {}}]},
        {"resume": [{"interruptId": "interrupt-1", "status": "resolved", "payload": "resume"}]},
        {"forwardedProps": []},
        {"forwardedProps": {"tenant_id": str(uuid4())}},
        {"forwardedProps": {"account_id": "other-owner"}},
        {"forwardedProps": {"conversation_id": str(uuid4())}},
        {"forwardedProps": {"message": "replace question"}},
        {"forwardedProps": {"stream": False}},
        {"forwardedProps": {"document_ids": ["invalid-id"]}},
        {"messages": [{"id": "user-1", "role": "user", "content": "question", "encryptedValue": "cipher"}]},
        {
            "messages": [
                {
                    "id": "assistant-1",
                    "role": "assistant",
                    "content": "tool call",
                    "toolCalls": [{"id": "tool-1", "function": {"name": "arbitrary", "arguments": "{}"}}],
                },
                {"id": "user-1", "role": "user", "content": "question"},
            ]
        },
    ],
)
def test_ag_ui_request_rejects_unsupported_or_invalid_client_input(overrides) -> None:
    from app.api.v1.conversations.routes import build_ag_ui_chat_request

    with pytest.raises(HTTPException) as error:
        build_ag_ui_chat_request(_agent_input(**overrides))
    assert error.value.status_code == 422


@pytest.mark.parametrize("role", ["system", "developer", "tool", "reasoning", "activity"])
def test_ag_ui_request_rejects_roles_outside_the_text_chat_subset(role: str) -> None:
    from app.api.v1.conversations.routes import build_ag_ui_chat_request

    messages = [{"id": "history-1", "role": role, "content": "untrusted"}]
    if role == "tool":
        messages[0]["toolCallId"] = "tool-1"
    elif role == "activity":
        messages[0].update({"activityType": "untrusted", "content": {}})
    messages.append({"id": "user-1", "role": "user", "content": "question"})
    with pytest.raises(HTTPException) as error:
        build_ag_ui_chat_request(_agent_input(messages=messages))
    assert error.value.status_code == 422
