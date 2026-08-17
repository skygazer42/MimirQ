"""
Agent evaluation framework for RAG quality assessment.

Provides comprehensive evaluation capabilities including:
- Response quality evaluation
- Retrieval relevance scoring
- Trajectory analysis for agent workflows
- Benchmark integration

Usage:
    from app.rag.evaluation.agent_evals import RAGEvaluator

    evaluator = RAGEvaluator()
    result = await evaluator.evaluate(
        question="What is Python?",
        answer="Python is a programming language.",
        contexts=["Python is a high-level programming language..."],
    )
"""

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.evaluation.agent_evals")


# Configuration
AGENT_EVALS_ENABLED = getattr(settings, "AGENT_EVALS_ENABLED", False)


class MetricType(str, Enum):
    """Types of evaluation metrics."""

    FAITHFULNESS = "faithfulness"
    RELEVANCE = "relevance"
    CONTEXT_PRECISION = "context_precision"
    CONTEXT_RECALL = "context_recall"
    ANSWER_CORRECTNESS = "answer_correctness"
    ANSWER_SIMILARITY = "answer_similarity"
    HARMFULNESS = "harmfulness"
    TRAJECTORY = "trajectory"


@dataclass
class EvaluationScore:
    """Score for a single metric."""

    metric: MetricType
    score: float  # 0.0 to 1.0
    explanation: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Check if score passes threshold (>= 0.7)."""
        return self.score >= 0.7


@dataclass
class EvaluationResult:
    """Complete evaluation result."""

    question: str
    answer: str
    scores: list[EvaluationScore] = field(default_factory=list)
    overall_score: float = 0.0
    passed: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_score(self, metric: MetricType) -> EvaluationScore | None:
        """Get score for a specific metric."""
        for score in self.scores:
            if score.metric == metric:
                return score
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "question": self.question,
            "answer": self.answer,
            "scores": [
                {
                    "metric": s.metric.value,
                    "score": s.score,
                    "explanation": s.explanation,
                    "details": s.details,
                }
                for s in self.scores
            ],
            "overall_score": self.overall_score,
            "passed": self.passed,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ============================================================================
# Base Evaluator
# ============================================================================


class BaseEvaluator(ABC):
    """Base class for evaluators."""

    @property
    @abstractmethod
    def metric(self) -> MetricType:
        """The metric this evaluator measures."""
        pass

    @abstractmethod
    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str] | None = None,
        ground_truth: str | None = None,
        **kwargs,
    ) -> EvaluationScore:
        """
        Evaluate a response.

        Args:
            question: The question asked
            answer: The generated answer
            contexts: Retrieved contexts
            ground_truth: Expected answer
            **kwargs: Additional arguments

        Returns:
            Evaluation score
        """
        pass


# ============================================================================
# Faithfulness Evaluator
# ============================================================================


class FaithfulnessEvaluator(BaseEvaluator):
    """
    Evaluates if the answer is faithful to the provided contexts.

    Checks for hallucinations and unsupported claims.
    """

    def __init__(self, llm: Any = None):
        self.llm = llm

    @property
    def metric(self) -> MetricType:
        return MetricType.FAITHFULNESS

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str] | None = None,
        ground_truth: str | None = None,
        **kwargs,
    ) -> EvaluationScore:
        if not contexts:
            return EvaluationScore(
                metric=self.metric,
                score=0.0,
                explanation="No contexts provided",
            )

        if self.llm is None:
            # Simple heuristic evaluation
            return self._heuristic_evaluate(answer, contexts)

        return await self._llm_evaluate(question, answer, contexts)

    def _heuristic_evaluate(
        self,
        answer: str,
        contexts: list[str],
    ) -> EvaluationScore:
        """Simple heuristic-based faithfulness check."""
        combined_context = " ".join(contexts).lower()
        answer_words = set(answer.lower().split())

        # Check word overlap
        context_words = set(combined_context.split())
        overlap = len(answer_words & context_words)
        total = len(answer_words)

        if total == 0:
            score = 0.0
        else:
            score = min(1.0, overlap / (total * 0.5))

        return EvaluationScore(
            metric=self.metric,
            score=score,
            explanation=f"Word overlap: {overlap}/{total}",
            details={"overlap": overlap, "total_words": total},
        )

    async def _llm_evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str],
    ) -> EvaluationScore:
        """LLM-based faithfulness evaluation."""
        prompt = f"""Evaluate if the following answer is faithful to the provided contexts.

Question: {question}

