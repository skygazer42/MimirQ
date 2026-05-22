# Remote Test Ledger - 2026-05-22

Scope: server-side verification on `/data/MimirQ` at `10.168.2.253`.

This ledger records what has already been tested remotely so future runs do not repeat expensive parser, KG, or RAG checks unless the related code/config changes.

## Completed

| Area | Evidence | Result | Notes |
| --- | --- | --- | --- |
| Docker/root env wiring | `plans/server-integration-verification-2026-05-22.md` | pass | API/worker restarted with root `.env`; parser URLs aligned to Docker service names. |
| Parser matrix smoke | `artifacts/parser-matrix/remote-20260522-051241` | pass | `Calls: 411 | Failures: 0 | Missing: 0`. |
| Explicit parser backends | `artifacts/parser-matrix/remote-detail-20260522-052736/report.json` | pass | `basic`, `markitdown`, `docling`, `mineru`, `magicpdf`, `paddle_vl`, `textin` returned the requested backend. |
| Remote API chain | `artifacts/remote-api-chain/remote-api-chain-20260522-055729/report.json` | pass | 4 documents completed; parsed markdown persisted; 5 chunk preview strategies; KG extract/search/stats; RAG retrieve; chat. |
| RAG retrieve/chat | `artifacts/remote-api-chain/remote-api-chain-20260522-055729/report.json` | pass | 4 citations; chat status 200; chat elapsed 0.209s. |
| KG smoke | `artifacts/remote-api-chain/remote-api-chain-20260522-055729/report.json` | pass | Heuristic extraction passed for 3 docs; each document took about 5.8s-6.9s. |
| Chunking matrix extension | `artifacts/chunk-governance-matrix/remote-20260522-063015/report.json` | pass | 15/15 product-relevant strategies passed through `/api/v1/documents/chunk-preview`; max elapsed 0.034s. |
| Governance preview matrix | `artifacts/chunk-governance-matrix/remote-20260522-063015/report.json` | pass | 6/6 governance cases passed through `/api/v1/pipeline/clean-preview`: PII, secrets, URL normalization, duplicate drop, HTML/table normalization, low-density drop. |
| KG scale guard | `artifacts/kg-scale-guard/remote-20260522-072703/report.json` | pass | 12/12 documents completed and 12/12 heuristic KG extracts returned 200 after API/worker images were rebuilt. Avg extract 8.329s, P95 14.868s, max 14.928s; KG stats 200 in 0.153s; KG search 200 in 0.408s. |
| API/worker retry runtime | remote Docker containers on `/data/MimirQ` | pass | Rebuilt API/worker images and verified running worker config: document max tries 80, KG max tries 80, retry defer 30s. This fixed the earlier 12-doc run where 2 docs stayed pending after 3 worker retries. |
| Large PDF parser baseline | `artifacts/pdf-performance/remote-20260522-081140/report.json` | pass | 144-page arXiv PDF (`2303.18223`, 5.85 MB): `basic` 4.011s, `markitdown` 55.557s, `docling` 340.648s. |
| MinerU VLM GPU parser | `artifacts/pdf-performance/remote-20260522-092203/report.json` | pass | Same 144-page PDF through MimirQ API with `MINERU_BACKEND=vlm-http-client`: `mineru` 241.55s, 886,217 markdown chars, page count 144. VLM service returned `/v1/models`; observed A6000 memory about 39.9 GiB and GPU utilization up to 91% during parsing. |

## Next Remote Tests

| Priority | Area | Why |
| --- | --- | --- |
| P2 | Parser batch/concurrency performance | Single large PDF latency is measured; still need controlled batch/concurrency runs before changing production defaults. |
| P2 | Browser UI walkthrough | API is verified; UI click-through has not been rerun for this server deployment. |

## Known Gaps

- `scripts/production_readiness_chain.py` is not portable on the remote host/container as-is: host lacks `python-docx`, API container lacks `requests`.
- Use `scripts/remote_api_chain_smoke.py` for dependency-light server checks until the full readiness script is made portable.
- KG scale is functionally passing for 12 synthetic documents. Next optimization is extraction density/latency tuning on larger real PDFs, not another small-doc smoke rerun.
- KG event density and usefulness need product discussion before changing defaults. The current 12-doc scale guard generated 12 events because each synthetic document contains one obvious incident; this proves the channel is bounded and stable, but not that the event budget is useful for real KG-assisted RAG. Later discussion should compare baseline RAG vs KG-assisted RAG on real questions before increasing extraction density.
