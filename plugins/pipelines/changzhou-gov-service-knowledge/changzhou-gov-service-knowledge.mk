.PHONY: changzhou-gov-plugin-help changzhou-gov-plugin-chunk-report changzhou-gov-plugin-chunk-evidence changzhou-gov-plugin-test-report changzhou-gov-plugin-test-evidence changzhou-gov-plugin-corpus-closed-loop-smoke changzhou-gov-plugin-corpus-closed-loop-evidence changzhou-gov-delivery-pack changzhou-gov-delivery-pack-refresh changzhou-gov-delivery-pack-refresh-with-audit changzhou-dify-knowledge-map-check changzhou-dify-mimirq-direct-gate changzhou-dify-mimirq-direct-kg-off-gate changzhou-dify-mimirq-direct-kg-on-gate changzhou-dify-kg-compare-gate changzhou-dify-kg-on-off-gate changzhou-dify-external-probe changzhou-dify-workflow-lint changzhou-dify-workflow-sync-dry-run changzhou-dify-workflow-sync-apply changzhou-dify-full-gate changzhou-dify-readiness-summary changzhou-dify-readiness-status changzhou-dify-readiness-evidence changzhou-dify-readiness-persist-audit changzhou-dify-readiness-gate changzhou-dify-readiness-gate-quiet changzhou-human-mixed-cases changzhou-eval-pack-generate changzhou-eval-pack-import changzhou-dify-4way-preflight changzhou-dify-4way-smoke changzhou-dify-4way-full changzhou-dify-4way-merge-report changzhou-kg-on-off-benchmark

PLUGIN_HELP_TARGETS += changzhou-gov-plugin-help

