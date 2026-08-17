"""
Test question generator.

Generates test questions from documents or conversation history for RAGAS regression.
"""

import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.core.secure_random import secure_random_float01, secure_sample
from app.models.chat import Conversation, Message
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.http import httpx_trust_env
from app.rag.core.logging import get_logger
from app.services.chat_conversation_access import ensure_conversation_access
from app.services.document_access import filter_allowed_document_ids
from app.services.prompt_resolver import resolve_prompt_template

logger = get_logger("rag.evaluation.test_generator")


_DEFAULT_DOCUMENT_QUESTION_TYPES = ["factual", "multi_hop", "comparison"]
_ALLOWED_QUESTION_TYPES = {"factual", "multi_hop", "comparison", "conditional", "unanswerable"}


class GeneratedQuestion(BaseModel):
    """Generated question."""

    question: str = Field(description="Question content")
    expected_answer: str | None = Field(default=None, description="Expected answer (optional)")
    context: str | None = Field(default=None, description="Question source context")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


@dataclass(frozen=True)
class TestGeneratorPromptSelection:
    prompt_template_text: str
    prompt_variables: list[str]
    prompt_template_id: str | None
    prompt_template_key: str | None
    prompt_ab_experiment_key: str | None
    prompt_ab_variant: str | None


def _build_testgen_http_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    """
    Build LangChain HTTP clients with the same proxy safety as RAGAS.

    Some developer shells expose ALL_PROXY=socks://... while httpx socks support
    is not installed. In that case, disable env proxy trust and pass both clients
    so LangChain/OpenAI does not re-read the unsupported proxy from env.
    """
    trust_env = httpx_trust_env(logger=logger)
    timeout = float(getattr(settings, "LLM_TIMEOUT", 60) or 60)
    return httpx.Client(trust_env=trust_env, timeout=timeout), httpx.AsyncClient(
        trust_env=trust_env,
        timeout=timeout,
    )


def _close_testgen_http_clients(http_client: httpx.Client, http_async_client: httpx.AsyncClient) -> None:
    http_client.close()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(http_async_client.aclose())
        return
    loop.create_task(http_async_client.aclose())


# Prompt template for generating questions.
GENERATE_QUESTIONS_FROM_TEXT_PROMPT = (
    "You are an expert test question generator. Please generate high-quality test questions "
    "based on the following text content.\n\n"
    """Text content:
{text}

Requirements:
1. Generate {num_questions} questions
2. Question types include: {question_types}
   - factual: Ask about specific information in the text
   - multi_hop: Requires combining 2+ pieces of information from the text
   - comparison: Compare different concepts or things in the text
   - conditional: Ask "if/when" conditional questions based on the text
   - unanswerable: Cannot be answered from the text; should be refused/abstained
3. Questions should be clear, specific, and answerable from the text
4. Each question should have a reference answer (except unanswerable)
   - For unanswerable: expected_answer should be empty and expected_refusal=true

Please return in JSON format as follows:
{{
  "questions": [
    {{
      "question": "Question content",
      "expected_answer": "Reference answer (empty string if unanswerable)",
      "question_type": "factual|multi_hop|comparison|conditional|unanswerable",
      "expected_refusal": false
    }}
  ]
}}
"""
)

EXTRACT_QUESTIONS_FROM_CONVERSATION_PROMPT = (
    "You are an expert Q&A extractor. Please extract and refine user questions from the following "
    "conversation history.\n\n"
    """Conversation history:
{conversations}

Requirements:
1. Extract {num_questions} high-quality questions
2. Prioritize:
   - Clear and specific questions
   - Questions with practical value
   - Questions covering different topics
3. Appropriately rewrite extracted questions to make them more standardized and general
4. Deduplicate and avoid extracting similar questions
5. If the assistant's answer is high quality, use it as the reference answer

Please return in JSON format as follows:
{{
  "questions": [
    {{
      "question": "Refined question",
      "expected_answer": "Reference answer (if available)",
      "original_question": "Original question"
    }}
  ]
}}
"""
)


