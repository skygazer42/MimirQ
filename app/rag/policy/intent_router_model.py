
import json
import re
from pathlib import Path
from typing import Any

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


def _safe_tokenize(query: str) -> set[str]:
    out: set[str] = set()
    for m in _TOKEN_RE.finditer(str(query or "")):
        tok = str(m.group(0) or "").strip()
        if not tok:
            continue
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


def normalize_intent_router_model(raw: Any) -> dict[str, Any] | None:
    payload = raw if isinstance(raw, dict) else {}
    if str(payload.get("schema") or "").strip() != INTENT_ROUTER_MODEL_SCHEMA_V1:
        return None
    rules_raw = payload.get("rules")
    if not isinstance(rules_raw, list):
        return None

    rules: list[dict[str, Any]] = []
    for item in rules_raw[:200]:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("rule_id") or "").strip()[:40]
        if not rid:
            continue
        tokens_raw = item.get("tokens")
        if not isinstance(tokens_raw, list):
            continue
        tokens: list[str] = []
        seen: set[str] = set()
        for token in tokens_raw:
            tok = str(token or "").strip()
            if not tok:
                continue
            key = tok.casefold() if tok.isascii() else tok
            if key in seen:
                continue
            seen.add(key)
            tokens.append(tok[:64])
            if len(tokens) >= 24:
                break
        if not tokens:
            continue

        overrides_raw = item.get("overrides")
        if not isinstance(overrides_raw, dict):
            continue
        overrides = {str(k): v for k, v in overrides_raw.items() if str(k) in _ALLOWED_OVERRIDES}
        if not overrides:
            continue

        min_match = max(1, _coerce_int(item.get("min_match"), default=1))
        min_match = min(min_match, len(tokens))
        confidence = _coerce_float(item.get("confidence"), default=0.0)
        confidence = min(1.0, max(0.0, confidence))
        weight = _coerce_float(item.get("weight"), default=1.0)
        weight = min(2.0, max(0.0, weight))

        rules.append(
            {
                "rule_id": rid,
                "tokens": tokens,
                "min_match": min_match,
                "confidence": confidence,
                "weight": weight,
                "overrides": overrides,
            }
        )

    if not rules:
        return None
    return {
        "schema": INTENT_ROUTER_MODEL_SCHEMA_V1,
        "version": max(1, _coerce_int(payload.get("version"), default=1)),
        "rules": rules,
    }


def load_intent_router_model(path: str | None) -> dict[str, Any] | None:
    path_s = str(path or "").strip()
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
    if str(resolved.suffix or "").lower() != ".json":
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
    model: dict[str, Any] | None,
) -> dict[str, Any]:
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

    best: tuple[float, dict[str, Any] | None, int] = (0.0, None, 0)
    for rule in (mdl.get("rules") or []):
        if not isinstance(rule, dict):
            continue
        toks = [str(v) for v in (rule.get("tokens") or []) if str(v).strip()]
        if not toks:
            continue
        toks_norm = {t.casefold() if t.isascii() else t for t in toks}
        matched = len(toks_norm.intersection(query_tokens))
        min_match = max(1, _coerce_int(rule.get("min_match"), default=1))
        if matched < min_match:
            continue
        token_ratio = float(matched) / float(max(1, len(toks_norm)))
        confidence = min(1.0, max(0.0, _coerce_float(rule.get("confidence"), default=0.0)))
        weight = min(2.0, max(0.0, _coerce_float(rule.get("weight"), default=1.0)))
        score = float(token_ratio * confidence * weight)

        best_score, _best_rule, best_matched = best
        if score > best_score or (score == best_score and matched > best_matched):
            best = (score, rule, matched)

    score, chosen, matched = best
    if not isinstance(chosen, dict):
        return {
            "schema": INTENT_ROUTER_HINT_SCHEMA_V1,
            "used": False,
            "confidence": 0.0,
            "reason_codes": ["no_rule_match"],
            "overrides": {},
            "rule_id": None,
        }

    overrides = chosen.get("overrides")
    overrides = overrides if isinstance(overrides, dict) else {}
    return {
        "schema": INTENT_ROUTER_HINT_SCHEMA_V1,
        "used": bool(overrides),
        "confidence": round(float(score), 6),
        "reason_codes": ["rule_match"],
        "rule_id": str(chosen.get("rule_id") or ""),
        "matched_tokens": int(matched),
        "overrides": dict(overrides),
    }


__all__ = [
    "INTENT_ROUTER_MODEL_SCHEMA_V1",
    "load_intent_router_model",
    "normalize_intent_router_model",
    "predict_learned_router_hint",
]