Contexts:
{chr(10).join(f"- {c[:500]}" for c in contexts)}

Answer: {answer}

Rate the faithfulness from 0 to 1:
- 1.0: Completely faithful, all claims supported by contexts
- 0.7: Mostly faithful, minor unsupported details
- 0.5: Partially faithful, some claims not supported
- 0.3: Mostly unfaithful, major claims unsupported
- 0.0: Completely unfaithful or hallucinated

Respond with JSON: {{"score": <float>, "explanation": "<string>"}}
"""
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            result = json.loads(content)
            return EvaluationScore(
                metric=self.metric,
                score=float(result.get("score", 0.5)),
                explanation=result.get("explanation", ""),
            )
        except Exception as e:
            logger.exception("LLM faithfulness evaluation failed: %s", e)
            return self._heuristic_evaluate(answer, contexts)


# ============================================================================
# Relevance Evaluator
# ============================================================================


class RelevanceEvaluator(BaseEvaluator):
    """
    Evaluates if the answer is relevant to the question.
    """

    def __init__(self, llm: Any = None):
        self.llm = llm

    @property
    def metric(self) -> MetricType:
        return MetricType.RELEVANCE

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str] | None = None,
        ground_truth: str | None = None,
        **kwargs,
    ) -> EvaluationScore:
        if self.llm is None:
            return self._heuristic_evaluate(question, answer)

        return await self._llm_evaluate(question, answer)

    def _heuristic_evaluate(
        self,
        question: str,
        answer: str,
    ) -> EvaluationScore:
        """Simple heuristic relevance check."""
        q_words = set(question.lower().split())
        a_words = set(answer.lower().split())

        # Remove common words
        common = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "what",
            "how",
            "why",
            "when",
            "where",
            "who",
            "的",
            "是",
            "在",
            "有",
            "和",
        }
        q_words -= common
        a_words -= common

        overlap = len(q_words & a_words)
        if len(q_words) == 0:
            score = 0.5
        else:
            score = min(1.0, overlap / len(q_words) + 0.3)

        return EvaluationScore(
            metric=self.metric,
            score=score,
            explanation=f"Keyword overlap: {overlap}",
        )

    async def _llm_evaluate(
        self,
        question: str,
        answer: str,
    ) -> EvaluationScore:
        """LLM-based relevance evaluation."""
        prompt = f"""Evaluate if the answer is relevant to the question.

Question: {question}

Answer: {answer}

Rate the relevance from 0 to 1:
- 1.0: Directly answers the question completely
- 0.7: Answers most of the question
- 0.5: Partially relevant
- 0.3: Tangentially related
- 0.0: Completely irrelevant

Respond with JSON: {{"score": <float>, "explanation": "<string>"}}
"""
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            result = json.loads(content)
            return EvaluationScore(
                metric=self.metric,
                score=float(result.get("score", 0.5)),
                explanation=result.get("explanation", ""),
            )
        except Exception as e:
            logger.exception("LLM relevance evaluation failed: %s", e)
            return self._heuristic_evaluate(question, answer)


# ============================================================================
# Context Precision Evaluator
# ============================================================================


class ContextPrecisionEvaluator(BaseEvaluator):
    """
    Evaluates precision of retrieved contexts.
    """

    def __init__(self, llm: Any = None):
        self.llm = llm

    @property
    def metric(self) -> MetricType:
        return MetricType.CONTEXT_PRECISION

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str] | None = None,
        ground_truth: str | None = None,
        **kwargs,
    ) -> EvaluationScore:
        if not contexts:
            return EvaluationScore(
                metric=self.metric,
                score=0.0,
                explanation="No contexts provided",
            )

        relevant_count = 0
        for ctx in contexts:
            if self._is_relevant(question, ctx):
                relevant_count += 1

        precision = relevant_count / len(contexts) if contexts else 0

        return EvaluationScore(
            metric=self.metric,
            score=precision,
            explanation=f"{relevant_count}/{len(contexts)} contexts relevant",
            details={"relevant": relevant_count, "total": len(contexts)},
        )

    def _is_relevant(self, question: str, context: str) -> bool:
        """Check if context is relevant to question."""
        q_words = set(question.lower().split())
        c_words = set(context.lower().split())

        common = {"the", "a", "an", "is", "are", "was", "were", "what", "how", "why", "的", "是", "在", "有"}
        q_words -= common

        overlap = len(q_words & c_words)
        return overlap >= len(q_words) * 0.3


# ============================================================================
# Answer Correctness Evaluator
# ============================================================================


class AnswerCorrectnessEvaluator(BaseEvaluator):
    """
    Evaluates correctness against ground truth.
    """

    def __init__(self, llm: Any = None):
        self.llm = llm

    @property
    def metric(self) -> MetricType:
        return MetricType.ANSWER_CORRECTNESS

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str] | None = None,
        ground_truth: str | None = None,
        **kwargs,
    ) -> EvaluationScore:
        if not ground_truth:
            return EvaluationScore(
                metric=self.metric,
                score=0.5,
                explanation="No ground truth provided",
            )

        if self.llm is None:
            return self._heuristic_evaluate(answer, ground_truth)

        return await self._llm_evaluate(question, answer, ground_truth)

    def _heuristic_evaluate(
        self,
        answer: str,
        ground_truth: str,
    ) -> EvaluationScore:
        """Simple heuristic correctness check."""
        a_words = set(answer.lower().split())
        g_words = set(ground_truth.lower().split())

        intersection = len(a_words & g_words)
        union = len(a_words | g_words)

        score = intersection / union if union > 0 else 0

        return EvaluationScore(
            metric=self.metric,
            score=score,
            explanation=f"Jaccard similarity: {score:.2f}",
        )

    async def _llm_evaluate(
        self,
        question: str,
        answer: str,
        ground_truth: str,
    ) -> EvaluationScore:
        """LLM-based correctness evaluation."""
        prompt = f"""Compare the answer with the ground truth.

