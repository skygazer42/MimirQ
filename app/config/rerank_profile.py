
from dataclasses import dataclass


@dataclass(frozen=True)
class RerankProfile:
    name: str
    search_k: int


_RERANK_PROFILES = {
    "sweet_spot": RerankProfile(name="sweet_spot", search_k=20),
}


def get_rerank_profile(name: str | None) -> RerankProfile | None:
    key = str(name or "").strip().lower()
    if not key:
        return None
    return _RERANK_PROFILES.get(key)


def resolve_rerank_search_k(*, requested_k: int, profile: str | None) -> int:
    base = max(1, int(requested_k or 0))
    cfg = get_rerank_profile(profile)
    if cfg is None:
        return base
    return max(base, int(cfg.search_k or 0))
