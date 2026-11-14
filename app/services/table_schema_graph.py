import math
import re
from typing import Any, TypedDict

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


class _NormalizedTable(TypedDict):
    table_name: str
    table_aliases: list[str]
    columns: list[dict[str, Any]]
    row_count: int | None
    sample_rows: list[dict[str, Any]]


class _JoinSpec(TypedDict):
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float
    reason: str
    left_row_count: int | None
    right_row_count: int | None


class _RelationshipCandidate(_JoinSpec):
    penalties: list[str]
    penalty_score: float
    base_penalty_score: float
    cost_penalty_score: float
    cost_signals: dict[str, Any]


class _SchemaGraph(TypedDict):
    nodes: list[str]
    edges: list[_RelationshipCandidate]


class _CandidateScore(TypedDict):
    candidate_id: str
    score: float
    confidence: float
    penalty_score: float
    selected_tables: list[str]


class _JoinCandidate(_CandidateScore):
    base_penalty_score: float
    cost_penalty_score: float
    penalties: list[str]
    cost_signals: dict[str, Any]
    join: _JoinSpec


class _JoinPlanResult(TypedDict):
    graph: _SchemaGraph
    candidates: list[_JoinCandidate]
    selected: _JoinCandidate | None
    ambiguous: bool
    ambiguity_gap: float | None


class _MultiJoinState(TypedDict):
    joins: list[_JoinSpec]
    join_ids: list[str]
    tables: set[str]
    score_sum: float
    confidence_sum: float
    penalty_sum: float


class _MultiJoinCandidate(_CandidateScore):
    joins: list[_JoinSpec]
    hop_count: int


class _MultiJoinResult(TypedDict):
    graph: _SchemaGraph
    candidates: list[_MultiJoinCandidate]
    selected: _MultiJoinCandidate | None
    ambiguous: bool
    ambiguity_gap: float | None
    states_explored: int
    max_states: int


def _normalize_ident(value: str) -> str:
    raw = value.strip().casefold()
    if not raw:
        return ""
    return re.sub(_NON_IDENT_RE, "_", raw).strip("_")


def _singularize(token: str) -> str:
    t = token.strip()
    if not t:
        return ""
    if t.endswith("ies") and len(t) > 3:
        return t[:-3] + "y"
    if t.endswith("ses") and len(t) > 3:
        return t[:-2]
    if t.endswith("s") and len(t) > 3 and not t.endswith("ss"):
        return t[:-1]
    return t


def _alias_bases(table_name: str, aliases: list[str]) -> set[str]:
    out: set[str] = set()
    for raw in [table_name, *aliases]:
        s = raw.strip()
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
    for c in columns:
        name = c["name"].strip()
        if not name:
            continue
        out.append(name)
    return out


def _safe_positive_int(value: Any) -> int | None:
    try:
        iv = int(value) if value is not None else None
    except (OverflowError, TypeError, ValueError):
        return None
    if iv is None or iv <= 0:
        return None
    return iv


def _sample_column_selectivity(*, rows: list[dict[str, Any]], column_name: str) -> float | None:
    col = column_name.strip()
    if not col:
        return None
    sample = rows[:50]
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
    return min(1.0, max(0.0, uniq / total))


def _edge_penalties(
    *,
    left_column: str,
    right_column: str,
    left_table: str,
    right_table: str,
) -> tuple[list[str], float]:
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

    return penalties, round(total, 6)


