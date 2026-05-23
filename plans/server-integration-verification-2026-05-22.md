# MimirQ Server Integration Verification Plan

Date: 2026-05-22
Scope: local host and remote/server deployment verification for parser, chunking, governance, knowledge inventory, KG, RAG, prompts, and Docker/env wiring.

## Success Criteria

- Backend and dependency health is green on the active environment: PostgreSQL, Milvus, Redis, uploads path, and configured parser services.
- Root `.env` is the single source for runtime configuration; Docker does not maintain divergent parser/model settings.
- Each parser backend reports either true success with the requested backend or a clear unavailable status. No explicit parser request may silently fall back to `basic`.
- Parser, governance, chunking, knowledge ingestion, KG extraction/search, RAG retrieval/chat, and prompt-backed workflows are tested with real files and real API responses.
- Speed evidence exists for the main production path: parse time, chunk time, ingestion completion, RAG retrieval latency, KG query latency, and end-to-end answer latency.
- Test artifacts are written under `artifacts/` and summarize pass/fail with enough detail to reproduce.
- Code changes are committed with a Lore-style commit after fixes and verification.

## Work Plan

### P0 - Environment and Config Baseline

- Verify local git state, current commit, and uncommitted files.
- Verify backend health and dependency health.
- Verify `.env` active model settings use the intended low-cost model first.
- Verify Docker env usage references root `.env` instead of a separate divergent file.

Evidence target:
- Command output captured in `artifacts/server-integration-verification/`.

### P0 - Parser Matrix Correctness

- Test explicit parser backends: `basic`, `markitdown`, `docling`, `mineru`, `magicpdf`, `paddle_vl`, `textin`.
- Mark each backend as one of:
  - `pass`: returned backend matches requested backend and produced segments
  - `unavailable`: configuration/service unavailable and API says so clearly
  - `fail`: error, timeout, or silent fallback
- Fix silent fallback for explicit parser requests.
- Keep `auto` mode fallback behavior intact.

Evidence target:
- `artifacts/parser-matrix/<timestamp>/report.json`
- Focused tests covering explicit parser fallback behavior

### P1 - Chunking Matrix

- Test every production chunking strategy with Markdown, PDF-derived text, HTML, DOCX, XLSX/CSV, and long text samples.
- Verify chunk count, coverage, overlap, empty chunk count, and persisted metadata.

Evidence target:
- `artifacts/chunking-strategy-matrix/<timestamp>/report.json`

### P1 - Governance Matrix

- Test conservative governance, noise removal, PII/secret masking, profile application, quarantine trigger, and governance-to-chunk transition.
- Verify before/after content and audit records are real backend records.

Evidence target:
- `artifacts/governance-matrix/<timestamp>/report.json`

### P1 - Knowledge and RAG Matrix

- Ingest a mixed corpus into one dataset and one cross-dataset scope.
- Verify inventory filters, dataset isolation, chunk retrieval, citation correctness, and no cross-dataset leakage.
- Measure retrieval P50/P95 and answer latency.

Evidence target:
- `artifacts/rag-matrix/<timestamp>/report.json`

### P1 - KG Matrix

- Verify KG extraction is bounded by sampling/event limits rather than unbounded extraction.
- Test KG search, KG-assisted recall, graph snapshot/query endpoints, and degraded behavior when KG is disabled.
- Measure KG query latency and graph size.

Evidence target:
- `artifacts/kg-matrix/<timestamp>/report.json`

### P2 - Prompt Workflows

- Verify RAG answer prompt, KG extraction prompt, LLM-as-Judge prompt, and test-set generation prompt on real data.
- Confirm outputs are stored or surfaced where product flows expect them.

Evidence target:
- `artifacts/prompt-matrix/<timestamp>/report.json`

### P2 - Remote Server / Docker Verification

- Pull latest code on `/data/MimirQ`.
- Apply root `.env` from the local source of truth.
- Restart Docker services without preserving stale containers.
- Run the same parser, chunking, governance, RAG, and KG smoke tests against the server endpoint.

Evidence target:
- `artifacts/server-integration-verification/<timestamp>/remote-report.json`

### P0 - Product Quality Backlog To Track In This Task

This task also tracks the next quality pass across the product surface. Do not split these into isolated one-off checks unless the evidence is still linked back here.

