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
from app.rag.evaluation.hard_negative_stress import evaluate_hard_negative_case, run_hard_negative_stress

# RAGAS evaluation (merged from app/evaluation/)
from app.rag.evaluation.ragas import (
    run_conversation_ragas_evaluation,
    run_regression_ragas_evaluation,
)
from app.rag.evaluation.ragcap_bench_runner import evaluate_ragcap_case, run_ragcap_bench

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
    "evaluate_hard_negative_case",
    "run_hard_negative_stress",
    "evaluate_ragcap_case",
    "run_ragcap_bench",
    # RAGAS
    "run_conversation_ragas_evaluation",
    "run_regression_ragas_evaluation",
]
