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
    n = int(len(neighbors))
    dim = max(1, int(params.dim or 0))
    num_walks = max(0, int(params.num_walks or 0))
    walk_length = max(0, int(params.walk_length or 0))
    window_size = max(1, int(params.window_size or 0))
    seed = int(params.seed or 0)

    emb = np.zeros((n, dim), dtype=np.float32)
    if n == 0 or num_walks <= 0 or walk_length <= 0:
        return emb

    # Precompute stable hashing buckets/signs for context nodes.
    bucket = np.zeros((n,), dtype=np.int32)
    sign = np.ones((n,), dtype=np.float32)
    base = _mix32(seed ^ 0x9E3779B9)
    for idx in range(n):
        h = _mix32(int(idx) ^ int(base))
        bucket[idx] = int(h % dim)
        sign[idx] = -1.0 if (h & 0x80000000) else 1.0

    # Walk generation + co-occurrence updates.
    # Complexity ~ O(N * num_walks * walk_length * window_size).
    for start in range(n):
        if not neighbors[start]:
            continue
        for walk_idx in range(num_walks):
            walk: list[int] = [start]
            cur = start
            for step in range(walk_length):
                nbrs = neighbors[cur]
                if not nbrs:
                    break
                # Deterministic pseudo-random neighbor choice without relying on `random` (PRNG hotspot).
                h = _mix32(seed ^ (start * 0x9E3779B9) ^ (walk_idx * 0x85EBCA6B) ^ (step * 0xC2B2AE35) ^ cur)
                cur = nbrs[int(h % len(nbrs))]
                walk.append(cur)

            walk_len = len(walk)
            if walk_len <= 1:
                continue
            for i, center in enumerate(walk):
                left = max(0, i - window_size)
                right = min(walk_len, i + window_size + 1)
                # Update hashed co-occurrence features for center node.
                for j in range(left, right):
                    if j == i:
                        continue
                    ctx = walk[j]
                    dist = abs(j - i)
                    w = 1.0 / float(dist)
                    emb[center, bucket[ctx]] += float(sign[ctx]) * float(w)

    # Normalize (avoid div-by-zero).
    norms = np.linalg.norm(emb, axis=1)
    nonzero = norms > 0
    emb[nonzero] = emb[nonzero] / norms[nonzero, None]
    return emb


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

    def _add(a: str, b: str) -> None:
        if not a or not b or a == b:
            return
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    # Always include seeds as nodes even if isolated.
    for eid in seed_entity_ids or []:
        s = str(eid or "").strip()
        if not s:
            continue
        adj.setdefault(f"ent:{s}", set())

    for ev_id in event_ids or []:
        ev = str(ev_id or "").strip()
        if not ev:
            continue
        ev_node = f"ev:{ev}"
        links = event_entity_links.get(ev) or event_entity_links.get(ev_node) or event_entity_links.get(str(ev_id)) or []
        for link in links:
            # link is expected to have `.entity_id` attribute (KgEventEntity).
            ent_id = str(getattr(link, "entity_id", "") or "").strip()
            if not ent_id or ent_id not in kept_entity_ids:
                continue
            _add(ev_node, f"ent:{ent_id}")

    for a, b in relation_edges or []:
        aa = str(a or "").strip()
        bb = str(b or "").strip()
        if not aa or not bb:
            continue
        if aa not in kept_entity_ids or bb not in kept_entity_ids:
            continue
        _add(f"ent:{aa}", f"ent:{bb}")

    # Convert to list adjacency (sorted for determinism).
    out: dict[str, list[str]] = {}
    for k, v in adj.items():
        out[str(k)] = sorted(str(x) for x in v if str(x))
    return out