def _build_relationship_candidate(
    *,
    left_table: str,
    left_column: str,
    right_table: str,
    right_column: str,
    confidence: float,
    reason: str,
    left_row_count: int | None,
    right_row_count: int | None,
    left_sample_rows: list[dict[str, Any]],
    right_sample_rows: list[dict[str, Any]],
) -> _RelationshipCandidate:
    base_penalties, base_penalty_score = _edge_penalties(
        left_column=left_column,
        right_column=right_column,
        left_table=left_table,
        right_table=right_table,
    )
    cost_penalties, cost_penalty_score, cost_signals = _cost_model_penalties(
        left_row_count=left_row_count,
        right_row_count=right_row_count,
        left_sample_rows=left_sample_rows,
        right_sample_rows=right_sample_rows,
        left_column=left_column,
        right_column=right_column,
    )
    penalties = list(base_penalties)
    for penalty in cost_penalties:
        if penalty not in penalties:
            penalties.append(penalty)
    penalty_score = round(base_penalty_score + cost_penalty_score, 6)
    return {
        "left_table": left_table,
        "left_column": left_column,
        "right_table": right_table,
        "right_column": right_column,
        "confidence": round(confidence, 6),
        "reason": reason.strip(),
        "penalties": penalties,
        "penalty_score": penalty_score,
        "base_penalty_score": round(base_penalty_score, 6),
        "cost_penalty_score": round(cost_penalty_score, 6),
        "cost_signals": dict(cost_signals),
        "left_row_count": left_row_count,
        "right_row_count": right_row_count,
    }


def _relationship_candidate_score(candidate: _RelationshipCandidate) -> float:
    return candidate["confidence"] - candidate["penalty_score"]


def _prefer_relationship_candidate(
    current: _RelationshipCandidate | None, candidate: _RelationshipCandidate
) -> _RelationshipCandidate:
    if current is None:
        return candidate
    candidate_score = _relationship_candidate_score(candidate)
    current_score = _relationship_candidate_score(current)
    if candidate_score > current_score:
        return candidate
    if candidate_score == current_score:
        candidate_confidence = candidate["confidence"]
        current_confidence = current["confidence"]
        if candidate_confidence > current_confidence:
            return candidate
    return current


def _same_key_relationship_candidate(
    *,
    left_table: str,
    left_column: str,
    left_row_count: int | None,
    left_sample_rows: list[dict[str, Any]],
    right_table: str,
    right_column: str,
    right_row_count: int | None,
    right_sample_rows: list[dict[str, Any]],
    left_norm: str,
    right_norm: str,
) -> _RelationshipCandidate | None:
    if left_norm != right_norm or not _is_likely_key_column(left_norm):
        return None
    return _build_relationship_candidate(
        left_table=left_table,
        left_column=left_column,
        right_table=right_table,
        right_column=right_column,
        confidence=0.96,
        reason="same_key_name",
        left_row_count=left_row_count,
        right_row_count=right_row_count,
        left_sample_rows=left_sample_rows,
        right_sample_rows=right_sample_rows,
    )


def _fk_relationship_candidate(
    *,
    left_table: str,
    left_column: str,
    left_row_count: int | None,
    left_sample_rows: list[dict[str, Any]],
    right_table: str,
    right_column: str,
    right_row_count: int | None,
    right_sample_rows: list[dict[str, Any]],
    left_norm: str,
    right_norm: str,
    target_bases: set[str],
) -> _RelationshipCandidate | None:
    if not left_norm.endswith("_id"):
        return None
    base = left_norm[: -len("_id")]
    if not base or right_norm not in {"id", f"{base}_id"}:
        return None
    confidence = 0.90
    reason = "fk_to_id"
    if base in target_bases:
        confidence = 0.95
        reason = "fk_to_table_id"
    return _build_relationship_candidate(
        left_table=left_table,
        left_column=left_column,
        right_table=right_table,
        right_column=right_column,
        confidence=confidence,
        reason=reason,
        left_row_count=left_row_count,
        right_row_count=right_row_count,
        left_sample_rows=left_sample_rows,
        right_sample_rows=right_sample_rows,
    )