| Area | Required follow-up | Acceptance evidence |
| --- | --- | --- |
| Parsing | Serviceize MagicPDF instead of relying on API-container local CLI; keep parser tests serial for heavy GPU backends; record requested/resolved backend mismatches as failures. | MagicPDF service health + real PDF parse report; parser matrix with `basic`, `markitdown`, `deepdoc`, `docling`, `mineru`, `etl4llm`, `marker`, `paddle_vl`, `olmocr`, `textin`, `qianfan_ocr`, `magicpdf`. |
| Chunking | Re-run product-relevant chunk strategies on real parsed outputs, not only synthetic preview text; include PDF, Markdown, Office, HTML, and long-document cases. | Chunk report with count, coverage, overlap waste, empty chunks, average length, and persisted metadata checks. |
| KG | Revisit KG event density and sampling policy on real long documents; compare baseline RAG vs KG-assisted RAG before increasing extraction volume. | KG matrix with events/entities/links, extraction latency, query latency, graph size, and answer-quality comparison. |
| Prompt | Validate main answer prompt, KG extraction prompt, judge prompt, and test-set generation prompt with low-cost model defaults first. | Prompt matrix with citations, refusal behavior, JSON/structured-output validity, cost/latency, and failure examples. |
| Knowledge Base | Test knowledge inventory, dataset isolation, document lifecycle, parsed-content view, citations, cross-dataset retrieval boundaries, and delete/purge cleanup. | End-to-end knowledge-base report proving upload -> parse -> chunks -> retrieve/chat -> delete/purge without orphan vector/KG/object assets. |
| Governance | Verify governance profiles/rules before and after chunking, including PII, secrets, duplicate/noise cleanup, HTML/table normalization, and quarantine triggers. | Governance matrix with before/after text, audit records, quarantine state, and retrieval impact. |
| Admin/Permissions | Test admin-only settings, dataset/document permissions, group/ACL paths, access graph export/summary, and denial behavior for non-admin users. | Permission report with allowed/denied cases, no cross-tenant leakage, and settings endpoints requiring the intended role. |

## Current Known Evidence

- Local backend health is green on `127.0.0.1:8000`.
- Latest committed production readiness run exists at `artifacts/production-readiness/rerun-20260522-121334`.
- Remote parser matrix passed after root `.env` parser URLs were aligned to Docker service names:
  `artifacts/parser-matrix/remote-20260522-051241` reported `Calls: 411 | Failures: 0 | Missing: 0`.
- Remote explicit parser sample passed for `basic`, `markitdown`, `docling`, `mineru`, `magicpdf`, `paddle_vl`, and `textin`.
  Detailed artifact: `artifacts/parser-matrix/remote-detail-20260522-052736`.
- Remote live API chain passed on the server through real HTTP API:
  `artifacts/remote-api-chain/remote-api-chain-20260522-055729`.
  The run created dataset `f240f701-1472-4045-b619-b7fe9e8055b2`, uploaded 4 files, completed 4 documents, verified persisted parsed markdown, tested 5 chunk preview strategies, ran KG extraction/search/stats, retrieved 4 RAG citations, and returned a chat answer with status 200 in 0.209s.
- Remote chunk/governance matrix passed:
  `artifacts/chunk-governance-matrix/remote-20260522-063015`.
  The run tested 15 product-relevant chunk strategies through `/api/v1/documents/chunk-preview` and 6 governance preview cases through `/api/v1/pipeline/clean-preview`.
  Governance coverage included PII masking, secret masking, URL normalization, duplicate paragraph cleanup, HTML/table normalization, and low-density drop.
- Remote KG scale guard passed after rebuilding stale API/worker images:
  `artifacts/kg-scale-guard/remote-20260522-072703`.
  The first 12-document run exposed a deployment issue: running API/worker containers were older than `/data/MimirQ` and still used the ARQ default 3 tries, leaving 2 documents pending after retry exhaustion.
  Rebuilt containers now report document max tries 80, KG max tries 80, retry defer 30s, and `/health` is healthy.
  The rerun completed 12/12 documents and 12/12 KG extracts; average extraction was 8.329s, P95 14.868s, max 14.928s. KG stats returned 12 events, 39 entities, 156 links in 0.153s; KG search returned 200 in 0.408s.
