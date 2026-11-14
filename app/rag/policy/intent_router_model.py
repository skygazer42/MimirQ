import json
import re
from pathlib import Path
from typing import Any, NotRequired, TypedDict

INTENT_ROUTER_MODEL_SCHEMA_V1 = "mimirq.intent_router_model.v1"
INTENT_ROUTER_HINT_SCHEMA_V1 = "mimirq.intent_router_hint.v1"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]{2,64}|[\u4e00-\u9fff]{2,16}")
_ALLOWED_OVERRIDES = {
    "retrieval_mode",
    "retrieval_profile",
    "top_k",
    "score_threshold",
    "enable_reranker",
    "enable_weight_rerank",
    "enable_multi_query",
    "enable_query_alias_expansion",
    "reranker_provider",
    "reranker_top_n",
}
_SAFE_MODEL_PATH_RE = re.compile(r"^[A-Za-z0-9_.\-/]{1,240}$")


class IntentRouterModelRule(TypedDict):
    rule_id: str
    tokens: list[str]
    min_match: int
    confidence: float
    weight: float
    overrides: dict[str, Any]


class IntentRouterModel(TypedDict):
    schema: str
    version: int
    rules: list[IntentRouterModelRule]


class LearnedRouterHint(TypedDict):
    schema: str
    used: bool
    confidence: float
    reason_codes: list[str]
    overrides: dict[str, Any]
    rule_id: str | None
    matched_tokens: NotRequired[int]


def _safe_tokenize(query: str) -> set[str]:
    out: set[str] = set()
    for m in _TOKEN_RE.finditer(query):
        tok = m.group(0)
        out.add(tok.casefold() if tok.isascii() else tok)
        if len(out) >= 256:
            break
    return out


def _coerce_float(value: Any, *, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _normalize_rule_tokens(tokens_raw: Any) -> list[str]:
    if not isinstance(tokens_raw, list):
        return []

    tokens: list[str] = []
    seen: set[str] = set()
    for token in tokens_raw:
        if token is None:
            continue
        tok = str(token).strip()[:64]
        if not tok:
            continue
        key = tok.casefold() if tok.isascii() else tok
        if key in seen:
            continue
        seen.add(key)
        tokens.append(tok)
        if len(tokens) >= 24:
            break
    return tokens


def _normalize_rule_overrides(overrides_raw: Any) -> dict[str, Any]:
    if not isinstance(overrides_raw, dict):
        return {}
    return {str(k): v for k, v in overrides_raw.items() if str(k) in _ALLOWED_OVERRIDES}


def _normalize_rule(item: dict[str, Any]) -> IntentRouterModelRule | None:
    raw_id = item.get("rule_id")
    rid = str(raw_id).strip()[:40] if raw_id is not None else None
    if not rid:
        return None

    tokens = _normalize_rule_tokens(item.get("tokens"))
    if not tokens:
        return None

    overrides = _normalize_rule_overrides(item.get("overrides"))
    if not overrides:
        return None

    min_match = min(max(1, _coerce_int(item.get("min_match"), default=1)), len(tokens))
    confidence = min(1.0, max(0.0, _coerce_float(item.get("confidence"), default=0.0)))
    weight = min(2.0, max(0.0, _coerce_float(item.get("weight"), default=1.0)))
    return {
        "rule_id": rid,
        "tokens": tokens,
        "min_match": min_match,
        "confidence": confidence,
        "weight": weight,
        "overrides": overrides,
    }


def normalize_intent_router_model(raw: Any) -> IntentRouterModel | None:
    payload = raw if isinstance(raw, dict) else {}
    schema = payload.get("schema")
    if not isinstance(schema, str) or schema.strip() != INTENT_ROUTER_MODEL_SCHEMA_V1:
        return None
    rules_raw = payload.get("rules")
    if not isinstance(rules_raw, list):
        return None

    rules: list[IntentRouterModelRule] = []
    for item in rules_raw[:200]:
        if not isinstance(item, dict):
            continue
        normalized_rule = _normalize_rule(item)
        if normalized_rule is not None:
            rules.append(normalized_rule)

    if not rules:
        return None
    return {
        "schema": INTENT_ROUTER_MODEL_SCHEMA_V1,
        "version": max(1, _coerce_int(payload.get("version"), default=1)),
        "rules": rules,
    }


def load_intent_router_model(path: str | None) -> IntentRouterModel | None:
    path_s = path.strip() if path is not None else None
    if not path_s:
        return None
    if not _SAFE_MODEL_PATH_RE.fullmatch(path_s):
        return None
    if path_s.startswith(("/", "\\", "~")):
        return None

    p = Path(path_s)
    if any(part == ".." for part in p.parts):
        return None

    base = Path.cwd().resolve(strict=False)
    try:
        resolved = (base / p).resolve(strict=False)
        resolved.relative_to(base)
    except Exception:
        return None
    if resolved.suffix.lower() != ".json":
        return None
    try:
        if not resolved.exists():
            return None
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return None
    return normalize_intent_router_model(raw)


def predict_learned_router_hint(
    *,
    query: str,
    model: IntentRouterModel | dict[str, Any] | None,
) -> LearnedRouterHint:
    mdl = normalize_intent_router_model(model)
    if mdl is None:
        return {
            "schema": INTENT_ROUTER_HINT_SCHEMA_V1,
            "used": False,
            "confidence": 0.0,
            "reason_codes": ["model_unavailable"],
            "overrides": {},
            "rule_id": None,
        }

    query_tokens = _safe_tokenize(query)
    if not query_tokens:
        return {
            "schema": INTENT_ROUTER_HINT_SCHEMA_V1,
            "used": False,
            "confidence": 0.0,
            "reason_codes": ["empty_query"],
            "overrides": {},
            "rule_id": None,
        }

    best_score = 0.0
    best_rule: IntentRouterModelRule | None = None
    best_matched = 0
    for rule in mdl["rules"]:
        toks_norm = {token.casefold() if token.isascii() else token for token in rule["tokens"]}
        matched = len(toks_norm.intersection(query_tokens))
        if matched < rule["min_match"]:
            continue
        token_ratio = matched / len(toks_norm)
        score = token_ratio * rule["confidence"] * rule["weight"]

        if score > best_score or (score == best_score and matched > best_matched):
            best_score = score
            best_rule = rule
            best_matched = matched

    if best_rule is None:
        return {
            "schema": INTENT_ROUTER_HINT_SCHEMA_V1,
            "used": False,
            "confidence": 0.0,
            "reason_codes": ["no_rule_match"],
            "overrides": {},
            "rule_id": None,
        }

    overrides = best_rule["overrides"]
    return {
        "schema": INTENT_ROUTER_HINT_SCHEMA_V1,
        "used": bool(overrides),
        "confidence": round(best_score, 6),
        "reason_codes": ["rule_match"],
        "rule_id": best_rule["rule_id"],
        "matched_tokens": best_matched,
        "overrides": dict(overrides),
    }


__all__ = [
    "INTENT_ROUTER_MODEL_SCHEMA_V1",
    "load_intent_router_model",
    "normalize_intent_router_model",
    "predict_learned_router_hint",
]
