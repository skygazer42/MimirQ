"""
Structured output module with Union type support.

Provides multiple output modes that the LLM can automatically select
based on the query type. Supports FAQ, Summary, ActionItems, and more.

Usage:
    from app.rag.output import get_structured_output, OutputMode

    # Let LLM choose the best output format
    result = await get_structured_output(llm, query, context)

    # Force a specific mode
    result = await get_structured_output(llm, query, context, mode=OutputMode.FAQ)
"""

import json
from enum import Enum
from typing import Any, Union

from pydantic import BaseModel, Field

from app.rag.core.logging import get_logger
from app.rag.llm.structured_output import (
    build_structured_output_instructions,
    parse_and_repair_structured_output,
)

logger = get_logger("rag.output")

_DESC_OUTPUT_MODE_IDENTIFIER = "Output mode identifier"
_DESC_SOURCE_REFERENCES = "Source references"


class OutputMode(str, Enum):
    """Available output modes."""

    AUTO = "auto"
    FAQ = "faq"
    SUMMARY = "summary"
    ACTION_ITEMS = "action_items"
    COMPARISON = "comparison"
    STEP_BY_STEP = "step_by_step"
    ANALYSIS = "analysis"
    PLAIN = "plain"


# ============================================================================
# Output Schema Definitions
# ============================================================================


class FAQOutput(BaseModel):
    """FAQ-style output with question and answer."""

    mode: str = Field(default="faq", description=_DESC_OUTPUT_MODE_IDENTIFIER)
    question: str = Field(description="The original question")
    answer: str = Field(description="Direct answer to the question")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score")
    related_questions: list[str] = Field(default_factory=list, description="Related questions")
    sources: list[str] = Field(default_factory=list, description=_DESC_SOURCE_REFERENCES)


class SummaryOutput(BaseModel):
    """Summary-style output for long content."""

    mode: str = Field(default="summary", description=_DESC_OUTPUT_MODE_IDENTIFIER)
    title: str = Field(description="Summary title")
    summary: str = Field(description="Main summary text")
    key_points: list[str] = Field(default_factory=list, description="Key points")
    word_count: int = Field(default=0, description="Original content word count")
    sources: list[str] = Field(default_factory=list, description=_DESC_SOURCE_REFERENCES)


class ActionItem(BaseModel):
    """Single action item."""

    task: str = Field(description="Task description")
    priority: str = Field(default="medium", description="Priority level")
    assignee: str | None = Field(default=None, description="Assigned person")
    deadline: str | None = Field(default=None, description="Deadline")
    status: str = Field(default="pending", description="Status")


class ActionItemsOutput(BaseModel):
    """Action items extracted from content."""

    mode: str = Field(default="action_items", description=_DESC_OUTPUT_MODE_IDENTIFIER)
    title: str = Field(description="Action items title")
    items: list[ActionItem] = Field(default_factory=list, description="List of action items")
    total_count: int = Field(default=0, description="Total action items")
    sources: list[str] = Field(default_factory=list, description=_DESC_SOURCE_REFERENCES)


class ComparisonItem(BaseModel):
    """Single comparison item."""

    aspect: str = Field(description="Comparison aspect")
    option_a: str = Field(description="First option value")
    option_b: str = Field(description="Second option value")
    winner: str | None = Field(default=None, description="Winner if applicable")


class ComparisonOutput(BaseModel):
    """Comparison-style output."""

    mode: str = Field(default="comparison", description=_DESC_OUTPUT_MODE_IDENTIFIER)
    title: str = Field(description="Comparison title")
    option_a_name: str = Field(description="First option name")
    option_b_name: str = Field(description="Second option name")
    comparisons: list[ComparisonItem] = Field(default_factory=list, description="Comparison items")
    conclusion: str = Field(description="Overall conclusion")
    sources: list[str] = Field(default_factory=list, description=_DESC_SOURCE_REFERENCES)


class Step(BaseModel):
    """Single step in a process."""

    number: int = Field(description="Step number")
    title: str = Field(description="Step title")
    description: str = Field(description="Step description")
    tips: list[str] = Field(default_factory=list, description="Tips for this step")