- Large-PDF parser verification added an important parser-design follow-up:
  MagicPDF should move to a standalone service like Marker/Paddle-VL/OLMOCR because the API-container local CLI mode is fragile in Docker deployment. Serviceization details are tracked in `plans/magicpdf-serviceization-plan-2026-05-23.md`.
- Remote MagicPDF serviceization is now validated on the server for real PDFs:
  `artifacts/parser-service-matrix/magicpdf-service-final-20260523-000212/report.json`
  proved `parse-preview` resolved `backend=magicpdf` on a 2-page fixture, and
  `artifacts/pdf-performance/magicpdf-service-20260523-000543/report.json`
  proved the 144-page arXiv PDF (`2303.18223`) also resolved `backend=magicpdf`
  in 163.729s with 810,438 markdown chars.
- Full real-PDF chain is now scriptable and has one successful server proof:
  `artifacts/real-pdf-chain/final-20260523-014839/report.json`
  created dataset `fa2c3946-56d2-4853-9d81-97b5a1634501`, uploaded the same 144-page PDF through
  `magicpdf`, persisted document `d7359385-2767-4c09-b18f-c7c4a9ccbb86`, confirmed `670` stored chunks,
  completed default KG extraction in `13.616s`, and returned both baseline chat (`8.09s`) and graph-enabled
  chat (`0.217s`) responses through the live API.
- Dataset/document lifecycle cleanup is now also validated on a real-PDF dataset:
  dataset `f833c04d-e64e-46ac-8773-bc77a81d6ab9` was purged with `POST /api/v1/datasets/{id}/purge?dry_run=false`,
  which deleted `1` document in `1.646s`; a follow-up export returned `0` documents, `/api/v1/kg/stats` returned
  `0 events / 0 entities / 0 links`, and `DELETE /api/v1/datasets/{id}` then returned `204`.
- `remote_real_pdf_chain.py` now proves the same lifecycle automatically:
  `artifacts/real-pdf-chain/cleanup-20260523-022146/report.json`
  completed the 144-page PDF chain end to end and then ran scripted cleanup:
  purge deleted `1` document in `1.327s`, dataset export returned `0` documents,
  KG stats returned zero graph assets, and dataset delete returned `204`.
- Admin/permission verification is now scriptable and its latest server proof covers
  the access-graph endpoints too:
  `artifacts/permission-matrix/access-graph-20260523-025503/report.json`
  proved admin allow for `GET /api/v1/settings/status`, `GET /api/v1/groups/`,
  `GET /api/v1/audit/access-graph/summary`,
  `GET /api/v1/audit/access-graph/export?export_format=json&limit=10`,
  and document ACL management; the same run proved outsider `403` on those
  admin-only routes plus `GET /api/v1/documents/{id}/access` and
  `PUT /api/v1/documents/{id}/access`, and then cleaned up its disposable dataset.
- Governance on real ingestion paths is now scriptable and has one server proof:
  `artifacts/governance-ingest-matrix/remote-20260523-031333/report.json`
  created dataset `af331df5-9b5c-474b-98ff-1f638ccd23eb` and proved five live cases:
  PII masking (`governance_pii_hits.email=1`, `phone=1`), secrets masking
  (`governance_secrets_hits.openai_key=1`), HTML rule-pack cleanup plus table
  normalization (`governance_rule_packs=[web_navigation, web_cookie_banners]`,
  `governance_tables_normalized=1`), duplicate-paragraph cleanup with the noisy
  footer removed from parsed content and retrieval citations, and an outline-only
  document quarantined with `governance_drop_reasons.outline_only=1`. The same
  run also proved retrieval remained available for the four completed cases and
  cleanup deleted all `5` documents, cleared KG stats to zero, and deleted the dataset.
