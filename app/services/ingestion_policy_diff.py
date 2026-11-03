"""
Ingestion policy diff helpers.

Used by precheck "suggest ingestion policy" to show how the suggested policy differs
from the currently configured dataset policy.
"""

import json
from typing import Any

from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionRule


def _canonical_rule(rule: IngestionRule) -> str:
    """
    Convert a rule into a stable string for comparisons.

    We avoid hashing to keep it inspectable in logs when needed.
    """
    obj = rule.model_dump(exclude_none=True)
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def diff_ingestion_policies(before: IngestionPolicy | None, after: IngestionPolicy | None) -> dict[str, Any]:
    before_rules = before.rules if before is not None else []
    after_rules = after.rules if after is not None else []

    before_by_id = {rule.id: rule for rule in before_rules}
    after_by_id = {rule.id: rule for rule in after_rules}

    before_ids = set(before_by_id)
    after_ids = set(after_by_id)

    added = sorted(after_ids - before_ids)
    removed = sorted(before_ids - after_ids)

    changed: list[str] = []
    for rid in sorted(before_ids & after_ids):
        try:
            if _canonical_rule(before_by_id[rid]) != _canonical_rule(after_by_id[rid]):
                changed.append(rid)
        except Exception:
            # Conservative: if comparison fails, mark as changed to avoid false negatives.
            changed.append(rid)

    return {
        "before_rule_count": len(before_rules),
        "after_rule_count": len(after_rules),
        "added_rule_ids": added,
        "removed_rule_ids": removed,
        "changed_rule_ids": sorted(changed),
    }


__all__ = ["diff_ingestion_policies"]
