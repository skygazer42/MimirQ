"""
Connector source-ACL mapping schemas.

These schemas provide a connector-level interface for representing *source* permissions
and mapping them into tenant groups / document access controls.

Design goals:
- Typed + bounded payloads (defense-in-depth for untrusted configs)
- Tenant-safe by construction (group ids are validated at runtime by the API layer)
- Fail-closed defaults (unmapped principals should not accidentally open access)
"""


from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.api.schemas.document import DocumentAccessMode

SourceSystem = Literal["github", "confluence", "jira", "drive", "generic"]
SourcePrincipalKind = Literal["user", "group", "team", "role", "policy", "domain", "anyone"]


class SourcePrincipal(BaseModel):
    """
    A normalized identity from an upstream system.

    Examples:
    - {"system":"github","kind":"team","id":"myorg/platform"}
    - {"system":"confluence","kind":"group","id":"confluence-users"}
    - {"system":"jira","kind":"role","id":"developers"}
    - {"system":"jira","kind":"policy","id":"security-level/10001"}
    - {"system":"drive","kind":"domain","id":"example.com"}
    - {"system":"drive","kind":"anyone","id":""}
    """

    system: SourceSystem
    kind: SourcePrincipalKind
    id: str = Field(default="", max_length=512, description="Principal identifier in the upstream system")
    display: str | None = Field(default=None, max_length=512, description="Optional human display label (best-effort)")

    @model_validator(mode="after")
    def _normalize(self) -> "SourcePrincipal":
        self.id = str(self.id or "").strip()
        if self.kind == "anyone":
            # Normal form: anyone has no id.
            self.id = ""
        if self.kind == "domain":
            # Domains are case-insensitive; normalize to lower for stable mapping.
            self.id = self.id.lower()
        if not self.id and self.kind != "anyone":
            raise ValueError("id is required")

        if self.display is not None:
            d = str(self.display or "").strip()
            self.display = d or None
        return self

    def key(self) -> str:
        """
        Stable mapping key for rule lookups.
        """

        return f"{self.system}:{self.kind}:{self.id}"


class SourceAcl(BaseModel):
    """
    Connector-provided "who can read" view for a single source object.

    Note: this is intentionally minimal (read access only). Later iterations may
    extend this to include roles and provenance.
    """

    principals: list[SourcePrincipal] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _normalize(self) -> "SourceAcl":
        cleaned: list[SourcePrincipal] = []
        seen: set[str] = set()
        for p in self.principals or []:
            if not isinstance(p, SourcePrincipal):
                continue
            k = p.key()
            if k in seen:
                continue
            seen.add(k)
            cleaned.append(p)
            if len(cleaned) >= 500:
                break
        self.principals = cleaned
        return self

    def has_anyone(self) -> bool:
        return any(p.kind == "anyone" for p in (self.principals or []))


class SourceAclGroupMappingRule(BaseModel):
    """
    Map a source principal into a tenant group.

    Multiple rules may map the same source principal to multiple tenant groups.
    """

    source: SourcePrincipal
    group_id: UUID = Field(..., description="TenantGroup.id")


SourceAclMode = Literal["disabled", "inherit"]


class ConnectorSourceAclConfig(BaseModel):
    """
    Connector-level policy for applying source ACLs (if the connector supports it).
    """

    mode: SourceAclMode = Field(
        default="disabled",
        description="disabled: ignore source ACL; inherit: apply mapped source ACL to document access.",
    )
    group_mappings: list[SourceAclGroupMappingRule] = Field(
        default_factory=list,
        max_length=200,
        description="Bounded mapping rules from source principals -> tenant groups.",
    )
    allow_anyone: bool = Field(
        default=False,
        description="If true, treat kind=anyone as all_team_members (explicit opt-in; default off).",
    )
    fallback_mode: DocumentAccessMode = Field(
        default="partial_members",
        description=(
            "When mode=inherit and no mapped groups are found, apply this access mode. "
            "Default is partial_members (owner-only when allowlists are empty), which fails closed."
        ),
    )

    @model_validator(mode="after")
    def _normalize(self) -> "ConnectorSourceAclConfig":
        # De-dupe mapping rules (keep stable order; cap again for defense-in-depth).
        cleaned: list[SourceAclGroupMappingRule] = []
        seen: set[tuple[str, UUID]] = set()
        for rule in self.group_mappings or []:
            src = getattr(rule, "source", None)
            gid = getattr(rule, "group_id", None)
            if src is None or gid is None:
                continue
            key = (src.key(), gid)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(rule)
            if len(cleaned) >= 200:
                break
        self.group_mappings = cleaned
        return self
