"""Model query inputs and controlled text providers shared by sync/async tests."""

import asyncio
import threading


def model_query_settings():
    from app.rag.retrieval.planning.contracts import (
        DecompositionSettings,
        ModelQuerySettings,
        MultiQueryExperiment,
        MultiQuerySettings,
        TextQuerySettings,
    )

    return ModelQuerySettings(
        MultiQuerySettings(True, 3, 0.0, 400, MultiQueryExperiment(None, None, None, False)),
        TextQuerySettings(True, 0.0, 400, 400),
        TextQuerySettings(True, 0.0, 400, 400),
        DecompositionSettings(True, 3, 0, 400, 0.2, False, True),
    )


def model_query_request(*, query="base", mode="hybrid", settings=None):
    from app.rag.retrieval.planning.contracts import ModelQueryRequest

    return ModelQueryRequest(query, mode, model_query_settings() if settings is None else settings)


class ModelReplies:
    def __init__(self, **replies):
        self.replies = {
            "multi_query": '["first", "second"]',
            "hyde": "hypothetical",
            "step_back": "broader view",
            "decomposition": '["part one", "part two"]',
            **replies,
        }
        self.calls = []

    def _select(self, kind):
        self.calls.append(("resolve", kind))
        owner = self

        class Model:
            model_name = kind

            def invoke(self, *, query):
                owner.calls.append(("invoke", kind, query))
                value = owner.replies[kind]
                if isinstance(value, BaseException):
                    raise value
                return value

        return Model()

    def multi_query(self, *, count, temperature):
        return self._select("multi_query")

    def hyde(self, *, temperature):
        return self._select("hyde")

    def step_back(self, *, temperature):
        return self._select("step_back")

    def decompose(self, *, max_questions, temperature):
        return self._select("decomposition")


class AsyncReplies(ModelReplies):
    def _select(self, kind):
        self.calls.append(("resolve", kind))
        owner = self

        class Model:
            model_name = kind

            def invoke(self, **kwargs):
                raise AssertionError("async strategy used a synchronous model call")

            async def ainvoke(self, *, query):
                owner.calls.append(("invoke", kind, query, threading.get_ident()))
                await asyncio.sleep(0)
                value = owner.replies[kind]
                if isinstance(value, BaseException):
                    raise value
                return value

        return Model()


def build_test_query_plan(question, **options):
    from app.rag.retrieval.planning.contracts import QueryPreparationOverrides, RetrievalRequest
    from app.rag.retrieval.planning.options import parse_query_expansion_budget, resolve_query_preparation_request
    from app.rag.retrieval.planning.planner import prepare_query_plan

    preferences = {
        "intent_router": False,
        "adaptive_router": False,
        "enable_multi_query": False,
        "enable_hyde": False,
        "enable_query_decomposition": False,
        "enable_kg_query_expansion": False,
        **options,
    }
    request = RetrievalRequest(
        resolve_query_preparation_request(
            question,
            "(No conversation history)",
            QueryPreparationOverrides(enable_rewrite=False, industry_enabled=False),
            temporal_enabled=False,
        ),
        preferences,
        parse_query_expansion_budget(preferences),
    )
    return prepare_query_plan(request, models=ModelReplies())