CHANGZHOU_DIFY_APP_ID ?= 00000000-0000-0000-0000-000000000003
CHANGZHOU_DIFY_BASE_URL ?= https://dify.example.com:5001/v1
CHANGZHOU_DIFY_API_KEY_FILE ?= /tmp/dify_remote_app_api_key.json
CHANGZHOU_DIFY_STORAGE_STATE ?= $(DIFY_CONSOLE_STORAGE_STATE)
CHANGZHOU_DIFY_MIMIRQ_BASE_URL ?= http://127.0.0.1:8000
CHANGZHOU_DIFY_OUT_PREFIX ?= /tmp/changzhou_gov_dify_full_gate
CHANGZHOU_DIFY_CASES ?= plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json
CHANGZHOU_DIFY_EXTRA_ARGS ?= --quality-profile changzhou-retrieval
CHANGZHOU_DIFY_EFFECTIVE_EXTRA_ARGS ?= $(CHANGZHOU_DIFY_EXTRA_ARGS)
CHANGZHOU_DIFY_READINESS_EXTRA_ARGS ?= --min-generated-answer-grounding-rate 0.9 --min-generated-answer-key-point-recall 0.9
CHANGZHOU_DIFY_TRACE_TIMEOUT ?= 15
CHANGZHOU_DIFY_EXTERNAL_API_ID ?=
CHANGZHOU_DIFY_PROBE_OUT ?= /tmp/changzhou_gov_dify_external_probe.json
CHANGZHOU_DIFY_PROBE_TOP_K ?= 5
CHANGZHOU_DIFY_PROBE_TIMEOUT ?= 45
CHANGZHOU_DIFY_MIMIRQ_ENV_FILE ?= .env
CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT ?= /tmp/changzhou_gov_dify_mimirq_direct_gate.json
CHANGZHOU_DIFY_MIMIRQ_DIRECT_EXTRA_ARGS ?= --quality-profile changzhou-retrieval --min-hit-at-1 1 --min-answer-grounding-rate 1 --min-answer-key-point-recall 1
CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_OFF_OUT ?= /tmp/changzhou_gov_dify_mimirq_direct_kg_off.json
CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_ON_OUT ?= /tmp/changzhou_gov_dify_mimirq_direct_kg_on.json
CHANGZHOU_DIFY_KG_BASELINE_REPORT ?= $(CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_OFF_OUT)
CHANGZHOU_DIFY_KG_CANDIDATE_REPORT ?= $(CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_ON_OUT)
CHANGZHOU_DIFY_KG_ON_OFF_COMPARE_OUT ?= /tmp/changzhou_gov_dify_kg_compare.json
CHANGZHOU_DIFY_KG_COMPARE_OUT ?=
CHANGZHOU_DIFY_KG_COMPARE_EXTRA_ARGS ?= --quality-profile changzhou-retrieval
CHANGZHOU_DIFY_READINESS_OUT ?= /tmp/changzhou_gov_dify_readiness_summary.json
CHANGZHOU_DIFY_READINESS_EVIDENCE_OUT ?= /tmp/changzhou_gov_dify_readiness_evidence.md
CHANGZHOU_DIFY_READINESS_AUDIT_OUT ?= /tmp/changzhou_gov_dify_readiness_persist_audit.json
CHANGZHOU_DIFY_READINESS_LOG ?= /tmp/changzhou_gov_dify_readiness_gate.log
CHANGZHOU_DIFY_KNOWLEDGE_MAP_ENV_FILE ?= .env
CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT ?= /tmp/changzhou_gov_dify_knowledge_map_check.json
CHANGZHOU_DIFY_WORKFLOW_LINT_OUT ?= /tmp/changzhou_gov_dify_workflow_lint.json
CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT ?= /tmp/changzhou_gov_dify_workflow_sanitized.json
CHANGZHOU_DIFY_WORKFLOW_BACKUP_OUT ?= /tmp/changzhou_gov_dify_workflow_current_draft_backup.json
CHANGZHOU_DIFY_WORKFLOW_PAYLOAD_OUT ?= /tmp/changzhou_gov_dify_workflow_sync_payload.json
CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT ?= /tmp/changzhou_gov_dify_workflow_sync.json
CHANGZHOU_DIFY_WORKFLOW_SYNC_EXTRA_ARGS ?=
MIXED_RAG_CASES ?= plugins/pipelines/changzhou-gov-service-knowledge/human_mixed_eval_cases.json
CHANGZHOU_HUMAN_MIXED_SOURCE ?= /tmp/changzhou_composite_100_cases.json
CHANGZHOU_HUMAN_MIXED_OUT ?= plugins/pipelines/changzhou-gov-service-knowledge/human_mixed_eval_cases.json
CHANGZHOU_HUMAN_MIXED_TOTAL ?= 100
CHANGZHOU_HUMAN_MIXED_MAX_QA_RATIO ?= 0.0
CHANGZHOU_GOV_PLUGIN_DIR ?= plugins/pipelines/changzhou-gov-service-knowledge
CHANGZHOU_GOV_PLUGIN_SAMPLE ?= plugins/pipelines/changzhou-gov-service-knowledge/sample.json
CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT ?= /tmp/changzhou_gov_plugin_chunk_report.json
CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_MD ?= /tmp/changzhou_gov_plugin_chunk_report.md
CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_OUT ?= /tmp/changzhou_gov_plugin_chunk_evidence.json
CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_MD ?= /tmp/changzhou_gov_plugin_chunk_evidence.md
CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT ?= /tmp/changzhou_gov_plugin_test_report.json
CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_OUT ?= /tmp/changzhou_gov_plugin_test_evidence.json
CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_MD ?= /tmp/changzhou_gov_plugin_test_evidence.md
CHANGZHOU_GOV_PLUGIN_REF ?= plugin:changzhou-gov-service-knowledge@1.0.0:chunk
CHANGZHOU_GOV_CORPUS_SOURCE_DIR ?=
CHANGZHOU_GOV_CORPUS_DATASET_ID ?=
CHANGZHOU_GOV_CORPUS_REPORT_OUT ?= /tmp/changzhou_gov_plugin_corpus_closed_loop_report.json
CHANGZHOU_GOV_CORPUS_EVIDENCE_OUT ?= /tmp/changzhou_gov_plugin_corpus_closed_loop_evidence.json
CHANGZHOU_GOV_CORPUS_EVIDENCE_MD ?= /tmp/changzhou_gov_plugin_corpus_closed_loop_evidence.md
CHANGZHOU_EVAL_CORPUS_ROOT ?= /path/to/gov-service-knowledge
CHANGZHOU_EVAL_QA_COUNT ?= 100
CHANGZHOU_EVAL_SERVICE_COUNT ?= 200
CHANGZHOU_EVAL_USER_COUNT ?= 800
CHANGZHOU_EVAL_BACKEND_BASE_URL ?= http://127.0.0.1:8000/api/v1
CHANGZHOU_EVAL_OUT ?= artifacts/changzhou_eval_pack_full
CHANGZHOU_EVAL_LIVE_OUT ?= artifacts/changzhou_eval_pack_full_live
CHANGZHOU_DIFY_4WAY_PREFLIGHT_OUT ?= artifacts/changzhou_dify_4way_preflight
CHANGZHOU_DIFY_4WAY_SMOKE_OUT ?= artifacts/changzhou_dify_4way_smoke
CHANGZHOU_DIFY_4WAY_FULL_OUT ?= artifacts/changzhou_dify_4way_full
CHANGZHOU_DIFY_4WAY_APP_KEYS ?= /tmp/dify_4way_app_keys.json
CHANGZHOU_DIFY_4WAY_MERGED_OUT ?= artifacts/changzhou_dify_4way_merged
CHANGZHOU_KG_ON_OFF_OUT ?= artifacts/changzhou_kg_on_off_benchmark
CHANGZHOU_GOV_CORPUS_EXTENSIONS ?= .txt,.docx,.xlsx,.doc
CHANGZHOU_GOV_CORPUS_MAX_FILES ?= 0
CHANGZHOU_GOV_CORPUS_MAX_FILES_PER_GROUP ?= 0
CHANGZHOU_GOV_CORPUS_SAMPLE_GROUP_DEPTH ?= 1
CHANGZHOU_GOV_CORPUS_UPLOAD_BATCH_SIZE ?= 0
CHANGZHOU_GOV_CORPUS_GOLDEN_MAX_ITEMS ?= 200
CHANGZHOU_GOV_CORPUS_GOLDEN_MAX_CHUNKS ?= 5000
CHANGZHOU_GOV_CORPUS_REGRESSION_TOP_K ?= 2
CHANGZHOU_GOV_CORPUS_REGRESSION_RERANKER_TOP_N ?= 0
CHANGZHOU_GOV_CORPUS_REGRESSION_SCORE_THRESHOLD ?= 0.0
CHANGZHOU_GOV_CORPUS_HTTP_TIMEOUT ?= 120
CHANGZHOU_GOV_CORPUS_PROCESSING_TIMEOUT ?= 1800
CHANGZHOU_GOV_CORPUS_POLL_INTERVAL ?= 2
CHANGZHOU_GOV_CORPUS_MIN_RETRIEVAL_RECALL ?= 1.0
CHANGZHOU_GOV_CORPUS_MIN_RETRIEVAL_HIT_AT_3 ?= 0.8
CHANGZHOU_GOV_CORPUS_MIN_EXPECTED_METADATA_HIT_RATE ?= 1.0
CHANGZHOU_GOV_CORPUS_MIN_EXPECTED_METADATA_RECALL ?= 1.0
CHANGZHOU_GOV_CORPUS_MIN_CITATION_ACCURACY ?= 0.5
CHANGZHOU_GOV_CORPUS_MIN_CITATION_COVERAGE ?= 0.0
CHANGZHOU_GOV_CORPUS_EXTRA_ARGS ?=
CHANGZHOU_GOV_DELIVERY_PACK_OUT ?= /tmp/changzhou_gov_delivery_pack.json
CHANGZHOU_GOV_DELIVERY_PACK_MD ?= /tmp/changzhou_gov_delivery_pack.md
CHANGZHOU_GOV_DELIVERY_PACK_MAX_READINESS_AGE_MINUTES ?= 30
CHANGZHOU_GOV_DELIVERY_PACK_REQUIRE_READINESS_AUDIT ?= 0

