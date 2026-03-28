# MimirQ-om6n 图数据库选型评估计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decide whether MimirQ needs a native graph database for upcoming KG and community-search work, and if so, choose the first POC target without committing to a premature platform migration.

**Architecture:** Keep PostgreSQL + Milvus as the current system of record for KG facts and vector recall. Evaluate native graph databases as optional read-side accelerators for traversal-heavy or community-oriented queries, not as an immediate replacement for the existing KG storage model.

**Tech Stack:** PostgreSQL, Milvus, existing KG pipeline, Neo4j, NebulaGraph, JanusGraph

---

## Current MimirQ Baseline

Relevant repo anchors:

- `docs/guides/knowledge_graph.md`
  KG facts already live in PostgreSQL, with Milvus used for KG vector recall.
- `app/rag/kg/pipeline.py`
  KG search already exists as application logic.
- `app/rag/kg/search/query_mode.py`
  Query routing already distinguishes `local`, `global`, `drift`, and `auto`.

Current conclusion:

- MimirQ does not currently have a "missing graph database" problem in the abstract.
- It has a "do we need a better read model for specific graph-style workloads" question.
- That distinction matters, because it changes the evaluation from "what should replace Postgres" to "what should augment the current stack, if anything".

## Options Compared

| Option | Use it for | Strengths | Weaknesses | Recommendation |
| --- | --- | --- | --- | --- |
| A. Stay on PostgreSQL + Milvus only | Current KG search, evidence-backed graph recall | Lowest ops complexity; no migration risk; already implemented | Limited ergonomics for deeper traversal, graph algorithms, and exploratory community search | Baseline, but not sufficient as the only decision |
| B. Neo4j as read-side replica | Traversals, neighborhood exploration, community debug, graph-centric POC queries | Fastest path to developer productivity; mature graph query model and tooling | Additional sync path; product/licensing review needed before broad adoption | Recommended first POC target if native graph DB is required |
| C. NebulaGraph | Larger-scale distributed graph workloads | Better scale story if graph becomes very large and graph-first workloads dominate | Higher operational complexity and weaker team familiarity | Keep as second-stage option |
| D. JanusGraph | Custom large-scale graph deployments with pluggable backends | Flexible architecture on paper | Highest operational complexity and most moving parts | Reject as first choice |

## Recommendation

Recommendation in two parts:

1. Short term
   Keep PostgreSQL + Milvus as the source of truth. Do not migrate KG persistence yet.

2. If a native graph DB POC is needed
   Use Neo4j first, but only as a derived read model for a narrow query class:
   - path / neighborhood exploration,
   - community search inspection,
   - global or drift-style exploratory graph queries that are awkward in the current relational model.

This recommendation is intentionally conservative because the repo already has working KG behavior. A migration should be justified by measured pain, not by architectural taste.

## Why Neo4j First

Neo4j is the best first POC candidate because it minimizes time-to-learning:

- query ergonomics are clear for graph-shaped experiments;
- it supports the kind of "show me nearby nodes / communities / relationships" debugging that research phases need;
- it is much easier to validate whether graph-native traversal actually improves MimirQ's KG use cases;
- and it lets us prove or disprove the need for a graph DB before building a large dual-write architecture.

## Why Not NebulaGraph or JanusGraph First

NebulaGraph may become relevant later if MimirQ proves it needs a distributed graph store at much larger scale, but it is not the best first decision vehicle because:

- the team first needs product learning, not cluster-scale graph ops;
- the POC questions are about usefulness of graph-native read patterns, not maximum distributed throughput.

JanusGraph is a poor first choice because:

- it adds the most operational surface area;
- it requires more backend/index coordination;
- and it does not shorten the path from "question" to "evidence".

## Minimum POC Boundary

The first POC should not be a migration. It should be a replica experiment.

POC boundary:

- one or two representative datasets only;
- export or sync derived KG entities, events, and relations into the graph DB;
- no dual-write requirement for online ingestion;
- no production read path cutover;
- query battery limited to:
  - 1-hop and 2-hop neighborhood exploration,
  - community expansion/debug,
  - a small set of `global` and `drift` query patterns that are hard to express in the current stack.

Success criteria:

- graph-native queries are clearly easier or faster to express;
- the read replica stays derivable from current KG facts without schema chaos;
- and the graph DB reveals concrete product value that the existing stack cannot deliver cheaply enough.

## Required Dependencies and Data

1. Derived graph export contract
   Define how `kg_entities`, `kg_source_events`, `kg_event_entities`, and `kg_relations` become graph nodes/edges.

2. Query battery
   Build a representative set of graph-heavy questions from current KG workloads, not synthetic demos only.

3. Sync model
   Start with batch export or periodic snapshot sync. Avoid online dual writes until the read-model value is proven.

4. Measurement
   Compare:
   - query complexity to implement,
   - traversal latency,
   - data freshness lag,
   - operator burden.

## Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Premature migration | Could add major ops burden without user-visible gain | Keep POC read-only and derived |
| Sync drift | Graph replica may diverge from Postgres facts | Use snapshot/versioned exports first |
| Schema mismatch | Current KG is evidence-centric, not purely graph-native | Preserve provenance fields in replica model |
| Tooling bias | Easy demos can exaggerate value | Use real MimirQ global/drift/local questions |
| Licensing / deployment review | Could block later production use | Treat this as an explicit evaluation dimension up front |

## Rollout Steps

### Phase 1: Decision memo and schema sketch

- Freeze the POC query battery.
- Define a derived graph schema from current KG tables.
- Decide whether Neo4j desktop/local or managed dev environment is sufficient.

### Phase 2: Batch replica

- Export one tenant/dataset snapshot.
- Load it into Neo4j.
- Reproduce representative graph traversals and community lookups.

### Phase 3: Product fit review

- Compare whether the graph DB materially helps:
  - community search,
  - drift exploration,
  - graph explainability/debugging,
  - future read APIs.

### Phase 4: Re-evaluate the need for broader adoption

Only after the replica POC succeeds should the team decide whether to:

- keep graph DB as an internal research/debug tool,
- use it only for community/global search reads,
- or reject it and continue on Postgres + Milvus.

## What Would Justify Closing `MimirQ-om6n`

This issue can be closed once the team has:

- a ranked decision, with Neo4j first and clear reasons against the alternatives;
- an explicit statement that Postgres + Milvus remains the source of truth for now;
- a bounded read-side POC definition;
- follow-on execution tickets for export/sync and query evaluation if the POC is approved.

## References

- Neo4j vector index / Cypher docs: `https://neo4j.com/docs/`
- NebulaGraph docs: `https://docs.nebula-graph.io/`
- JanusGraph docs: `https://docs.janusgraph.org/master/index-backend/`