class StepByStepOutput(BaseModel):
    """Step-by-step guide output."""

    mode: str = Field(default="step_by_step", description=_DESC_OUTPUT_MODE_IDENTIFIER)
    title: str = Field(description="Guide title")
    introduction: str = Field(default="", description="Introduction text")
    steps: list[Step] = Field(default_factory=list, description="List of steps")
    conclusion: str = Field(default="", description="Conclusion text")
    sources: list[str] = Field(default_factory=list, description=_DESC_SOURCE_REFERENCES)


class AnalysisSection(BaseModel):
    """Analysis section."""

    title: str = Field(description="Section title")
    content: str = Field(description="Section content")
    findings: list[str] = Field(default_factory=list, description="Key findings")


class AnalysisOutput(BaseModel):
    """Detailed analysis output."""

    mode: str = Field(default="analysis", description=_DESC_OUTPUT_MODE_IDENTIFIER)
    title: str = Field(description="Analysis title")
    overview: str = Field(description="Overview text")
    sections: list[AnalysisSection] = Field(default_factory=list, description="Analysis sections")
    conclusions: list[str] = Field(default_factory=list, description="Conclusions")
    recommendations: list[str] = Field(default_factory=list, description="Recommendations")
    sources: list[str] = Field(default_factory=list, description=_DESC_SOURCE_REFERENCES)


class PlainOutput(BaseModel):
    """Plain text output."""

    mode: str = Field(default="plain", description=_DESC_OUTPUT_MODE_IDENTIFIER)
    content: str = Field(description="Plain text content")
    sources: list[str] = Field(default_factory=list, description=_DESC_SOURCE_REFERENCES)


# Union type for all outputs
StructuredOutput = Union[
    FAQOutput,
    SummaryOutput,
    ActionItemsOutput,
    ComparisonOutput,
    StepByStepOutput,
    AnalysisOutput,
    PlainOutput,
]


# ============================================================================
# Output Schema Registry
# ============================================================================


OUTPUT_SCHEMAS: dict[OutputMode, type[BaseModel]] = {
    OutputMode.FAQ: FAQOutput,
    OutputMode.SUMMARY: SummaryOutput,
    OutputMode.ACTION_ITEMS: ActionItemsOutput,
    OutputMode.COMPARISON: ComparisonOutput,
    OutputMode.STEP_BY_STEP: StepByStepOutput,
    OutputMode.ANALYSIS: AnalysisOutput,
    OutputMode.PLAIN: PlainOutput,
}


def get_schema_for_mode(mode: OutputMode) -> type[BaseModel]:
    """Get the schema class for a given mode."""
    return OUTPUT_SCHEMAS.get(mode, PlainOutput)


def get_all_schemas_description() -> str:
    """Get description of all output schemas for prompts."""
    descriptions = []
    for mode, schema in OUTPUT_SCHEMAS.items():
        if mode == OutputMode.AUTO:
            continue
        desc = f"- {mode.value}: {schema.__doc__ or 'No description'}"
        descriptions.append(desc)
    return "\n".join(descriptions)


def _shared_preset_for_mode(mode: OutputMode | None) -> str | None:
    if mode == OutputMode.FAQ:
        return "faq"
    if mode == OutputMode.SUMMARY:
        return "summary"
    if mode == OutputMode.ACTION_ITEMS:
        return "action_items"
    return None