changzhou-gov-plugin-help:
	@echo "  make changzhou-gov-plugin-chunk-report - write Changzhou plugin governance/chunk/KG review report"
	@echo "  make changzhou-gov-plugin-chunk-evidence - write shareable sanitized plugin chunk evidence"
	@echo "  make changzhou-gov-plugin-test-report - write Changzhou plugin local test + Golden draft report"
	@echo "  make changzhou-gov-plugin-test-evidence - write shareable sanitized plugin test evidence"
	@echo "  make changzhou-gov-plugin-corpus-closed-loop-smoke - live ingest a corpus with the plugin and run Golden retrieval"
	@echo "  make changzhou-gov-plugin-corpus-closed-loop-evidence - sanitize the live corpus closed-loop smoke report"
	@echo "  make changzhou-gov-delivery-pack - write combined Changzhou plugin + Dify readiness handoff pack"
	@echo "  make changzhou-gov-delivery-pack-refresh - quietly refresh remote readiness, then write delivery pack"
	@echo "  make changzhou-gov-delivery-pack-refresh-with-audit - refresh readiness, persist retrieval audit, then write audited delivery pack"
	@echo "  make changzhou-dify-knowledge-map-check - validate local Changzhou Dify knowledge map routes"
	@echo "  make changzhou-dify-mimirq-direct-gate - run MimirQ-only Changzhou golden retrieval gate"
	@echo "  make changzhou-dify-kg-on-off-gate - run KG-off/KG-on MimirQ golden gates and compare reports"
	@echo "  make changzhou-dify-kg-compare-gate - compare saved KG-off/KG-on Changzhou golden reports"
	@echo "  make changzhou-dify-external-probe - compare Dify external hit-testing with direct MimirQ retrieval"
	@echo "  make changzhou-dify-workflow-lint - lint and write a sanitized Changzhou Dify draft workflow JSON"
	@echo "  make changzhou-dify-workflow-sync-dry-run - stage Changzhou Dify draft sync without writing remote state"
	@echo "  make changzhou-dify-workflow-sync-apply - explicitly write the staged Changzhou Dify draft workflow"
	@echo "  make changzhou-dify-full-gate - run Changzhou Dify/MimirQ remote golden gate"
	@echo "  make changzhou-dify-readiness-gate - run external probe, full Dify/MimirQ gate, and write readiness summary"
	@echo "  make changzhou-dify-readiness-gate-quiet - run readiness gate with raw output redirected to a local log"
	@echo "  make changzhou-dify-readiness-status - print compact readiness status from the latest summary"
	@echo "  make changzhou-dify-readiness-evidence - write PII-safe Markdown readiness evidence"
	@echo "  make changzhou-dify-readiness-persist-audit - persist latest readiness retrieval_audit into a dataset report"
	@echo "  make changzhou-human-mixed-cases - build human-like mixed cases with capped QA-derived share"
	@echo "  make changzhou-eval-pack-generate - build the 1100-question corpus-grounded eval pack from raw政务知识"
	@echo "  make changzhou-eval-pack-import - resolve live chunk refs, import regression cases, and seed local /evaluations records"
	@echo "  make changzhou-dify-4way-preflight - validate native/http/external/MimirQ-direct against the generated eval pack"
	@echo "  make changzhou-dify-4way-smoke - run a small 4-way smoke benchmark from the generated eval pack"
	@echo "  make changzhou-dify-4way-full - run the full 4-way benchmark from the generated eval pack"
	@echo "  make changzhou-dify-4way-merge-report - merge separately produced native/http/external/direct runs into one final report"
	@echo "  make changzhou-kg-on-off-benchmark - compare local MimirQ direct results with KG off vs on on the same eval pack"

