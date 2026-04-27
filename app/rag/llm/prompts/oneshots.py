from __future__ import annotations

KB_ASSISTANT_ONESHOT = {
    "question": "What does the deployment guide require before starting the service?",
    "answer": "The guide requires configuring the environment variables before starting the service.",
    "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
}

KB_SUMMARY_ONESHOT = {
    "answer": "The document explains MQTT broker setup for industrial gateways.",
    "citations": [{"document_id": "doc-2", "chunk_id": "chunk-2"}],
    "bullets": ["Broker host and port are configurable.", "Credentials must be updated for the field device."],
    "summary": "MQTT broker setup and connection parameters are covered.",
}

KB_ACTION_ITEMS_ONESHOT = {
    "answer": "Two concrete actions are described.",
    "citations": [{"document_id": "doc-3", "chunk_id": "chunk-3"}],
    "actions": [
        {"item": "Update the broker host", "owner": "", "due": ""},
        {"item": "Validate gateway credentials", "owner": "", "due": ""},
    ],
}

__all__ = [
    "KB_ACTION_ITEMS_ONESHOT",
    "KB_ASSISTANT_ONESHOT",
    "KB_SUMMARY_ONESHOT",
]