- Prompt workflows are now scriptable and have one server proof:
  `artifacts/prompt-matrix/remote-20260523-034943/report.json`
  created dataset `11aa37b3-9884-4deb-baff-4b7d6efd6edd` and proved all four
  builtin prompt selectors on live product paths: `rag_answer_claude_xml_zh`
  on `/api/v1/rag/prompt-preview` (`2` citations, `1085` prompt chars) and
  `/api/v1/chat` (`2` citations, correct answer about the blue flag),
  `kg_extract_graphrag_zh` on KG extraction (`event_id=1db31a17-b299-47b4-b878-b039c3ae26e6`,
  `kg_prompt_template_key=kg_extract_graphrag_zh`), `testset_generation_ragas_zh`
  on document test generation (`2` generated questions, `2` saved regression cases),
  and `judge_faithfulness_ragas_zh` on the regression LLM judge
  (`run_id=326a5f12-c49b-4f05-8cdd-ca669afe0c7b`, `llm_judge_items=2`,
  summary/item metadata both recorded the expected judge template key). The same
  run also deleted both generated regression cases, purged the dataset documents,
  reset KG stats to zero, and deleted the dataset.
- KG usefulness now has one targeted server proof for graph-helpful question types:
  `artifacts/kg-usefulness-matrix/remote-20260523-044912/report.json`
  created dataset `7c07e419-54a1-48a3-8a6e-d32bdfb4c0ba`, ingested three linked
  documents (`Atlas acquisition` -> `integration lead` -> `Orion migration`),
  and created two grounded regression cases. `/api/v1/kg/search` returned
  `11` clues / `3` events for the acquisition->leader question and `6` clues /
  `2` events for the leader->service question. `/api/v1/evaluations/kg/search/diagnostics`
  then completed run `4aa0ef5e-0a3d-4729-9e3d-93e111ebe3eb` with
  `baseline_hit_rate=1.0`, `baseline_recall=1.0`, and no failure breakdown.
  A later rerun after improving extractive fallback wording strengthened the same
  proof under
  `artifacts/kg-usefulness-matrix/remote-20260523-052501/report.json`:
  both baseline and graph chat now restate the expected answers explicitly for
  both multi-hop questions (`Mira Chen` and `Orion billing service`) while
  keeping `kg_search_clues=11/6` and `baseline_hit_rate=1.0`, `baseline_recall=1.0`.
  Cleanup deleted both generated regression cases, purged `3` documents, reset
  KG stats to zero, and deleted the dataset.
- Browser/UI click-through now has two live proofs. The first,
  `artifacts/ui-clickthrough/backend-business-surfaces-live-20260523-remote-backend.json`,
  passed `1/1` Playwright business-surface smoke in `58.336s` using a local
  frontend dev server plus SSH-tunneled remote API. The second,
  `artifacts/ui-clickthrough/backend-business-surfaces-live-20260523-remote-web.json`,
  passed `1/1` in `12.246s` after rebuilding the remote `web` container from
  `main@059028d9` and tunneling both the deployed page host and API to localhost.
  Together the runs proved real page visits and interactions for `/settings`
  (industry-rules preview + RTBF section visibility), `/graph`,
  `/datasets/{id}/profile`, and `/history?id=...` against both the live backend
  and the deployed frontend page host itself. This closes the remaining
  deployment-specific UI walkthrough gap.
- A deeper UI workflow is now also proven on the deployed page host itself:
  `artifacts/ui-clickthrough/live-stack-remote-web-20260523.json`
  passed `1/1` in `27.282s` and exercised upload -> parse -> viewer -> real
  chat -> command-menu handoff against the remote `web` + `api` stack. This
  run exposed and then verified a real runtime fix: `main@ca40dd49` bounds
  cross-encoder cold-start waits to `2.0s`, so the first
  `BAAI/bge-reranker-v2-m3` download now degrades to base retrieval order
  instead of stalling assistant replies and health checks. After the proof, the
  smoke's `enterprise-telemetry-sample.md` parsing documents were deleted.
- Knowledge-base dataset boundaries now have one dedicated server proof:
  `artifacts/kb-boundary-matrix/remote-20260523/report.json`
  created two disposable datasets (`alpha`, `beta`) with mutually exclusive
  tokens and verified three things on the live API: dataset-scoped inventory
  export returned only the owning document; dataset-scoped retrieval/chat did
  not leak the other dataset's token; and explicit cross-dataset `document_ids`
  scope could surface the beta document while staying inside the allowed
  two-document scope. Cleanup purged and deleted both proof datasets, and the
  earlier failed-iteration leftovers were also swept from the server.
