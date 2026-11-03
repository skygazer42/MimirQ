"""LangChain model-call bindings used by synchronous retrieval and native streaming."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseLanguageModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import BasePromptTemplate, ChatPromptTemplate

from app.rag.core.query_rewrite_strategy import get_query_rewrite_prompt_template

if TYPE_CHECKING:
    from app.rag.engine import RAGEngine


class RewriteModelCall:
    def __init__(
        self, model: BaseLanguageModel, *, model_name: str | None, strategy_id: str, temperature: float
    ) -> None:
        self.model, self.model_name = model, model_name
        self.strategy_id, self.temperature = strategy_id, temperature

    def invoke(self, *, question: str, history: str) -> str:
        prompt = ChatPromptTemplate.from_template(get_query_rewrite_prompt_template(self.strategy_id))
        return (prompt | self.model.bind(temperature=self.temperature) | StrOutputParser()).invoke(
            {"history": history, "question": question}
        )

    async def ainvoke(self, *, question: str, history: str) -> str:
        prompt = ChatPromptTemplate.from_template(get_query_rewrite_prompt_template(self.strategy_id))
        return await (prompt | self.model.bind(temperature=self.temperature) | StrOutputParser()).ainvoke(
            {"history": history, "question": question}
        )


class TextQueryModelCall:
    def __init__(
        self,
        model: BaseLanguageModel,
        *,
        prompt: BasePromptTemplate,
        model_name: str | None,
        temperature: float,
        count: int | None = None,
    ) -> None:
        self.model, self.prompt, self.model_name = model, prompt, model_name
        self.temperature, self.count = temperature, count

    def _payload(self, query: str) -> dict[str, str | int]:
        payload: dict[str, str | int] = {"query": query}
        if self.count is not None:
            payload["n"] = self.count
        return payload

    def invoke(self, *, query: str) -> str:
        return (self.prompt | self.model.bind(temperature=self.temperature) | StrOutputParser()).invoke(
            self._payload(query)
        )

    async def ainvoke(self, *, query: str) -> str:
        return await (self.prompt | self.model.bind(temperature=self.temperature) | StrOutputParser()).ainvoke(
            self._payload(query)
        )


class EngineQueryModels:
    def __init__(
        self, engine_factory: Callable[[], "RAGEngine"], *, fallback_model: BaseLanguageModel | None = None
    ) -> None:
        self.engine_factory = engine_factory
        self.fallback_model = fallback_model

    def _selected_model(self, engine: "RAGEngine") -> tuple[BaseLanguageModel, str | None]:
        model = engine.models.get("fast") or self.fallback_model or engine.models["default"]
        return model, getattr(model, "model_name", None) or getattr(model, "model", None)

    def rewrite(self, *, strategy_id: str, temperature: float) -> RewriteModelCall:
        engine = self.engine_factory()
        model, name = self._selected_model(engine)
        return RewriteModelCall(model, model_name=name, strategy_id=strategy_id, temperature=temperature)

    def multi_query(self, *, count: int, temperature: float) -> TextQueryModelCall:
        engine = self.engine_factory()
        model, name = self._selected_model(engine)
        return TextQueryModelCall(
            model, prompt=engine.multi_query_prompt, model_name=name, temperature=temperature, count=count
        )

    def hyde(self, *, temperature: float) -> TextQueryModelCall:
        engine = self.engine_factory()
        model, name = self._selected_model(engine)
        return TextQueryModelCall(model, prompt=engine.hyde_prompt, model_name=name, temperature=temperature)

    def step_back(self, *, temperature: float) -> TextQueryModelCall:
        engine = self.engine_factory()
        model, name = self._selected_model(engine)
        return TextQueryModelCall(model, prompt=engine.step_back_prompt, model_name=name, temperature=temperature)

    def decompose(self, *, max_questions: int, temperature: float) -> TextQueryModelCall:
        engine = self.engine_factory()
        model, name = self._selected_model(engine)
        return TextQueryModelCall(
            model, prompt=engine.decompose_prompt, model_name=name, temperature=temperature, count=max_questions
        )