changzhou-dify-external-probe:
	$(PY) scripts/changzhou_gov_dify_external_knowledge_probe.py \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--external-api-id "$(CHANGZHOU_DIFY_EXTERNAL_API_ID)" \
		--console-base-url "$(DIFY_CONSOLE_BASE_URL)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--timeout $(CHANGZHOU_DIFY_PROBE_TIMEOUT) \
		--top-k $(CHANGZHOU_DIFY_PROBE_TOP_K) \
		--out "$(CHANGZHOU_DIFY_PROBE_OUT)"

changzhou-gov-plugin-chunk-report:
	$(PY) scripts/changzhou_gov_plugin_chunk_report.py \
		--plugin-dir "$(CHANGZHOU_GOV_PLUGIN_DIR)" \
		--input "$(CHANGZHOU_GOV_PLUGIN_SAMPLE)" \
		--json-out "$(CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_MD)"

changzhou-gov-plugin-chunk-evidence: changzhou-gov-plugin-chunk-report
	$(PY) scripts/changzhou_gov_plugin_chunk_evidence.py \
		--input "$(CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT)" \
		--json-out "$(CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_MD)"

changzhou-gov-plugin-test-report:
	@mkdir -p "$$(dirname "$(CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT)")"
	$(PY) scripts/pipeline_plugin_runner.py test "$(CHANGZHOU_GOV_PLUGIN_DIR)" \
		--input "$(CHANGZHOU_GOV_PLUGIN_SAMPLE)" \
		--stage governance \
		--stage chunk \
		--stage kg \
		--no-write-report >"$(CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT)"

changzhou-gov-plugin-test-evidence: changzhou-gov-plugin-test-report
	$(PY) scripts/changzhou_gov_plugin_test_evidence.py \
		--input "$(CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT)" \
		--json-out "$(CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_MD)"

changzhou-gov-plugin-corpus-closed-loop-smoke:
	@test -n "$(CHANGZHOU_GOV_CORPUS_SOURCE_DIR)" || (echo "Set CHANGZHOU_GOV_CORPUS_SOURCE_DIR=/path/to/corpus" >&2; exit 2)
	$(PY) scripts/plugin_corpus_closed_loop_smoke.py \
		--base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--source-dir "$(CHANGZHOU_GOV_CORPUS_SOURCE_DIR)" \
		--dataset-id "$(CHANGZHOU_GOV_CORPUS_DATASET_ID)" \
		--plugin-ref "$(CHANGZHOU_GOV_PLUGIN_REF)" \
		--extensions "$(CHANGZHOU_GOV_CORPUS_EXTENSIONS)" \
		--max-files $(CHANGZHOU_GOV_CORPUS_MAX_FILES) \
		--max-files-per-group $(CHANGZHOU_GOV_CORPUS_MAX_FILES_PER_GROUP) \
		--sample-group-depth $(CHANGZHOU_GOV_CORPUS_SAMPLE_GROUP_DEPTH) \
		--upload-batch-size $(CHANGZHOU_GOV_CORPUS_UPLOAD_BATCH_SIZE) \
		--timeout $(CHANGZHOU_GOV_CORPUS_HTTP_TIMEOUT) \
		--golden-max-items $(CHANGZHOU_GOV_CORPUS_GOLDEN_MAX_ITEMS) \
		--golden-max-chunks $(CHANGZHOU_GOV_CORPUS_GOLDEN_MAX_CHUNKS) \
		--processing-timeout $(CHANGZHOU_GOV_CORPUS_PROCESSING_TIMEOUT) \
		--poll-interval $(CHANGZHOU_GOV_CORPUS_POLL_INTERVAL) \
		--regression-top-k $(CHANGZHOU_GOV_CORPUS_REGRESSION_TOP_K) \
		--regression-reranker-top-n $(CHANGZHOU_GOV_CORPUS_REGRESSION_RERANKER_TOP_N) \
		--regression-score-threshold $(CHANGZHOU_GOV_CORPUS_REGRESSION_SCORE_THRESHOLD) \
		$(CHANGZHOU_GOV_CORPUS_EXTRA_ARGS) >"$(CHANGZHOU_GOV_CORPUS_REPORT_OUT)"