def _adapt_shared_payload(
    *,
    mode: OutputMode,
    payload: dict[str, Any],
    query: str,
    context: str,
    sources: list[str],
) -> StructuredOutput:
    if mode == OutputMode.FAQ:
        qa_pairs = list(payload.get("qa_pairs") or [])
        related_questions = [
            str(item.get("question") or "").strip()
            for item in qa_pairs[1:]
            if isinstance(item, dict) and str(item.get("question") or "").strip()
        ]
        return FAQOutput(
            question=str(query or "").strip(),
            answer=str(payload.get("answer") or "").strip(),
            confidence=0.0,
            related_questions=related_questions,
            sources=list(sources or []),
        )

    if mode == OutputMode.SUMMARY:
        summary = str(payload.get("summary") or payload.get("answer") or "").strip()
        bullets = [str(item or "").strip() for item in payload.get("bullets") or [] if str(item or "").strip()]
        return SummaryOutput(
            title=str(query or "").strip() or "Summary",
            summary=summary,
            key_points=bullets,
            word_count=len(str(context or "").split()),
            sources=list(sources or []),
        )

    if mode == OutputMode.ACTION_ITEMS:
        raw_actions = list(payload.get("actions") or [])
        items: list[ActionItem] = []
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            task = str(item.get("item") or item.get("task") or "").strip()
            if not task:
                continue
            items.append(
                ActionItem(
                    task=task,
                    priority=str(item.get("priority") or "medium").strip() or "medium",
                    assignee=(str(item.get("owner") or item.get("assignee") or "").strip() or None),
                    deadline=(str(item.get("due") or item.get("deadline") or "").strip() or None),
                    status=str(item.get("status") or "pending").strip() or "pending",
                )
            )
        return ActionItemsOutput(
            title=str(query or "").strip() or "Action Items",
            items=items,
            total_count=len(items),
            sources=list(sources or []),
        )

    return PlainOutput(content=str(payload.get("answer") or "").strip(), sources=list(sources or []))


# ============================================================================
# Mode Detection
# ============================================================================


MODE_KEYWORDS: dict[OutputMode, list[str]] = {
    OutputMode.FAQ: ["什么是", "如何", "为什么", "怎么", "what is", "how to", "why", "explain"],
    OutputMode.SUMMARY: ["总结", "概括", "摘要", "summarize", "summary", "overview"],
    OutputMode.ACTION_ITEMS: ["待办", "任务", "行动项", "action items", "todo", "tasks"],
    OutputMode.COMPARISON: ["比较", "对比", "区别", "compare", "vs", "versus", "difference"],
    OutputMode.STEP_BY_STEP: ["步骤", "流程", "教程", "指南", "steps", "guide", "tutorial", "how-to"],
    OutputMode.ANALYSIS: ["分析", "评估", "研究", "analyze", "analysis", "evaluate", "assess"],
}


def detect_output_mode(query: str) -> OutputMode:
    """
    Detect the best output mode based on query keywords.

    Args:
        query: User query

    Returns:
        Detected OutputMode
    """
    query_lower = query.lower()

    scores: dict[OutputMode, int] = dict.fromkeys(OutputMode, 0)

    for mode, keywords in MODE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in query_lower:
                scores[mode] += 1

    # Find mode with highest score
    best_mode = max(scores, key=scores.get)
    if scores[best_mode] > 0:
        return best_mode

    # Default to FAQ for questions, plain for statements
    if any(q in query_lower for q in ["?", "？", "吗", "呢"]):
        return OutputMode.FAQ

    return OutputMode.PLAIN


# ============================================================================
# Structured Output Generator
# ============================================================================


