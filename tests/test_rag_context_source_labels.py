from langchain_core.documents import Document

from app.rag.pipelines.langgraph import _build_context
from app.rag.retrieval.source_labels import (
    derive_document_title,
    maybe_build_source_identification_answer,
    should_replace_source_label,
)


def test_derive_document_title_combines_deepdoc_title_lines() -> None:
    title = derive_document_title(
        filename="bert-pretraining_1810.04805.pdf",
        doc_metadata={},
        first_chunk_content=(
            "BERT: Pre-training of Deep Bidirectional Transformers for@@1 116.0 482.0 70.3 85.0## "
            "Language Understanding@@1 218.7 379.3 86.7 101.7##\n"
            "Kenton LeeJacob DevlinMing-Wei ChangKristina Toutanova Google AI Language@@1 247.3 479.3 130.5 157.0##"
        ),
    )

    assert title == "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"


def test_derive_document_title_falls_back_to_readable_filename() -> None:
    title = derive_document_title(
        filename="attention-is-all-you-need_1706.03762.pdf",
        doc_metadata={},
        first_chunk_content="1 Introduction@@2 106.7 192.0 71.7 84.0##",
    )

    assert title == "attention is all you need"


def test_uuid_pdf_source_label_is_replaced_by_original_filename() -> None:
    assert should_replace_source_label(
        "1832291a-b12a-4c23-9a25-9a6a7c5c9b3e.pdf",
        document_id="1832291a-b12a-4c23-9a25-9a6a7c5c9b3e",
    )
    assert not should_replace_source_label(
        "attention-is-all-you-need_1706.03762.pdf",
        document_id="1832291a-b12a-4c23-9a25-9a6a7c5c9b3e",
    )


def test_build_context_exposes_title_and_filename_to_answer_generator() -> None:
    context = _build_context(
        [
            Document(
                page_content="In this work we propose the Transformer.",
                metadata={
                    "source": "attention-is-all-you-need_1706.03762.pdf",
                    "filename": "attention-is-all-you-need_1706.03762.pdf",
                    "document_title": "Attention Is All You Need",
                },
            )
        ],
        query="Which paper introduced scaled dot-product attention and multi-head attention?",
    )

    assert "Title: Attention Is All You Need" in context
    assert "File: attention-is-all-you-need_1706.03762.pdf" in context


def test_source_identification_answer_prefers_title_over_filename() -> None:
    answer = maybe_build_source_identification_answer(
        question="Which paper pretrains BERT with masked language modeling?",
        docs=[
            Document(
                page_content="The training loss is masked LM and next sentence prediction.",
                metadata={
                    "document_title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
                    "filename": "bert-pretraining_1810.04805.pdf",
                    "source": "bert-pretraining_1810.04805.pdf",
                },
            )
        ],
    )

    assert answer == (
        'The paper is "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding" '
        "(source file: bert-pretraining_1810.04805.pdf)."
    )


def test_source_identification_answer_does_not_override_general_questions() -> None:
    answer = maybe_build_source_identification_answer(
        question="How does BERT pretraining work?",
        docs=[
            Document(
                page_content="BERT uses masked LM and next sentence prediction.",
                metadata={
                    "document_title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
                    "filename": "bert-pretraining_1810.04805.pdf",
                },
            )
        ],
    )

    assert answer is None
