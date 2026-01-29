"""
RAG Evaluation module.

Provides comprehensive evaluation capabilities for RAG systems.
Includes both agent-based evaluation and RAGAS integration.
"""

from app.rag.evaluation.agent_evals import (
    AnswerCorrectnessEvaluator,
    BaseEvaluator,
    ContextPrecisionEvaluator,
    EvaluationResult,
    EvaluationScore,
    FaithfulnessEvaluator,
    MetricType,
    RAGEvaluator,
    RelevanceEvaluator,
    TrajectoryEvaluator,
    TrajectoryStep,
    evaluate_response,
    get_evaluator,
)

# RAGAS evaluation (merged from app/evaluation/)
from app.rag.evaluation.ragas import (
    run_conversation_ragas_evaluation,
    run_regression_ragas_evaluation,
)

__all__ = [
    # Types
    "MetricType",
    "EvaluationScore",
    "EvaluationResult",
    "TrajectoryStep",
    # Evaluators
    "BaseEvaluator",
    "FaithfulnessEvaluator",
    "RelevanceEvaluator",
    "ContextPrecisionEvaluator",
    "AnswerCorrectnessEvaluator",
    "TrajectoryEvaluator",
    "RAGEvaluator",
    # Functions
    "get_evaluator",
    "evaluate_response",
    # RAGAS
    "run_conversation_ragas_evaluation",
    "run_regression_ragas_evaluation",
]