- Knowledge-base file-type breadth now has one dedicated server proof:
  `artifacts/kb-format-matrix/remote-20260523/report.json`
  created one disposable mixed-format dataset and ingested `md`, `html`, `csv`,
  `json`, `docx`, and `xlsx` together. All six files completed with non-empty
  parsed content and at least one chunk, and dataset-scoped retrieve + extractive
  chat both returned `200` with the expected document present in citations for
  every format. Cleanup purged all six documents and deleted the dataset.
- Parser batch/concurrency now has one dedicated server proof for the current
  production MagicPDF path:
  `artifacts/parser-concurrency/remote-20260523/report.json`
  ran `magicpdf` `parse-preview` on 4 stable small PDFs under concurrency
  `1/2/4`. All `12` requests returned `200` with `backend=magicpdf` and output
  above the markdown threshold. Aggregate results were:
  concurrency `1` -> wall `70.773s`, throughput `0.057 rps`, p95 `18.419s`;
  concurrency `2` -> wall `64.868s`, throughput `0.062 rps`, p95 `33.027s`;
  concurrency `4` -> wall `64.124s`, throughput `0.062 rps`, p95 `61.638s`.
  This is enough to show the standalone MagicPDF service sustains concurrent
  small-PDF traffic without health regressions, but not enough yet to sign off
  on larger PDFs or other heavy backends.
- Parser batch/concurrency now also has one dedicated large-PDF server proof:
  `artifacts/parser-concurrency/remote-large-20260523/report.json`
  ran the same standalone MagicPDF path on two RFC-scale PDFs
  (`rfc9000-quic.pdf`, `rfc9110-http-semantics.pdf`) at concurrency `1` and
  `2`. Both requests succeeded in both lanes with resolved backend `magicpdf`
  and large markdown outputs (`355,649` and `442,373` chars). Aggregate
  results: concurrency `1` -> wall `250.554s`, throughput `0.008 rps`, p95
  `144.491s`; concurrency `2` -> wall `251.003s`, throughput `0.008 rps`, p95
  `243.787s`. This is evidence that the service stays healthy under large
  concurrent load, but also that large-document throughput does not improve at
  concurrency `2` for this pair and tail latency gets worse.
- Parser contention now also has one dedicated mixed-backend server proof:
  `artifacts/parser-contention/remote-20260523/report.json`
  ran `magicpdf` and `marker` together on the same 2-page parser-service
  fixture for `2` rounds (`4` total requests). All requests returned `200`
  with the requested backend and sufficient markdown. Overall wall time was
  `56.647s` at `0.071 rps`. Per-backend latencies diverged materially:
  `magicpdf` p50/p95 = `36.489s / 42.614s`, while `marker` p50/p95 =
  `13.514s / 13.660s`. This is the first explicit server-side evidence for
  cross-backend contention on the current parser stack.
- A second mixed-backend contention attempt on `magicpdf + olmocr` is also now
  recorded:
  `artifacts/parser-contention/remote-olmocr-20260523/report.json`
  ran the same 2-page fixture for `1` round. `magicpdf` still succeeded in
  `19.183s`, but `olmocr` took `498.099s` and ultimately resolved
  `backend=basic`, so the run failed the requested-backend check even though
  API health stayed green. This is useful evidence that `olmocr` is currently
  not a viable peer lane for the bounded small-doc contention matrix.
- Knowledge-base permissions now also have one dedicated outsider/viewer proof:
  `artifacts/kb-permission-boundary/remote-20260523/report.json`
  normalized `outsider` to `viewer` and covered three read-scope layers on the
  live API. First, shared-vs-private datasets: shared inventory/retrieve/chat
  returned `200`, private inventory/retrieve/chat returned `403`, and mixed
  `document_ids` scope kept only the readable shared document. Second,
  group-based dataset sharing: a disposable tenant group was created, outsider
  was added, one dataset was shared via `partial_group_list`, and outsider
  inventory/retrieve/chat returned `200` on the group-shared dataset while
  mixed scope still filtered out the unreadable private document. Third,
  document-level ACL overrides inside a readable dataset: one visible doc, one
  owner-only doc (`partial_member_list=[demo]`), and one group-only doc
  (`partial_group_list=[group_id]`) were ingested into the same readable
  dataset; outsider inventory showed only the visible + group-guarded docs,
  private-doc direct scope returned `403`, and retrieve/chat never leaked the
  owner-only token. Cleanup purged/deleted all proof datasets, deleted the
  disposable group, and swept the first failed-run leftovers from the server.
