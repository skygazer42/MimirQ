
import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is importable when invoked as:
#   python scripts/check_retrieval_profile_compat.py
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _parse_bool(raw: str | bool) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {raw!r}")


def _build_parser() -> argparse.ArgumentParser:
    from app.core.config import settings

    p = argparse.ArgumentParser(
        description="Validate retrieval_profile + reranker compatibility before runtime.",
    )
    p.add_argument("--retrieval-profile", type=str, default="recall50")
    p.add_argument("--top-k", type=int, default=int(getattr(settings, "RETRIEVAL_TOP_K", 10) or 10))
    p.add_argument("--score-threshold", type=float, default=float(getattr(settings, "SIMILARITY_THRESHOLD", 0.0) or 0.0))
    p.add_argument("--retrieval-mode", type=str, default=str(getattr(settings, "RETRIEVAL_MODE", "hybrid") or "hybrid"))
    p.add_argument("--enable-reranker", type=_parse_bool, default=bool(getattr(settings, "ENABLE_RERANKER", False)))
    p.add_argument("--reranker-provider", type=str, default=str(getattr(settings, "RERANKER_PROVIDER", "llm") or "llm"))
    p.add_argument("--reranker-top-n", type=int, default=int(getattr(settings, "RERANKER_TOP_N", 20) or 20))
    p.add_argument("--enable-weight-rerank", type=_parse_bool, default=True)
    p.add_argument("--json", action="store_true", help="print result as JSON")
    return p


def _collect_issues(args: argparse.Namespace) -> tuple[list[str], dict[str, Any]]:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides, normalize_retrieval_profile
    from app.rag.reranker.factory import describe_reranker_provider

    issues: list[str] = []
    profile = normalize_retrieval_profile(args.retrieval_profile)
    cross_encoder_aliases = {
        "cross_encoder",
        "cross-encoder",
        "sentence_transformers",
        "sentence-transformers",
    }

    try:
        effective = apply_retrieval_profile_overrides(
            profile=profile,
            top_k=int(args.top_k or 0),
            score_threshold=float(args.score_threshold or 0.0),
            retrieval_mode=str(args.retrieval_mode or "hybrid"),
            enable_reranker=bool(args.enable_reranker),
            reranker_provider=str(args.reranker_provider or ""),
            reranker_top_n=int(args.reranker_top_n or 0),
            enable_weight_rerank=bool(args.enable_weight_rerank),
        )
    except Exception as exc:  # noqa: BLE001
        issues.append(f"invalid retrieval profile configuration: {str(exc)}")
        effective = {
            "retrieval_profile": profile,
            "top_k": int(args.top_k or 0),
            "score_threshold": float(args.score_threshold or 0.0),
            "retrieval_mode": str(args.retrieval_mode or "hybrid"),
            "enable_reranker": bool(args.enable_reranker),
            "reranker_provider": str(args.reranker_provider or ""),
            "reranker_top_n": int(args.reranker_top_n or 0),
            "enable_weight_rerank": bool(args.enable_weight_rerank),
        }

    requested_provider = str(args.reranker_provider or "").strip().lower()
    requested_enable_reranker = bool(args.enable_reranker)
    requested_top_n = int(args.reranker_top_n or 0)

    effective_provider = str(effective.get("reranker_provider") or "").strip().lower()
    provider_meta = describe_reranker_provider(effective_provider or None)
    provider_norm = str(provider_meta.get("provider") or effective_provider or "").strip().lower()
    provider_tier = str(provider_meta.get("tier") or "").strip().lower()
    effective_enable_reranker = bool(effective.get("enable_reranker"))
    effective_top_n = int(effective.get("reranker_top_n") or 0)

    # Profile contract checks (fail-fast, actionable).
    if profile == "hybrid_ce":
        if not requested_enable_reranker:
            issues.append("hybrid_ce requires --enable-reranker=true")
        if requested_provider and requested_provider not in cross_encoder_aliases:
            issues.append(
                "hybrid_ce only supports cross_encoder family rerankers. "
                f"received --reranker-provider={requested_provider}; expected cross_encoder."
            )
        if requested_top_n <= 0:
            issues.append("hybrid_ce requires --reranker-top-n > 0")

    if effective_enable_reranker:
        if provider_norm in {"none", "off", "false", "0"} or provider_tier == "disabled":
            issues.append("enable_reranker=true is incompatible with a disabled reranker provider")
        if effective_top_n <= 0:
            issues.append("enable_reranker=true requires reranker_top_n > 0")

    result = {
        "schema": "mimirq.retrieval_profile_compat.v1",
        "compatible": len(issues) == 0,
        "issues": issues,
        "requested": {
            "retrieval_profile": profile,
            "retrieval_mode": str(args.retrieval_mode or ""),
            "top_k": int(args.top_k or 0),
            "score_threshold": float(args.score_threshold or 0.0),
            "enable_reranker": requested_enable_reranker,
            "reranker_provider": requested_provider or None,
            "reranker_top_n": requested_top_n,
        },
        "effective": {
            "retrieval_profile": effective.get("retrieval_profile"),
            "retrieval_mode": effective.get("retrieval_mode"),
            "top_k": int(effective.get("top_k") or 0),
            "score_threshold": float(effective.get("score_threshold") or 0.0),
            "enable_reranker": effective_enable_reranker,
            "reranker_provider": provider_norm or None,
            "reranker_tier": provider_tier or None,
            "reranker_top_n": effective_top_n,
            "enable_weight_rerank": bool(effective.get("enable_weight_rerank", True)),
        },
    }
    return issues, result


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    issues, result = _collect_issues(args)

    if args.json:
        payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if issues:
            print(payload, file=sys.stderr)
        else:
            print(payload)
    else:
        if issues:
            print("Incompatible retrieval profile configuration:", file=sys.stderr)
            for item in issues:
                print(f"- {item}", file=sys.stderr)
        else:
            print("Compatible retrieval profile configuration.")
            print(
                "Effective:",
                f"profile={result['effective']['retrieval_profile']},",
                f"mode={result['effective']['retrieval_mode']},",
                f"reranker={result['effective']['reranker_provider']},",
                f"top_n={result['effective']['reranker_top_n']}",
            )

    return 2 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
