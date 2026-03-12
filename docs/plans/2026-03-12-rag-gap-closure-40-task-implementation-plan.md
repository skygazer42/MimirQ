# RAG Gap Closure (40 Tasks) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close six backend RAG gaps with deterministic recall contracts, structured DB recall fallback, parse-to-recall diagnostics, strict evidence constraints, feedback automation hooks, and converged default retrieval profile behavior.

**Architecture:** Keep existing retrieval orchestration intact and add opt-in contract switches plus deterministic fallbacks. Favor incremental, test-first changes in `orchestrator`, `chat schema`, and `table tag` bridge modules, then expose behavior through metrics/trace and docs.

**Tech Stack:** FastAPI, Pydantic settings, LangChain retriever orchestration, SQLite TAG bridge, pytest.

---

## Task Index (40 Issues)

1. `MimirQ-upky.1` `G1-01 Contract mode skeleton`
2. `MimirQ-upky.2` `G1-02 Hard fallback setting`
3. `MimirQ-upky.3` `G1-03 Empty-result fallback pass`
4. `MimirQ-upky.4` `G1-04 Fallback trace fields`
5. `MimirQ-upky.5` `G1-05 Fallback config fingerprint`
6. `MimirQ-upky.6` `G1-06 Empty-retrieval diagnosis upgrade`
7. `MimirQ-upky.7` `G1-07 Deterministic fallback tests`
8. `MimirQ-upky.8` `G2-01 Deterministic SQL generator`
9. `MimirQ-upky.9` `G2-02 SQL fallback guard setting`
10. `MimirQ-upky.10` `G2-03 NL2SQL no-key fallback`
11. `MimirQ-upky.11` `G2-04 TAG provenance enrichment`
12. `MimirQ-upky.12` `G2-05 TAG citation evidence keys`
13. `MimirQ-upky.13` `G2-06 TAG selection deterministic tie-break`
14. `MimirQ-upky.14` `G2-07 TAG fallback tests`
15. `MimirQ-upky.15` `G3-01 Parse-quality retrieval settings`
16. `MimirQ-upky.16` `G3-02 Parse-quality risk metrics`
17. `MimirQ-upky.17` `G3-03 Parse-quality trace block`
18. `MimirQ-upky.18` `G3-04 Parse-quality recommendation helper`
19. `MimirQ-upky.19` `G3-05 Dataset profile linkage`
20. `MimirQ-upky.20` `G3-06 Parse-quality diagnostics tests`
21. `MimirQ-upky.21` `G3-07 Docs parse->recall loop`
22. `MimirQ-upky.22` `G4-01 Evidence span strict setting`
23. `MimirQ-upky.23` `G4-02 Citation span filter`
24. `MimirQ-upky.24` `G4-03 Evidence strict metrics`
25. `MimirQ-upky.25` `G4-04 Evidence strict abstain`
26. `MimirQ-upky.26` `G4-05 Claim-check strict default profile`
27. `MimirQ-upky.27` `G4-06 Evidence trace schema bump guard`
28. `MimirQ-upky.28` `G4-07 Evidence strict tests`
29. `MimirQ-upky.29` `G5-01 Hardcase auto-capture setting`
30. `MimirQ-upky.30` `G5-02 Hardcase candidate builder`
31. `MimirQ-upky.31` `G5-03 Hardcase export hook`
32. `MimirQ-upky.32` `G5-04 Hardcase dedupe key`
33. `MimirQ-upky.33` `G5-05 Hardcase tests`
34. `MimirQ-upky.34` `G5-06 Docs feedback automation`
35. `MimirQ-upky.35` `G6-01 Default retrieval profile setting`
36. `MimirQ-upky.36` `G6-02 Chat schema default profile apply`
37. `MimirQ-upky.37` `G6-03 Preserve explicit override semantics`
38. `MimirQ-upky.38` `G6-04 Retrieval profiles endpoint defaults`
39. `MimirQ-upky.39` `G6-05 Default-profile regression tests`
40. `MimirQ-upky.40` `G6-06 Changelog+ops notes`

## Execution Order

1. Retrieval contract and fallback (`.1`-`.7`)
2. DB structured fallback (`.8`-`.14`)
3. Evidence strictness (`.22`-`.28`)
4. Default profile convergence (`.35`-`.39`)
5. Parse->recall diagnostics (`.15`-`.21`)
6. Feedback automation (`.29`-`.34`)
7. Changelog/docs (`.40`)

## Test Strategy

- Unit tests first for each behavior change:
  - Retrieval orchestrator fallback path and trace fields.
  - TAG deterministic SQL fallback.
  - Evidence strict span filtering and abstain.
  - Chat default retrieval profile semantics.
- Focused test runs per module, then targeted integration sanity:
  - `pytest -q tests/test_empty_retrieval_reasons.py ...`
  - `pytest -q tests/test_retrieval_profile_schema.py ...`
  - `pytest -q tests/test_retrieval_profiles_endpoint.py ...`
- Final gate:
  - `make test`
  - If runtime allows: `make verify`

## Deliverables

- Updated backend behavior with opt-in strict contract toggles.
- Extended retrieval metrics/trace for deterministic fallback and evidence strictness.
- Deterministic TAG SQL fallback for no-LLM/no-key scenarios.
- Converged chat default profile policy without breaking explicit request overrides.
- Documentation/changelog updates.