def _build_testgen_prompt_inputs(
    *,
    chunk_text: str,
    num_questions: int,
    normalized_types: list[str],
    existing_questions: list[str],
    prompt_variables: list[str] | None,
) -> dict[str, Any]:
    supported = {str(item).strip() for item in (prompt_variables or []) if str(item).strip()}
    text = str(chunk_text or "")[:2000]
    payload: dict[str, Any] = {}
    if "document_chunk" in supported:
        payload["document_chunk"] = text
    if "text" in supported:
        payload["text"] = text
    if "n" in supported:
        payload["n"] = int(num_questions)
    if "num_questions" in supported:
        payload["num_questions"] = int(num_questions)
    if "existing_questions" in supported:
        payload["existing_questions"] = "\n".join(str(item) for item in (existing_questions or []) if str(item).strip())
    if "question_types" in supported:
        payload["question_types"] = ", ".join(str(item) for item in (normalized_types or []) if str(item).strip())
    return payload


def _testgen_rows(result: dict[str, Any]) -> list[Any]:
    rows = result.get("questions")
    if not isinstance(rows, list):
        rows = result.get("qa_pairs")
    return rows if isinstance(rows, list) else []


def _normalize_testgen_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": item.get("question", ""),
        "expected_answer": (item.get("expected_answer") if "expected_answer" in item else item.get("ground_truth")),
        "question_type": (item.get("question_type") if "question_type" in item else item.get("difficulty")),
        "expected_refusal": bool(item.get("expected_refusal")),
        "evidence_quotes": (
            list(item.get("evidence_quotes") or []) if isinstance(item.get("evidence_quotes"), list) else []
        ),
        "expected_chunks": (
            list(item.get("expected_chunks") or []) if isinstance(item.get("expected_chunks"), list) else []
        ),
    }


def _normalize_testgen_result_rows(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    rows = _testgen_rows(result)
    if not rows:
        return []

    normalized: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        normalized.append(_normalize_testgen_row(item))
    return normalized


def _normalize_question_types(question_types: list[str] | None) -> list[str]:
    raw_types = question_types if question_types is not None else _DEFAULT_DOCUMENT_QUESTION_TYPES
    normalized_types: list[str] = []
    for raw_type in raw_types or []:
        key = str(raw_type or "").strip().lower()
        if not key:
            continue
        if key == "reasoning":
            key = "multi_hop"
        if key not in _ALLOWED_QUESTION_TYPES or key in normalized_types:
            continue
        normalized_types.append(key)
    return normalized_types or ["factual"]


def _resolve_document_scope_ids(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    document_ids: list[UUID] | None,
) -> list[UUID]:
    if document_ids:
        return filter_allowed_document_ids(db, tenant_id, account_id, document_ids)
    if dataset_id:
        from app.services.dataset_service import DatasetService

        DatasetService.ensure_member(db, tenant_id, account_id)
        query = db.query(DBDocument).filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.status == "completed",
        )
        return [doc.id for doc in query.all()]
    from app.services.document_access import list_accessible_document_ids

    return list_accessible_document_ids(db, tenant_id, account_id)


def _resolve_testgen_prompt_selection(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    prompt_template_id: UUID | None,
    prompt_template_key: str | None,
    prompt_ab_experiment_key: str | None,
) -> TestGeneratorPromptSelection:
    selected_template = None
    if prompt_template_id or (prompt_template_key or "").strip() or (prompt_ab_experiment_key or "").strip():
        try:
            selected_template = resolve_prompt_template(
                db=db,
                tenant_id=tenant_id,
                prompt_template_id=prompt_template_id,
                template_key=prompt_template_key,
                ab_experiment_key=prompt_ab_experiment_key,
                ab_user_key=account_id,
            )
        except Exception as exc:
            logger.warning("Failed to resolve test generator prompt template: %s", exc)
            selected_template = None
    prompt_template_text = (
        str(getattr(selected_template, "content", "") or "").strip()
        if selected_template is not None
        else GENERATE_QUESTIONS_FROM_TEXT_PROMPT
    )
    prompt_variables = list(getattr(selected_template, "variables", None) or [])
    if not prompt_variables:
        prompt_variables = ["text", "num_questions", "question_types"]
    return TestGeneratorPromptSelection(
        prompt_template_text=prompt_template_text,
        prompt_variables=prompt_variables,
        prompt_template_id=(
            (str(getattr(selected_template, "id", "") or "") or None) if selected_template is not None else None
        ),
        prompt_template_key=(
            (str(getattr(selected_template, "template_key", "") or "").strip() or None)
            if selected_template is not None
            else None
        ),
        prompt_ab_experiment_key=(str(getattr(selected_template, "ab_experiment_key", "") or "").strip() or None)
        if selected_template is not None
        else None,
        prompt_ab_variant=(
            (str(getattr(selected_template, "ab_variant", "") or "").strip() or None)
            if selected_template is not None
            else None
        ),
    )


