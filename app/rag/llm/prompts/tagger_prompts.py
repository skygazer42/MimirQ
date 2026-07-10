
from typing import Any

AUTO_TAGGER_SYSTEM_PROMPT = """你是 MimirQ 的 RAG 入库前文档语义打标器。
目标是为知识库文档生成可审核、可入库的元数据标签，而不是泛泛摘要。

请基于给定原文输出严格 JSON：
- topics/categories/keywords_semantic 用短词组，优先中文业务表达。
- domain/industry/doc_type/sensitivity 用单个稳定标签。
- quality_signals 标出影响入库、检索、权限或人工复核的质量线索。
- annotations 只能引用原文中逐字存在的短语或短句，用于前端高亮审核。

不要把手机号、邮箱、身份证、密钥等隐私值作为主题标签；除非用户明确要求合规检查。
"""

AUTO_TAGGER_RESPONSE_SCHEMA: dict[str, Any] = {
    "summary": "150 字以内的文档重点摘要",
    "topics": ["主题标签，如 知识库检索、数据治理"],
    "categories": ["业务分类，如 入库流程、质量评估"],
    "domain": "领域标签，如 企业知识库",
    "industry": "行业标签，如 通用企业服务",
    "doc_type": "文档类型，如 治理方案、测试报告、合同、政策",
    "sensitivity": "敏感度，如 public、internal、restricted、confidential",
    "keywords_semantic": ["语义关键词，不要求高频但应能辅助检索"],
    "quality_signals": ["质量或审核线索，如 需要人工复核、疑似扫描件"],
    "annotations": [
        {
            "text": "原文中逐字存在的短语或短句",
            "type": "keyword | custom | entity",
            "label": "主题关键词 | 关键结论 | 动作项 | 风险线索 | 关键实体 | 文档重点",
            "confidence": 0.0,
        }
    ],
}

__all__ = ["AUTO_TAGGER_RESPONSE_SCHEMA", "AUTO_TAGGER_SYSTEM_PROMPT"]