def _best_candidate_for_column_pair(
    *,
    best: _RelationshipCandidate | None,
    left_table: str,
    left_column: str,
    left_row_count: int | None,
    left_sample_rows: list[dict[str, Any]],
    left_bases: set[str],
    right_table: str,
    right_column: str,
    right_row_count: int | None,
    right_sample_rows: list[dict[str, Any]],
    right_bases: set[str],
) -> _RelationshipCandidate | None:
    left_norm = _normalize_ident(left_column)
    right_norm = _normalize_ident(right_column)
    if not left_norm or not right_norm:
        return best

    same_key = _same_key_relationship_candidate(
        left_table=left_table,
        left_column=left_column,
        left_row_count=left_row_count,
        left_sample_rows=left_sample_rows,
        right_table=right_table,
        right_column=right_column,
        right_row_count=right_row_count,
        right_sample_rows=right_sample_rows,
        left_norm=left_norm,
        right_norm=right_norm,
    )
    if same_key is not None:
        return _prefer_relationship_candidate(best, same_key)
    if left_norm == right_norm and left_norm in _GENERIC_NON_KEY_COLUMNS:
        return best

    forward_fk = _fk_relationship_candidate(
        left_table=left_table,
        left_column=left_column,
        left_row_count=left_row_count,
        left_sample_rows=left_sample_rows,
        right_table=right_table,
        right_column=right_column,
        right_row_count=right_row_count,
        right_sample_rows=right_sample_rows,
        left_norm=left_norm,
        right_norm=right_norm,
        target_bases=right_bases,
    )
    if forward_fk is not None:
        return _prefer_relationship_candidate(best, forward_fk)

    reverse_fk = _fk_relationship_candidate(
        left_table=right_table,
        left_column=right_column,
        left_row_count=right_row_count,
        left_sample_rows=right_sample_rows,
        right_table=left_table,
        right_column=left_column,
        right_row_count=left_row_count,
        right_sample_rows=left_sample_rows,
        left_norm=right_norm,
        right_norm=left_norm,
        target_bases=left_bases,
    )
    if reverse_fk is not None:
        return _prefer_relationship_candidate(best, reverse_fk)
    return best


def _cost_model_penalties(
    *,
    left_row_count: int | None,
    right_row_count: int | None,
    left_sample_rows: list[dict[str, Any]],
    right_sample_rows: list[dict[str, Any]],
    left_column: str,
    right_column: str,
) -> tuple[list[str], float, dict[str, Any]]:
    if not settings.TABLE_TAG_COST_MODEL_ENABLED:
        return [], 0.0, {"enabled": False}

    penalties: list[str] = []
    total = 0.0
    signals: dict[str, Any] = {"enabled": True}

    # 1) Fanout risk: strongly imbalanced table sizes increase many-to-many join risk.
    fanout_ratio: float | None = None
    if left_row_count and right_row_count and left_row_count > 0 and right_row_count > 0:
        fanout_ratio = float(max(left_row_count, right_row_count)) / float(min(left_row_count, right_row_count))
        fanout_ratio = max(1.0, fanout_ratio)
        signals["fanout_ratio"] = round(fanout_ratio, 6)
        alert = settings.TABLE_TAG_COST_FANOUT_RATIO_ALERT or 20.0
        alert = max(1.0, alert)
        if fanout_ratio >= alert:
            weight = settings.TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT or 0.08
            over = (fanout_ratio / alert) - 1.0
            penalty = min(0.45, max(0.0, over * weight))
            if penalty > 0:
                penalties.append("high_join_fanout")
                total += penalty
                signals["fanout_penalty"] = round(penalty, 6)

    # 2) Selectivity risk: low distinctness in join keys implies broad join expansion.
    left_sel = _sample_column_selectivity(rows=left_sample_rows, column_name=left_column)
    right_sel = _sample_column_selectivity(rows=right_sample_rows, column_name=right_column)
    if left_sel is not None:
        signals["left_selectivity"] = round(left_sel, 6)
    if right_sel is not None:
        signals["right_selectivity"] = round(right_sel, 6)

    selectivity_candidates = [v for v in (left_sel, right_sel) if v is not None]
    if selectivity_candidates:
        min_selectivity = min(selectivity_candidates)
        threshold = settings.TABLE_TAG_COST_SELECTIVITY_MIN or 0.2
        threshold = min(1.0, max(0.0, threshold))
        signals["selectivity_threshold"] = round(threshold, 6)
        if min_selectivity < threshold and threshold > 0.0:
            weight = settings.TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT or 0.12
            gap_ratio = (threshold - min_selectivity) / threshold
            # Add mild log scaling so extreme low-selectivity joins are clearly penalized.
            penalty = min(0.45, max(0.0, math.log1p(gap_ratio) * weight * 2.0))
            if penalty > 0:
                penalties.append("low_join_selectivity")
                total += penalty
                signals["selectivity_penalty"] = round(penalty, 6)

    return penalties, round(total, 6), signals