- Real parsed-output chunking on the same 144-page PDF exposed large strategy spread:
  `langchain_recursive=1151` chunks in `174.793s`,
  `parent_child=3702` chunks in `1.900s`,
  `semantic_sentence=1272` chunks in `2.233s`,
  `markdown_hierarchy=6203` chunks in `1.880s`.
- Real long-document KG density/latency on the same 144-page PDF still needs a bounded policy:
  an exploratory default LLM KG extraction run created dataset `cd232ae7-609d-415f-a43a-cca768aee664`
  and document `f20f6207-f808-4bd9-a8ae-8c2d92455793` (670 persisted chunks, ~816k chars),
  but the synchronous KG extract was still running after `250+` extraction batches and did not
  finish within the probe window. During the run, `/api/v1/kg/stats` still reported zero committed
  events/entities/links because extraction had not completed.
- `scripts/production_readiness_chain.py` is not portable on the remote host/container as-is: the host lacks `python-docx`, and the API container lacks `requests`.
  The live service passed through `scripts/remote_api_chain_smoke.py`, which uses only the standard library.

## Execution Log

- 2026-05-22 12:57: Plan created. Next action: reproduce and fix explicit parser fallback behavior.
- 2026-05-22 13:12: Remote `/data/MimirQ` pulled to commit `386548e0`; API/worker restarted with root `.env`.
- 2026-05-22 13:27: Remote parser matrix passed for configured live parser backends.
- 2026-05-22 13:57: Remote API chain passed end to end with parser, ingestion, chunk preview, KG, RAG retrieval, and chat.
- 2026-05-22 14:30: Remote chunk/governance matrix passed: 15/15 chunk strategies and 6/6 governance preview cases.
- 2026-05-22 15:30: Remote KG scale guard passed after API/worker image rebuild: 12 documents completed, 12 KG extracts succeeded, stats/search endpoints returned 200.
- 2026-05-23 03:10: Added product quality backlog to keep parser serviceization, KG density, chunking, prompts, knowledge-base lifecycle, governance, and admin/permission checks under this same server verification task.
- 2026-05-23 08:18: Remote MagicPDF serviceization completed on `192.0.2.253`; 2-page and 144-page real PDF both resolved `backend=magicpdf` through the standalone service.
- 2026-05-23 08:34: Real parsed-output chunking on the 144-page PDF showed major strategy spread (`1151` to `6203` chunks depending on strategy).
- 2026-05-23 08:52: Default LLM KG extraction on the same 144-page PDF remained too slow for product defaults, continuing past `250+` extraction batches without completing inside the probe window.
- 2026-05-23 09:20: Deployed `main@154af84` with document-level KG chunk budget (`120`, `uniform`) and re-ran KG extraction on the same 144-page PDF. Server logs showed the rerun restarted at batch `1` and progressed through about batch `98` before entering embedding/indexing work, rather than continuing unbounded past `250+` extraction batches. This confirms the chunk budget is taking effect, but the default low-cost LLM path is still too slow to treat as a comfortable long-document default.
- 2026-05-23 09:34: Deployed `main@57f7c75` with automatic long-document backend routing (`KG_EXTRACT_LONG_DOC_BACKEND=heuristic`, threshold `300` chunks). The same 144-page PDF then completed default KG extraction in `13.411s` with `event_count=120`; final `/api/v1/kg/stats` for dataset `cd232ae7-609d-415f-a43a-cca768aee664` reported `120 events / 1148 entities / 1887 links`.
- 2026-05-23 09:48: Added `scripts/remote_real_pdf_chain.py` and ran the first full real-PDF server chain. The 144-page PDF completed end-to-end through parse, stored chunks, default heuristic KG extraction, and baseline/graph chat under artifact `artifacts/real-pdf-chain/final-20260523-014839/`.
- 2026-05-23 10:17: Verified knowledge-base lifecycle cleanup on a real-PDF dataset: purge deleted the only document, dataset export returned empty, KG stats reset to zero, and dataset delete returned `204`.
- 2026-05-23 10:26: Re-ran the full real-PDF chain using the scripted cleanup mode (`remote_real_pdf_chain.py --cleanup-mode purge_dataset --delete-dataset-after`) and confirmed the automated lifecycle path matches the manual cleanup proof.
- 2026-05-23 10:44: Added `scripts/remote_permission_matrix.py` and verified one server-side permission matrix run. Because this host still auto-bootstraps unknown accounts as `owner`, the script now first downgrades the disposable outsider account to `viewer` through local Postgres before running the deny checks.
- 2026-05-23 10:55: Re-ran the permission matrix on `main@d3bb639f` from a clean remote worktree and extended the proof to `GET /api/v1/audit/access-graph/summary` plus `GET /api/v1/audit/access-graph/export?export_format=json&limit=10`; admin returned `200`, outsider returned `403`, and scripted dataset cleanup still passed.
- 2026-05-23 11:13: Added `scripts/remote_governance_ingest_matrix.py` and verified a full live governance ingest matrix on `main@f71242f`. The server proof covered masked PII, masked secrets, HTML rule-pack cleanup with table normalization, duplicate cleanup visible in persisted content/citations, outline-only quarantine, and scripted dataset purge/delete cleanup.
- 2026-05-23 11:49: Added `scripts/remote_prompt_matrix.py`, wired builtin prompt selectors into document test generation and regression LLM judge, and verified a full live prompt matrix on `main@312e6cc`. The server proof covered builtin sync, answer prompt preview, answer prompt chat, KG extract prompt selection, builtin testset generation, builtin judge prompt selection, generated-case cleanup, dataset purge, and dataset delete.
- 2026-05-23 12:49: Added `scripts/remote_kg_usefulness_matrix.py` and verified one targeted KG usefulness run on `main@fb5d02c`. The server proof showed stable KG clues and diagnostics hits on two handcrafted multi-hop questions, but also showed that the extractive chat surface still did not restate `Mira Chen` verbatim for the acquisition->leader question, so chat-surface answer lift remains only partially proven.
- 2026-05-23 13:25: Improved extractive fallback answer selection on `main@ea55803` and re-ran the KG usefulness matrix. The follow-up server proof (`remote-20260523-052501`) kept the same strong KG clue/diagnostics signal and also made both extractive chat paths restate the expected answers explicitly for the two multi-hop questions.
- 2026-05-23 14:00: Re-ran a Playwright live business-surface smoke against the remote backend via localhost SSH tunnel and updated the spec to current UI labels (`行业规则`, `预览`). The passing run (`backend-business-surfaces-live-20260523-remote-backend.json`) proved `/settings`, `/graph`, `/datasets/{id}/profile`, and `/history` page clicks on the current product surface.
- 2026-05-23 14:30: Added a dedicated `web/playwright.remote-web.config.ts` lane so the same business-surface smoke can target the remote `web` container page host directly. The first remote-web reruns still fail with React hydration error `#418` on the history page, even after adding hydration guards for sidebar relative times, message-group labels, selected-conversation created-at chips, sidebar group labels, and minimal assistant timestamps. The remaining UI gap is now precisely scoped to a deployment-specific hydration mismatch, not a missing smoke path.
- 2026-05-23 14:54: Rebuilt the remote `web` container from clean worktree `/tmp/MimirQ-main-webfix` at `main@059028d9` and re-ran `pnpm e2e:live:remote-web` through SSH tunnels to the deployed page host and API. The remote-web lane passed (`backend-business-surfaces-live-20260523-remote-web.json`, `1/1` in `12.246s`), closing the last deployment-specific UI walkthrough caveat.
- 2026-05-23 15:11: A deeper deployed-frontend live-stack smoke initially failed because the first real chat request synchronously triggered a HuggingFace cross-encoder download, which stalled assistant replies and even `/api/v1/health/ready`. `main@ca40dd49` fixed that by bounding local cross-encoder load waits to `2.0s` and degrading to base retrieval order while the model keeps warming in the background.
- 2026-05-23 15:12: Rebuilt the remote `api` container from `main@ca40dd49` and re-ran the deeper live-stack smoke against the deployed `web` + `api` stack. The run passed (`live-stack-remote-web-20260523.json`, `1/1` in `27.282s`), proving upload -> parse -> viewer -> real chat -> command-menu handoff on the deployed page host without sacrificing API health during the cross-encoder cold start.
- 2026-05-23 15:27: Added `scripts/remote_kb_boundary_matrix.py` and verified one dedicated knowledge-base boundary run through the live API. The proof (`artifacts/kb-boundary-matrix/remote-20260523/report.json`) created two disposable datasets, checked dataset-scoped inventory export, dataset-scoped retrieve/chat non-leakage, and explicit cross-dataset `document_ids` scope, then purged/deleted both datasets and swept the earlier failed-run leftovers.
- 2026-05-23 15:36: Added `scripts/remote_kb_permission_boundary.py` and verified one dedicated outsider/viewer knowledge-base permission run through the live API. The proof (`artifacts/kb-permission-boundary/remote-20260523/report.json`) normalized `outsider` to `viewer`, proved shared-vs-private dataset read behavior (`200` vs `403`), and confirmed mixed `document_ids` scope filters out the unreadable private document in both retrieval and extractive chat before purging/deleting both proof datasets.
- 2026-05-23 15:42: Extended `scripts/remote_kb_permission_boundary.py` to cover group-based dataset sharing. The rerun created a disposable group, added `outsider`, shared one dataset via `partial_group_list`, and proved outsider inventory/retrieve/chat on that dataset while mixed `document_ids` scope still filtered out the unreadable private document. Cleanup deleted all proof datasets and the temporary group.
- 2026-05-23 16:02: Fixed `app/api/v1/document_listing.py` so document inventory respects `DocumentGroupPermission` in addition to direct `DocumentPermission`. After rebuilding the remote `api`, the KB permission proof was rerun successfully and now also covers document-level ACL overrides inside a readable dataset (`partial_member_list` owner-only doc plus `partial_group_list` group-only doc).
- 2026-05-23 16:10: Added `scripts/remote_kb_format_matrix.py` and verified one mixed-format KB breadth run through the live API. The proof (`artifacts/kb-format-matrix/remote-20260523/report.json`) ingested `md`, `html`, `csv`, `json`, `docx`, and `xlsx` into one disposable dataset, then proved dataset-scoped retrieve + extractive chat on all six formats before purging the dataset.
- 2026-05-23 16:20: Added `scripts/remote_parser_concurrency_probe.py` and verified one controlled MagicPDF concurrency run through the live API. The proof (`artifacts/parser-concurrency/remote-20260523/report.json`) used 4 stable small PDFs and measured the current standalone MagicPDF path at concurrency `1/2/4`, confirming all `12` requests returned `200` with resolved backend `magicpdf` while showing latency/throughput tradeoffs rather than health failures.
- 2026-05-23 16:34: Extended `scripts/remote_parser_concurrency_probe.py` to accept explicit fixture paths and re-ran it on two RFC-scale PDFs (`rfc9000-quic.pdf`, `rfc9110-http-semantics.pdf`) at concurrency `1/2`. The resulting artifact (`artifacts/parser-concurrency/remote-large-20260523/report.json`) showed both large requests succeeded with resolved backend `magicpdf` while API health stayed green, but throughput did not improve at concurrency `2` and p95 latency worsened materially.
- 2026-05-23 17:08: Added `scripts/remote_parser_mixed_contention_probe.py` and verified one bounded mixed-backend contention run through the live API. The proof (`artifacts/parser-contention/remote-20260523/report.json`) ran `magicpdf` and `marker` together for `2` rounds on the same 2-page fixture, confirming all `4` requests returned `200` while showing materially higher p50/p95 latency on the MagicPDF lane than on the Marker lane under shared load.
- 2026-05-23 17:16: Extended `scripts/remote_parser_mixed_contention_probe.py` with a per-task timeout so slow backend combinations cannot hang the whole contention lane indefinitely. A bounded `magicpdf + olmocr` rerun (`artifacts/parser-contention/remote-olmocr-20260523/report.json`) showed `magicpdf` succeeding in `19.183s` while `olmocr` ran for `498.099s` and resolved `backend=basic`, making that pair unsuitable for the current small-doc contention matrix even though API health remained green.
- 2026-05-23 16:10: Added `scripts/remote_kb_format_matrix.py` and verified one mixed-format KB breadth run through the live API. The proof (`artifacts/kb-format-matrix/remote-20260523/report.json`) ingested `md`, `html`, `csv`, `json`, `docx`, and `xlsx` into one disposable dataset, then proved dataset-scoped retrieve + extractive chat on all six formats before purging the dataset.
