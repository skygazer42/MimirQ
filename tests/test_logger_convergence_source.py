from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_targeted_logger_cluster_uses_get_logger() -> None:
    targets = {
        "app/storage/vector/milvus.py": 'logger = get_logger("storage.vector.milvus")',
        "app/storage/vector/factory.py": 'logger = get_logger("storage.vector.factory")',
        "app/services/jwt_group_sync_service.py": 'logger = get_logger("services.jwt_group_sync")',
        "app/core/jwt_verify.py": 'logger = get_logger("core.jwt_verify")',
        "app/core/pii_redaction.py": 'logger = get_logger("core.pii_redaction")',
        "app/core/exceptions.py": 'logger = get_logger("core.exceptions")',
        "app/rag/checkpointer/factory.py": 'logger = get_logger("rag.checkpointer.factory")',
        "app/rag/checkpointer/memory.py": 'logger = get_logger("rag.checkpointer.memory")',
        "app/rag/checkpointer/time_travel.py": 'logger = get_logger("rag.checkpointer.time_travel")',
        "app/rag/store/factory.py": 'logger = get_logger("rag.store.factory")',
        "app/rag/memory/long_term.py": 'logger = get_logger("rag.memory.long_term")',
        "app/rag/memory/short_term.py": 'logger = get_logger("rag.memory.short_term")',
        "app/rag/pipelines/langgraph.py": 'logger = get_logger("rag.pipelines.langgraph")',
        "app/rag/llm/langchain_chat.py": 'logger = get_logger("rag.llm.langchain_chat")',
        "app/rag/core/interrupt.py": 'logger = get_logger("rag.core.interrupt")',
        "app/rag/core/stream_writer.py": 'logger = get_logger("rag.core.stream_writer")',
        "app/rag/retrievers/multi_vector.py": 'logger = get_logger("rag.retrievers.multi_vector")',
    }

    for rel, marker in targets.items():
        src = _source(rel)
        assert "logging.getLogger(__name__)" not in src, rel
        assert "from app.rag.core.logging import get_logger" in src, rel
        assert marker in src, rel
