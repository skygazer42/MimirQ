"""
Evaluator-Optimizer Workflow Pattern.

Iterative improvement loop where answers are evaluated
and optimized until quality threshold is met.

Pattern: Generate -> Evaluate -> (Score < threshold) -> Optimize -> Evaluate -> ... -> Result
"""


import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.workflows.base import (
    BaseWorkflow,
    WorkflowMode,
    WorkflowResult,
)

logger = get_logger("rag.workflows.evaluator_optimizer")

# Configuration
EVALUATOR_MAX_ITERATIONS = getattr(settings, "EVALUATOR_MAX_ITERATIONS", 3)
EVALUATOR_THRESHOLD = getattr(settings, "EVALUATOR_THRESHOLD", 0.8)


class EvaluationResult:
    """Result of answer evaluation."""

    def __init__(
        self,
        score: float,
        feedback: str = "",
        criteria_scores: dict[str, float] | None = None,
    ):
        self.score = score
        self.feedback = feedback
        self.criteria_scores = criteria_scores or {}

    def passed(self, threshold: float) -> bool:
        """Check if evaluation passed threshold."""
        return self.score >= threshold


class EvaluatorOptimizerWorkflow(BaseWorkflow):
    """
    Evaluator-Optimizer workflow iteratively improves answers.

    Generates an initial answer, evaluates quality, and if below
    threshold, optimizes and re-evaluates until passing or max iterations.

    Usage:
        workflow = EvaluatorOptimizerWorkflow(llm=my_llm)
        workflow.set_generator(my_generator)
        workflow.set_evaluator(my_evaluator)
        workflow.set_optimizer(my_optimizer)
        result = await workflow.run({"question": "..."})
    """

    def __init__(
        self,
        llm: Any | None = None,
        threshold: float = EVALUATOR_THRESHOLD,
        max_iterations: int = EVALUATOR_MAX_ITERATIONS,
        **kwargs,
    ):
        """
        Initialize the evaluator-optimizer workflow.

        Args:
            llm: Language model for evaluation/optimization
            threshold: Quality threshold (0-1)
            max_iterations: Maximum optimization iterations
            **kwargs: Additional configuration
        """
        super().__init__(max_iterations=max_iterations, **kwargs)
        self._llm = llm
        self.threshold = threshold
        self._generator: Callable[[dict[str, Any]], Awaitable[str]] | None = None
        self._evaluator: Callable[[str, str, list[dict[str, Any]]], Awaitable[EvaluationResult]] | None = None
        self._optimizer: Callable[[str, str, str], Awaitable[str]] | None = None

    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.EVALUATOR

    def set_llm(self, llm: Any) -> "EvaluatorOptimizerWorkflow":
        """Set the language model."""
        self._llm = llm
        return self

    def set_generator(
        self,
        generator: Callable[[dict[str, Any]], Awaitable[str]],
    ) -> "EvaluatorOptimizerWorkflow":
        """Set the answer generator function."""
        self._generator = generator
        return self

    def set_evaluator(
        self,
        evaluator: Callable[[str, str, list[dict[str, Any]]], Awaitable[EvaluationResult]],
    ) -> "EvaluatorOptimizerWorkflow":
        """
        Set the evaluator function.

        Evaluator signature: (question, answer, contexts) -> EvaluationResult
        """
        self._evaluator = evaluator
        return self

    def set_optimizer(
        self,
        optimizer: Callable[[str, str, str], Awaitable[str]],
    ) -> "EvaluatorOptimizerWorkflow":
        """
        Set the optimizer function.

        Optimizer signature: (question, answer, feedback) -> improved_answer
        """
        self._optimizer = optimizer
        return self

    async def _default_generate(self, state: dict[str, Any]) -> str:
        """Default generation using LLM."""
        if self._llm is None:
            raise ValueError("LLM not configured")

        question = self.get_question(state)
        contexts = state.get("contexts", [])

        context_text = ""
        if contexts:
            context_parts = []
            for i, ctx in enumerate(contexts[:5], 1):
                content = ctx.get("content", "")[:1000]
                context_parts.append(f"[{i}] {content}")
            context_text = "\n".join(context_parts)

        prompt = f"""Answer the following question based on the provided context.

Context:
{context_text if context_text else 'No context available.'}

Question: {question}

Provide a clear, comprehensive answer:"""

        response = await self._llm.ainvoke(prompt)
        return response.content if hasattr(response, 'content') else str(response)

    async def _default_evaluate(
        self,
        question: str,
        answer: str,
        contexts: list[dict[str, Any]],
    ) -> EvaluationResult:
        """Default evaluation using LLM."""
        if self._llm is None:
            # Simple heuristic evaluation
            score = 0.5
            if len(answer) > 50:
                score += 0.2
            if len(answer) > 200:
                score += 0.1
            if any(c.get("content", "")[:100].lower() in answer.lower() for c in contexts[:3]):
                score += 0.2
            return EvaluationResult(min(score, 1.0), "Heuristic evaluation")

        context_text = "\n".join(
            ctx.get("content", "")[:500] for ctx in contexts[:3]
        ) if contexts else "No context"

        prompt = f"""Evaluate the quality of the following answer.

Question: {question}

Context (for reference):
{context_text}

Answer to evaluate:
{answer}

Rate the answer on these criteria (0-1 scale):
1. Relevance: Does it address the question?
2. Accuracy: Is it factually correct based on context?
3. Completeness: Does it cover all key aspects?
4. Clarity: Is it well-structured and clear?

Respond in this format:
Relevance: [score]
Accuracy: [score]
Completeness: [score]
Clarity: [score]
Overall: [average score]
Feedback: [specific feedback for improvement]"""

        response = await self._llm.ainvoke(prompt)
        content = response.content if hasattr(response, 'content') else str(response)

        # Parse scores
        criteria_scores = {}
        overall = 0.5
        feedback = ""

        for line in content.strip().split("\n"):
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()

                if key == "feedback":
                    feedback = value
                elif key == "overall":
                    try:
                        overall = float(value)
                    except ValueError as exc:
                        logger.debug("Ignoring non-critical evaluator optimizer parse fallback: %s", exc)
                else:
                    try:
                        criteria_scores[key] = float(value)
                    except ValueError as exc:
                        logger.debug("Ignoring non-critical evaluator optimizer parse fallback: %s", exc)

        return EvaluationResult(overall, feedback, criteria_scores)

    async def _default_optimize(
        self,
        question: str,
        answer: str,
        feedback: str,
    ) -> str:
        """Default optimization using LLM."""
        if self._llm is None:
            return answer  # No optimization possible

        prompt = f"""Improve the following answer based on the feedback.

Question: {question}

Current Answer:
{answer}

Feedback for Improvement:
{feedback}

Provide an improved answer that addresses the feedback:"""

        response = await self._llm.ainvoke(prompt)
        return response.content if hasattr(response, 'content') else str(response)

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        """
        Execute the evaluator-optimizer workflow.

        Args:
            state: Initial state (should include contexts from retrieval)

        Returns:
            WorkflowResult with optimized answer
        """
        if not self.validate_state(state):
            return self.create_result(
                state,
                success=False,
                error="Invalid state: missing question/query",
            )

        question = self.get_question(state)
        contexts = state.get("contexts", [])
        current_state = dict(state)
        execution_path: list[str] = []
        iterations = 0
        evaluation_history: list[dict[str, Any]] = []

        # Get functions (use defaults if not set)
        generate = self._generator or self._default_generate
        evaluate = self._evaluator or self._default_evaluate
        optimize = self._optimizer or self._default_optimize

        # Initial generation
        execution_path.append("generate")
        try:
            answer = await generate(current_state)
            current_state["answer"] = answer
        except Exception as e:
            logger.exception("Generation failed: %s", e)
            return self.create_result(
                current_state,
                success=False,
                error=f"Generation failed: {e}",
                execution_path=execution_path,
            )

        # Evaluation-optimization loop
        for iteration in range(self.max_iterations):
            iterations = iteration + 1

            # Evaluate
            execution_path.append(f"evaluate:{iteration}")
            try:
                eval_result = await evaluate(question, answer, contexts)
                evaluation_history.append({
                    "iteration": iteration,
                    "score": eval_result.score,
                    "feedback": eval_result.feedback,
                    "criteria": eval_result.criteria_scores,
                })
                current_state["score"] = eval_result.score
                current_state["evaluation_feedback"] = eval_result.feedback

                logger.debug(
                    "Iteration %d: score=%.2f, threshold=%.2f",
                    iteration, eval_result.score, self.threshold
                )

            except Exception as e:
                logger.exception("Evaluation failed: %s", e)
                # Continue with assumed pass
                break

            # Check if passed threshold
            if eval_result.passed(self.threshold):
                execution_path.append("pass")
                current_state["evaluation_history"] = evaluation_history

                return self.create_result(
                    current_state,
                    success=True,
                    execution_path=execution_path,
                    iterations=iterations,
                    metadata={
                        "final_score": eval_result.score,
                        "iterations_needed": iterations,
                    },
                )

            # Optimize if not at max iterations
            if iteration < self.max_iterations - 1:
                execution_path.append(f"optimize:{iteration}")
                try:
                    answer = await optimize(question, answer, eval_result.feedback)
                    current_state["answer"] = answer
                except Exception as e:
                    logger.exception("Optimization failed: %s", e)
                    # Continue with current answer
                    break

        # Max iterations reached
        current_state["evaluation_history"] = evaluation_history
        final_score = evaluation_history[-1]["score"] if evaluation_history else 0.0

        return self.create_result(
            current_state,
            success=final_score >= self.threshold * 0.8,  # Partial success if close
            execution_path=execution_path,
            iterations=iterations,
            metadata={
                "final_score": final_score,
                "threshold": self.threshold,
                "max_iterations_reached": True,
            },
        )


