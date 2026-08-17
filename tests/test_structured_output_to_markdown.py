from app.rag.output import (
    ActionItem,
    ActionItemsOutput,
    AnalysisOutput,
    AnalysisSection,
    ComparisonItem,
    ComparisonOutput,
    FAQOutput,
    PlainOutput,
    Step,
    StepByStepOutput,
    SummaryOutput,
    structured_output_to_markdown,
)


def test_structured_output_to_markdown_renders_faq_with_related_questions_in_order() -> None:
    output = FAQOutput(
        question="How do I reset it?",
        answer="Use `reset --hard`? No.",
        related_questions=["What if it hangs?", "Pipe | stays literal"],
    )

    assert structured_output_to_markdown(output) == (
        "## How do I reset it?\n\n"
        "Use `reset --hard`? No.\n"
        "\n### Related Questions\n"
        "- What if it hangs?\n"
        "- Pipe | stays literal\n"
    )


def test_structured_output_to_markdown_omits_empty_faq_related_questions_section() -> None:
    output = FAQOutput(question="", answer="", related_questions=[])

    assert structured_output_to_markdown(output) == "## \n\n\n"


def test_structured_output_to_markdown_renders_summary_key_points_in_order() -> None:
    output = SummaryOutput(
        title="Weekly Summary",
        summary="A short summary with *markdown*.",
        key_points=["First point", "Second | point"],
    )

    assert structured_output_to_markdown(output) == (
        "## Weekly Summary\n\nA short summary with *markdown*.\n\n### Key Points\n- First point\n- Second | point\n"
    )


def test_structured_output_to_markdown_omits_empty_summary_key_points_section() -> None:
    output = SummaryOutput(title="T", summary="", key_points=[])

    assert structured_output_to_markdown(output) == "## T\n\n\n"


def test_structured_output_to_markdown_renders_action_items_badges_and_optional_fields() -> None:
    output = ActionItemsOutput(
        title="Tasks",
        items=[
            ActionItem(task="Ship feature", priority="high", assignee="alice", deadline="2026-08-20"),
            ActionItem(task="Review docs", priority="medium", assignee=None, deadline="soon"),
            ActionItem(task="Quiet item", priority="low", assignee="", deadline=""),
            ActionItem(task="Custom priority", priority="urgent", assignee="bob", deadline=None),
        ],
    )

    assert structured_output_to_markdown(output) == (
        "## Tasks\n\n"
        "- 🔴 **Ship feature** (@alice) - Due: 2026-08-20\n"
        "- 🟡 **Review docs** - Due: soon\n"
        "- 🟢 **Quiet item**\n"
        "- ⚪ **Custom priority** (@bob)\n"
    )


def test_structured_output_to_markdown_renders_empty_action_items_header_only() -> None:
    output = ActionItemsOutput(title="Tasks", items=[])

    assert structured_output_to_markdown(output) == "## Tasks\n\n"


def test_structured_output_to_markdown_renders_comparison_table_without_escaping() -> None:
    output = ComparisonOutput(
        title="Pick one",
        option_a_name="Alpha",
        option_b_name="Beta",
        comparisons=[
            ComparisonItem(aspect="Speed | latency", option_a="Fast", option_b="Steady"),
            ComparisonItem(aspect="Cost", option_a="$10", option_b="$20"),
        ],
        conclusion="Alpha wins.",
    )

    assert structured_output_to_markdown(output) == (
        "## Pick one\n\n"
        "| Aspect | Alpha | Beta |\n"
        "|--------|--------|--------|\n"
        "| Speed | latency | Fast | Steady |\n"
        "| Cost | $10 | $20 |\n"
        "\n**Conclusion:** Alpha wins.\n"
    )


def test_structured_output_to_markdown_renders_comparison_with_no_rows() -> None:
    output = ComparisonOutput(
        title="Empty compare",
        option_a_name="A",
        option_b_name="B",
        comparisons=[],
        conclusion="Need more data.",
    )

    assert structured_output_to_markdown(output) == (
        "## Empty compare\n\n| Aspect | A | B |\n|--------|--------|--------|\n\n**Conclusion:** Need more data.\n"
    )


def test_structured_output_to_markdown_renders_steps_with_optional_intro_conclusion_and_tips() -> None:
    output = StepByStepOutput(
        title="Install",
        introduction="Start here.",
        steps=[
            Step(number=1, title="Download", description="Get the file.", tips=["Use wifi", "Check hash"]),
            Step(number=2, title="Run", description="Execute it.", tips=[]),
        ],
        conclusion="Done.",
    )

    assert structured_output_to_markdown(output) == (
        "## Install\n\n"
        "Start here.\n\n"
        "### Step 1: Download\n\n"
        "Get the file.\n"
        "\n**Tips:**\n"
        "- Use wifi\n"
        "- Check hash\n"
        "\n"
        "### Step 2: Run\n\n"
        "Execute it.\n"
        "\n"
        "**Conclusion:** Done.\n"
    )


def test_structured_output_to_markdown_renders_steps_without_optional_sections() -> None:
    output = StepByStepOutput(title="Bare", introduction="", steps=[], conclusion="")

    assert structured_output_to_markdown(output) == "## Bare\n\n"


def test_structured_output_to_markdown_renders_analysis_sections_findings_and_tail_sections() -> None:
    output = AnalysisOutput(
        title="Analysis",
        overview="Overview first.",
        sections=[
            AnalysisSection(title="Signals", content="Things happened.", findings=["One", "Two | still raw"]),
            AnalysisSection(title="Noise", content="Nothing else.", findings=[]),
        ],
        conclusions=["Ship it"],
        recommendations=["Monitor closely"],
    )

    assert structured_output_to_markdown(output) == (
        "## Analysis\n\n"
        "Overview first.\n\n"
        "### Signals\n\n"
        "Things happened.\n"
        "\n**Findings:**\n"
        "- One\n"
        "- Two | still raw\n"
        "\n"
        "### Noise\n\n"
        "Nothing else.\n"
        "\n"
        "### Conclusions\n"
        "- Ship it\n"
        "\n### Recommendations\n"
        "- Monitor closely\n"
    )


def test_structured_output_to_markdown_renders_analysis_without_optional_lists() -> None:
    output = AnalysisOutput(title="A", overview="", sections=[], conclusions=[], recommendations=[])

    assert structured_output_to_markdown(output) == "## A\n\n\n\n"


def test_structured_output_to_markdown_returns_plain_content_verbatim() -> None:
    output = PlainOutput(content="Already markdown\n- keep it")

    assert structured_output_to_markdown(output) == "Already markdown\n- keep it"


def test_structured_output_to_markdown_falls_back_to_string_representation() -> None:
    class UnknownOutput:
        def __str__(self) -> str:
            return "fallback-render"

    assert structured_output_to_markdown(UnknownOutput()) == "fallback-render"  # type: ignore[arg-type]
