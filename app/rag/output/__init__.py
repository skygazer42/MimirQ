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
import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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
    mode: str = Field(default="faq", description="Output mode identifier")
    question: str = Field(description="The original question")
    answer: str = Field(description="Direct answer to the question")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score")
    related_questions: List[str] = Field(default_factory=list, description="Related questions")
    sources: List[str] = Field(default_factory=list, description="Source references")


class SummaryOutput(BaseModel):
    """Summary-style output for long content."""
    mode: str = Field(default="summary", description="Output mode identifier")
    title: str = Field(description="Summary title")
    summary: str = Field(description="Main summary text")
    key_points: List[str] = Field(default_factory=list, description="Key points")
    word_count: int = Field(default=0, description="Original content word count")
    sources: List[str] = Field(default_factory=list, description="Source references")


class ActionItem(BaseModel):
    """Single action item."""
    task: str = Field(description="Task description")
    priority: str = Field(default="medium", description="Priority level")
    assignee: Optional[str] = Field(default=None, description="Assigned person")
    deadline: Optional[str] = Field(default=None, description="Deadline")
    status: str = Field(default="pending", description="Status")


class ActionItemsOutput(BaseModel):
    """Action items extracted from content."""
    mode: str = Field(default="action_items", description="Output mode identifier")
    title: str = Field(description="Action items title")
    items: List[ActionItem] = Field(default_factory=list, description="List of action items")
    total_count: int = Field(default=0, description="Total action items")
    sources: List[str] = Field(default_factory=list, description="Source references")


class ComparisonItem(BaseModel):
    """Single comparison item."""
    aspect: str = Field(description="Comparison aspect")
    option_a: str = Field(description="First option value")
    option_b: str = Field(description="Second option value")
    winner: Optional[str] = Field(default=None, description="Winner if applicable")


class ComparisonOutput(BaseModel):
    """Comparison-style output."""
    mode: str = Field(default="comparison", description="Output mode identifier")
    title: str = Field(description="Comparison title")
    option_a_name: str = Field(description="First option name")
    option_b_name: str = Field(description="Second option name")
    comparisons: List[ComparisonItem] = Field(default_factory=list, description="Comparison items")
    conclusion: str = Field(description="Overall conclusion")
    sources: List[str] = Field(default_factory=list, description="Source references")


class Step(BaseModel):
    """Single step in a process."""
    number: int = Field(description="Step number")
    title: str = Field(description="Step title")
    description: str = Field(description="Step description")
    tips: List[str] = Field(default_factory=list, description="Tips for this step")


class StepByStepOutput(BaseModel):
    """Step-by-step guide output."""
    mode: str = Field(default="step_by_step", description="Output mode identifier")
    title: str = Field(description="Guide title")
    introduction: str = Field(default="", description="Introduction text")
    steps: List[Step] = Field(default_factory=list, description="List of steps")
    conclusion: str = Field(default="", description="Conclusion text")
    sources: List[str] = Field(default_factory=list, description="Source references")


class AnalysisSection(BaseModel):
    """Analysis section."""
    title: str = Field(description="Section title")
    content: str = Field(description="Section content")
    findings: List[str] = Field(default_factory=list, description="Key findings")


class AnalysisOutput(BaseModel):
    """Detailed analysis output."""
    mode: str = Field(default="analysis", description="Output mode identifier")
    title: str = Field(description="Analysis title")
    overview: str = Field(description="Overview text")
    sections: List[AnalysisSection] = Field(default_factory=list, description="Analysis sections")
    conclusions: List[str] = Field(default_factory=list, description="Conclusions")
    recommendations: List[str] = Field(default_factory=list, description="Recommendations")
    sources: List[str] = Field(default_factory=list, description="Source references")


class PlainOutput(BaseModel):
    """Plain text output."""
    mode: str = Field(default="plain", description="Output mode identifier")
    content: str = Field(description="Plain text content")
    sources: List[str] = Field(default_factory=list, description="Source references")


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


OUTPUT_SCHEMAS: Dict[OutputMode, Type[BaseModel]] = {
    OutputMode.FAQ: FAQOutput,
    OutputMode.SUMMARY: SummaryOutput,
    OutputMode.ACTION_ITEMS: ActionItemsOutput,
    OutputMode.COMPARISON: ComparisonOutput,
    OutputMode.STEP_BY_STEP: StepByStepOutput,
    OutputMode.ANALYSIS: AnalysisOutput,
    OutputMode.PLAIN: PlainOutput,
}


def get_schema_for_mode(mode: OutputMode) -> Type[BaseModel]:
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


