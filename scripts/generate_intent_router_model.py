#!/usr/bin/env python3
"""
Generate a compact intent-router model artifact from exported training rows.
"""


import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]{2,64}|[\u4e00-\u9fff]{2,16}")


def _load_training(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    items = raw.get("items") if isinstance(raw, dict) else []
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _TOKEN_RE.finditer(str(text or "")):
        tok = str(m.group(0) or "").strip()
        if not tok:
            continue
        key = tok.casefold() if tok.isascii() else tok
        if key in seen:
            continue
        seen.add(key)
        out.append(tok)
        if len(out) >= 80:
            break
    return out


def _sig(overrides: dict[str, Any]) -> str:
    return json.dumps(overrides, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def generate_model(
    *,
    items: list[dict[str, Any]],
    max_rules: int = 12,
    max_tokens_per_rule: int = 8,
    min_token_support: int = 2,
) -> dict[str, Any]:
    label_count: Counter[str] = Counter()
    label_overrides: dict[str, dict[str, Any]] = {}
    token_counts_by_label: dict[str, Counter[str]] = defaultdict(Counter)

    total_rows = 0
    for item in items:
        query = str(item.get("query") or "").strip()
        overrides = item.get("label_overrides")
        if not query or not isinstance(overrides, dict) or not overrides:
            continue
        total_rows += 1
        signature = _sig(overrides)
        label_count[signature] += 1
        label_overrides[signature] = dict(overrides)
        for tok in _tokenize(query):
            token_counts_by_label[signature][tok] += 1

    if total_rows <= 0:
        return {
            "schema": "mimirq.intent_router_model.v1",
            "version": 1,
            "rules": [],
            "summary": {"rows_total": 0},
        }

    rules: list[dict[str, Any]] = []
    for idx, (signature, support) in enumerate(label_count.most_common(max(1, int(max_rules or 1))), start=1):
        tok_counter = token_counts_by_label.get(signature, Counter())
        tokens = [
            tok
            for tok, freq in tok_counter.most_common(max(1, int(max_tokens_per_rule or 1)))
            if int(freq) >= max(1, int(min_token_support or 1))
        ]
        if not tokens:
            continue
        confidence = min(1.0, max(0.0, float(support) / float(total_rows)))
        min_match = 1 if len(tokens) <= 3 else 2
        rules.append(
            {
                "rule_id": f"r{idx:02d}",
                "tokens": tokens,
                "min_match": int(min_match),
                "confidence": round(float(confidence), 6),
                "weight": 1.0,
                "support": int(support),
                "overrides": dict(label_overrides.get(signature) or {}),
            }
        )

    return {
        "schema": "mimirq.intent_router_model.v1",
        "version": 1,
        "rules": rules,
        "summary": {
            "rows_total": int(total_rows),
            "label_signatures": int(len(label_count)),
            "rules_total": int(len(rules)),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate intent router model from training rows")
    parser.add_argument("--input", required=True, help="Input training JSON path")
    parser.add_argument("--out", required=True, help="Output model JSON path")
    parser.add_argument("--max-rules", type=int, default=12)
    parser.add_argument("--max-tokens-per-rule", type=int, default=8)
    parser.add_argument("--min-token-support", type=int, default=2)
    args = parser.parse_args(argv)

    items = _load_training(Path(args.input))
    model = generate_model(
        items=items,
        max_rules=max(1, int(args.max_rules or 1)),
        max_tokens_per_rule=max(1, int(args.max_tokens_per_rule or 1)),
        min_token_support=max(1, int(args.min_token_support or 1)),
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rules_total": (model.get("summary") or {}).get("rules_total", 0)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

