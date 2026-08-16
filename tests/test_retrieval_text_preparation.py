
from langchain_core.documents import Document

from app.rag.retrieval.hybrid.text_preparation import (
    normalize_document_questions,
    prepare_retrieval_document,
    question_channel_overlap_score,
    rerank_text_from_result,
)


def test_prepare_retrieval_document_appends_unique_questions_and_preserves_display_content() -> None:
    prepared = prepare_retrieval_document(
        Document(
            page_content="Original Body",
            metadata={
                "_retrieval_display_content": "Original Body",
                "_retrieval_text": "[title] guide original body",
                "document_questions": [
                    "How do I install MimirQ?",
                    "How do I install MimirQ?",
                    "Where is the config file?",
                ],
            },
        ),
        log_fallback=lambda *_args, **_kwargs: None,
    )

    assert prepared.page_content == (
        "[title] guide original body\n\nQuestions:\n"
        "- How do I install MimirQ?\n"
        "- Where is the config file?"
    )
    assert prepared.metadata["_retrieval_display_content"] == "Original Body"
    assert prepared.metadata["_retrieval_questions_channel_applied"] is True


def test_rerank_text_from_result_adds_deduped_metadata_header_lines() -> None:
    text = rerank_text_from_result(
        {
            "content": "Chunk body",
            "metadata": {
                "_display_metadata": {
                    "title": "Install Guide",
                    "tags": ["setup", "linux", "setup"],
                },
                "_evaluable_metadata": {
                    "title": "Install Guide",
                    "locale": "en-US",
                },
            },
        }
    )

    assert text == (
        "Metadata:\n"
        "- tags: setup, linux, setup\n"
        "- title: Install Guide\n"
        "- locale: en-US\n\n"
        "Chunk body"
    )


def test_question_channel_overlap_score_uses_normalized_unique_questions() -> None:
    score = question_channel_overlap_score(
        query_tokens=["install", "mimirq", "guide"],
        metadata={
            "document_questions": [
                "How do I install MimirQ?",
                "How do I install MimirQ?",
                "Where is the config file?",
            ]
        },
        tokenize=lambda text: [token.strip("?.!,").lower() for token in text.split()],
    )

    assert score == 2 / 3
    assert normalize_document_questions([" One ", "one", "", None, "Two"]) == ["One", "Two"]
