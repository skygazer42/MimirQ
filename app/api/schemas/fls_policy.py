"""
Field-level security (FLS) / redacted view policy schemas.

Policies are stored in dataset metadata and enforced server-side on structured responses.
"""


from pydantic import BaseModel, Field


class FlsRule(BaseModel):
    """
    One FLS rule.

    Semantics:
    - If the rule matches a field/column name for a given source, and the current user is not allowed,
      the field is redacted using the configured mask.
    """

    id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    enabled: bool = True

    # Where this rule applies.
    sources: list[str] = Field(default_factory=list, max_length=10)

    # Regex applied to the field/column name (case-insensitive by default).
    column_name_regex: str = Field(..., min_length=1, max_length=200)

    # Allowlist.
    allow_roles: list[str] = Field(default_factory=list, max_length=50)
    allow_account_ids: list[str] = Field(default_factory=list, max_length=200)

    # Optional override; default is enforced server-side.
    mask: str | None = Field(default=None, max_length=80)


class FlsPolicy(BaseModel):
    version: str = Field(default="1", description="Policy schema version")
    rules: list[FlsRule] = Field(default_factory=list)