changzhou-gov-plugin-corpus-closed-loop-evidence:
	$(PY) scripts/plugin_corpus_closed_loop_evidence.py \
		--input "$(CHANGZHOU_GOV_CORPUS_REPORT_OUT)" \
		--json-out "$(CHANGZHOU_GOV_CORPUS_EVIDENCE_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_CORPUS_EVIDENCE_MD)" \
		--min-retrieval-recall $(CHANGZHOU_GOV_CORPUS_MIN_RETRIEVAL_RECALL) \
		--min-retrieval-hit-at-3 $(CHANGZHOU_GOV_CORPUS_MIN_RETRIEVAL_HIT_AT_3) \
		--min-expected-metadata-hit-rate $(CHANGZHOU_GOV_CORPUS_MIN_EXPECTED_METADATA_HIT_RATE) \
		--min-expected-metadata-recall $(CHANGZHOU_GOV_CORPUS_MIN_EXPECTED_METADATA_RECALL) \
		--min-citation-accuracy $(CHANGZHOU_GOV_CORPUS_MIN_CITATION_ACCURACY) \
		--min-citation-coverage $(CHANGZHOU_GOV_CORPUS_MIN_CITATION_COVERAGE)

changzhou-gov-delivery-pack: changzhou-gov-plugin-chunk-evidence changzhou-gov-plugin-test-evidence changzhou-dify-readiness-evidence
	$(PY) scripts/changzhou_gov_delivery_pack.py \
		--plugin-report "$(CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT)" \
		--plugin-chunk-evidence "$(CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_OUT)" \
		--plugin-chunk-evidence-markdown "$(CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_MD)" \
		--plugin-test-report "$(CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT)" \
		--plugin-test-evidence "$(CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_OUT)" \
		--readiness-summary "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		--readiness-evidence "$(CHANGZHOU_DIFY_READINESS_EVIDENCE_OUT)" \
		--readiness-audit "$(CHANGZHOU_DIFY_READINESS_AUDIT_OUT)" \
		$(if $(filter 1 true yes,$(CHANGZHOU_GOV_DELIVERY_PACK_REQUIRE_READINESS_AUDIT)),--require-readiness-audit-persisted) \
		--max-readiness-age-minutes $(CHANGZHOU_GOV_DELIVERY_PACK_MAX_READINESS_AGE_MINUTES) \
		--json-out "$(CHANGZHOU_GOV_DELIVERY_PACK_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_DELIVERY_PACK_MD)"

changzhou-gov-delivery-pack-refresh: changzhou-dify-readiness-gate-quiet changzhou-gov-delivery-pack

changzhou-gov-delivery-pack-refresh-with-audit: changzhou-dify-readiness-gate-quiet changzhou-dify-readiness-persist-audit
	$(MAKE) changzhou-gov-delivery-pack CHANGZHOU_GOV_DELIVERY_PACK_REQUIRE_READINESS_AUDIT=1

changzhou-dify-workflow-lint:
	$(PY) scripts/changzhou_gov_dify_workflow_lint.py \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--preflight-gate \
		--out "$(CHANGZHOU_DIFY_WORKFLOW_LINT_OUT)" \
		--patched-workflow-out "$(CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT)"

changzhou-dify-workflow-sync-dry-run:
	$(PY) scripts/changzhou_gov_dify_workflow_sync.py \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--workflow-json "$(CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--backup-out "$(CHANGZHOU_DIFY_WORKFLOW_BACKUP_OUT)" \
		--payload-out "$(CHANGZHOU_DIFY_WORKFLOW_PAYLOAD_OUT)" \
		--out "$(CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT)" \
		$(CHANGZHOU_DIFY_WORKFLOW_SYNC_EXTRA_ARGS)

changzhou-dify-workflow-sync-apply:
	$(PY) scripts/changzhou_gov_dify_workflow_sync.py \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--workflow-json "$(CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--backup-out "$(CHANGZHOU_DIFY_WORKFLOW_BACKUP_OUT)" \
		--payload-out "$(CHANGZHOU_DIFY_WORKFLOW_PAYLOAD_OUT)" \
		--out "$(CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT)" \
		--apply \
		$(CHANGZHOU_DIFY_WORKFLOW_SYNC_EXTRA_ARGS)

changzhou-dify-knowledge-map-check:
	$(PY) scripts/changzhou_gov_dify_knowledge_map_check.py \
		--env-file "$(CHANGZHOU_DIFY_KNOWLEDGE_MAP_ENV_FILE)" \
		--out "$(CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT)"

changzhou-dify-mimirq-direct-gate:
	$(PY) scripts/changzhou_gov_golden_eval.py \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--env-file "$(CHANGZHOU_DIFY_MIMIRQ_ENV_FILE)" \
		--top-k $(CHANGZHOU_DIFY_PROBE_TOP_K) \
		--timeout $(CHANGZHOU_DIFY_PROBE_TIMEOUT) \
		--out "$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT)" \
		$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_EXTRA_ARGS)

changzhou-dify-mimirq-direct-kg-off-gate:
	$(PY) scripts/changzhou_gov_golden_eval.py \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--env-file "$(CHANGZHOU_DIFY_MIMIRQ_ENV_FILE)" \
		--top-k $(CHANGZHOU_DIFY_PROBE_TOP_K) \
		--timeout $(CHANGZHOU_DIFY_PROBE_TIMEOUT) \
		--kg-mode off \
		--out "$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_OFF_OUT)" \
		$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_EXTRA_ARGS)