def create_ragas_evaluator(
    metrics: list[str] | None = None,
) -> Callable[[str, str, list[dict[str, Any]]], Awaitable[EvaluationResult]]:
    """
    Create an evaluator using RAGAS metrics.

    Args:
        metrics: List of RAGAS metrics to use

    Returns:
        Evaluator function
    """
    metrics = metrics or ["faithfulness", "answer_relevancy"]

    async def evaluator(
        question: str,
        answer: str,
        contexts: list[dict[str, Any]],
    ) -> EvaluationResult:
        try:
            from datasets import Dataset
            from ragas import evaluate
            from ragas.metrics import answer_relevancy, faithfulness

            # Prepare data
            context_texts = [ctx.get("content", "") for ctx in contexts]

            data = {
                "question": [question],
                "answer": [answer],
                "contexts": [context_texts],
            }
            dataset = Dataset.from_dict(data)

            # Run evaluation
            result = await asyncio.to_thread(evaluate, dataset, metrics=[faithfulness, answer_relevancy])

            # Calculate overall score
            scores = {}
            for metric in ["faithfulness", "answer_relevancy"]:
                if metric in result:
                    scores[metric] = result[metric]

            overall = sum(scores.values()) / len(scores) if scores else 0.5

            return EvaluationResult(
                score=overall,
                feedback=f"RAGAS scores: {scores}",
                criteria_scores=scores,
            )

        except ImportError:
            logger.warning("RAGAS not available, using fallback evaluation")
            # Fallback to simple heuristics
            score = 0.6 if len(answer) > 100 else 0.4
            return EvaluationResult(score, "RAGAS not available")
        except Exception as e:
            logger.exception("RAGAS evaluation failed: %s", e)
            return EvaluationResult(0.5, f"Evaluation error: {e}")

    return evaluator
