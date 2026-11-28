"""Query contracts shared by dataset analysis and export endpoints."""

from pydantic import BaseModel, Field


class _AnalysisWindowQuery(BaseModel):
    from_ts: str | None = None
    to_ts: str | None = None
    feedback_polarity: str | None = None


class DatasetAnalysisQuery(_AnalysisWindowQuery):
    category: str | None = None


class DatasetAnalysisDashboardQuery(_AnalysisWindowQuery):
    limit: int = Field(default=20, ge=1, le=200)


class DatasetAnalysisExamplesQuery(DatasetAnalysisQuery):
    limit: int = Field(default=20, ge=1, le=200)


class DatasetAnalysisRulesQuery(_AnalysisWindowQuery):
    ruleset: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=200)


class DatasetAnalysisWritebackQuery(DatasetAnalysisQuery):
    ruleset: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=200)