changzhou-dify-mimirq-direct-kg-on-gate:
	$(PY) scripts/changzhou_gov_golden_eval.py \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--env-file "$(CHANGZHOU_DIFY_MIMIRQ_ENV_FILE)" \
		--top-k $(CHANGZHOU_DIFY_PROBE_TOP_K) \
		--timeout $(CHANGZHOU_DIFY_PROBE_TIMEOUT) \
		--kg-mode on \
		--out "$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_ON_OUT)" \
		$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_EXTRA_ARGS)

changzhou-dify-kg-compare-gate:
	@test -n "$(CHANGZHOU_DIFY_KG_BASELINE_REPORT)" || (echo "CHANGZHOU_DIFY_KG_BASELINE_REPORT is required" >&2; exit 2)
	@test -n "$(CHANGZHOU_DIFY_KG_CANDIDATE_REPORT)" || (echo "CHANGZHOU_DIFY_KG_CANDIDATE_REPORT is required" >&2; exit 2)
	@test -n "$(CHANGZHOU_DIFY_KG_COMPARE_OUT)" || (echo "CHANGZHOU_DIFY_KG_COMPARE_OUT is required" >&2; exit 2)
	$(PY) scripts/changzhou_gov_golden_eval.py \
		--baseline-report "$(CHANGZHOU_DIFY_KG_BASELINE_REPORT)" \
		--candidate-report "$(CHANGZHOU_DIFY_KG_CANDIDATE_REPORT)" \
		--out "$(CHANGZHOU_DIFY_KG_COMPARE_OUT)" \
		$(CHANGZHOU_DIFY_KG_COMPARE_EXTRA_ARGS)

changzhou-dify-kg-on-off-gate:
	$(MAKE) changzhou-dify-mimirq-direct-kg-off-gate
	$(MAKE) changzhou-dify-mimirq-direct-kg-on-gate
	$(MAKE) changzhou-dify-kg-compare-gate \
		CHANGZHOU_DIFY_KG_BASELINE_REPORT="$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_OFF_OUT)" \
		CHANGZHOU_DIFY_KG_CANDIDATE_REPORT="$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_ON_OUT)" \
		CHANGZHOU_DIFY_KG_COMPARE_OUT="$(if $(strip $(CHANGZHOU_DIFY_KG_COMPARE_OUT)),$(CHANGZHOU_DIFY_KG_COMPARE_OUT),$(CHANGZHOU_DIFY_KG_ON_OFF_COMPARE_OUT))"

changzhou-dify-readiness-gate: CHANGZHOU_DIFY_EFFECTIVE_EXTRA_ARGS = $(CHANGZHOU_DIFY_EXTRA_ARGS) $(CHANGZHOU_DIFY_READINESS_EXTRA_ARGS)
changzhou-dify-readiness-gate:
	@set +e; \
	rm -f "$(CHANGZHOU_DIFY_PROBE_OUT)" "$(CHANGZHOU_DIFY_OUT_PREFIX).json" "$(CHANGZHOU_DIFY_OUT_PREFIX)_answers.json" \
		"$(CHANGZHOU_DIFY_OUT_PREFIX)_eval.json" "$(CHANGZHOU_DIFY_OUT_PREFIX)_trace.json" "$(CHANGZHOU_DIFY_OUT_PREFIX)_summary.json" "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		"$(CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT)" "$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT)" "$(DIFY_CONSOLE_CHECK_OUT)"; \
	$(MAKE) changzhou-dify-knowledge-map-check; map_rc=$$?; \
	if [ $$map_rc -eq 0 ]; then \
		$(MAKE) changzhou-dify-mimirq-direct-gate; direct_rc=$$?; \
	else \
		direct_rc=1; \
	fi; \
	if [ $$map_rc -eq 0 ] && [ $$direct_rc -eq 0 ]; then \
		$(MAKE) dify-console-ensure; auth_rc=$$?; \
	else \
		auth_rc=1; \
	fi; \
	if [ $$map_rc -eq 0 ] && [ $$direct_rc -eq 0 ] && [ $$auth_rc -eq 0 ]; then \
		$(MAKE) changzhou-dify-external-probe; probe_rc=$$?; \
	else \
		probe_rc=1; \
	fi; \
	if [ $$auth_rc -eq 0 ] && [ $$probe_rc -eq 0 ]; then \
		$(MAKE) changzhou-dify-full-gate CHANGZHOU_DIFY_EFFECTIVE_EXTRA_ARGS="$(CHANGZHOU_DIFY_EXTRA_ARGS) $(CHANGZHOU_DIFY_READINESS_EXTRA_ARGS)"; full_rc=$$?; \
	else \
		full_rc=1; \
	fi; \
	$(MAKE) changzhou-dify-readiness-summary; summary_rc=$$?; \
	if [ $$map_rc -ne 0 ] || [ $$direct_rc -ne 0 ] || [ $$auth_rc -ne 0 ] || [ $$probe_rc -ne 0 ] || [ $$full_rc -ne 0 ] || [ $$summary_rc -ne 0 ]; then \
		exit 1; \
	fi

