from __future__ import annotations

from dataclasses import dataclass

from app.rag.llm.prompts.formal_templates import (
    FORMAL_PROMPT_TAGS,
    render_formal_json_prompt,
    render_formal_xml_prompt,
)


@dataclass(frozen=True)
class BuiltinPromptTemplate:
    template_key: str
    name: str
    description: str
    content: str
    variables: list[str]
    category: str
    tags: list[str]
    version: int = 1


_FORMAL_VERSION = 2


def _tags(*values: str) -> list[str]:
    return ["builtin", *FORMAL_PROMPT_TAGS, *values]


_RAG_ANSWER_CLAUDE_XML_ZH = render_formal_xml_prompt(
    role="企业知识库检索增强问答助手",
    objective="仅基于检索上下文回答用户问题，输出可审计、可追溯、可拒答的企业答案。",
    documents_slot="<context>\n{context}\n</context>",
    task_sections=[
        ("history", "{history}"),
        ("question", "{question}"),
        ("output_format", "{format_instructions}"),
    ],
    output_contract=(
        "1. 直接输出最终答案，不输出前置解释。\n"
        "2. 每条事实结论尽量附引用；支持结构化来源时使用 <source idx=\"N\"/>，否则使用 [来源: 文件名#页码]。\n"
        "3. 若 <output_format> 提供结构化约束，必须优先满足该格式。\n"
        "4. 答案必须简洁、专业、保守，不使用 emoji 或营销化语言。"
    ),
)


_KG_EXTRACT_GRAPHRAG_ZH = render_formal_json_prompt(
    role="知识图谱抽取器",
    objective="从企业文档片段中抽取实体、关系和事件，保留逐字证据，并为后续 GraphRAG 检索提供稳定结构。",
    task_rules=[
        "采用 GraphRAG 风格实体-关系-事件三层抽取，实体类型必须来自枚举。",
        "识别所有明确出现的实体，标注 type、description、evidence_quote。",
        "识别成对实体关系，标注 type、description、strength(1-10)、evidence_quote。",
        "识别最多 {max_events} 个重要事件；每个事件最多关联 {max_entities} 个实体。",
        "执行一轮轻量 gleaning：输出前自查是否遗漏关键实体、关系或事件；若发现遗漏，补入结果。",
        "不得抽取无证据实体；不得把标题、页脚或噪声当作业务事实。",
    ],
    examples="""[Few-shot Example]
Input:
Alpha rollout uses the blue flag. Alice approved the rollout on 2026-05-22.
Output:
{
  "entities": [
    {
      "name": "Alpha rollout",
      "type": "Event",
      "description": "一次使用 blue flag 的发布活动",
      "evidence_quote": "Alpha rollout uses the blue flag"
    },
    {
      "name": "Alice",
      "type": "Person",
      "description": "批准发布活动的人员",
      "evidence_quote": "Alice approved the rollout"
    }
  ],
  "relations": [
    {
      "source": "Alice",
      "target": "Alpha rollout",
      "type": "approved",
      "description": "Alice 批准 Alpha rollout",
      "strength": 8,
      "evidence_quote": "Alice approved the rollout on 2026-05-22"
    }
  ],
  "events": [
    {
      "title": "Alpha 发布获批",
      "summary": "Alpha rollout 使用 blue flag，并由 Alice 在 2026-05-22 批准。",
      "entities": ["Alpha rollout", "Alice"]
    }
  ]
}
""",
    input_sections=[("Real Data", "{context}")],
    output_schema="""{
  "type": "object",
  "required": ["entities", "relations", "events"],
  "properties": {
    "entities": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "type", "description", "evidence_quote"],
        "properties": {
          "name": {"type": "string"},
          "type": {
            "type": "string",
            "enum": ["Organization", "Person", "Location", "Product", "Event", "Time", "Money", "Metric", "Concept", "Protocol"]
          },
          "description": {"type": "string"},
          "evidence_quote": {"type": "string"}
        }
      }
    },
    "relations": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["source", "target", "type", "description", "strength", "evidence_quote"],
        "properties": {
          "source": {"type": "string"},
          "target": {"type": "string"},
          "type": {"type": "string"},
          "description": {"type": "string"},
          "strength": {"type": "integer", "minimum": 1, "maximum": 10},
          "evidence_quote": {"type": "string"}
        }
      }
    },
    "events": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title", "summary", "entities"],
        "properties": {
          "title": {"type": "string"},
          "summary": {"type": "string"},
          "entities": {"type": "array", "items": {"type": "string"}}
        }
      }
    }
  }
}""",
)


