"""
Test question generator.

Generates test questions from documents or conversation history for RAGAS regression.
"""
import logging
import re
from collections import Counter
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
from app.core.utils import get_proxy_url
from app.models.chat import Conversation, Message
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.services.document_access import filter_allowed_document_ids

logger = logging.getLogger(__name__)


class GeneratedQuestion(BaseModel):
    """Generated question."""
    question: str = Field(description="Question content")
    expected_answer: str | None = Field(default=None, description="Expected answer (optional)")
    context: str | None = Field(default=None, description="Question source context")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


# Prompt template for generating questions.
GENERATE_QUESTIONS_FROM_TEXT_PROMPT = """You are an expert test question generator. Please generate high-quality test questions based on the following text content.

Text content:
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

EXTRACT_QUESTIONS_FROM_CONVERSATION_PROMPT = """You are an expert Q&A extractor. Please extract and refine user questions from the following conversation history.

Conversation history:
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


def _calculate_text_diversity_scores(texts: list[str]) -> list[float]:
    """
    Calculate text diversity scores (simplified TF-IDF).

    Higher scores indicate more unique vocabulary.
    """
    if not texts:
        return []
    
    # Simple tokenization (by spaces and punctuation).
    def tokenize(text: str) -> list[str]:
        return [w.lower() for w in re.findall(r'\w+', text) if len(w) > 1]
    
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
        score = sum(
            (1.0 / doc_freq[token]) * count
            for token, count in token_counts.items()
        ) / len(tokens)
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
    combined_scores = [
        0.7 * div + 0.3 * secure_random_float01()
        for div in diversity_scores
    ]
    
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
    allowed_types = {"factual", "multi_hop", "comparison", "conditional", "unanswerable"}
    if question_types is None:
        question_types = ["factual", "multi_hop", "comparison"]

    normalized_types: list[str] = []
    for raw_type in question_types or []:
        key = str(raw_type or "").strip().lower()
        if not key:
            continue
        if key == "reasoning":
            key = "multi_hop"
        if key not in allowed_types or key in normalized_types:
            continue
        normalized_types.append(key)
    if not normalized_types:
        normalized_types = ["factual"]

    if document_ids:
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, document_ids)
    elif dataset_id:
        from app.services.dataset_service import DatasetService

        DatasetService.ensure_member(db, tenant_id, account_id)
        query = db.query(DBDocument).filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.status == "completed",
        )
        allowed_doc_ids = [doc.id for doc in query.all()]
    else:
        from app.services.document_access import list_accessible_document_ids

        allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id)

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

    proxy_url = get_proxy_url()
    timeout = int(getattr(settings, "LLM_TIMEOUT", 60) or 60)
    http_client = httpx.Client(proxy=proxy_url, timeout=timeout) if proxy_url else None
    try:
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
            temperature=0.7,
            timeout=timeout,
            http_client=http_client,
        )

        parser = JsonOutputParser()
        prompt = PromptTemplate(
            template=GENERATE_QUESTIONS_FROM_TEXT_PROMPT,
            input_variables=["text", "num_questions", "question_types"],
        )
        chain = prompt | llm | parser

        all_questions: list[GeneratedQuestion] = []
        questions_per_chunk = max(1, num_questions // len(sampled_chunks))
        for chunk in sampled_chunks:
            try:
                result = chain.invoke(
                    {
                        "text": chunk.content[:2000],
                        "num_questions": questions_per_chunk,
                        "question_types": ", ".join(normalized_types),
                    }
                )
                if isinstance(result, dict) and "questions" in result:
                    for q in result["questions"]:
                        q_type = str(q.get("question_type") or "factual").strip().lower() or "factual"
                        if q_type == "reasoning":
                            q_type = "multi_hop"
                        if q_type not in allowed_types:
                            q_type = normalized_types[0]
                        expected_refusal = bool(q.get("expected_refusal")) or q_type == "unanswerable"
                        all_questions.append(
                            GeneratedQuestion(
                                question=q.get("question", ""),
                                expected_answer=(None if expected_refusal else q.get("expected_answer")),
                                context=chunk.content[:500],
                                metadata={
                                    "source_type": "document",
                                    "source_id": str(chunk.document_id),
                                    "chunk_id": str(chunk.id),
                                    "question_type": q_type,
                                    "expected_refusal": expected_refusal,
                                    "reference_chunk_ids": [str(chunk.id)],
                                },
                            )
                        )
            except Exception as e:
                logger.warning("Failed to generate questions: %s", e)
                continue

            if len(all_questions) >= num_questions:
                break

        return all_questions[:num_questions]
    finally:
        if http_client is not None:
            http_client.close()


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
    # Query conversations and messages.
    conversations = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.id.in_(conversation_ids)
        )
        .all()
    )
    
    if not conversations:
        return []
    
    # Collect high-quality user questions.
    high_quality_turns: list[tuple[str, str, UUID]] = []
    
    for conv in conversations:
        messages = (
            db.query(Message)
            .filter(
                Message.conversation_id == conv.id,
                Message.tenant_id == tenant_id
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        
        # Pair user-assistant messages.
        pending_user = None
        for msg in messages:
            if msg.role == "user":
                pending_user = msg
            elif msg.role == "assistant" and pending_user:
                # Quality score based on message length and citation count.
                user_len = len(pending_user.content.strip())
                assistant_len = len(msg.content.strip())
                num_citations = len(msg.citations) if msg.citations else 0
                
                # Simple scoring rules.
                quality_score = 0.0
                if user_len >= 10:  # Question long enough.
                    quality_score += 0.3
                if assistant_len >= 50:  # Answer detailed enough.
                    quality_score += 0.3
                if num_citations > 0:  # Has citations.
                    quality_score += 0.4
                
                if quality_score >= quality_threshold:
                    high_quality_turns.append((
                        pending_user.content,
                        msg.content,
                        conv.id
                    ))
                
                pending_user = None
    
    if not high_quality_turns:
        return []
    
    # If many high-quality conversations, sample randomly.
    if len(high_quality_turns) > num_questions * 2:
        high_quality_turns = secure_sample(high_quality_turns, num_questions * 2)
    
    # Prepare conversation text.
    conversation_text = "\n\n".join([
        f"User: {user}\nAssistant: {assistant}"
        for user, assistant, _ in high_quality_turns
    ])
    
    # Prepare LLM.
    proxy_url = get_proxy_url()
    timeout = int(getattr(settings, "LLM_TIMEOUT", 60) or 60)
    http_client = httpx.Client(proxy=proxy_url, timeout=timeout) if proxy_url else None
    try:
        llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
            temperature=0.7,
            timeout=timeout,
            http_client=http_client,
        )
        
        parser = JsonOutputParser()
        prompt = PromptTemplate(
            template=EXTRACT_QUESTIONS_FROM_CONVERSATION_PROMPT,
            input_variables=["conversations", "num_questions"]
        )
        
        chain = prompt | llm | parser
        
        try:
            result = chain.invoke({
                "conversations": conversation_text[:8000],  # Limit length.
                "num_questions": num_questions
            })
            
            questions: list[GeneratedQuestion] = []
            
            if isinstance(result, dict) and "questions" in result:
                for q in result["questions"]:
                    questions.append(GeneratedQuestion(
                        question=q.get("question", ""),
                        expected_answer=q.get("expected_answer"),
                        context=q.get("original_question"),
                        metadata={
                            "source_type": "conversation",
                            "original_question": q.get("original_question", "")
                        }
                    ))
            
            return questions[:num_questions]
        
        except Exception as e:
            logger.warning("Failed to generate questions from conversation: %s", e)
            return []
    finally:
        if http_client is not None:
            http_client.close()