changzhou-dify-readiness-gate-quiet:
	@set +e; \
	$(MAKE) --no-print-directory changzhou-dify-readiness-gate >"$(CHANGZHOU_DIFY_READINESS_LOG)" 2>&1; rc=$$?; \
	$(MAKE) --no-print-directory changzhou-dify-readiness-status; \
	echo "Readiness raw log: $(CHANGZHOU_DIFY_READINESS_LOG)"; \
	exit $$rc

changzhou-dify-readiness-summary:
	$(PY) scripts/changzhou_gov_dify_readiness_summary.py \
		--knowledge-map "$(CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT)" \
		--mimirq-direct "$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT)" \
		--console-auth "$(DIFY_CONSOLE_CHECK_OUT)" \
		--external-probe "$(CHANGZHOU_DIFY_PROBE_OUT)" \
		$(if $(strip $(CHANGZHOU_DIFY_KG_COMPARE_OUT)),--kg-compare "$(CHANGZHOU_DIFY_KG_COMPARE_OUT)") \
		--full-summary "$(CHANGZHOU_DIFY_OUT_PREFIX)_summary.json" \
		--answers "$(CHANGZHOU_DIFY_OUT_PREFIX)_answers.json" \
		--eval "$(CHANGZHOU_DIFY_OUT_PREFIX)_eval.json" \
		--trace "$(CHANGZHOU_DIFY_OUT_PREFIX)_trace.json" \
		--out "$(CHANGZHOU_DIFY_READINESS_OUT)"

changzhou-dify-readiness-status:
	$(PY) scripts/changzhou_gov_dify_readiness_status.py \
		--summary "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		--console-ui-base-url "$(DIFY_CONSOLE_UI_BASE_URL)" \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" || true

changzhou-dify-readiness-evidence:
	$(PY) scripts/changzhou_gov_dify_readiness_status.py \
		--summary "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		--console-ui-base-url "$(DIFY_CONSOLE_UI_BASE_URL)" \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--markdown-out "$(CHANGZHOU_DIFY_READINESS_EVIDENCE_OUT)"

changzhou-dify-readiness-persist-audit:
	@test -n "$(CHANGZHOU_GOV_CORPUS_DATASET_ID)" || (echo "Set CHANGZHOU_GOV_CORPUS_DATASET_ID=<dataset_uuid>" >&2; exit 2)
	$(PY) scripts/persist_retrieval_audit_snapshot.py \
		--summary "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		--base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--dataset-id "$(CHANGZHOU_GOV_CORPUS_DATASET_ID)" \
		--tenant-id "$(MIMIRQ_TENANT_ID)" \
		--account-id "$(MIMIRQ_ACCOUNT_ID)" \
		--user-id "$(MIMIRQ_USER_ID)" \
		$(if $(strip $(MIMIRQ_API_TOKEN)),--bearer "$(MIMIRQ_API_TOKEN)") \
		--timeout $(MIMIRQ_API_TIMEOUT) \
		--verify-report \
		--out "$(CHANGZHOU_DIFY_READINESS_AUDIT_OUT)"

changzhou-dify-full-gate:
	$(PY) scripts/changzhou_gov_dify_full_gate.py \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--dify-base-url "$(CHANGZHOU_DIFY_BASE_URL)" \
		--dify-api-key-file "$(CHANGZHOU_DIFY_API_KEY_FILE)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--mimirq-base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--out "$(CHANGZHOU_DIFY_OUT_PREFIX).json" \
		--answers-out "$(CHANGZHOU_DIFY_OUT_PREFIX)_answers.json" \
		--eval-out "$(CHANGZHOU_DIFY_OUT_PREFIX)_eval.json" \
		--trace-out "$(CHANGZHOU_DIFY_OUT_PREFIX)_trace.json" \
		--summary-out "$(CHANGZHOU_DIFY_OUT_PREFIX)_summary.json" \
		--trace-timeout "$(CHANGZHOU_DIFY_TRACE_TIMEOUT)" \
		$(CHANGZHOU_DIFY_EFFECTIVE_EXTRA_ARGS)

changzhou-human-mixed-cases:
	$(PY) plugins/pipelines/changzhou-gov-service-knowledge/tools/build_human_mixed_cases.py \
		--cases "$(CHANGZHOU_HUMAN_MIXED_SOURCE)" \
		--out "$(CHANGZHOU_HUMAN_MIXED_OUT)" \
		--total "$(CHANGZHOU_HUMAN_MIXED_TOTAL)" \
		--max-qa-ratio "$(CHANGZHOU_HUMAN_MIXED_MAX_QA_RATIO)"

changzhou-eval-pack-generate:
	$(PY) scripts/changzhou_gov_eval_pack.py \
		--corpus-root "$(CHANGZHOU_EVAL_CORPUS_ROOT)" \
		--out-dir "$(CHANGZHOU_EVAL_OUT)" \
		--qa-count "$(CHANGZHOU_EVAL_QA_COUNT)" \
		--service-count "$(CHANGZHOU_EVAL_SERVICE_COUNT)" \
		--user-count "$(CHANGZHOU_EVAL_USER_COUNT)"

