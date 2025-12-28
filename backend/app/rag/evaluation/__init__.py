"""
RAG Evaluation module.

Provides comprehensive evaluation capabilities for RAG systems.
"""

from app.rag.evaluation.agent_evals import (
    MetricType,
    EvaluationScore,
    EvaluationResult,
    TrajectoryStep,
    BaseEvaluator,
    FaithfulnessEvaluator,
    RelevanceEvaluator,
    ContextPrecisionEvaluator,
    AnswerCorrectnessEvaluator,
    TrajectoryEvaluator,
    RAGEvaluator,
    get_evaluator,
    evaluate_response,
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
]