def _pick_best_relationship_between(
    *,
    left_table: str,
    left_aliases: list[str],
    left_columns: list[dict[str, Any]],
    left_row_count: int | None,
    left_sample_rows: list[dict[str, Any]],
    right_table: str,
    right_aliases: list[str],
    right_columns: list[dict[str, Any]],
    right_row_count: int | None,
    right_sample_rows: list[dict[str, Any]],
) -> _RelationshipCandidate | None:
    left_col_names = _safe_col_names(left_columns)
    right_col_names = _safe_col_names(right_columns)
    if not left_col_names or not right_col_names:
        return None

    left_bases = _alias_bases(left_table, left_aliases)
    right_bases = _alias_bases(right_table, right_aliases)
    best: _RelationshipCandidate | None = None

    for l_raw in left_col_names:
        for r_raw in right_col_names:
            best = _best_candidate_for_column_pair(
                best=best,
                left_table=left_table,
                left_column=l_raw,
                left_row_count=left_row_count,
                left_sample_rows=left_sample_rows,
                left_bases=left_bases,
                right_table=right_table,
                right_column=r_raw,
                right_row_count=right_row_count,
                right_sample_rows=right_sample_rows,
                right_bases=right_bases,
            )

    return best


def build_table_schema_graph(*, tables: list[dict[str, Any]]) -> _SchemaGraph:
    normalized: list[_NormalizedTable] = []
    for raw in tables:
        if not isinstance(raw, dict):
            continue
        tname = raw["table_name"].strip()
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

    edges: list[_RelationshipCandidate] = []
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            left = normalized[i]
            right = normalized[j]
            rel = _pick_best_relationship_between(
                left_table=left["table_name"],
                left_aliases=left["table_aliases"],
                left_columns=left["columns"],
                left_row_count=left["row_count"],
                left_sample_rows=left["sample_rows"],
                right_table=right["table_name"],
                right_aliases=right["table_aliases"],
                right_columns=right["columns"],
                right_row_count=right["row_count"],
                right_sample_rows=right["sample_rows"],
            )
            if rel:
                edges.append(rel)

    edges.sort(
        key=lambda r: (
            -(r["confidence"] - r["penalty_score"]),
            r["penalty_score"],
            r["left_table"],
            r["right_table"],
            r["left_column"],
            r["right_column"],
        )
    )
    return {
        "nodes": [t["table_name"] for t in normalized],
        "edges": edges,
    }