def _generated_question_from_row(
    *,
    row: dict[str, Any],
    chunk: DocumentChunk,
    normalized_types: list[str],
    prompt_selection: TestGeneratorPromptSelection,
) -> GeneratedQuestion:
    question_type = str(row.get("question_type") or "factual").strip().lower() or "factual"
    if question_type == "reasoning":
        question_type = "multi_hop"
    if question_type not in _ALLOWED_QUESTION_TYPES:
        question_type = normalized_types[0]
    expected_refusal = bool(row.get("expected_refusal")) or question_type == "unanswerable"
    return GeneratedQuestion(
        question=row.get("question", ""),
        expected_answer=(None if expected_refusal else row.get("expected_answer")),
        context=chunk.content[:500],
        metadata={
            "source_type": "document",
            "source_id": str(chunk.document_id),
            "chunk_id": str(chunk.id),
            "question_type": question_type,
            "expected_refusal": expected_refusal,
            "reference_chunk_ids": [str(chunk.id)],
            "evidence_quotes": list(row.get("evidence_quotes") or []),
            "expected_chunks": list(row.get("expected_chunks") or []),
            "prompt_template_id": prompt_selection.prompt_template_id,
            "prompt_template_key": prompt_selection.prompt_template_key,
            "prompt_ab_experiment_key": prompt_selection.prompt_ab_experiment_key,
            "prompt_ab_variant": prompt_selection.prompt_ab_variant,
        },
    )


def _calculate_text_diversity_scores(texts: list[str]) -> list[float]:
    """
    Calculate text diversity scores (simplified TF-IDF).

    Higher scores indicate more unique vocabulary.
    """
    if not texts:
        return []

    # Simple tokenization (by spaces and punctuation).
    def tokenize(text: str) -> list[str]:
        return [w.lower() for w in re.findall(r"\w+", text) if len(w) > 1]

    # Count token frequency.
    all_tokens = []
    text_tokens = []
    for text in texts:
        tokens = tokenize(text)
        text_tokens.append(tokens)
        all_tokens.extend(tokens)

    # Compute document frequency.
    doc_freq = Counter()
    for tokens in text_tokens:
        doc_freq.update(set(tokens))

    # Compute diversity score for each text.
    scores = []
    for tokens in text_tokens:
        if not tokens:
            scores.append(0.0)
            continue

        # Score = average IDF of unique tokens.
        token_counts = Counter(tokens)
        score = sum((1.0 / doc_freq[token]) * count for token, count in token_counts.items()) / len(tokens)
        scores.append(score)

    return scores


def _sample_diverse_chunks(
    chunks: list[DocumentChunk],
    num_samples: int,
    max_chars: int = 2000,
) -> list[DocumentChunk]:
    """
    Sample chunks to ensure diversity.

    Strategy:
    1. Filter out short chunks
    2. Compute diversity scores
    3. Combine randomness with diversity
    """
    if not chunks:
        return []

    # Filter out very short chunks (< 50 chars).
    valid_chunks = [c for c in chunks if len(c.content.strip()) >= 50]

    if len(valid_chunks) <= num_samples:
        return valid_chunks

    # Truncate long content to speed up computation.
    chunk_texts = [c.content[:max_chars] for c in valid_chunks]

    # Compute diversity scores.
    diversity_scores = _calculate_text_diversity_scores(chunk_texts)

    # Normalize scores to [0, 1].
    max_score = max(diversity_scores) if diversity_scores else 1.0
    if max_score > 0:
        diversity_scores = [s / max_score for s in diversity_scores]

    # Combine randomness: 70% diversity, 30% random.
    combined_scores = [0.7 * div + 0.3 * secure_random_float01() for div in diversity_scores]

    # Select top-scoring chunks.
    indexed_scores = list(enumerate(combined_scores))
    indexed_scores.sort(key=lambda x: x[1], reverse=True)

    selected_indices = [idx for idx, _ in indexed_scores[:num_samples]]
    return [valid_chunks[idx] for idx in selected_indices]


