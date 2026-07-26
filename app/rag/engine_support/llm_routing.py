"""LLM construction and dynamic model/retrieval routing mixin for the RAGEngine.

Must not import ``app.rag.engine`` or ``app.rag.retrieval.orchestrator``.
Instance attributes referenced via ``self`` (``http_client``,
``http_async_client``, ``models``, ``multi_query_prompt``) are declared on the
core ``RAGEngine`` class, not here.
"""

import re
import time
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.core.text import parse_json_from_text
from app.rag.llm.langchain_chat import build_chat_model_from_config


class LlmRoutingMixin:
    """Owns LLM building, complexity scoring, model routing, and multi-query generation."""

    # Coarse, low-dependency "complex query" indicators used for dynamic model routing.
    # Intentionally conservative: we only use these signals when routing is enabled.
    _COMPLEXITY_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\b(analyze|compare|contrast|evaluate|synthesize)\b", flags=re.IGNORECASE),
        re.compile(r"\b(step[- ]by[- ]step|first.*then|multiple|several)\b", flags=re.IGNORECASE),
        re.compile(r"\b(calculate|compute|solve|prove|derive)\b", flags=re.IGNORECASE),
        re.compile(r"\b(code|function|algorithm|implement|debug)\b", flags=re.IGNORECASE),
        re.compile(r"\b(because|therefore|however|although|despite)\b", flags=re.IGNORECASE),
        re.compile(r"\$.*\$", flags=re.DOTALL),  # inline math-ish blocks
        re.compile(r"```"),  # fenced code blocks
        re.compile(r"\d+\.\s+"),  # numbered list
    )

    def _build_llm(self, chat_cls: type[ChatOpenAI], model_name: str) -> Any:
        """Create a ChatOpenAI-compatible LLM with shared HTTP clients.

        In dev/E2E we optionally use a fake streaming LLM to avoid external network calls.
        """
        _ = chat_cls
        if bool(getattr(settings, "LLM_MOCK_ENABLED", False)):
            # Lazy import to keep default startup lightweight.
            from langchain_core.language_models.fake import FakeStreamingListLLM

            response = str(getattr(settings, "LLM_MOCK_RESPONSE", "") or "Hello from mock LLM.")
            return FakeStreamingListLLM(responses=[response])

        return build_chat_model_from_config(
            model_config={
                "model": model_name,
                "api_key": settings.LLM_API_KEY,
                "base_url": normalize_openai_compatible_base_url(settings.LLM_API_BASE),
                "temperature": settings.LLM_TEMPERATURE,
                "timeout": settings.LLM_TIMEOUT,
                "max_retries": settings.LLM_MAX_RETRIES,
            },
            http_client=self.http_client,
            http_async_client=self.http_async_client,
            streaming=True,
        )

    @staticmethod
    def _is_route_model_compatible(
        *,
        route_model_name: str | None,
        default_model_name: str,
    ) -> bool:
        """Avoid routing to stale fast/heavy model aliases after provider changes."""
        route_model = str(route_model_name or "").strip()
        default_model = str(default_model_name or "").strip()
        if not route_model:
            return False
        if not default_model or route_model == default_model:
            return True

        # OpenAI-compatible providers use very different model-id namespaces.
        # If the primary model changed from a plain provider alias
        # (e.g. qwen3.6-plus) to a registry path (e.g. deepseek-ai/DeepSeek-V3),
        # the previous fast/heavy aliases are almost certainly stale and should
        # not be selected automatically.
        if ("/" in route_model) != ("/" in default_model):
            return False

        api_base = str(getattr(settings, "LLM_API_BASE", "") or "").casefold()
        if "siliconflow" in api_base and "/" not in route_model:
            return False
        return True

    @staticmethod
    def _model_name_for_route(*, llm: Any, model_route: str) -> str:
        route = str(model_route or "").strip().lower()
        if route == "heavy" and settings.LLM_MODEL_HEAVY:
            return str(settings.LLM_MODEL_HEAVY)
        if route == "fast" and settings.LLM_MODEL_FAST:
            return str(settings.LLM_MODEL_FAST)
        value = getattr(llm, "model_name", None) or getattr(llm, "model", None) or settings.LLM_MODEL
        return str(value or settings.LLM_MODEL or "gpt-5.4-mini")

    def _maybe_override_llm_for_request(
        self,
        *,
        llm: Any,
        model_route: str,
        structured_output: bool,
    ) -> tuple[Any, dict[str, Any]]:
        base_temperature = float(getattr(settings, "LLM_TEMPERATURE", 0.0) or 0.0)
        target_temperature = float(getattr(settings, "LLM_STRUCTURED_TEMPERATURE", base_temperature) or 0.0)
        meta = {
            "structured_temperature": target_temperature,
            "base_temperature": base_temperature,
            "structured_temperature_override_applied": False,
        }

        if not structured_output or bool(getattr(settings, "LLM_MOCK_ENABLED", False)):
            return llm, meta
        if abs(target_temperature - base_temperature) < 1e-9:
            return llm, meta

        model_name = self._model_name_for_route(llm=llm, model_route=model_route)
        request_llm = build_chat_model_from_config(
            model_config={
                "model": model_name,
                "api_key": settings.LLM_API_KEY,
                "base_url": normalize_openai_compatible_base_url(settings.LLM_API_BASE),
                "temperature": target_temperature,
                "timeout": settings.LLM_TIMEOUT,
                "max_retries": settings.LLM_MAX_RETRIES,
            },
            http_client=self.http_client,
            http_async_client=self.http_async_client,
            streaming=True,
        )
        meta["structured_temperature_override_applied"] = True
        meta["model_name"] = model_name
        return request_llm, meta

    def _score_question_complexity(self, question: str, history: list[dict[str, str]] | None) -> float:
        """
        Coarse-grained complexity scoring:
        - question length
        - history length * weight
        - "complex query" indicators (analysis/code/multi-step phrasing)

        This stays dependency-free and is only used for model routing heuristics.
        """
        q = question or ""

        history = history or []
        history_len = sum(len(msg.get("content", "")) for msg in history if isinstance(msg, dict))
        score = float(len(q)) + settings.MODEL_COMPLEXITY_HISTORY_WEIGHT * float(history_len)

        # If routing is enabled, treat certain patterns as "complex" even when the
        # question is short (e.g., "analyze/compare", step-by-step requests, code).
        # Scale the bonus relative to the configured threshold so deployments can tune one knob.
        try:
            pattern_matches = sum(1 for p in self._COMPLEXITY_PATTERNS if p.search(q))
        except re.error:
            pattern_matches = 0

        if pattern_matches > 0:
            threshold = float(getattr(settings, "MODEL_COMPLEXITY_THRESHOLD", 160) or 160)
            bonus_per_match = max(0.0, threshold * 0.35)
            score += float(min(pattern_matches, 6)) * bonus_per_match

        return score

    def _select_llm(self, question: str, history: list[dict[str, str]] | None) -> tuple[Any, str, str]:
        """
        Dynamic model routing: inspired by agent/middleware dynamic model selection pattern.
        Returns: (llm instance, route identifier, reason)
        """
        if not settings.ENABLE_DYNAMIC_MODEL_ROUTING:
            return self.models["default"], "default", "routing disabled"

        score = self._score_question_complexity(question, history)
        threshold = settings.MODEL_COMPLEXITY_THRESHOLD

        if "heavy" in self.models and score >= threshold:
            return self.models["heavy"], "heavy", f"score {score:.1f} >= threshold {threshold}"

        if "fast" in self.models:
            return self.models["fast"], "fast", f"score {score:.1f} < threshold {threshold}"

        return self.models["default"], "default", "fallback to default"

    def _route_retrieval_params(self, complexity_score: float) -> dict[str, Any]:
        """Apply coarse retrieval overrides for simple vs. complex queries."""
        if not bool(getattr(settings, "ADAPTIVE_RETRIEVAL_ROUTING_ENABLED", False)):
            return {}

        simple_threshold = float(getattr(settings, "ADAPTIVE_RETRIEVAL_SIMPLE_THRESHOLD", 80.0) or 80.0)
        complex_threshold = float(getattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_THRESHOLD", 200.0) or 200.0)

        if complexity_score < simple_threshold:
            return {
                "top_k": max(1, int(getattr(settings, "ADAPTIVE_RETRIEVAL_SIMPLE_TOP_K", 10) or 10)),
                "enable_multi_query": False,
            }

        if complexity_score >= complex_threshold:
            return {
                "top_k": max(1, int(getattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_TOP_K", 40) or 40)),
                "enable_multi_query": True,
                "multi_query_count": max(
                    1,
                    int(getattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_MQ_COUNT", 5) or 5),
                ),
                "retrieval_profile": "recall50",
            }

        return {}

    async def _generate_multi_queries(
        self,
        *,
        query: str,
        llm: Any,
        enabled: bool,
        count: int,
        temperature: float,
        max_chars: int,
    ) -> tuple[list[str], float, str | None, dict[str, Any]]:
        if not enabled or count <= 0 or max_chars <= 0 or len(query or "") > max_chars:
            return [], 0.0, None, {"ok": False, "method": None, "error": None}

        mq_llm = self.models.get("fast") or llm
        model_used = getattr(mq_llm, "model_name", None) or getattr(mq_llm, "model", None)
        parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
        queries: list[str] = []
        elapsed = 0.0

        try:
            mq_chain = self.multi_query_prompt | mq_llm.bind(temperature=temperature) | StrOutputParser()
            mq_start = time.time()
            mq_raw = await mq_chain.ainvoke({"query": query, "n": count})
            elapsed = time.time() - mq_start
            mq_data, parse_meta = parse_json_from_text(mq_raw, expected="array")

            if isinstance(mq_data, list):
                seen: set[str] = set()
                for item in mq_data:
                    if not isinstance(item, str):
                        continue
                    candidate = (item or "").strip().strip('"').strip()
                    if not candidate or candidate == query or candidate in seen:
                        continue
                    if len(candidate) > 400:
                        candidate = candidate[:400] + "..."
                    seen.add(candidate)
                    queries.append(candidate)
                    if len(queries) >= count:
                        break
        except Exception as exc:  # noqa: BLE001
            elapsed = 0.0
            parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
            queries = []

        return queries, elapsed, model_used, parse_meta
