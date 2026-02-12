from app.rag.chunking.integrated_pipeline.common.constants import LLMType


def test_integrated_strenum_is_stringy():
    assert isinstance(LLMType.CHAT, str)
    assert str(LLMType.CHAT) == "chat"
    assert LLMType.CHAT == "chat"

