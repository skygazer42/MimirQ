from dataclasses import dataclass


@dataclass(frozen=True)
class RerankProfile:
    name: str
    search_k: int


_RERANK_PROFILES = {
    "sweet_spot": RerankProfile(name="sweet_spot", search_k=20),
}


def normalize_rerank_profile(name):
    key = (name or "").strip().lower()
    return key if key else None


def get_rerank_profile(name: str | None) -> RerankProfile | None:
    key = normalize_rerank_profile(name)
    if not key:
        return None
    return _RERANK_PROFILES.get(key)


def resolve_rerank_search_k(*, requested_k: int, profile: str | None) -> int:
    base = max(1, requested_k or 0)
    cfg = get_rerank_profile(profile)
    if cfg is None:
        return base
    return max(base, cfg.search_k)
