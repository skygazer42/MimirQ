"""
Graph embeddings for KG search (offline/deterministic).

Wave16 goal:
- Provide a node2vec-like structural signal for entity recall when vector recall (Milvus + text embeddings)
  is unavailable/disabled.
- Must be deterministic, offline, and safe to run in CI.

Implementation notes:
- We intentionally avoid heavy third-party deps (networkx/gensim) and avoid any network access.
- The v1 embedding is a lightweight DeepWalk-style random-walk co-occurrence embedding using the
  hashing trick (signed feature hashing) instead of training a skip-gram model.
  This is "node2vec-like" in the sense that it embeds graph structure via random walks,
  while remaining fast and reproducible for small/medium subgraphs.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class WalkHashParams:
    dim: int = 64
    num_walks: int = 8
    walk_length: int = 20
    window_size: int = 5
    seed: int = 42


def _mix32(x: int) -> int:
    """
    Deterministic 32-bit integer mixing (MurmurHash3 finalizer-like).

    Used to assign stable (bucket, sign) pairs for feature hashing without relying on Python's
    randomized `hash()`.
    """
    x &= 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= x >> 16
    return x & 0xFFFFFFFF


def _walkhash_config(*, node_count: int, params: WalkHashParams) -> tuple[int, int, int, int, int]:
    return (
        max(1, int(params.dim or 0)),
        max(0, int(params.num_walks or 0)),
        max(0, int(params.walk_length or 0)),
        max(1, int(params.window_size or 0)),
        int(params.seed or 0),
    )


def _init_hash_buckets(*, node_count: int, dim: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    bucket = np.zeros((node_count,), dtype=np.int32)
    sign = np.ones((node_count,), dtype=np.float32)
    base = _mix32(seed ^ 0x9E3779B9)
    for idx in range(node_count):
        mixed = _mix32(int(idx) ^ int(base))
        bucket[idx] = int(mixed % dim)
        sign[idx] = -1.0 if (mixed & 0x80000000) else 1.0
    return bucket, sign


def _generate_walk(
    *,
    start: int,
    walk_idx: int,
    neighbors: Sequence[Sequence[int]],
    walk_length: int,
    seed: int,
) -> list[int]:
    walk: list[int] = [start]
    cur = start
    for step in range(walk_length):
        nbrs = neighbors[cur]
        if not nbrs:
            break
        mixed = _mix32(seed ^ (start * 0x9E3779B9) ^ (walk_idx * 0x85EBCA6B) ^ (step * 0xC2B2AE35) ^ cur)
        cur = nbrs[int(mixed % len(nbrs))]
        walk.append(cur)
    return walk


def _accumulate_walk_context(
    *,
    emb: np.ndarray,
    walk: Sequence[int],
    bucket: np.ndarray,
    sign: np.ndarray,
    window_size: int,
) -> None:
    walk_len = len(walk)
    if walk_len <= 1:
        return
    for index, center in enumerate(walk):
        left = max(0, index - window_size)
        right = min(walk_len, index + window_size + 1)
        for ctx_index in range(left, right):
            if ctx_index == index:
                continue
            ctx = walk[ctx_index]
            dist = abs(ctx_index - index)
            weight = 1.0 / float(dist)
            emb[center, bucket[ctx]] += float(sign[ctx]) * float(weight)


def _normalize_embeddings(emb: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(emb, axis=1)
    nonzero = norms > 0
    emb[nonzero] = emb[nonzero] / norms[nonzero, None]
    return emb


def compute_walkhash_embeddings(
    *,
    neighbors: Sequence[Sequence[int]],
    params: WalkHashParams,
) -> np.ndarray:
    """
    Compute deterministic random-walk hashing embeddings for all nodes in a graph.

    Args:
        neighbors: adjacency list by integer node index.
        params: embedding params.

    Returns:
        np.ndarray shape (N, dim), L2-normalized rows (rows may be all zeros if isolated).
    """
    node_count = int(len(neighbors))
    dim, num_walks, walk_length, window_size, seed = _walkhash_config(
        node_count=node_count,
        params=params,
    )

    emb = np.zeros((node_count, dim), dtype=np.float32)
    if node_count == 0 or num_walks <= 0 or walk_length <= 0:
        return emb

    bucket, sign = _init_hash_buckets(node_count=node_count, dim=dim, seed=seed)

    # Walk generation + co-occurrence updates.
    # Complexity ~ O(N * num_walks * walk_length * window_size).
    for start in range(node_count):
        if not neighbors[start]:
            continue
        for walk_idx in range(num_walks):
            walk = _generate_walk(
                start=start,
                walk_idx=walk_idx,
                neighbors=neighbors,
                walk_length=walk_length,
                seed=seed,
            )
            _accumulate_walk_context(
                emb=emb,
                walk=walk,
                bucket=bucket,
                sign=sign,
                window_size=window_size,
            )

    return _normalize_embeddings(emb)


def _normalize_adj(adjacency: dict[str, Iterable[str]]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {}
    for src, nbrs in (adjacency or {}).items():
        s = str(src or "").strip()
        if not s:
            continue
        out: list[str] = []
        seen: set[str] = set()
        for nb in nbrs or []:
            t = str(nb or "").strip()
            if not t or t == s:
                continue
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
        out.sort()
        adj[s] = out

    # Ensure neighbor targets exist as keys (isolated nodes still get vectors).
    all_nodes = set(adj.keys())
    for nbrs in adj.values():
        all_nodes.update(nbrs)
    for node in sorted(all_nodes):
        adj.setdefault(node, [])

    return adj


def recall_similar_entity_nodes(
    *,
    adjacency: dict[str, Iterable[str]],
    seed_entity_node_keys: Sequence[str],
    params: WalkHashParams,
    top_k: int,
    min_similarity: float,
    entity_prefix: str = "ent:",
) -> list[dict]:
    """
    Given an adjacency dict and a set of seed entity nodes, return top-K similar entity nodes.

    Notes:
    - Node keys are arbitrary strings. By convention we use:
      - entity nodes: f\"{entity_prefix}{uuid}\"
      - event nodes:  f\"ev:{uuid}\"
    - Similarity is cosine similarity in embedding space, clamped to [0, 1].

    Returns:
        List of {\"node_key\", \"similarity\", \"seed_node_key\"}.
    """
    adj = _normalize_adj(adjacency)
    seeds = [str(s or "").strip() for s in (seed_entity_node_keys or []) if str(s or "").strip()]
    seeds = sorted(set(seeds))
    if not adj or not seeds:
        return []

    nodes = sorted(adj.keys())
    idx_by_node = {n: i for i, n in enumerate(nodes)}
    neighbors_idx: list[list[int]] = []
    for n in nodes:
        nbrs = [idx_by_node[t] for t in adj.get(n, []) if t in idx_by_node]
        neighbors_idx.append(nbrs)

    seed_idx: list[int] = [idx_by_node[s] for s in seeds if s in idx_by_node]
    if not seed_idx:
        return []

    entity_nodes = [n for n in nodes if n.startswith(str(entity_prefix))]
    if not entity_nodes:
        return []

    entity_idx = [idx_by_node[n] for n in entity_nodes]
    candidate_idx = [i for i in entity_idx if i not in set(seed_idx)]
    if not candidate_idx:
        return []

    emb = compute_walkhash_embeddings(neighbors=neighbors_idx, params=params)

    seed_mat = emb[np.array(seed_idx, dtype=np.int32)]
    cand_mat = emb[np.array(candidate_idx, dtype=np.int32)]
    if seed_mat.size == 0 or cand_mat.size == 0:
        return []

    sims = cand_mat @ seed_mat.T  # cosine since rows normalized
    best = sims.max(axis=1)
    best_seed = sims.argmax(axis=1)

    hits: list[dict] = []
    for row_idx, cand_i in enumerate(candidate_idx):
        raw = float(best[row_idx])
        sim = max(0.0, min(1.0, raw))
        if sim < float(min_similarity or 0.0):
            continue
        seed_i = int(seed_idx[int(best_seed[row_idx])])
        hits.append(
            {
                "node_key": nodes[cand_i],
                "similarity": sim,
                "seed_node_key": nodes[seed_i],
            }
        )

    # Deterministic order: similarity desc, node_key asc.
    hits.sort(key=lambda x: (-float(x.get("similarity", 0.0) or 0.0), str(x.get("node_key") or "")))
    return hits[: max(0, int(top_k or 0))]


def build_entity_event_adjacency(
    *,
    seed_entity_ids: Sequence[str],
    event_ids: Sequence[str],
    event_entity_links: dict[str, Sequence[object]],
    kept_entity_ids: set[str],
    relation_edges: Sequence[tuple[str, str]] | None = None,
) -> dict[str, list[str]]:
    """
    Build adjacency dict for a bipartite Entity<->Event graph with optional Entity<->Entity relation edges.

    This helper is intentionally decoupled from SQLAlchemy so it can be unit-tested easily.
    """
    adj: dict[str, set[str]] = {}
    _add_seed_entity_nodes(adj=adj, seed_entity_ids=seed_entity_ids)
    _add_event_entity_edges(
        adj=adj,
        event_ids=event_ids,
        event_entity_links=event_entity_links,
        kept_entity_ids=kept_entity_ids,
    )
    _add_relation_entity_edges(
        adj=adj,
        relation_edges=relation_edges,
        kept_entity_ids=kept_entity_ids,
    )
    return _freeze_sorted_adjacency(adj)


def _add_undirected_edge(adj: dict[str, set[str]], *, left: str, right: str) -> None:
    if not left or not right or left == right:
        return
    adj.setdefault(left, set()).add(right)
    adj.setdefault(right, set()).add(left)


def _add_seed_entity_nodes(*, adj: dict[str, set[str]], seed_entity_ids: Sequence[str]) -> None:
    for entity_id in seed_entity_ids or []:
        normalized = str(entity_id or "").strip()
        if normalized:
            adj.setdefault(f"ent:{normalized}", set())


def _event_links_for_id(
    *,
    event_entity_links: dict[str, Sequence[object]],
    event_id: object,
    event_node: str,
) -> Sequence[object]:
    raw_event_id = str(event_id)
    return (
        event_entity_links.get(event_node.removeprefix("ev:"))
        or event_entity_links.get(event_node)
        or event_entity_links.get(raw_event_id)
        or []
    )


def _add_event_entity_edges(
    *,
    adj: dict[str, set[str]],
    event_ids: Sequence[str],
    event_entity_links: dict[str, Sequence[object]],
    kept_entity_ids: set[str],
) -> None:
    for event_id in event_ids or []:
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            continue
        event_node = f"ev:{normalized_event}"
        for link in _event_links_for_id(
            event_entity_links=event_entity_links,
            event_id=event_id,
            event_node=event_node,
        ):
            entity_id = str(getattr(link, "entity_id", "") or "").strip()
            if entity_id and entity_id in kept_entity_ids:
                _add_undirected_edge(adj, left=event_node, right=f"ent:{entity_id}")


def _add_relation_entity_edges(
    *,
    adj: dict[str, set[str]],
    relation_edges: Sequence[tuple[str, str]] | None,
    kept_entity_ids: set[str],
) -> None:
    for left, right in relation_edges or []:
        left_id = str(left or "").strip()
        right_id = str(right or "").strip()
        if not left_id or not right_id:
            continue
        if left_id not in kept_entity_ids or right_id not in kept_entity_ids:
            continue
        _add_undirected_edge(adj, left=f"ent:{left_id}", right=f"ent:{right_id}")


def _freeze_sorted_adjacency(adj: dict[str, set[str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, values in adj.items():
        out[str(key)] = sorted(str(value) for value in values if str(value))
    return out