class StructuredOutputGenerator:
    """
    Generator for structured outputs.

    Handles mode detection, schema selection, and output parsing.
    """

    def __init__(self, llm: Any = None):
        """
        Initialize the generator.

        Args:
            llm: Language model instance
        """
        self.llm = llm

    def set_llm(self, llm: Any) -> "StructuredOutputGenerator":
        """Set the language model."""
        self.llm = llm
        return self

    def detect_mode(self, query: str) -> OutputMode:
        """Detect the best output mode for a query."""
        return detect_output_mode(query)

    def get_schema(self, mode: OutputMode) -> type[BaseModel]:
        """Get the schema for a mode."""
        return get_schema_for_mode(mode)

    async def generate(
        self,
        query: str,
        context: str,
        mode: OutputMode | None = None,
        sources: list[str] | None = None,
    ) -> StructuredOutput:
        """
        Generate structured output.

        Args:
            query: User query
            context: Context from retrieval
            mode: Output mode (auto-detected if None)
            sources: Source references

        Returns:
            Structured output object
        """
        if self.llm is None:
            raise ValueError("LLM not configured")

        # Detect mode if not specified
        if mode is None or mode == OutputMode.AUTO:
            mode = self.detect_mode(query)

        schema = self.get_schema(mode)
        sources = sources or []

        # Build prompt
        prompt = self._build_prompt(query, context, mode, schema)

        try:
            # Try using with_structured_output if available
            if hasattr(self.llm, "with_structured_output") and _shared_preset_for_mode(mode) is None:
                structured_llm = self.llm.with_structured_output(schema)
                result = await structured_llm.ainvoke(prompt)
                if isinstance(result, BaseModel):
                    # Add sources if not already present
                    if hasattr(result, "sources") and not result.sources:
                        result.sources = sources
                    return result

            # Fallback: parse JSON from response
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return self._parse_response(content, mode, schema, sources, query=query, context=context)

        except Exception as e:
            logger.exception("Structured output generation failed: %s", e)
            # Return plain output as fallback
            return PlainOutput(
                content=f"Error generating structured output: {e}",
                sources=sources,
            )

    def _build_prompt(
        self,
        query: str,
        context: str,
        mode: OutputMode,
        schema: type[BaseModel],
    ) -> str:
        """Build the prompt for structured output generation."""
        shared_preset = _shared_preset_for_mode(mode)
        if shared_preset:
            return (
                "Based on the context provided, answer the query in a structured format.\n\n"
                f"Context:\n{context}\n\n"
                f"Query: {query}\n\n"
                f"{build_structured_output_instructions(shared_preset)}"
            )

        schema_json = schema.model_json_schema()
        schema_str = json.dumps(schema_json, indent=2, ensure_ascii=False)

        return f"""Based on the context provided, answer the query in a structured format.

Context:
{context}

Query: {query}

Output Mode: {mode.value}

You must respond with a valid JSON object matching this schema:
{schema_str}

Respond with ONLY the JSON object, no additional text.

JSON Response:"""

    def _parse_response(
        self,
        content: str,
        mode: OutputMode,
        schema: type[BaseModel],
        sources: list[str],
        query: str = "",
        context: str = "",
    ) -> StructuredOutput:
        """Parse LLM response into structured output."""
        shared_preset = _shared_preset_for_mode(mode)
        if shared_preset:
            payload, _meta = parse_and_repair_structured_output(
                content,
                preset=shared_preset,
                fallback_answer="",
                fallback_citations=[],
            )
            return _adapt_shared_payload(
                mode=mode,
                payload=payload,
                query=query,
                context=context,
                sources=sources,
            )

        # Try to extract JSON from response
        content = content.strip()

        # Remove markdown code blocks if present
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

        try:
            data = json.loads(content)
            if "sources" not in data or not data["sources"]:
                data["sources"] = sources
            return schema.model_validate(data)
        except Exception as e:
            logger.warning("Failed to parse structured output: %s", e)
            return PlainOutput(content=content, sources=sources)


# ============================================================================
# Convenience Functions
# ============================================================================


async def get_structured_output(
    llm: Any,
    query: str,
    context: str,
    mode: OutputMode | None = None,
    sources: list[str] | None = None,
) -> StructuredOutput:
    """
    Generate structured output from query and context.

    Args:
        llm: Language model
        query: User query
        context: Retrieved context
        mode: Output mode (auto if None)
        sources: Source references

    Returns:
        Structured output
    """
    generator = StructuredOutputGenerator(llm)
    return await generator.generate(query, context, mode, sources)


def parse_structured_output(
    content: str,
    mode: OutputMode | None = None,
) -> StructuredOutput:
    """
    Parse a string into structured output.

    Args:
        content: Content to parse
        mode: Expected mode

    Returns:
        Structured output
    """
    if mode is None:
        mode = OutputMode.PLAIN

    shared_preset = _shared_preset_for_mode(mode)
    if shared_preset:
        payload, _meta = parse_and_repair_structured_output(
            content,
            preset=shared_preset,
            fallback_answer="",
            fallback_citations=[],
        )
        default_query = ""
        if mode == OutputMode.SUMMARY:
            default_query = "Summary"
        elif mode == OutputMode.ACTION_ITEMS:
            default_query = "Action Items"
        return _adapt_shared_payload(
            mode=mode,
            payload=payload,
            query=default_query,
            context="",
            sources=[],
        )

    schema = get_schema_for_mode(mode)

    try:
        data = json.loads(content)
        return schema.model_validate(data)
    except Exception:
        return PlainOutput(content=content)


