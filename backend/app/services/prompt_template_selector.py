"""
PromptTemplate 选择器：支持
- 指定 prompt_template_id
- 按 template_key 选择最新可用版本
- A/B 实验（按 ab_experiment_key + 权重）做稳定分流

该模块用于 chat/RAG 引擎侧在运行时决定“到底用哪个模板”，并把结果写入 message_metadata，
以便评测闭环（对比版本/A-B、关联用户反馈、回归集等）。
"""

from __future__ import annotations

import hashlib
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.prompt_template import PromptTemplate


def _stable_unit_interval(seed: str) -> float:
    """将 seed 映射到 [0, 1) 的稳定伪随机数（用于 A/B 分流）。"""
    raw = hashlib.sha256(seed.encode("utf-8")).digest()
    num = int.from_bytes(raw[:8], "big", signed=False)
    return (num % 1_000_000) / 1_000_000.0


def resolve_prompt_template(
    *,
    db: Session,
    tenant_id: UUID,
    prompt_template_id: Optional[UUID] = None,
    template_key: Optional[str] = None,
    ab_experiment_key: Optional[str] = None,
    ab_user_key: Optional[str] = None,
) -> Optional[PromptTemplate]:
    """
    解析出最终要使用的 PromptTemplate（返回 ORM 对象）。

    优先级：
    1) prompt_template_id
    2) template_key（取 is_active 且 version 最大）
    3) ab_experiment_key（取 is_active 变体集合，按 ab_weight 稳定分流）
    """
    if prompt_template_id:
        return (
            db.query(PromptTemplate)
            .filter(
                PromptTemplate.id == prompt_template_id,
                PromptTemplate.tenant_id == tenant_id,
                PromptTemplate.is_active == True,  # noqa: E712
            )
            .first()
        )

    query = db.query(PromptTemplate).filter(
        PromptTemplate.tenant_id == tenant_id,
        PromptTemplate.is_active == True,  # noqa: E712
    )

    if template_key:
        return (
            query.filter(PromptTemplate.template_key == template_key)
            .order_by(PromptTemplate.version.desc())
            .first()
        )

    if ab_experiment_key:
        variants = (
            query.filter(PromptTemplate.ab_experiment_key == ab_experiment_key)
            .order_by(PromptTemplate.ab_variant.asc().nullslast(), PromptTemplate.updated_at.desc())
            .all()
        )
        if not variants:
            return None
        if len(variants) == 1:
            return variants[0]

        weights = []
        total = 0.0
        for v in variants:
            w = float(getattr(v, "ab_weight", 1.0) or 0.0)
            if w < 0:
                w = 0.0
            weights.append(w)
            total += w
        if total <= 0:
            weights = [1.0 for _ in variants]
            total = float(len(variants))

        seed = f"{ab_experiment_key}:{ab_user_key or ''}"
        r = _stable_unit_interval(seed) * total
        acc = 0.0
        for v, w in zip(variants, weights):
            acc += w
            if r <= acc:
                return v
        return variants[-1]

    return None

