"""Encode chat domain events as one AG-UI run."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any
from uuid import uuid4

from ag_ui.core import (
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder

logger = logging.getLogger(__name__)


async def encode_chat_events(
    events: AsyncIterator[dict[str, Any]],
    *,
    thread_id: str,
    run_id: str,
    assistant_message_id: str,
    request_id: str,
    parent_run_id: str | None = None,
) -> AsyncIterator[str]:
    encoder = EventEncoder()
    metadata = {
        "requestId": request_id,
        "threadId": thread_id,
        "runId": run_id,
        "assistantMessageId": assistant_message_id,
    }
    yield encoder.encode(
        RunStartedEvent(
            thread_id=thread_id, run_id=run_id, parent_run_id=parent_run_id, protocol_version="1.0", metadata=metadata
        )
    )
    yield encoder.encode(TextMessageStartEvent(message_id=assistant_message_id, role="assistant", metadata=metadata))
    completion = None
    failure = None
    try:
        async with aclosing(events):
            async for event in events:
                kind = event["type"]
                data = event["data"]
                if kind == "heartbeat":
                    yield ": keepalive\n\n"
                elif kind == "token":
                    if data["content"]:
                        yield encoder.encode(
                            TextMessageContentEvent(
                                message_id=assistant_message_id, delta=data["content"], metadata=metadata
                            )
                        )
                elif kind == "done":
                    # Drain the producer so it can dispatch persistence and record final metrics.
                    if completion is not None:
                        raise ValueError("Chat emitted more than one completion")
                    completion = data
                elif kind == "error":
                    failure = RunErrorEvent(
                        message=data["message"],
                        code=data.get("error_code"),
                        metadata={**metadata, "details": data},
                    )
                    break
                elif kind == "agentic_step" and data["step"] == "tool_call":
                    tool_call_id = data["tool_call_id"]
                    yield encoder.encode(
                        ToolCallStartEvent(
                            tool_call_id=tool_call_id,
                            tool_call_name=data["tool"],
                            parent_message_id=assistant_message_id,
                            metadata=metadata,
                        )
                    )
                    yield encoder.encode(
                        ToolCallArgsEvent(
                            tool_call_id=tool_call_id,
                            delta=json.dumps(data["arguments"], ensure_ascii=False),
                            metadata=metadata,
                        )
                    )
                    yield encoder.encode(ToolCallEndEvent(tool_call_id=tool_call_id, metadata=metadata))
                elif kind == "agentic_step" and data["step"] == "tool_result":
                    result = {"success": data["success"], "error": data["error"]}
                    yield encoder.encode(
                        ToolCallResultEvent(
                            message_id=str(uuid4()),
                            tool_call_id=data["tool_call_id"],
                            content=json.dumps(result, ensure_ascii=False),
                            role="tool",
                            metadata={**metadata, **result, "tool": data["tool"]},
                        )
                    )
                else:
                    yield encoder.encode(CustomEvent(name=f"ragvia.{kind}", value=data, metadata=metadata))
    except Exception:
        logger.exception("Chat event production failed")
        failure = RunErrorEvent(
            message="An error occurred during chat processing", code="STREAM_ERROR", metadata=metadata
        )

    yield encoder.encode(TextMessageEndEvent(message_id=assistant_message_id, metadata=metadata))
    if failure is not None:
        yield encoder.encode(failure)
    elif completion is None:
        yield encoder.encode(
            RunErrorEvent(message="Chat stream ended before completion", code="INCOMPLETE_STREAM", metadata=metadata)
        )
    else:
        yield encoder.encode(RunFinishedEvent(thread_id=thread_id, run_id=run_id, result=completion, metadata=metadata))