_JUDGE_FAITHFULNESS_RAGAS_ZH = render_formal_json_prompt(
    role="RAG 事实一致性评测专家",
    objective="评估回答是否被上下文支持，并把引用错误视为事实错误。",
    task_rules=[
        "把回答拆成 atomic_facts，每条只包含一个可验证事实。",
        "对每条 atomic fact 在上下文中寻找逐字证据。",
        "状态只能是 supported | contradicted | not_found。",
        "score = supported / total；若没有可评估事实，score 为 0。",
        "若回答引用不存在、引用不支持结论或引用错位，标为 not_found 或 contradicted。",
    ],
    input_sections=[
        ("问题", "{question}"),
        ("上下文", "{contexts}"),
        ("回答", "{answer}"),
    ],
    output_schema="""{
  "type": "object",
  "required": ["atomic_facts", "score", "reason"],
  "properties": {
    "atomic_facts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["fact", "status", "evidence_quote"],
        "properties": {
          "fact": {"type": "string"},
          "status": {"type": "string", "enum": ["supported", "contradicted", "not_found"]},
          "evidence_quote": {"type": "string"}
        }
      }
    },
    "score": {"type": "number", "minimum": 0, "maximum": 1},
    "reason": {"type": "string"}
  }
}""",
)


_TESTSET_GENERATION_RAGAS_ZH = render_formal_json_prompt(
    role="RAG 评测集生成器",
    objective="从文档片段生成可回归的高质量问答对，覆盖事实、推理、拒答、引用和召回难点。",
    task_rules=[
        "生成 {n} 个高质量问答对，问题必须能由文档片段或明确缺失证据判定。",
        "覆盖 simple、reasoning、multi_context、conditional、counterfactual、refusal。",
        "必须包含至少一种时态陷阱或术语变体难点；可根据片段内容选择是否生成。",
        "ground_truth 必须基于片段总结，不得依赖外部知识。",
        "evidence_quotes 必须逐字摘录；refusal 样本的 evidence_quotes 可为空但必须说明缺失证据。",
        "避免与 existing_questions 重复。",
    ],
    input_sections=[
        ("文档片段", "{document_chunk}"),
        ("已生成问题清单（避免重复）", "{existing_questions}"),
    ],
    output_schema="""{
  "type": "object",
  "required": ["qa_pairs"],
  "properties": {
    "qa_pairs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["question", "ground_truth", "evidence_quotes", "difficulty", "challenge_type"],
        "properties": {
          "question": {"type": "string", "description": "用户提问，中文口语化"},
          "ground_truth": {"type": "string", "description": "基于片段的真实答案，50-200 字；refusal 样本说明无法回答原因"},
          "evidence_quotes": {"type": "array", "items": {"type": "string"}},
          "difficulty": {
            "type": "string",
            "enum": ["simple", "reasoning", "multi_context", "conditional", "counterfactual", "refusal"]
          },
          "challenge_type": {
            "type": "string",
            "enum": ["direct_fact", "时态陷阱", "术语变体", "cross_context", "missing_evidence", "contradiction"]
          },
          "expected_chunks": {"type": "array", "items": {"type": "string"}}
        }
      }
    }
  }
}""",
)


_BUILTIN_PROMPT_TEMPLATES: tuple[BuiltinPromptTemplate, ...] = (
    BuiltinPromptTemplate(
        template_key="rag_answer_claude_xml_zh",
        name="RAG 主答案（Claude XML 中文）",
        description="用于企业知识库主回答链路，强调上下文边界、拒答、引用和提示词注入防护。",
        content=_RAG_ANSWER_CLAUDE_XML_ZH,
        variables=["context", "history", "question", "format_instructions"],
        category="rag_answer",
        tags=_tags("rag", "answer", "citation", "zh"),
        version=_FORMAL_VERSION,
    ),
    BuiltinPromptTemplate(
        template_key="kg_extract_graphrag_zh",
        name="知识图谱抽取（GraphRAG 中文）",
        description="用于 KG 实体、关系和事件抽取，要求 evidence_quote 逐字证据。",
        content=_KG_EXTRACT_GRAPHRAG_ZH,
        variables=["context", "max_events", "max_entities"],
        category="kg_extract",
        tags=_tags("kg", "graphrag", "evidence", "zh"),
        version=_FORMAL_VERSION,
    ),
    BuiltinPromptTemplate(
        template_key="judge_faithfulness_ragas_zh",
        name="事实一致性评测（RAGAS 中文）",
        description="用于 LLM-as-Judge，将答案拆成原子事实并按上下文支持度评分。",
        content=_JUDGE_FAITHFULNESS_RAGAS_ZH,
        variables=["question", "contexts", "answer"],
        category="llm_judge",
        tags=_tags("ragas", "faithfulness", "evaluation", "zh"),
        version=_FORMAL_VERSION,
    ),
    BuiltinPromptTemplate(
        template_key="testset_generation_ragas_zh",
        name="评测集生成（RAGAS 中文）",
        description="用于从文档片段生成带 ground truth 和逐字证据的 RAG 评测问答。",
        content=_TESTSET_GENERATION_RAGAS_ZH,
        variables=["document_chunk", "n", "existing_questions"],
        category="testset_generation",
        tags=_tags("testset", "ragas", "qa", "zh"),
        version=_FORMAL_VERSION,
    ),
)


def list_builtin_prompt_templates() -> list[BuiltinPromptTemplate]:
    return list(_BUILTIN_PROMPT_TEMPLATES)


__all__ = ["BuiltinPromptTemplate", "list_builtin_prompt_templates"]
