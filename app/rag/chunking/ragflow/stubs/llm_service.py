"""
Stub for ragflow api services.
These are ragflow-internal APIs that are not available in this project.
"""


class LLMBundle:
    """Stub LLMBundle - not functional without full ragflow setup."""

    def __init__(self, tenant_id, llm_type, **kwargs):
        self.tenant_id = tenant_id
        self.llm_type = llm_type
        self.kwargs = kwargs
        raise NotImplementedError(
            "LLMBundle requires full ragflow installation. "
            "Vision-based parsing features are not available."
        )