def score_join_plan_candidates(
    *,
    tables: list[dict[str, Any]],
    top_n: int,
    ambiguity_score_gap: float,
) -> _JoinPlanResult:
    graph = build_table_schema_graph(tables=tables)
    edges = graph["edges"]
    candidates: list[_JoinCandidate] = []
    n = max(1, top_n)
    for e in edges[: max(n, 12)]:
        confidence = e["confidence"]
        penalty = e["penalty_score"]
        score = round(max(0.0, confidence - penalty), 6)
        left_table = e["left_table"]
        right_table = e["right_table"]
        left_col = e["left_column"]
        right_col = e["right_column"]
        key = f"{left_table}.{left_col}->{right_table}.{right_col}"
        candidates.append(
            {
                "candidate_id": stable_hash(key, length=16),
                "score": score,
                "confidence": round(confidence, 6),
                "penalty_score": round(penalty, 6),
                "base_penalty_score": round(e["base_penalty_score"], 6),
                "cost_penalty_score": round(e["cost_penalty_score"], 6),
                "penalties": e["penalties"][:8],
                "cost_signals": dict(e["cost_signals"]),
                "join": {
                    "left_table": left_table,
                    "left_column": left_col,
                    "right_table": right_table,
                    "right_column": right_col,
                    "confidence": round(confidence, 6),
                    "reason": e["reason"],
                    "left_row_count": e["left_row_count"],
                    "right_row_count": e["right_row_count"],
                },
                "selected_tables": [left_table, right_table],
            }
        )

    candidates.sort(
        key=lambda c: (
            -c["score"],
            -c["confidence"],
            c["join"]["left_table"],
            c["join"]["right_table"],
        )
    )
    candidates = candidates[:n]
    selected = candidates[0] if candidates else None

    gap = None
    ambiguous = False
    if len(candidates) >= 2:
        s0 = candidates[0]["score"]
        s1 = candidates[1]["score"]
        gap = round(s0 - s1, 6)
        ambiguous = gap <= max(0.0, ambiguity_score_gap)

    return {
        "graph": graph,
        "candidates": candidates,
        "selected": selected,
        "ambiguous": ambiguous,
        "ambiguity_gap": gap,
    }


def _empty_multi_join_result(*, graph: _SchemaGraph, max_states: int) -> _MultiJoinResult:
    return {
        "graph": graph,
        "candidates": [],
        "selected": None,
        "ambiguous": False,
        "ambiguity_gap": None,
        "states_explored": 0,
        "max_states": max(4, max_states),
    }


def _multi_join_state_score(state: _MultiJoinState) -> float:
    joins_n = len(state["joins"])
    avg_score = state["score_sum"] / joins_n
    coverage_bonus = 0.01 * len(state["tables"])
    return round(avg_score + coverage_bonus, 6)


def _multi_join_state_sort_key(state: _MultiJoinState) -> tuple[Any, ...]:
    join_ids = state["join_ids"]
    return (
        -_multi_join_state_score(state),
        -len(state["tables"]),
        ",".join(sorted(join_ids)),
    )


def _seed_multi_join_states(edge_candidates: list[_JoinCandidate]) -> list[_MultiJoinState]:
    states: list[_MultiJoinState] = []
    for candidate in edge_candidates:
        join = candidate["join"]
        left_table = join["left_table"]
        right_table = join["right_table"]
        states.append(
            {
                "joins": [join],
                "join_ids": [candidate["candidate_id"]],
                "tables": {left_table, right_table},
                "score_sum": candidate["score"],
                "confidence_sum": candidate["confidence"],
                "penalty_sum": candidate["penalty_score"],
            }
        )
    return states


def _expand_multi_join_states(
    *,
    states: list[_MultiJoinState],
    edge_candidates: list[_JoinCandidate],
) -> list[_MultiJoinState]:
    expanded: list[_MultiJoinState] = []
    for state in states:
        current_tables = set(state["tables"])
        current_join_ids = set(state["join_ids"])
        for candidate in edge_candidates:
            candidate_id = candidate["candidate_id"]
            if candidate_id in current_join_ids:
                continue
            join = candidate["join"]
            left_table = join["left_table"]
            right_table = join["right_table"]
            candidate_tables = {left_table, right_table}
            if not (candidate_tables & current_tables):
                continue
            if candidate_tables.issubset(current_tables):
                continue
            expanded.append(
                {
                    "joins": list(state["joins"]) + [join],
                    "join_ids": list(state["join_ids"]) + [candidate_id],
                    "tables": set(current_tables | candidate_tables),
                    "score_sum": state["score_sum"] + candidate["score"],
                    "confidence_sum": state["confidence_sum"] + candidate["confidence"],
                    "penalty_sum": state["penalty_sum"] + candidate["penalty_score"],
                }
            )
    return expanded


