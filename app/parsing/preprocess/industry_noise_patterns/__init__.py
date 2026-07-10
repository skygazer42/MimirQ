
from app.parsing.preprocess.industry_noise_patterns.finance import RULES as FINANCE_RULES
from app.parsing.preprocess.industry_noise_patterns.industrial_control import RULES as INDUSTRIAL_CONTROL_RULES
from app.parsing.preprocess.industry_noise_patterns.legal import RULES as LEGAL_RULES
from app.rag.preprocessing.cleaning import RegexRule

_REGISTRY: dict[str, list[RegexRule]] = {
    "industrial_control": list(INDUSTRIAL_CONTROL_RULES),
    "finance": list(FINANCE_RULES),
    "legal": list(LEGAL_RULES),
}


def list_industry_noise_profiles() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_industry_noise_rules(profile: str) -> list[RegexRule]:
    key = str(profile or "").strip().lower()
    rules = _REGISTRY.get(key)
    if rules is None:
        raise ValueError(f"unsupported industry noise profile: {key or '<empty>'}")
    return list(rules)


__all__ = ["get_industry_noise_rules", "list_industry_noise_profiles"]
