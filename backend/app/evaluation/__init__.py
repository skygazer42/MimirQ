"""
DEPRECATED: This module has been moved to app.rag.evaluation

Please update your imports to use the new location:
    from app.rag.evaluation import run_conversation_ragas_evaluation, run_regression_ragas_evaluation
"""

import warnings
warnings.warn(
    "app.evaluation is deprecated. Use app.rag.evaluation instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export for backward compatibility
from app.rag.evaluation.ragas import run_conversation_ragas_evaluation, run_regression_ragas_evaluation

__all__ = [
    "run_conversation_ragas_evaluation",
    "run_regression_ragas_evaluation",
]