def generate_questions_from_documents(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None = None,
    document_ids: list[UUID] | None = None,
    num_questions: int = 10,
    question_types: list[str] | None = None,
    prompt_template_id: UUID | None = None,
    prompt_template_key: str | None = None,
    prompt_ab_experiment_key: str | None = None,
) -> list[GeneratedQuestion]:
    """
    Generate test questions from documents.

    Args:
        db: Database session.
        tenant_id: Tenant ID.
        account_id: Account ID.
        dataset_id: Dataset ID (optional).
        document_ids: Document IDs (optional, preferred over dataset_id).
        num_questions: Number of questions to generate.
        question_types: Question type list.

    Returns:
        Generated question list.
    """
    normalized_types = _normalize_question_types(question_types)
    allowed_doc_ids = _resolve_document_scope_ids(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        document_ids=document_ids,
    )

    if not allowed_doc_ids:
        return []

    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id.in_(allowed_doc_ids),
        )
        .all()
    )
    if not chunks:
        return []

    num_chunks_needed = max(3, (num_questions + 2) // 3)
    sampled_chunks = _sample_diverse_chunks(chunks, num_chunks_needed)

    http_client, http_async_client = _build_testgen_http_clients()
    try:
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
            temperature=0.7,
            timeout=settings.LLM_TIMEOUT,
            http_client=http_client,
            http_async_client=http_async_client,
        )

        parser = JsonOutputParser()
        prompt_selection = _resolve_testgen_prompt_selection(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            prompt_template_id=prompt_template_id,
            prompt_template_key=prompt_template_key,
            prompt_ab_experiment_key=prompt_ab_experiment_key,
        )

        prompt = PromptTemplate(
            template=prompt_selection.prompt_template_text,
            input_variables=prompt_selection.prompt_variables,
        )
        chain = prompt | llm | parser

        all_questions: list[GeneratedQuestion] = []
        questions_per_chunk = max(1, num_questions // len(sampled_chunks))
        for chunk in sampled_chunks:
            try:
                prompt_inputs = _build_testgen_prompt_inputs(
                    chunk_text=chunk.content,
                    num_questions=questions_per_chunk,
                    normalized_types=normalized_types,
                    existing_questions=[item.question for item in all_questions if str(item.question or "").strip()],
                    prompt_variables=prompt_selection.prompt_variables,
                )
                result = chain.invoke(prompt_inputs)
                for q in _normalize_testgen_result_rows(result):
                    all_questions.append(
                        _generated_question_from_row(
                            row=q,
                            chunk=chunk,
                            normalized_types=normalized_types,
                            prompt_selection=prompt_selection,
                        )
                    )
            except Exception as e:
                logger.warning("Failed to generate questions: %s", e)
                continue

            if len(all_questions) >= num_questions:
                break

        return all_questions[:num_questions]
    finally:
        _close_testgen_http_clients(http_client, http_async_client)


def generate_questions_from_conversations(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    conversation_ids: list[UUID],
    num_questions: int = 10,
    quality_threshold: float = 0.7,
) -> list[GeneratedQuestion]:
    """
    Generate test questions from conversation history.

    Args:
        db: Database session.
        tenant_id: Tenant ID.
        account_id: Account ID.
        conversation_ids: Conversation ID list.
        num_questions: Number of questions to generate.
        quality_threshold: Quality threshold (0-1).

    Returns:
        Generated question list.
    """
    scoped_conversations = _load_scoped_conversations(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_ids=conversation_ids,
    )
    if not scoped_conversations:
        return []

    high_quality_turns = _collect_high_quality_conversation_turns(
        db=db,
        tenant_id=tenant_id,
        scoped_conversations=scoped_conversations,
        quality_threshold=quality_threshold,
    )
    if not high_quality_turns:
        return []

    conversation_text = _conversation_turns_text(
        _sample_high_quality_turns(
            high_quality_turns,
            num_questions=num_questions,
        )
    )
    return _generate_questions_from_conversation_text(
        conversation_text=conversation_text,
        num_questions=num_questions,
    )


def _load_scoped_conversations(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    conversation_ids: list[UUID],
) -> list[Conversation]:
    conversations = (
        db.query(Conversation).filter(Conversation.tenant_id == tenant_id, Conversation.id.in_(conversation_ids)).all()
    )
    if not conversations:
        return []

    conversation_by_id = {conversation.id: conversation for conversation in conversations}
    scoped_conversations: list[Conversation] = []
    for conversation_id in dict.fromkeys(conversation_ids):
        conversation = conversation_by_id.get(conversation_id)
        if conversation is None:
            continue
        ensure_conversation_access(db, tenant_id, account_id, conversation)
        scoped_conversations.append(conversation)
    return scoped_conversations


def _conversation_turn_quality(*, user_content: str, assistant_content: str, citations: Any) -> float:
    quality_score = 0.0
    if len(user_content.strip()) >= 10:
        quality_score += 0.3
    if len(assistant_content.strip()) >= 50:
        quality_score += 0.3
    if citations:
        quality_score += 0.4
    return quality_score


def _conversation_messages(db: Session, *, tenant_id: UUID, conversation_id: UUID) -> list[Message]:
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.tenant_id == tenant_id)
        .order_by(Message.created_at.asc())
        .all()
    )


