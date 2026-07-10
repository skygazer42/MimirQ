
from pydantic import BaseModel, Field


class BasePromptSchema(BaseModel):
    answer: str = Field(default="")
    citations: list[dict] = Field(default_factory=list)


class AssistantPromptSchema(BasePromptSchema):
    pass


class SummaryPromptSchema(BasePromptSchema):
    bullets: list[str] = Field(default_factory=list)
    summary: str = Field(default="")


class ActionItemsPromptSchema(BasePromptSchema):
    actions: list[dict] = Field(default_factory=list)


__all__ = [
    "ActionItemsPromptSchema",
    "AssistantPromptSchema",
    "BasePromptSchema",
    "SummaryPromptSchema",
]