Question: {question}

Generated Answer: {answer}

Ground Truth: {ground_truth}

Rate the correctness from 0 to 1:
- 1.0: Semantically equivalent
- 0.7: Mostly correct with minor differences
- 0.5: Partially correct
- 0.3: Mostly incorrect
- 0.0: Completely wrong

Respond with JSON: {{"score": <float>, "explanation": "<string>"}}
"""
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            result = json.loads(content)
            return EvaluationScore(
                metric=self.metric,
                score=float(result.get("score", 0.5)),
                explanation=result.get("explanation", ""),
            )
        except Exception as e:
            logger.exception("LLM correctness evaluation failed: %s", e)
            return self._heuristic_evaluate(answer, ground_truth)


# ============================================================================
# Trajectory Evaluator
# ============================================================================


@dataclass
class TrajectoryStep:
    """A step in an agent trajectory."""

    action: str
    observation: str
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TrajectoryEvaluator(BaseEvaluator):
    """
    Evaluates agent trajectory quality.
    """

    @property
    def metric(self) -> MetricType:
        return MetricType.TRAJECTORY

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str] | None = None,
        ground_truth: str | None = None,
        trajectory: list[TrajectoryStep] | None = None,
        **kwargs,
    ) -> EvaluationScore:
        if not trajectory:
            return EvaluationScore(
                metric=self.metric,
                score=0.5,
                explanation="No trajectory provided",
            )

        # Evaluate trajectory properties
        efficiency_score = self._evaluate_efficiency(trajectory)
        coherence_score = self._evaluate_coherence(trajectory)
        completeness_score = self._evaluate_completeness(trajectory, question)

        overall = (efficiency_score + coherence_score + completeness_score) / 3

        return EvaluationScore(
            metric=self.metric,
            score=overall,
            explanation=(
                f"Efficiency: {efficiency_score:.2f}, Coherence: {coherence_score:.2f}, "
                f"Completeness: {completeness_score:.2f}"
            ),
            details={
                "efficiency": efficiency_score,
                "coherence": coherence_score,
                "completeness": completeness_score,
                "step_count": len(trajectory),
            },
        )

    def _evaluate_efficiency(self, trajectory: list[TrajectoryStep]) -> float:
        """Evaluate trajectory efficiency (fewer steps = better)."""
        step_count = len(trajectory)
        if step_count <= 3:
            return 1.0
        elif step_count <= 5:
            return 0.8
        elif step_count <= 8:
            return 0.6
        elif step_count <= 12:
            return 0.4
        else:
            return 0.2

    def _evaluate_coherence(self, trajectory: list[TrajectoryStep]) -> float:
        """Evaluate if steps are logically connected."""
        if len(trajectory) <= 1:
            return 1.0

        coherent_transitions = 0
        for i in range(len(trajectory) - 1):
            # Simple check: observation should influence next action
            if trajectory[i].observation and trajectory[i + 1].action:
                coherent_transitions += 1

        return coherent_transitions / (len(trajectory) - 1)

    def _evaluate_completeness(
        self,
        trajectory: list[TrajectoryStep],
        question: str,
    ) -> float:
        """Evaluate if trajectory addresses the question."""
        q_words = set(question.lower().split())

        addressed = set()
        for step in trajectory:
            step_words = set((step.action + " " + step.observation).lower().split())
            addressed |= q_words & step_words

        return len(addressed) / len(q_words) if q_words else 0


# ============================================================================
# Main Evaluator
# ============================================================================


class RAGEvaluator:
    """
    Main RAG evaluation class.

    Combines multiple evaluators for comprehensive assessment.
    """

    def __init__(
        self,
        llm: Any = None,
        metrics: list[MetricType] | None = None,
    ):
        """
        Initialize the evaluator.

        Args:
            llm: Language model for evaluation
            metrics: Metrics to evaluate
        """
        self.llm = llm
        self.metrics = metrics or [
            MetricType.FAITHFULNESS,
            MetricType.RELEVANCE,
            MetricType.CONTEXT_PRECISION,
        ]

        self._evaluators: dict[MetricType, BaseEvaluator] = {
            MetricType.FAITHFULNESS: FaithfulnessEvaluator(llm),
            MetricType.RELEVANCE: RelevanceEvaluator(llm),
            MetricType.CONTEXT_PRECISION: ContextPrecisionEvaluator(llm),
            MetricType.ANSWER_CORRECTNESS: AnswerCorrectnessEvaluator(llm),
            MetricType.TRAJECTORY: TrajectoryEvaluator(),
        }

    def add_evaluator(
        self,
        metric: MetricType,
        evaluator: BaseEvaluator,
    ) -> "RAGEvaluator":
        """Add or replace an evaluator."""
        self._evaluators[metric] = evaluator
        if metric not in self.metrics:
            self.metrics.append(metric)
        return self

    async def evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[str] | None = None,
        ground_truth: str | None = None,
        trajectory: list[TrajectoryStep] | None = None,
        **kwargs,
    ) -> EvaluationResult:
        """
        Evaluate a RAG response.

        Args:
            question: The question asked
            answer: Generated answer
            contexts: Retrieved contexts
            ground_truth: Expected answer
            trajectory: Agent trajectory
            **kwargs: Additional arguments

        Returns:
            Evaluation result
        """
        scores = []

        # Run evaluations in parallel
        tasks = []
        for metric in self.metrics:
            if metric in self._evaluators:
                evaluator = self._evaluators[metric]
                tasks.append(
                    evaluator.evaluate(
                        question=question,
                        answer=answer,
                        contexts=contexts,
                        ground_truth=ground_truth,
                        trajectory=trajectory,
                        **kwargs,
                    )
                )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, EvaluationScore):
                scores.append(result)
            elif isinstance(result, Exception):
                logger.error("Evaluation failed: %s", result)

        # Calculate overall score
        if scores:
            overall = sum(s.score for s in scores) / len(scores)
        else:
            overall = 0.0

        return EvaluationResult(
            question=question,
            answer=answer,
            scores=scores,
            overall_score=overall,
            passed=overall >= 0.7,
            metadata=kwargs,
        )

    async def evaluate_batch(
        self,
        samples: list[dict[str, Any]],
    ) -> list[EvaluationResult]:
        """
        Evaluate multiple samples.

        Args:
            samples: List of evaluation samples

        Returns:
            List of evaluation results
        """
        results = []

        for sample in samples:
            result = await self.evaluate(
                question=sample.get("question", ""),
                answer=sample.get("answer", ""),
                contexts=sample.get("contexts"),
                ground_truth=sample.get("ground_truth"),
                trajectory=sample.get("trajectory"),
            )
            results.append(result)

        return results


# ============================================================================
# Convenience Functions
# ============================================================================


_default_evaluator: RAGEvaluator | None = None


def get_evaluator(llm: Any = None) -> RAGEvaluator:
    """Get or create the default evaluator."""
    global _default_evaluator
    if _default_evaluator is None:
        _default_evaluator = RAGEvaluator(llm=llm)
    return _default_evaluator


async def evaluate_response(
    question: str,
    answer: str,
    contexts: list[str] | None = None,
    ground_truth: str | None = None,
) -> EvaluationResult:
    """Quick evaluation of a single response."""
    evaluator = get_evaluator()
    return await evaluator.evaluate(
        question=question,
        answer=answer,
        contexts=contexts,
        ground_truth=ground_truth,
    )