def _finalize_multi_join_candidates(
    *,
    states: list[_MultiJoinState],
    top_n: int,
) -> list[_MultiJoinCandidate]:
    candidates: list[_MultiJoinCandidate] = []
    for state in states:
        joins = list(state["joins"])
        join_ids = list(state["join_ids"])
        joins_n = len(joins)
        score_avg = state["score_sum"] / joins_n
        confidence_avg = state["confidence_sum"] / joins_n
        penalty_avg = state["penalty_sum"] / joins_n
        selected_tables = sorted(state["tables"])
        candidates.append(
            {
                "candidate_id": stable_hash("->".join(sorted(join_ids)), length=16),
                "score": round(score_avg, 6),
                "confidence": round(confidence_avg, 6),
                "penalty_score": round(penalty_avg, 6),
                "joins": joins,
                "selected_tables": selected_tables,
                "hop_count": len(joins),
            }
        )
    candidates.sort(
        key=lambda candidate: (
            -candidate["score"],
            -len(candidate["selected_tables"]),
            candidate["candidate_id"],
        )
    )
    return candidates[: max(1, top_n)]


def score_multi_join_plan_candidates(
    *,
    tables: list[dict[str, Any]],
    top_n: int,
    ambiguity_score_gap: float,
    max_states: int = 24,
) -> _MultiJoinResult:
    """
    Beam-search style multi-join planner scoring (bounded states).

    Returns candidate join paths for 2+ tables. This is deterministic and bounded.
    """
    graph = build_table_schema_graph(tables=tables)
    edges = graph["edges"]
    if not edges:
        return _empty_multi_join_result(graph=graph, max_states=max_states)

    # Reuse pairwise scoring signal as atomic edge scores.
    base = score_join_plan_candidates(
        tables=tables,
        top_n=max(12, len(edges)),
        ambiguity_score_gap=ambiguity_score_gap,
    )
    edge_candidates = base["candidates"]
    if not edge_candidates:
        return _empty_multi_join_result(graph=graph, max_states=max_states)

    beam_limit = max(4, max_states)
    table_names = [t["table_name"].strip() for t in tables if isinstance(t, dict)]
    target_tables = len([t for t in table_names if t])

    states = _seed_multi_join_states(edge_candidates)
    states.sort(key=_multi_join_state_sort_key)
    states = states[:beam_limit]
    states_explored = len(states)

    max_hops = max(1, min(target_tables - 1 if target_tables > 1 else 1, beam_limit))
    for _depth in range(2, max_hops + 1):
        expanded = _expand_multi_join_states(states=states, edge_candidates=edge_candidates)
        if not expanded:
            break
        expanded.sort(key=_multi_join_state_sort_key)
        states = expanded[:beam_limit]
        states_explored += len(expanded)

    candidates = _finalize_multi_join_candidates(states=states, top_n=top_n)
    selected = candidates[0] if candidates else None

    gap = None
    ambiguous = False
    if len(candidates) >= 2:
        s0 = candidates[0]["score"]
        s1 = candidates[1]["score"]
        gap = round(s0 - s1, 6)
        ambiguous = gap <= max(0.0, ambiguity_score_gap)

    return {
        "graph": graph,
        "candidates": candidates,
        "selected": selected,
        "ambiguous": ambiguous,
        "ambiguity_gap": gap,
        "states_explored": states_explored,
        "max_states": beam_limit,
    }


__all__ = [
    "build_table_schema_graph",
    "score_multi_join_plan_candidates",
    "score_join_plan_candidates",
]