# ============================================================================
# Mode Detection
# ============================================================================


MODE_KEYWORDS: Dict[OutputMode, List[str]] = {
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

    scores: Dict[OutputMode, int] = {mode: 0 for mode in OutputMode}

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

    def get_schema(self, mode: OutputMode) -> Type[BaseModel]:
        """Get the schema for a mode."""
        return get_schema_for_mode(mode)

    async def generate(
        self,
        query: str,
        context: str,
        mode: Optional[OutputMode] = None,
        sources: Optional[List[str]] = None,
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
            if hasattr(self.llm, 'with_structured_output'):
                structured_llm = self.llm.with_structured_output(schema)
                result = await structured_llm.ainvoke(prompt)
                if isinstance(result, BaseModel):
                    # Add sources if not already present
                    if hasattr(result, 'sources') and not result.sources:
                        result.sources = sources
                    return result

            # Fallback: parse JSON from response
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            return self._parse_response(content, schema, sources)

        except Exception as e:
            logger.error("Structured output generation failed: %s", e)
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
        schema: Type[BaseModel],
    ) -> str:
        """Build the prompt for structured output generation."""
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
        schema: Type[BaseModel],
        sources: List[str],
    ) -> StructuredOutput:
        """Parse LLM response into structured output."""
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
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse structured output: %s", e)
            return PlainOutput(content=content, sources=sources)


# ============================================================================
# Convenience Functions
# ============================================================================


async def get_structured_output(
    llm: Any,
    query: str,
    context: str,
    mode: Optional[OutputMode] = None,
    sources: Optional[List[str]] = None,
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
    mode: Optional[OutputMode] = None,
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

    schema = get_schema_for_mode(mode)

    try:
        data = json.loads(content)
        return schema.model_validate(data)
    except Exception:
        return PlainOutput(content=content)


def structured_output_to_markdown(output: StructuredOutput) -> str:
    """
    Convert structured output to markdown format.

    Args:
        output: Structured output

    Returns:
        Markdown string
    """
    if isinstance(output, FAQOutput):
        md = f"## {output.question}\n\n{output.answer}\n"
        if output.related_questions:
            md += "\n### Related Questions\n"
            for q in output.related_questions:
                md += f"- {q}\n"
        return md

    elif isinstance(output, SummaryOutput):
        md = f"## {output.title}\n\n{output.summary}\n"
        if output.key_points:
            md += "\n### Key Points\n"
            for point in output.key_points:
                md += f"- {point}\n"
        return md

    elif isinstance(output, ActionItemsOutput):
        md = f"## {output.title}\n\n"
        for item in output.items:
            priority_badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(item.priority, "⚪")
            md += f"- {priority_badge} **{item.task}**"
            if item.assignee:
                md += f" (@{item.assignee})"
            if item.deadline:
                md += f" - Due: {item.deadline}"
            md += "\n"
        return md

    elif isinstance(output, ComparisonOutput):
        md = f"## {output.title}\n\n"
        md += f"| Aspect | {output.option_a_name} | {output.option_b_name} |\n"
        md += "|--------|--------|--------|\n"
        for comp in output.comparisons:
            md += f"| {comp.aspect} | {comp.option_a} | {comp.option_b} |\n"
        md += f"\n**Conclusion:** {output.conclusion}\n"
        return md

    elif isinstance(output, StepByStepOutput):
        md = f"## {output.title}\n\n"
        if output.introduction:
            md += f"{output.introduction}\n\n"
        for step in output.steps:
            md += f"### Step {step.number}: {step.title}\n\n{step.description}\n"
            if step.tips:
                md += "\n**Tips:**\n"
                for tip in step.tips:
                    md += f"- {tip}\n"
            md += "\n"
        if output.conclusion:
            md += f"**Conclusion:** {output.conclusion}\n"
        return md

    elif isinstance(output, AnalysisOutput):
        md = f"## {output.title}\n\n{output.overview}\n\n"
        for section in output.sections:
            md += f"### {section.title}\n\n{section.content}\n"
            if section.findings:
                md += "\n**Findings:**\n"
                for finding in section.findings:
                    md += f"- {finding}\n"
            md += "\n"
        if output.conclusions:
            md += "### Conclusions\n"
            for c in output.conclusions:
                md += f"- {c}\n"
        if output.recommendations:
            md += "\n### Recommendations\n"
            for r in output.recommendations:
                md += f"- {r}\n"
        return md

    elif isinstance(output, PlainOutput):
        return output.content

    return str(output)
