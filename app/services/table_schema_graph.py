from __future__ import annotations

from typing import Any

from app.rag.core.hashing import stable_hash

_NON_IDENT_RE = r"[^a-z0-9]+"
_GENERIC_NON_KEY_COLUMNS = {
    "name",
    "title",
    "type",
    "status",
    "state",
    "value",
    "amount",
    "price",
    "date",
    "time",
    "timestamp",
    "region",
    "category",
}


def _normalize_ident(value: str) -> str:
    import re

    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    return re.sub(_NON_IDENT_RE, "_", raw).strip("_")


def _singularize(token: str) -> str:
    t = str(token or "").strip()
    if not t:
        return ""
    if t.endswith("ies") and len(t) > 3:
        return t[:-3] + "y"
    if t.endswith("ses") and len(t) > 3:
        return t[:-2]
    if t.endswith("s") and len(t) > 3 and not t.endswith("ss"):
        return t[:-1]
    return t


def _alias_bases(table_name: str, aliases: list[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in [table_name, *list(aliases or [])]:
        s = str(raw or "").strip()
        if not s:
            continue
        s = s.split(".")[0] if s.count(".") == 1 and s.lower().endswith((".csv", ".xls", ".xlsx")) else s
        s = s.split(".")[-1]
        norm = _normalize_ident(s)
        if not norm:
            continue
        parts = [p for p in norm.split("_") if p]
        for p in parts:
            out.add(p)
            out.add(_singularize(p))
        out.add(norm)
        out.add(_singularize(norm))
    return {v for v in out if v}


def _is_likely_key_column(col_name: str) -> bool:
    n = _normalize_ident(col_name)
    if not n:
        return False
    if n in {"id", "uuid"}:
        return True
    if n.endswith("_id"):
        return True
    if n.startswith("id_"):
        return True
    return False


def _safe_col_names(columns: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for c in columns or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        out.append(name)
    return out


def _edge_penalties(*, left_column: str, right_column: str, left_table: str, right_table: str) -> tuple[list[str], float]:
    penalties: list[str] = []
    total = 0.0

    ln = _normalize_ident(left_column)
    rn = _normalize_ident(right_column)
    if ln == rn and ln in _GENERIC_NON_KEY_COLUMNS:
        penalties.append("generic_column_overlap")
        total += 0.2

    if _normalize_ident(left_table) == _normalize_ident(right_table):
        penalties.append("self_join_candidate")
        total += 0.15

    if (not _is_likely_key_column(left_column)) and (not _is_likely_key_column(right_column)):
        penalties.append("non_key_join_columns")
        total += 0.1

    return penalties, round(float(total), 6)


def _pick_best_relationship_between(
    *,
    left_table: str,
    left_aliases: list[str] | None,
    left_columns: list[dict[str, Any]],
    right_table: str,
    right_aliases: list[str] | None,
    right_columns: list[dict[str, Any]],
) -> dict[str, Any] | None:
    left_col_names = _safe_col_names(left_columns)
    right_col_names = _safe_col_names(right_columns)
    if not left_col_names or not right_col_names:
        return None

    left_bases = _alias_bases(left_table, left_aliases)
    right_bases = _alias_bases(right_table, right_aliases)
    best: dict[str, Any] | None = None

    def _update(candidate: dict[str, Any]) -> None:
        nonlocal best
        if best is None or float(candidate.get("confidence") or 0.0) > float(best.get("confidence") or 0.0):
            best = candidate

    for l_raw in left_col_names:
        for r_raw in right_col_names:
            ln = _normalize_ident(l_raw)
            rn = _normalize_ident(r_raw)
            if not ln or not rn:
                continue

            if ln == rn and _is_likely_key_column(ln):
                penalties, penalty_score = _edge_penalties(
                    left_column=l_raw,
                    right_column=r_raw,
                    left_table=left_table,
                    right_table=right_table,
                )
                _update(
                    {
                        "left_table": left_table,
                        "left_column": l_raw,
                        "right_table": right_table,
                        "right_column": r_raw,
                        "confidence": 0.96,
                        "reason": "same_key_name",
                        "penalties": penalties,
                        "penalty_score": penalty_score,
                    }
                )
                continue

            if ln == rn and ln in _GENERIC_NON_KEY_COLUMNS:
                continue

            if ln.endswith("_id"):
                base = ln[: -len("_id")]
                if base and rn in {"id", f"{base}_id"}:
                    conf = 0.90
                    reason = "fk_to_id"
                    if base in right_bases:
                        conf = 0.95
                        reason = "fk_to_table_id"
                    penalties, penalty_score = _edge_penalties(
                        left_column=l_raw,
                        right_column=r_raw,
                        left_table=left_table,
                        right_table=right_table,
                    )
                    _update(
                        {
                            "left_table": left_table,
                            "left_column": l_raw,
                            "right_table": right_table,
                            "right_column": r_raw,
                            "confidence": conf,
                            "reason": reason,
                            "penalties": penalties,
                            "penalty_score": penalty_score,
                        }
                    )
                    continue

            if rn.endswith("_id"):
                base = rn[: -len("_id")]
                if base and ln in {"id", f"{base}_id"}:
                    conf = 0.90
                    reason = "fk_to_id"
                    if base in left_bases:
                        conf = 0.95
                        reason = "fk_to_table_id"
                    penalties, penalty_score = _edge_penalties(
                        left_column=r_raw,
                        right_column=l_raw,
                        left_table=right_table,
                        right_table=left_table,
                    )
                    _update(
                        {
                            "left_table": right_table,
                            "left_column": r_raw,
                            "right_table": left_table,
                            "right_column": l_raw,
                            "confidence": conf,
                            "reason": reason,
                            "penalties": penalties,
                            "penalty_score": penalty_score,
                        }
                    )
                    continue

    return best


def build_table_schema_graph(*, tables: list[dict[str, Any]]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for raw in tables or []:
        if not isinstance(raw, dict):
            continue
        tname = str(raw.get("table_name") or "").strip()
        cols = raw.get("columns")
        if not tname or not isinstance(cols, list):
            continue
        aliases = [str(v) for v in list(raw.get("table_aliases") or []) if str(v).strip()]
        normalized.append(
            {
                "table_name": tname,
                "table_aliases": aliases,
                "columns": [c for c in cols if isinstance(c, dict)],
            }
        )

    edges: list[dict[str, Any]] = []
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            left = normalized[i]
            right = normalized[j]
            rel = _pick_best_relationship_between(
                left_table=str(left.get("table_name") or ""),
                left_aliases=list(left.get("table_aliases") or []),
                left_columns=list(left.get("columns") or []),
                right_table=str(right.get("table_name") or ""),
                right_aliases=list(right.get("table_aliases") or []),
                right_columns=list(right.get("columns") or []),
            )
            if rel:
                edges.append(rel)

    edges.sort(
        key=lambda r: (
            -float(r.get("confidence") or 0.0),
            float(r.get("penalty_score") or 0.0),
            str(r.get("left_table") or ""),
            str(r.get("right_table") or ""),
            str(r.get("left_column") or ""),
            str(r.get("right_column") or ""),
        )
    )
    return {
        "nodes": [str(t.get("table_name") or "") for t in normalized],
        "edges": edges,
    }


def infer_schema_relationships_for_tables(*, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    graph = build_table_schema_graph(tables=tables)
    return [dict(e) for e in list(graph.get("edges") or [])]


def score_join_plan_candidates(
    *,
    tables: list[dict[str, Any]],
    top_n: int,
    ambiguity_score_gap: float,
) -> dict[str, Any]:
    graph = build_table_schema_graph(tables=tables)
    edges = [e for e in list(graph.get("edges") or []) if isinstance(e, dict)]
    candidates: list[dict[str, Any]] = []
    n = max(1, int(top_n or 1))
    for e in edges[: max(n, 12)]:
        confidence = float(e.get("confidence") or 0.0)
        penalty = float(e.get("penalty_score") or 0.0)
        score = round(max(0.0, confidence - penalty), 6)
        left_table = str(e.get("left_table") or "").strip()
        right_table = str(e.get("right_table") or "").strip()
        left_col = str(e.get("left_column") or "").strip()
        right_col = str(e.get("right_column") or "").strip()
        key = f"{left_table}.{left_col}->{right_table}.{right_col}"
        candidates.append(
            {
                "candidate_id": stable_hash(key, length=16),
                "score": score,
                "confidence": round(confidence, 6),
                "penalty_score": round(penalty, 6),
                "penalties": [str(v) for v in list(e.get("penalties") or []) if str(v).strip()][:8],
                "join": {
                    "left_table": left_table,
                    "left_column": left_col,
                    "right_table": right_table,
                    "right_column": right_col,
                    "confidence": round(confidence, 6),
                    "reason": str(e.get("reason") or "").strip(),
                },
                "selected_tables": [left_table, right_table],
            }
        )

    candidates.sort(
        key=lambda c: (
            -float(c.get("score") or 0.0),
            -float(c.get("confidence") or 0.0),
            str((c.get("join") or {}).get("left_table") or ""),
            str((c.get("join") or {}).get("right_table") or ""),
        )
    )
    candidates = candidates[:n]
    selected = candidates[0] if candidates else None

    gap = None
    ambiguous = False
    if len(candidates) >= 2:
        s0 = float(candidates[0].get("score") or 0.0)
        s1 = float(candidates[1].get("score") or 0.0)
        gap = round(float(s0 - s1), 6)
        ambiguous = gap <= max(0.0, float(ambiguity_score_gap or 0.0))

    return {
        "graph": graph,
        "candidates": candidates,
        "selected": selected,
        "ambiguous": bool(ambiguous),
        "ambiguity_gap": gap,
    }


__all__ = [
    "build_table_schema_graph",
    "infer_schema_relationships_for_tables",
    "score_join_plan_candidates",
]
