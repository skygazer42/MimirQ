# Data Governance: Markdown Normalization + PII/Secrets Scanning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Make the corpus safe and "retrieval-ready": normalize content to a canonical Markdown representation, scan for PII/secrets/copyright-risk patterns, and apply deterministic actions (allow/warn/redact/block) with auditability.

**Principles:**
- Deterministic rules first (regex + structured detectors); LLM only for optional classification.
- All governance decisions are persisted with versioned rule packs.
- Governance happens before chunking/vectorization; blocked content must not enter retrieval.

**Existing hooks to reuse:**
- PII helpers: `app/core/pii_redaction.py`, `app/core/regex_safety.py`

---

### Task 1: Canonical Markdown normalization pipeline

**Files:**
- Add: `app/governance/markdown_normalize.py`
- Modify: `app/parsing/pipeline.py` (or orchestration) to call normalizer
- Test: `tests/test_markdown_normalization_idempotent.py` (new)

**Step 1: Write failing idempotency tests**

Create `tests/test_markdown_normalization_idempotent.py` that asserts:
- Normalizing twice yields identical output (idempotent).
- Headings/lists/code blocks are preserved.
- Hard line wraps are removed in paragraphs but preserved in code blocks.

Run:
```bash
python -m pytest -q tests/test_markdown_normalization_idempotent.py
```
Expected: FAIL.

**Step 2: Implement normalization**

Implement `normalize_markdown(text: str) -> str` with:
- Newline normalization to `\n`
- Trim trailing whitespace
- Collapse 3+ blank lines to 2
- Preserve fenced code blocks exactly
- Optional: normalize tables (if we have a stable table serializer)

Persist normalized output to `doc_metadata.governance.normalized_markdown_sha256` (hash only) and store normalized Markdown in the document content field used for chunking (or an adjacent "normalized" field, depending on model).

**Step 3: Verify**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/governance/markdown_normalize.py app/parsing/pipeline.py tests/test_markdown_normalization_idempotent.py
git commit -m "feat(governance): add canonical markdown normalization"
```

---

### Task 2: Rule-pack based PII + secrets scanning (deterministic)

**Files:**
- Add: `app/governance/rule_packs/base.yaml`
- Add: `app/governance/scanner.py`
- Modify: `app/core/config.py` (enable/disable + actions)
- Test: `tests/test_governance_scanner_rule_pack.py` (new)

**Step 1: Write failing tests**

Create tests with sample strings asserting detections:
- Email, phone, ID-like patterns
- API keys (common providers), JWTs, private keys
- Cloud secrets (AWS access key patterns) via safe regex

Run:
```bash
python -m pytest -q tests/test_governance_scanner_rule_pack.py
```
Expected: FAIL.

**Step 2: Implement scanner**

Implement:
- `load_rule_pack(path) -> RulePack`
- `scan(text, rule_pack) -> list[Finding]` where Finding includes:
  - `rule_id`, `category`, `severity`, `span`, `match_preview`, `action`

Make `span` stable for the normalized Markdown.

**Step 3: Verify**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/governance/rule_packs/base.yaml app/governance/scanner.py app/core/config.py tests/test_governance_scanner_rule_pack.py
git commit -m "feat(governance): add deterministic rule-pack scanner for pii/secrets"
```

---

### Task 3: Enforcement actions (allow/warn/redact/block) with audit trail

**Files:**
- Add: `app/governance/enforcement.py`
- Modify: `app/ingest/indexer.py` (or entrypoint) to apply enforcement before indexing
- Test: `tests/test_governance_enforcement_blocks_indexing.py` (new)

**Step 1: Write failing test**

Test that when a finding has action `block`:
- The document is marked blocked (metadata + status).
- Chunking and vector indexing do not run for that document.

Run:
```bash
python -m pytest -q tests/test_governance_enforcement_blocks_indexing.py
```
Expected: FAIL.

**Step 2: Implement enforcement**

Introduce:
- `GovernanceDecision { rule_pack_version, findings, action_summary }`
- Persist to `doc_metadata.governance`:
  - `rule_pack_id`, `rule_pack_hash`, `decided_at`
  - `findings` (capped size; store full details optionally)
  - `status: allowed|warn|redacted|blocked`

Implement redaction as "structured redaction": replace only matched spans with placeholders (keep stable offsets if feasible).

**Step 3: Verify**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/governance/enforcement.py app/ingest/indexer.py tests/test_governance_enforcement_blocks_indexing.py
git commit -m "feat(governance): enforce scan actions with audit trail"
```

---

### Task 4: Governance reporting + dataset-level visibility

**Files:**
- Modify: `app/services/dataset_profile_service.py` (aggregate blocked/warn counts)
- Modify: `web/app/datasets/[id]/profile/page.tsx` (add governance panel)
- Test: `tests/test_dataset_profile_governance_counts.py` (new)

**Step 1: Add dataset profile fields**

Add counts:
- documents blocked/warn/redacted
- top rule ids (by count)

**Step 2: UI panel**

Add a "Governance" section showing:
- status breakdown
- top rules
- link to a list view (blocked docs)

**Step 3: Commit**

```bash
git add app/services/dataset_profile_service.py web/app/datasets/[id]/profile/page.tsx tests/test_dataset_profile_governance_counts.py
git commit -m "feat(governance): dataset-level reporting and UI visibility"
```

