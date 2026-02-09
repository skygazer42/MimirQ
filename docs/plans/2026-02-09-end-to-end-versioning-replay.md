# End-to-End Versioning: Pipeline Keys, Artifact Manifests, and Replay Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Full traceability and replay across the entire ingestion->retrieval pipeline. For any citation returned by retrieval, we must be able to answer:
- Which raw source bytes produced this content?
- Which parsing backend/version produced the parse artifacts?
- Which governance rules/version modified content?
- Which chunker/version produced chunk boundaries and metadata?
- Which embedding space/version produced vectors?
- Which index version contains this entry?

**Principle:** Everything is addressed by stable keys; any change in processing that can change retrieval must change a versioned key.

---

### Task 1: Define canonical identifiers and a pipeline key contract

**Files:**
- Add: `app/core/pipeline_keys.py`
- Modify: `app/db/models/document.py` (or metadata schema)
- Test: `tests/test_pipeline_key_contract.py` (new)

**Step 1: Define keys**

Implement stable identifiers:
- `source_sha256`: sha256 of raw bytes (or canonical download bytes if remote)
- `source_uri`: where it came from (file path, s3 uri, http url) plus `source_etag` if available
- `parse_backend_id` and `parse_backend_version`
- `governance_pack_id` and `governance_pack_hash`
- `chunker_id` and `chunker_version`
- `embedding_space_id` (model id + config hash)
- `index_id` and `index_version`

Define `pipeline_key` as a deterministic string derived from the above, e.g.:
`pk = sha256(parse_backend_id+parse_backend_version+governance_pack_hash+chunker_version+embedding_space_id+index_version)`

**Step 2: Persist keys**

Persist to document metadata and ensure chunk/vector rows copy the `pipeline_key`.

**Step 3: Tests**

`tests/test_pipeline_key_contract.py` should assert:
- `pipeline_key` changes when any component version changes
- `pipeline_key` is stable for identical inputs

**Step 4: Commit**

```bash
git add app/core/pipeline_keys.py app/db/models/document.py tests/test_pipeline_key_contract.py
git commit -m "feat(versioning): add pipeline key contract for traceability"
```

---

### Task 2: Artifact manifest and audit log per document

**Files:**
- Add: `app/core/artifact_manifest.py`
- Modify: `app/parsing/pipeline.py` (or orchestration) to write manifest entries
- Test: `tests/test_artifact_manifest_written.py` (new)

**Step 1: Define manifest**

Manifest should capture:
- `source_sha256`, `pipeline_key`
- pointers to stored artifacts (parsed json, governed markdown, chunk list, embeddings)
- timestamps and durations
- failures and retry history

**Step 2: Storage**

Store as:
- a DB table `document_artifacts` (preferred) OR
- a JSON blob in document metadata with bounded size + external storage for large payloads

**Step 3: Tests**

Test that a successful parse+govern+chunk writes a manifest with expected fields.

**Step 4: Commit**

```bash
git add app/core/artifact_manifest.py app/parsing/pipeline.py tests/test_artifact_manifest_written.py
git commit -m "feat(versioning): write artifact manifest per document"
```

---

### Task 3: Replay API (deterministic rerun)

**Files:**
- Add: `app/api/v1/replay.py`
- Add: `app/api/schemas/replay.py`
- Test: `tests/test_replay_endpoint_deterministic.py` (new)

**Step 1: Replay endpoint**

Add:
- `POST /api/v1/replay/document/{doc_id}` with optional overrides:
  - `parse_backend_id`
  - `governance_pack_id`
  - `chunker_id`
  - `embedding_space_id`

**Step 2: Determinism**

Replay should:
- lock to specific versions (no "latest" unless explicitly requested)
- produce a new `pipeline_key`
- write a new manifest entry

**Step 3: Tests**

Test two replays with same versions produce identical governed markdown sha and chunk content sha.

**Step 4: Commit**

```bash
git add app/api/v1/replay.py app/api/schemas/replay.py tests/test_replay_endpoint_deterministic.py
git commit -m "feat(api): add deterministic replay endpoint for document pipeline"
```