def _collect_high_quality_conversation_turns(
    *,
    db: Session,
    tenant_id: UUID,
    scoped_conversations: list[Conversation],
    quality_threshold: float,
) -> list[tuple[str, str, UUID]]:
    high_quality_turns: list[tuple[str, str, UUID]] = []
    for conv in scoped_conversations:
        messages = _conversation_messages(db, tenant_id=tenant_id, conversation_id=conv.id)
        pending_user: Message | None = None
        for msg in messages:
            if msg.role == "user":
                pending_user = msg
                continue
            if msg.role != "assistant" or pending_user is None:
                continue
            quality_score = _conversation_turn_quality(
                user_content=pending_user.content,
                assistant_content=msg.content,
                citations=msg.citations,
            )
            if quality_score >= quality_threshold:
                high_quality_turns.append((pending_user.content, msg.content, conv.id))
            pending_user = None
    return high_quality_turns


def _sample_high_quality_turns(
    high_quality_turns: list[tuple[str, str, UUID]],
    *,
    num_questions: int,
) -> list[tuple[str, str, UUID]]:
    if len(high_quality_turns) <= num_questions * 2:
        return high_quality_turns
    return secure_sample(high_quality_turns, num_questions * 2)


def _conversation_turns_text(high_quality_turns: list[tuple[str, str, UUID]]) -> str:
    return "\n\n".join(f"User: {user}\nAssistant: {assistant}" for user, assistant, _ in high_quality_turns)


def _conversation_generated_questions(result: Any) -> list[GeneratedQuestion]:
    if not isinstance(result, dict) or "questions" not in result:
        return []
    questions: list[GeneratedQuestion] = []
    for q in result["questions"]:
        questions.append(
            GeneratedQuestion(
                question=q.get("question", ""),
                expected_answer=q.get("expected_answer"),
                context=q.get("original_question"),
                metadata={"source_type": "conversation", "original_question": q.get("original_question", "")},
            )
        )
    return questions


def _generate_questions_from_conversation_text(
    *,
    conversation_text: str,
    num_questions: int,
) -> list[GeneratedQuestion]:
    http_client, http_async_client = _build_testgen_http_clients()
    try:
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
            temperature=0.7,
            timeout=settings.LLM_TIMEOUT,
            http_client=http_client,
            http_async_client=http_async_client,
        )

        parser = JsonOutputParser()
        prompt = PromptTemplate(
            template=EXTRACT_QUESTIONS_FROM_CONVERSATION_PROMPT, input_variables=["conversations", "num_questions"]
        )

        chain = prompt | llm | parser

        try:
            result = chain.invoke(
                {
                    "conversations": conversation_text[:8000],
                    "num_questions": num_questions,
                }
            )
            return _conversation_generated_questions(result)[:num_questions]

        except Exception as e:
            logger.warning("Failed to generate questions from conversation: %s", e)
            return []
    finally:
        _close_testgen_http_clients(http_client, http_async_client)
