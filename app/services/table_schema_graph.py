
import math
from typing import Any

from app.core.config import settings
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


def _safe_positive_int(value: Any) -> int | None:
    try:
        iv = int(value) if value is not None else None
    except Exception:
        return None
    if iv is None or iv <= 0:
        return None
    return int(iv)


def _sample_column_selectivity(*, rows: list[dict[str, Any]] | None, column_name: str) -> float | None:
    col = str(column_name or "").strip()
    if not col:
        return None
    sample = [r for r in (rows or []) if isinstance(r, dict)][:50]
    if not sample:
        return None

    values: list[str] = []
    for row in sample:
        if col not in row:
            continue
        raw = row.get(col)
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        key = s.casefold() if s.isascii() else s
        values.append(key)
    if not values:
        return None
    uniq = len(set(values))
    total = len(values)
    if total <= 0:
        return None
    return min(1.0, max(0.0, float(uniq) / float(total)))


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


def _cost_model_penalties(
    *,
    left_row_count: int | None,
    right_row_count: int | None,
    left_sample_rows: list[dict[str, Any]] | None,
    right_sample_rows: list[dict[str, Any]] | None,
    left_column: str,
    right_column: str,
) -> tuple[list[str], float, dict[str, Any]]:
    if not bool(getattr(settings, "TABLE_TAG_COST_MODEL_ENABLED", True)):
        return [], 0.0, {"enabled": False}

    penalties: list[str] = []
    total = 0.0
    signals: dict[str, Any] = {"enabled": True}

    # 1) Fanout risk: strongly imbalanced table sizes increase many-to-many join risk.
    fanout_ratio: float | None = None
    if left_row_count and right_row_count and left_row_count > 0 and right_row_count > 0:
        fanout_ratio = float(max(left_row_count, right_row_count)) / float(min(left_row_count, right_row_count))
        fanout_ratio = max(1.0, float(fanout_ratio))
        signals["fanout_ratio"] = round(float(fanout_ratio), 6)
        alert = float(getattr(settings, "TABLE_TAG_COST_FANOUT_RATIO_ALERT", 20.0) or 20.0)
        alert = max(1.0, float(alert))
        if fanout_ratio >= alert:
            weight = float(getattr(settings, "TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT", 0.08) or 0.08)
            over = (fanout_ratio / alert) - 1.0
            penalty = min(0.45, max(0.0, float(over) * float(weight)))
            if penalty > 0:
                penalties.append("high_join_fanout")
                total += penalty
                signals["fanout_penalty"] = round(float(penalty), 6)

    # 2) Selectivity risk: low distinctness in join keys implies broad join expansion.
    left_sel = _sample_column_selectivity(rows=left_sample_rows, column_name=left_column)
    right_sel = _sample_column_selectivity(rows=right_sample_rows, column_name=right_column)
    if left_sel is not None:
        signals["left_selectivity"] = round(float(left_sel), 6)
    if right_sel is not None:
        signals["right_selectivity"] = round(float(right_sel), 6)

    selectivity_candidates = [v for v in (left_sel, right_sel) if v is not None]
    if selectivity_candidates:
        min_selectivity = min(float(v) for v in selectivity_candidates)
        threshold = float(getattr(settings, "TABLE_TAG_COST_SELECTIVITY_MIN", 0.2) or 0.2)
        threshold = min(1.0, max(0.0, float(threshold)))
        signals["selectivity_threshold"] = round(float(threshold), 6)
        if min_selectivity < threshold and threshold > 0.0:
            weight = float(getattr(settings, "TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT", 0.12) or 0.12)
            gap_ratio = (threshold - min_selectivity) / threshold
            # Add mild log scaling so extreme low-selectivity joins are clearly penalized.
            penalty = min(0.45, max(0.0, math.log1p(gap_ratio) * float(weight) * 2.0))
            if penalty > 0:
                penalties.append("low_join_selectivity")
                total += penalty
                signals["selectivity_penalty"] = round(float(penalty), 6)

    return penalties, round(float(total), 6), signals


