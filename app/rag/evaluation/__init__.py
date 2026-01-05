"""
RAG Evaluation module.

Provides comprehensive evaluation capabilities for RAG systems.
Includes both agent-based evaluation and RAGAS integration.
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