changzhou-eval-pack-import:
	$(PY) scripts/changzhou_gov_eval_pack.py \
		--corpus-root "$(CHANGZHOU_EVAL_CORPUS_ROOT)" \
		--out-dir "$(CHANGZHOU_EVAL_LIVE_OUT)" \
		--qa-count "$(CHANGZHOU_EVAL_QA_COUNT)" \
		--service-count "$(CHANGZHOU_EVAL_SERVICE_COUNT)" \
		--user-count "$(CHANGZHOU_EVAL_USER_COUNT)" \
		--resolve-live-refs \
		--import-regression \
		--overwrite \
		--create-retrieval-run \
		--backend-base-url "$(CHANGZHOU_EVAL_BACKEND_BASE_URL)"

changzhou-dify-4way-preflight:
	$(PY) scripts/dify_3way_benchmark.py \
		--prebuilt-cases "$(CHANGZHOU_EVAL_OUT)/cases_1000.json" \
		--out-dir "$(CHANGZHOU_DIFY_4WAY_PREFLIGHT_OUT)" \
		--limit 1 \
		--app-key-file "$(CHANGZHOU_DIFY_4WAY_APP_KEYS)" \
		--app 'dify_native_kb:00000000-0000-0000-0000-000000000001:native_dify_knowledge:dify_native_kb:auto' \
		--app 'dify_http_mimirq:00000000-0000-0000-0000-000000000002:http_to_mimirq:dify_http_mimirq:auto' \
		--app 'dify_external_mimirq:00000000-0000-0000-0000-000000000003:external_to_mimirq:dify_external_mimirq:auto' \
		--include-mimirq-direct \
		--auto-mode \
		--timeout 120 \
		--preflight

changzhou-dify-4way-smoke:
	$(PY) scripts/dify_3way_benchmark.py \
		--prebuilt-cases "$(CHANGZHOU_EVAL_OUT)/cases_1000.json" \
		--out-dir "$(CHANGZHOU_DIFY_4WAY_SMOKE_OUT)" \
		--sample-per-type 2 \
		--app-key-file "$(CHANGZHOU_DIFY_4WAY_APP_KEYS)" \
		--app 'dify_native_kb:00000000-0000-0000-0000-000000000001:native_dify_knowledge:dify_native_kb:auto' \
		--app 'dify_http_mimirq:00000000-0000-0000-0000-000000000002:http_to_mimirq:dify_http_mimirq:auto' \
		--app 'dify_external_mimirq:00000000-0000-0000-0000-000000000003:external_to_mimirq:dify_external_mimirq:auto' \
		--include-mimirq-direct \
		--auto-mode \
		--concurrency 4 \
		--timeout 180 \
		--resume \
		--write-bundle

changzhou-dify-4way-full:
	$(PY) scripts/dify_3way_benchmark.py \
		--prebuilt-cases "$(CHANGZHOU_EVAL_OUT)/cases_1000.json" \
		--out-dir "$(CHANGZHOU_DIFY_4WAY_FULL_OUT)" \
		--app-key-file "$(CHANGZHOU_DIFY_4WAY_APP_KEYS)" \
		--app 'dify_native_kb:00000000-0000-0000-0000-000000000001:native_dify_knowledge:dify_native_kb:auto' \
		--app 'dify_http_mimirq:00000000-0000-0000-0000-000000000002:http_to_mimirq:dify_http_mimirq:auto' \
		--app 'dify_external_mimirq:00000000-0000-0000-0000-000000000003:external_to_mimirq:dify_external_mimirq:auto' \
		--include-mimirq-direct \
		--auto-mode \
		--concurrency 4 \
		--timeout 180 \
		--resume \
		--write-bundle

changzhou-dify-4way-merge-report:
	$(PY) scripts/assemble_dify_benchmark_report.py \
		--cases "$(CHANGZHOU_EVAL_OUT)/cases_1000.json" \
		--out-dir "$(CHANGZHOU_DIFY_4WAY_MERGED_OUT)" \
		--app-key-file "$(CHANGZHOU_DIFY_4WAY_APP_KEYS)" \
		--source-dir "$(CHANGZHOU_DIFY_4WAY_FULL_OUT)" \
		--source-dir artifacts/changzhou_dify_http_full \
		--source-dir artifacts/changzhou_dify_external_full \
		--include-mimirq-direct \
		--write-bundle \
		--app 'dify_native_kb:00000000-0000-0000-0000-000000000001:native_dify_knowledge:dify_native_kb:auto' \
		--app 'dify_http_mimirq:00000000-0000-0000-0000-000000000002:http_to_mimirq:dify_http_mimirq:auto' \
		--app 'dify_external_mimirq:00000000-0000-0000-0000-000000000003:external_to_mimirq:dify_external_mimirq:auto'

changzhou-kg-on-off-benchmark:
	$(PY) scripts/changzhou_gov_kg_on_off_benchmark.py \
		--cases "$(CHANGZHOU_EVAL_OUT)/cases_1000.json" \
		--out-dir "$(CHANGZHOU_KG_ON_OFF_OUT)" \
		--base-url "$(CHANGZHOU_EVAL_BACKEND_BASE_URL)"