_ACTION_ITEM_PRIORITY_BADGES = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def _render_faq_output(output: FAQOutput) -> str:
    parts = [f"## {output.question}\n\n{output.answer}\n"]
    if output.related_questions:
        parts.append("\n### Related Questions\n")
        parts.extend(f"- {question}\n" for question in output.related_questions)
    return "".join(parts)


def _render_summary_output(output: SummaryOutput) -> str:
    parts = [f"## {output.title}\n\n{output.summary}\n"]
    if output.key_points:
        parts.append("\n### Key Points\n")
        parts.extend(f"- {point}\n" for point in output.key_points)
    return "".join(parts)


def _render_action_items_output(output: ActionItemsOutput) -> str:
    parts = [f"## {output.title}\n\n"]
    for item in output.items:
        badge = _ACTION_ITEM_PRIORITY_BADGES.get(item.priority, "⚪")
        line = f"- {badge} **{item.task}**"
        if item.assignee:
            line += f" (@{item.assignee})"
        if item.deadline:
            line += f" - Due: {item.deadline}"
        parts.append(f"{line}\n")
    return "".join(parts)


def _render_comparison_output(output: ComparisonOutput) -> str:
    parts = [
        f"## {output.title}\n\n",
        f"| Aspect | {output.option_a_name} | {output.option_b_name} |\n",
        "|--------|--------|--------|\n",
    ]
    parts.extend(
        f"| {comparison.aspect} | {comparison.option_a} | {comparison.option_b} |\n"
        for comparison in output.comparisons
    )
    parts.append(f"\n**Conclusion:** {output.conclusion}\n")
    return "".join(parts)


def _render_step_by_step_output(output: StepByStepOutput) -> str:
    parts = [f"## {output.title}\n\n"]
    if output.introduction:
        parts.append(f"{output.introduction}\n\n")
    for step in output.steps:
        parts.append(f"### Step {step.number}: {step.title}\n\n{step.description}\n")
        if step.tips:
            parts.append("\n**Tips:**\n")
            parts.extend(f"- {tip}\n" for tip in step.tips)
        parts.append("\n")
    if output.conclusion:
        parts.append(f"**Conclusion:** {output.conclusion}\n")
    return "".join(parts)


def _render_analysis_output(output: AnalysisOutput) -> str:
    parts = [f"## {output.title}\n\n{output.overview}\n\n"]
    for section in output.sections:
        parts.append(f"### {section.title}\n\n{section.content}\n")
        if section.findings:
            parts.append("\n**Findings:**\n")
            parts.extend(f"- {finding}\n" for finding in section.findings)
        parts.append("\n")
    if output.conclusions:
        parts.append("### Conclusions\n")
        parts.extend(f"- {conclusion}\n" for conclusion in output.conclusions)
    if output.recommendations:
        parts.append("\n### Recommendations\n")
        parts.extend(f"- {recommendation}\n" for recommendation in output.recommendations)
    return "".join(parts)


def structured_output_to_markdown(output: StructuredOutput) -> str:
    """
    Convert structured output to markdown format.

    Args:
        output: Structured output

    Returns:
        Markdown string
    """
    if isinstance(output, FAQOutput):
        return _render_faq_output(output)
    if isinstance(output, SummaryOutput):
        return _render_summary_output(output)
    if isinstance(output, ActionItemsOutput):
        return _render_action_items_output(output)
    if isinstance(output, ComparisonOutput):
        return _render_comparison_output(output)
    if isinstance(output, StepByStepOutput):
        return _render_step_by_step_output(output)
    if isinstance(output, AnalysisOutput):
        return _render_analysis_output(output)
    if isinstance(output, PlainOutput):
        return output.content

    return str(output)