def _pick_best_relationship_between(
    *,
    left_table: str,
    left_aliases: list[str] | None,
    left_columns: list[dict[str, Any]],
    left_row_count: int | None,
    left_sample_rows: list[dict[str, Any]] | None,
    right_table: str,
    right_aliases: list[str] | None,
    right_columns: list[dict[str, Any]],
    right_row_count: int | None,
    right_sample_rows: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    left_col_names = _safe_col_names(left_columns)
    right_col_names = _safe_col_names(right_columns)
    if not left_col_names or not right_col_names:
        return None

    left_bases = _alias_bases(left_table, left_aliases)
    right_bases = _alias_bases(right_table, right_aliases)
    best: dict[str, Any] | None = None

    def _build_candidate(
        *,
        left_table_name: str,
        left_column_name: str,
        right_table_name: str,
        right_column_name: str,
        confidence: float,
        reason: str,
        left_rows: int | None,
        right_rows: int | None,
        left_samples: list[dict[str, Any]] | None,
        right_samples: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        base_penalties, base_penalty_score = _edge_penalties(
            left_column=left_column_name,
            right_column=right_column_name,
            left_table=left_table_name,
            right_table=right_table_name,
        )
        cost_penalties, cost_penalty_score, cost_signals = _cost_model_penalties(
            left_row_count=left_rows,
            right_row_count=right_rows,
            left_sample_rows=left_samples,
            right_sample_rows=right_samples,
            left_column=left_column_name,
            right_column=right_column_name,
        )
        penalties = list(base_penalties)
        for p in cost_penalties:
            if p not in penalties:
                penalties.append(p)
        penalty_score = round(float(base_penalty_score) + float(cost_penalty_score), 6)
        return {
            "left_table": left_table_name,
            "left_column": left_column_name,
            "right_table": right_table_name,
            "right_column": right_column_name,
            "confidence": round(float(confidence), 6),
            "reason": str(reason or "").strip(),
            "penalties": penalties,
            "penalty_score": penalty_score,
            "base_penalty_score": round(float(base_penalty_score), 6),
            "cost_penalty_score": round(float(cost_penalty_score), 6),
            "cost_signals": dict(cost_signals or {}),
            "left_row_count": left_rows,
            "right_row_count": right_rows,
        }

    def _update(candidate: dict[str, Any]) -> None:
        nonlocal best
        if best is None:
            best = candidate
            return
        cand_score = float(candidate.get("confidence") or 0.0) - float(candidate.get("penalty_score") or 0.0)
        best_score = float(best.get("confidence") or 0.0) - float(best.get("penalty_score") or 0.0)
        if cand_score > best_score:
            best = candidate
            return
        if cand_score == best_score and float(candidate.get("confidence") or 0.0) > float(best.get("confidence") or 0.0):
            best = candidate

    for l_raw in left_col_names:
        for r_raw in right_col_names:
            ln = _normalize_ident(l_raw)
            rn = _normalize_ident(r_raw)
            if not ln or not rn:
                continue

            if ln == rn and _is_likely_key_column(ln):
                _update(
                    _build_candidate(
                        left_table_name=left_table,
                        left_column_name=l_raw,
                        right_table_name=right_table,
                        right_column_name=r_raw,
                        confidence=0.96,
                        reason="same_key_name",
                        left_rows=left_row_count,
                        right_rows=right_row_count,
                        left_samples=left_sample_rows,
                        right_samples=right_sample_rows,
                    )
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
                    _update(
                        _build_candidate(
                            left_table_name=left_table,
                            left_column_name=l_raw,
                            right_table_name=right_table,
                            right_column_name=r_raw,
                            confidence=conf,
                            reason=reason,
                            left_rows=left_row_count,
                            right_rows=right_row_count,
                            left_samples=left_sample_rows,
                            right_samples=right_sample_rows,
                        )
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
                    _update(
                        _build_candidate(
                            left_table_name=right_table,
                            left_column_name=r_raw,
                            right_table_name=left_table,
                            right_column_name=l_raw,
                            confidence=conf,
                            reason=reason,
                            left_rows=right_row_count,
                            right_rows=left_row_count,
                            left_samples=right_sample_rows,
                            right_samples=left_sample_rows,
                        )
                    )

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
        aliases = [str(v) for v in (raw.get("table_aliases") or []) if str(v).strip()]
        row_count = _safe_positive_int(raw.get("row_count"))
        sample_rows_raw = raw.get("sample_rows")
        sample_rows = [r for r in sample_rows_raw if isinstance(r, dict)] if isinstance(sample_rows_raw, list) else []
        normalized.append(
            {
                "table_name": tname,
                "table_aliases": aliases,
                "columns": [c for c in cols if isinstance(c, dict)],
                "row_count": row_count,
                "sample_rows": sample_rows[:50],
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
                left_row_count=_safe_positive_int(left.get("row_count")),
                left_sample_rows=list(left.get("sample_rows") or []),
                right_table=str(right.get("table_name") or ""),
                right_aliases=list(right.get("table_aliases") or []),
                right_columns=list(right.get("columns") or []),
                right_row_count=_safe_positive_int(right.get("row_count")),
                right_sample_rows=list(right.get("sample_rows") or []),
            )
            if rel:
                edges.append(rel)

    edges.sort(
        key=lambda r: (
            -(float(r.get("confidence") or 0.0) - float(r.get("penalty_score") or 0.0)),
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
    return [dict(e) for e in (graph.get("edges") or [])]


def score_join_plan_candidates(
    *,
    tables: list[dict[str, Any]],
    top_n: int,
    ambiguity_score_gap: float,
) -> dict[str, Any]:
    graph = build_table_schema_graph(tables=tables)
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
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
                "base_penalty_score": round(float(e.get("base_penalty_score") or 0.0), 6),
                "cost_penalty_score": round(float(e.get("cost_penalty_score") or 0.0), 6),
                "penalties": [str(v) for v in (e.get("penalties") or []) if str(v).strip()][:8],
                "cost_signals": dict(e.get("cost_signals") or {}),
                "join": {
                    "left_table": left_table,
                    "left_column": left_col,
                    "right_table": right_table,
                    "right_column": right_col,
                    "confidence": round(confidence, 6),
                    "reason": str(e.get("reason") or "").strip(),
                    "left_row_count": _safe_positive_int(e.get("left_row_count")),
                    "right_row_count": _safe_positive_int(e.get("right_row_count")),
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


def score_multi_join_plan_candidates(
    *,
    tables: list[dict[str, Any]],
    top_n: int,
    ambiguity_score_gap: float,
    max_states: int = 24,
) -> dict[str, Any]:
    """
    Beam-search style multi-join planner scoring (bounded states).

    Returns candidate join paths for 2+ tables. This is deterministic and bounded.
    """
    graph = build_table_schema_graph(tables=tables)
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    if not edges:
        return {
            "graph": graph,
            "candidates": [],
            "selected": None,
            "ambiguous": False,
            "ambiguity_gap": None,
            "states_explored": 0,
            "max_states": max(4, int(max_states or 4)),
        }

    # Reuse pairwise scoring signal as atomic edge scores.
    base = score_join_plan_candidates(
        tables=tables,
        top_n=max(12, len(edges)),
        ambiguity_score_gap=ambiguity_score_gap,
    )
    edge_candidates = [c for c in (base.get("candidates") or []) if isinstance(c, dict)]
    if not edge_candidates:
        return {
            "graph": graph,
            "candidates": [],
            "selected": None,
            "ambiguous": False,
            "ambiguity_gap": None,
            "states_explored": 0,
            "max_states": max(4, int(max_states or 4)),
        }

    beam_limit = max(4, int(max_states or 4))
    table_names = [str(t.get("table_name") or "").strip() for t in (tables or []) if isinstance(t, dict)]
    target_tables = len([t for t in table_names if t])

    # Seed states with each pairwise candidate.
    states: list[dict[str, Any]] = []
    for c in edge_candidates:
        join = c.get("join") if isinstance(c.get("join"), dict) else {}
        left_table = str(join.get("left_table") or "").strip()
        right_table = str(join.get("right_table") or "").strip()
        if not left_table or not right_table:
            continue
        tables_set = {left_table, right_table}
        states.append(
            {
                "joins": [join],
                "join_ids": [str(c.get("candidate_id") or "").strip()],
                "tables": tables_set,
                "score_sum": float(c.get("score") or 0.0),
                "confidence_sum": float(c.get("confidence") or 0.0),
                "penalty_sum": float(c.get("penalty_score") or 0.0),
            }
        )

    def _state_score(state: dict[str, Any]) -> float:
        joins_n = max(1, int(len(list(state.get("joins") or []))))
        avg_score = float(state.get("score_sum") or 0.0) / float(joins_n)
        # Mild preference for wider table coverage.
        coverage_bonus = 0.01 * float(len(set(state.get("tables") or set())))
        return round(avg_score + coverage_bonus, 6)

    def _state_sort_key(state: dict[str, Any]) -> tuple[Any, ...]:
        join_ids = [str(v) for v in (state.get("join_ids") or []) if str(v).strip()]
        return (
            -_state_score(state),
            -int(len(set(state.get("tables") or set()))),
            ",".join(sorted(join_ids)),
        )

    states.sort(key=_state_sort_key)
    states = states[:beam_limit]
    states_explored = int(len(states))

    max_hops = max(1, min(int(target_tables) - 1 if target_tables > 1 else 1, int(beam_limit)))
    for _depth in range(2, max_hops + 1):
        expanded: list[dict[str, Any]] = []
        for state in states:
            current_tables = set(state.get("tables") or set())
            current_join_ids = {str(v) for v in (state.get("join_ids") or []) if str(v).strip()}
            for c in edge_candidates:
                cid = str(c.get("candidate_id") or "").strip()
                if not cid or cid in current_join_ids:
                    continue
                join = c.get("join") if isinstance(c.get("join"), dict) else {}
                left_table = str(join.get("left_table") or "").strip()
                right_table = str(join.get("right_table") or "").strip()
                if not left_table or not right_table:
                    continue
                candidate_tables = {left_table, right_table}
                # Must connect to the current path and add at least one new table.
                if not (candidate_tables & current_tables):
                    continue
                if candidate_tables.issubset(current_tables):
                    continue

                new_state = {
                    "joins": list(state.get("joins") or []) + [join],
                    "join_ids": list(state.get("join_ids") or []) + [cid],
                    "tables": set(current_tables | candidate_tables),
                    "score_sum": float(state.get("score_sum") or 0.0) + float(c.get("score") or 0.0),
                    "confidence_sum": float(state.get("confidence_sum") or 0.0) + float(c.get("confidence") or 0.0),
                    "penalty_sum": float(state.get("penalty_sum") or 0.0) + float(c.get("penalty_score") or 0.0),
                }
                expanded.append(new_state)

        if not expanded:
            break
        expanded.sort(key=_state_sort_key)
        states = expanded[:beam_limit]
        states_explored += len(expanded)

    candidates: list[dict[str, Any]] = []
    for st in states:
        joins = [j for j in (st.get("joins") or []) if isinstance(j, dict)]
        if not joins:
            continue
        join_ids = [str(v) for v in (st.get("join_ids") or []) if str(v).strip()]
        if not join_ids:
            continue
        joins_n = max(1, len(joins))
        score_avg = float(st.get("score_sum") or 0.0) / float(joins_n)
        confidence_avg = float(st.get("confidence_sum") or 0.0) / float(joins_n)
        penalty_avg = float(st.get("penalty_sum") or 0.0) / float(joins_n)
        selected_tables = sorted(str(v) for v in set(st.get("tables") or set()) if str(v).strip())
        candidates.append(
            {
                "candidate_id": stable_hash("->".join(sorted(join_ids)), length=16),
                "score": round(float(score_avg), 6),
                "confidence": round(float(confidence_avg), 6),
                "penalty_score": round(float(penalty_avg), 6),
                "joins": joins,
                "selected_tables": selected_tables,
                "hop_count": int(len(joins)),
            }
        )

    candidates.sort(
        key=lambda c: (
            -float(c.get("score") or 0.0),
            -int(len(list(c.get("selected_tables") or []))),
            str(c.get("candidate_id") or ""),
        )
    )
    n = max(1, int(top_n or 1))
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
        "states_explored": int(states_explored),
        "max_states": int(beam_limit),
    }


__all__ = [
    "build_table_schema_graph",
    "infer_schema_relationships_for_tables",
    "score_multi_join_plan_candidates",
    "score_join_plan_candidates",
]
