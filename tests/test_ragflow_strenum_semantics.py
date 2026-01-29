from app.rag.chunking.ragflow.common.constants import LLMType


def test_ragflow_strenum_is_stringy():
    assert isinstance(LLMType.CHAT, str)
    assert str(LLMType.CHAT) == "chat"
    assert LLMType.CHAT == "chat"

