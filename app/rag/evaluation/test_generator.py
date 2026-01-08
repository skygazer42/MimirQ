"""
Test question generator.

Generates test questions from documents or conversation history for RAGAS regression.
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
from collections import Counter

from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.utils import get_proxy_url
from app.models.document import Document as DBDocument, DocumentChunk
from app.models.chat import Conversation, Message
from app.services.document_access import filter_allowed_document_ids


class GeneratedQuestion(BaseModel):
    """Generated question."""
    question: str = Field(description="Question content")
    expected_answer: Optional[str] = Field(default=None, description="Expected answer (optional)")
    context: Optional[str] = Field(default=None, description="Question source context")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


# Prompt template for generating questions.
GENERATE_QUESTIONS_FROM_TEXT_PROMPT = """You are an expert test question generator. Please generate high-quality test questions based on the following text content.

Text content:
{text}

Requirements:
1. Generate {num_questions} questions
2. Question types include: {question_types}
   - factual: Ask about specific information in the text
   - reasoning: Requires understanding and reasoning to answer
   - comparison: Compare different concepts or things in the text
3. Questions should be clear, specific, and answerable from the text
4. Each question should have a reference answer

Please return in JSON format as follows:
{{
  "questions": [
    {{
      "question": "Question content",
      "expected_answer": "Reference answer",
      "question_type": "Question type"
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


def _calculate_text_diversity_scores(texts: List[str]) -> List[float]:
    """
    Calculate text diversity scores (simplified TF-IDF).

    Higher scores indicate more unique vocabulary.
    """
    if not texts:
        return []
    
    # Simple tokenization (by spaces and punctuation).
    def tokenize(text: str) -> List[str]:
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
    chunks: List[DocumentChunk],
    num_samples: int,
    max_chars: int = 2000
    ) -> List[DocumentChunk]:
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
        0.7 * div + 0.3 * random.random()
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
    dataset_id: Optional[UUID] = None,
    document_ids: Optional[List[UUID]] = None,
    num_questions: int = 10,
    question_types: Optional[List[str]] = None,
) -> List[GeneratedQuestion]:
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
    if question_types is None:
        question_types = ["factual", "reasoning", "comparison"]
    
    # Permission checks and document filtering.
    if document_ids:
        allowed_doc_ids = filter_allowed_document_ids(
            db, tenant_id, account_id, document_ids
        )
    elif dataset_id:
        from app.services.dataset_service import DatasetService
        DatasetService.ensure_member(db, tenant_id, account_id)
        query = db.query(DBDocument).filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.status == "completed"
        )
        allowed_doc_ids = [doc.id for doc in query.all()]
    else:
        # Fetch all accessible documents.
        from app.services.document_access import list_accessible_document_ids
        allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id)
    
    if not allowed_doc_ids:
        return []
    
    # Query document chunks.
    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id.in_(allowed_doc_ids)
        )
        .all()
    )
    
    if not chunks:
        return []
    
    # Sample chunks (one chunk per 3-4 questions).
    num_chunks_needed = max(3, (num_questions + 2) // 3)
    sampled_chunks = _sample_diverse_chunks(chunks, num_chunks_needed)
    
    # Prepare LLM.
    proxy_url = get_proxy_url()
    http_client_kwargs = {}
    if proxy_url:
        http_client_kwargs["proxies"] = proxy_url
    
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
        temperature=0.7,
        http_client=None if not http_client_kwargs else None,
        **http_client_kwargs
    )
    
    parser = JsonOutputParser()
    prompt = PromptTemplate(
        template=GENERATE_QUESTIONS_FROM_TEXT_PROMPT,
        input_variables=["text", "num_questions", "question_types"]
    )
    
    chain = prompt | llm | parser
    
    # Generate questions for each chunk.
    all_questions: List[GeneratedQuestion] = []
    questions_per_chunk = max(1, num_questions // len(sampled_chunks))
    
    for chunk in sampled_chunks:
        try:
            result = chain.invoke({
                "text": chunk.content[:2000],  # Limit length.
                "num_questions": questions_per_chunk,
                "question_types": ", ".join(question_types)
            })
            
            if isinstance(result, dict) and "questions" in result:
                for q in result["questions"]:
                    all_questions.append(GeneratedQuestion(
                        question=q.get("question", ""),
                        expected_answer=q.get("expected_answer"),
                        context=chunk.content[:500],
                        metadata={
                            "source_type": "document",
                            "source_id": str(chunk.document_id),
                            "chunk_id": str(chunk.id),
                            "question_type": q.get("question_type", "factual")
                        }
                    ))
        except Exception as e:
            print(f"Failed to generate questions: {e}")
            continue
        
        if len(all_questions) >= num_questions:
            break
    
    return all_questions[:num_questions]


def generate_questions_from_conversations(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    conversation_ids: List[UUID],
    num_questions: int = 10,
    quality_threshold: float = 0.7,
) -> List[GeneratedQuestion]:
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
    high_quality_turns: List[Tuple[str, str, UUID]] = []
    
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
        high_quality_turns = random.sample(high_quality_turns, num_questions * 2)
    
    # Prepare conversation text.
    conversation_text = "\n\n".join([
        f"User: {user}\nAssistant: {assistant}"
        for user, assistant, _ in high_quality_turns
    ])
    
    # Prepare LLM.
    proxy_url = get_proxy_url()
    http_client_kwargs = {}
    if proxy_url:
        http_client_kwargs["proxies"] = proxy_url
    
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
        temperature=0.7,
        http_client=None if not http_client_kwargs else None,
        **http_client_kwargs
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
        
        questions: List[GeneratedQuestion] = []
        
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
        print(f"Failed to generate questions from conversation: {e}")
        return []
