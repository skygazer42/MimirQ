"""
用户反馈（评测闭环）相关数据模型。

用于记录用户对某条 assistant 消息的评分、原因、期望答案等信息，
以便后续做质量分析、回归集构建、A/B 对比与模型迭代。
"""

 
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.core.database import Base


class MessageFeedback(Base):
    """对某条 assistant 消息的反馈记录（tenant 隔离）。"""

    __tablename__ = "message_feedback"
    __table_args__ = (
        # 同一用户对同一条消息只保留一条（重复提交走更新逻辑）
        UniqueConstraint("tenant_id", "message_id", "account_id", name="uq_message_feedback_once"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    account_id = Column(String(255), nullable=False, index=True)

    # 评分：建议 1~5（越高越好）
    rating = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    tags = Column(JSONB, default=list)
    expected_answer = Column(Text, nullable=True)
    extra = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

