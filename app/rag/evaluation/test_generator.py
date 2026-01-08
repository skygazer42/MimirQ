"""
测试问题生成器

从文档或对话历史中生成测试问题，用于 RAGAS 回归测试。
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
    """生成的问题"""
    question: str = Field(description="问题内容")
    expected_answer: Optional[str] = Field(default=None, description="期望答案（可选）")
    context: Optional[str] = Field(default=None, description="问题来源上下文")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


# 生成问题的提示词模板
GENERATE_QUESTIONS_FROM_TEXT_PROMPT = """你是一个专业的测试问题生成专家。请基于以下文本内容生成高质量的测试问题。

文本内容：
{text}

要求：
1. 生成 {num_questions} 个问题
2. 问题类型包括：{question_types}
   - factual（事实型）：询问文本中的具体信息
   - reasoning（推理型）：需要理解和推理才能回答
   - comparison（对比型）：比较文本中的不同概念或事物
3. 问题应该清晰、具体，可以从文本中找到答案
4. 每个问题都应该有参考答案

请以 JSON 格式返回，格式如下：
{{
  "questions": [
    {{
      "question": "问题内容",
      "expected_answer": "参考答案",
      "question_type": "问题类型"
    }}
  ]
}}
"""

EXTRACT_QUESTIONS_FROM_CONVERSATION_PROMPT = """你是一个专业的问答提炼专家。请从以下对话记录中提炼和改进用户的问题。

对话记录：
{conversations}

要求：
1. 提炼 {num_questions} 个高质量问题
2. 优先选择：
   - 清晰明确的问题
   - 有实际价值的问题
   - 覆盖不同主题的问题
3. 对提取的问题进行适当改写，使其更加规范和通用
4. 去重，避免提取相似的问题
5. 如果助手的回答质量高，可以将其作为参考答案

请以 JSON 格式返回，格式如下：
{{
  "questions": [
    {{
      "question": "提炼后的问题",
      "expected_answer": "参考答案（如果有）",
      "original_question": "原始问题"
    }}
  ]
}}
"""


def _calculate_text_diversity_scores(texts: List[str]) -> List[float]:
    """
    计算文本的多样性分数（基于 TF-IDF 思想的简化版本）
    
    返回每个文本的多样性分数，分数越高表示包含更多独特词汇
    """
    if not texts:
        return []
    
    # 简单分词（按空格和标点）
    def tokenize(text: str) -> List[str]:
        return [w.lower() for w in re.findall(r'\w+', text) if len(w) > 1]
    
    # 统计词频
    all_tokens = []
    text_tokens = []
    for text in texts:
        tokens = tokenize(text)
        text_tokens.append(tokens)
        all_tokens.extend(tokens)
    
    # 计算文档频率
    doc_freq = Counter()
    for tokens in text_tokens:
        doc_freq.update(set(tokens))

    # 计算每个文本的多样性分数
    scores = []
    for tokens in text_tokens:
        if not tokens:
            scores.append(0.0)
            continue
        
        # 分数 = 独特词汇的平均 IDF
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
    从文档切片中采样，确保多样性
    
    策略：
    1. 过滤掉太短的切片
    2. 计算多样性分数
    3. 结合随机性和多样性选择
    """
    if not chunks:
        return []
    
    # 过滤太短的切片（少于 50 字符）
    valid_chunks = [c for c in chunks if len(c.content.strip()) >= 50]
    
    if len(valid_chunks) <= num_samples:
        return valid_chunks
    
    # 截断过长的内容以加速计算
    chunk_texts = [c.content[:max_chars] for c in valid_chunks]
    
    # 计算多样性分数
    diversity_scores = _calculate_text_diversity_scores(chunk_texts)
    
    # 归一化分数到 [0, 1]
    max_score = max(diversity_scores) if diversity_scores else 1.0
    if max_score > 0:
        diversity_scores = [s / max_score for s in diversity_scores]
    
    # 结合随机性：70% 多样性权重，30% 随机权重
    combined_scores = [
        0.7 * div + 0.3 * random.random()
        for div in diversity_scores
    ]
    
    # 选择得分最高的切片
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
    从文档中生成测试问题
    
    Args:
        db: 数据库会话
        tenant_id: 租户 ID
        account_id: 账户 ID
        dataset_id: 知识库 ID（可选）
        document_ids: 文档 ID 列表（可选，优先于 dataset_id）
        num_questions: 生成问题数量
        question_types: 问题类型列表
    
    Returns:
        生成的问题列表
    """
    if question_types is None:
        question_types = ["factual", "reasoning", "comparison"]
    
    # 权限检查和文档过滤
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
        # 获取所有可访问文档
        from app.services.document_access import list_accessible_document_ids
        allowed_doc_ids = list_accessible_document_ids(db, tenant_id, account_id)
    
    if not allowed_doc_ids:
        return []
    
    # 查询文档切片
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
    
    # 采样切片（每 3-4 个问题需要一个切片）
    num_chunks_needed = max(3, (num_questions + 2) // 3)
    sampled_chunks = _sample_diverse_chunks(chunks, num_chunks_needed)
    
    # 准备 LLM
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
    
    # 为每个切片生成问题
    all_questions: List[GeneratedQuestion] = []
    questions_per_chunk = max(1, num_questions // len(sampled_chunks))
    
    for chunk in sampled_chunks:
        try:
            result = chain.invoke({
                "text": chunk.content[:2000],  # 限制长度
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
            print(f"生成问题失败: {e}")
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
    从对话历史中生成测试问题
    
    Args:
        db: 数据库会话
        tenant_id: 租户 ID
        account_id: 账户 ID
        conversation_ids: 对话 ID 列表
        num_questions: 生成问题数量
        quality_threshold: 质量阈值（0-1）
    
    Returns:
        生成的问题列表
    """
    # 查询对话和消息
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
    
    # 收集高质量的用户问题
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
        
        # 配对用户-助手消息
        pending_user = None
        for msg in messages:
            if msg.role == "user":
                pending_user = msg
            elif msg.role == "assistant" and pending_user:
                # 质量评分：基于消息长度和引用数量
                user_len = len(pending_user.content.strip())
                assistant_len = len(msg.content.strip())
                num_citations = len(msg.citations) if msg.citations else 0
                
                # 简单评分规则
                quality_score = 0.0
                if user_len >= 10:  # 问题足够长
                    quality_score += 0.3
                if assistant_len >= 50:  # 回答足够详细
                    quality_score += 0.3
                if num_citations > 0:  # 有引用
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
    
    # 如果高质量对话很多，随机采样
    if len(high_quality_turns) > num_questions * 2:
        high_quality_turns = random.sample(high_quality_turns, num_questions * 2)
    
    # 准备对话文本
    conversation_text = "\n\n".join([
        f"用户: {user}\n助手: {assistant}"
        for user, assistant, _ in high_quality_turns
    ])
    
    # 准备 LLM
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
            "conversations": conversation_text[:8000],  # 限制长度
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
        print(f"从对话生成问题失败: {e}")
        return []
