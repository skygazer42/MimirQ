# Changzhou Dify/MimirQ Readiness Runbook

本 runbook 面向常州政务知识库接入 Dify 的运维与交付验证。目标是用一组可复跑命令证明：

- MimirQ 直连检索质量可用。
- Dify external knowledge 能命中 MimirQ。
- Dify workflow 草稿没有会泄漏给用户的 prompt 模板控制语。
- Dify App 真实回答、检索路由、trace 结果全部通过 golden gate。

> 安全边界：不要把 token、password 或 API key 写入文档、commit 或工单。所有凭据通过本机文件或环境变量传入。

---

## 1. 前置条件

默认生产验证目标：

```bash
export CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://192.0.2.6:8000
export DIFY_CONSOLE_EMAIL='<operator-email>'
export DIFY_CONSOLE_PASSWORD_FILE=/tmp/dify_console_password.txt
```

本机需要存在：

- `/tmp/dify_console_password.txt`：Dify console 登录密码文件。
- `/tmp/dify_remote_app_api_key.json`：Dify App API key 文件。
- `/tmp/dify_console_storage_state.json`：Dify console storage state，失效时由 `make dify-console-ensure` 自动刷新。
- `.env`：MimirQ external knowledge key / Dify knowledge map 等本地配置。

先刷新或确认 Dify console 登录态：

```bash
DIFY_CONSOLE_EMAIL="$DIFY_CONSOLE_EMAIL" \
DIFY_CONSOLE_PASSWORD_FILE="$DIFY_CONSOLE_PASSWORD_FILE" \
make dify-console-ensure
```

---

## 2. 一键 readiness gate

标准复跑命令：

```bash
DIFY_CONSOLE_EMAIL="$DIFY_CONSOLE_EMAIL" \
DIFY_CONSOLE_PASSWORD_FILE="$DIFY_CONSOLE_PASSWORD_FILE" \
make changzhou-dify-readiness-gate \
  CHANGZHOU_DIFY_MIMIRQ_BASE_URL="$CHANGZHOU_DIFY_MIMIRQ_BASE_URL"
```

交付/协作时建议使用静默版，避免终端刷出原始 query、生成答案和证据正文：

```bash
DIFY_CONSOLE_EMAIL="$DIFY_CONSOLE_EMAIL" \
DIFY_CONSOLE_PASSWORD_FILE="$DIFY_CONSOLE_PASSWORD_FILE" \
make changzhou-dify-readiness-gate-quiet \
  CHANGZHOU_DIFY_MIMIRQ_BASE_URL="$CHANGZHOU_DIFY_MIMIRQ_BASE_URL"
```

静默版会把 raw stdout/stderr 写到本机：

- `/tmp/changzhou_gov_dify_readiness_gate.log`

该 log 只用于本机排障，不应作为可分享交付材料。

通过标准：

- `summary.passed=true`
- `failed_stages=[]`
- `stage_count=5`
- `knowledge_map.status=passed`
- `mimirq_direct.status=passed`
- `console_auth.status=passed`
- `external_probe.status=passed`
- `full_gate.status=passed`

主报告：

- `/tmp/changzhou_gov_dify_readiness_summary.json`

快速查看摘要：

```bash
make changzhou-dify-readiness-status
```

生成可分享的 PII-safe Markdown 证据：

```bash
make changzhou-dify-readiness-evidence
```

输出：

- `/tmp/changzhou_gov_dify_readiness_evidence.md`

生成交付总索引（插件切块证据 + Dify readiness 证据）：

```bash
make changzhou-gov-plugin-chunk-evidence
make changzhou-gov-plugin-test-report
make changzhou-gov-plugin-test-evidence
make changzhou-gov-delivery-pack
```

若需要先刷新远端 readiness gate 再生成交付总索引，使用：

```bash
DIFY_CONSOLE_EMAIL="$DIFY_CONSOLE_EMAIL" \
DIFY_CONSOLE_PASSWORD_FILE="$DIFY_CONSOLE_PASSWORD_FILE" \
make changzhou-gov-delivery-pack-refresh \
  CHANGZHOU_DIFY_MIMIRQ_BASE_URL="$CHANGZHOU_DIFY_MIMIRQ_BASE_URL"
```

输出：

- `/tmp/changzhou_gov_delivery_pack.json`
- `/tmp/changzhou_gov_delivery_pack.md`

该命令会刷新本地插件 01-06 切块 raw 审查报告、去掉样例内容的 plugin chunk evidence、
插件 local test/Golden draft raw 报告、以及去掉 Golden 样例问题的 plugin test evidence，
再读取 readiness summary/evidence 生成总索引；不会调用远端 Dify，不会写数据库、向量库
或 KG 存储。默认要求 readiness summary 生成时间不超过 30 分钟，超时会标记
`readiness_fresh=false` 并返回失败，避免把旧 gate 结果当成交付证据。

如果要证明真实语料已经经过插件治理/切块/KG、写入索引，并且 Golden 检索闭环通过，
显式运行 corpus closed-loop gate：

```bash
make changzhou-gov-plugin-corpus-closed-loop-smoke \
  CHANGZHOU_DIFY_MIMIRQ_BASE_URL="$CHANGZHOU_DIFY_MIMIRQ_BASE_URL" \
  CHANGZHOU_GOV_CORPUS_SOURCE_DIR="/path/to/20260522政务服务智能客服知识" \
  CHANGZHOU_GOV_CORPUS_EXTRA_ARGS="--include-source-root-name --overwrite-goldens"

make changzhou-gov-plugin-corpus-closed-loop-evidence
```

该 gate 会上传本地语料、触发插件 pipeline、等待文档处理/切片完成、从真实切片导入
Golden case，并启动 retrieval-only regression。它会写数据库、向量索引和 KG/事件索引；
因此不放进默认 delivery-pack-refresh，避免无意创建或污染数据集。若不传
`CHANGZHOU_GOV_CORPUS_DATASET_ID`，脚本会创建隔离测试数据集。
`/tmp/changzhou_gov_plugin_corpus_closed_loop_report.json` 是本机 raw report，可能包含
source path、document id、case id 和文件名；交付时使用
`/tmp/changzhou_gov_plugin_corpus_closed_loop_evidence.json` 和 `.md`，只保留文档/切片聚合、
插件包 provenance 和 Golden 检索聚合指标。默认 evidence gate 要求
`retrieval_recall>=1.0`、`retrieval_hit_at_3>=0.8`、`expected_metadata_hit_rate=1.0`
和 `expected_metadata_recall=1.0`；`retrieval_hit_at_1`、MRR、NDCG、`citation_accuracy`
和 `citation_coverage` 会展示出来用于判断首位排序和引用质量。citation 阈值默认不作为失败条件，
需要发布级引用质量门禁时可通过 `CHANGZHOU_GOV_CORPUS_MIN_CITATION_ACCURACY` 和
`CHANGZHOU_GOV_CORPUS_MIN_CITATION_COVERAGE` 显式设置。corpus evidence 还会展示
`citation_eval_limit_avg`、`citation_evaluated_count_avg` 和 `citation_total_count_avg`，
用于区分最终 top-k 评测窗口和层级召回扩展候选池规模。Changzhou corpus gate 默认
`CHANGZHOU_GOV_CORPUS_REGRESSION_TOP_K=5`，对齐 Dify 常用 top-k 消费窗口，并默认要求
`CHANGZHOU_GOV_CORPUS_MIN_CITATION_ACCURACY=0.5`；若要做更宽的召回审计，可显式改成
top10/top20，但不应把宽候选池 precision 当作最终回答上下文质量。

---

## 3. Gate 分层含义

`make changzhou-dify-readiness-gate` 按顺序运行：

1. `make changzhou-dify-knowledge-map-check`
   - 验证 Dify external knowledge map、本级知识库、区县 route、区县 knowledge id，以及声明的 `plugin_refs` 是否具备可用 `retrieval_policy`。
   - `summary.plugin_refs_checked`、`summary.plugin_refs_invalid`、`summary.plugin_refs_missing_retrieval_policy` 可直接用于定位插件绑定问题，并会进入 readiness status / Markdown evidence。
   - 失败先修 `.env` 里的 `DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON`。

2. `make changzhou-dify-mimirq-direct-gate`
   - 直接打 MimirQ `/api/v1/integrations/dify`，不经过 Dify App。
   - 关键指标：`hit_at_1=1.0`、`answer_grounding_rate=1.0`、`answer_key_point_recall=1.0`。
   - 失败说明 MimirQ 入库、插件切块、metadata、索引或检索策略有问题。

3. 可选：`make changzhou-dify-kg-on-off-gate`
   - 先用 `--kg-mode off/on` 分别请求 MimirQ direct gate，生成 KG-off 与 KG-on golden report，再做 saved-report 对比。
   - `--kg-mode` 是 MimirQ direct-gate 扩展：`default` 继承服务配置；`off/on` 用请求级 KG override 覆盖 Dify adapter 的 KG 查询扩展、KG chunk 注入与 KG boost。
   - 已有报告也可直接比较：
     `CHANGZHOU_DIFY_KG_BASELINE_REPORT=/tmp/kg-off.json CHANGZHOU_DIFY_KG_CANDIDATE_REPORT=/tmp/kg-on.json CHANGZHOU_DIFY_KG_COMPARE_OUT=/tmp/changzhou_gov_dify_kg_compare.json make changzhou-dify-kg-compare-gate`
   - 候选报告必须通过 `changzhou-retrieval` profile，且不能降低 hit、grounding、effective context、metadata match 等基线指标。
   - `kg_noise_rate` 走候选报告绝对上限，默认 `<= 0.1`，不和 KG-off 的 0 噪声做不合理比较。
   - 若设置 `CHANGZHOU_DIFY_KG_COMPARE_OUT=/tmp/changzhou_gov_dify_kg_compare.json`，`make changzhou-dify-readiness-summary` 会把它纳入 `kg_compare` 阶段；失败会阻断后续远端 Dify gate。

4. `make dify-console-ensure`
   - 验证 console token 未过期；需要 trace 和 workflow draft 读取。

5. `make changzhou-dify-external-probe`
   - 通过 Dify console 的 hit-testing 入口验证 external knowledge 边界。
   - 关键结论：`dify_external_boundary_ok`。
   - 若 `dify_runtime_empty_but_mimirq_direct_ok > 0`，通常是 Dify external endpoint、dataset binding 或网络访问问题。

6. `make changzhou-dify-full-gate`
   - 调 Dify App API 做真实回答采集，再用 MimirQ direct retrieval 做质量评估，并拉取 Dify workflow trace。
   - 关键指标：
     - `generated_answer_policy_clean_rate`
     - `generated_answer_grounding_rate`
     - `generated_answer_key_point_recall`
     - `fallback_cases`
     - `empty_retrieval_cases`
     - `route_mismatch_cases`

---

## 4. 关键 artifacts

统一 readiness summary 会引用这些文件：

- `/tmp/changzhou_gov_dify_knowledge_map_check.json`
- `/tmp/changzhou_gov_dify_mimirq_direct_gate.json`
- `/tmp/changzhou_gov_dify_kg_compare.json`
- `/tmp/dify_console_check.json`
- `/tmp/changzhou_gov_dify_external_probe.json`
- `/tmp/changzhou_gov_dify_full_gate_summary.json`
- `/tmp/changzhou_gov_dify_full_gate_answers.json`
- `/tmp/changzhou_gov_dify_full_gate_eval.json`
- `/tmp/changzhou_gov_dify_full_gate_trace.json`
- `/tmp/changzhou_gov_dify_readiness_summary.json`
- `/tmp/changzhou_gov_dify_readiness_evidence.md`
- `/tmp/changzhou_gov_dify_readiness_gate.log`
- `/tmp/changzhou_gov_plugin_chunk_evidence.json`
- `/tmp/changzhou_gov_plugin_chunk_evidence.md`
- `/tmp/changzhou_gov_plugin_test_evidence.json`
- `/tmp/changzhou_gov_plugin_test_evidence.md`
- `/tmp/changzhou_gov_plugin_corpus_closed_loop_evidence.json`（显式 corpus gate 后生成）
- `/tmp/changzhou_gov_plugin_corpus_closed_loop_evidence.md`（显式 corpus gate 后生成）
- `/tmp/changzhou_gov_delivery_pack.json`
- `/tmp/changzhou_gov_delivery_pack.md`

这些文件在 `/tmp`，用于当前机器上的交付证据和排障，不应提交到 git。
`/tmp/changzhou_gov_plugin_chunk_report.json` 和 `.md` 是本机 raw report，可能包含
切块样例预览，只用于人工审查和排障，不作为可分享交付材料。
`/tmp/changzhou_gov_plugin_test_report.json` 是本机 raw report，可能包含 Golden
草稿样例问题，只用于排障，不作为可分享交付材料。

---

## 5. Dify workflow 草稿修复流程

先 lint 当前 Dify workflow 草稿并生成清洗稿：

```bash
make changzhou-dify-workflow-lint
```

输出：

- `/tmp/changzhou_gov_dify_workflow_lint.json`
- `/tmp/changzhou_gov_dify_workflow_sanitized.json`

再 dry-run 同步。该步骤默认不写远程 Dify，只生成当前草稿 backup 和将要 POST 的 payload：

```bash
make changzhou-dify-workflow-sync-dry-run
```

输出：

- `/tmp/changzhou_gov_dify_workflow_current_draft_backup.json`
- `/tmp/changzhou_gov_dify_workflow_sync_payload.json`
- `/tmp/changzhou_gov_dify_workflow_sync.json`

确认 payload 后才显式写草稿：

```bash
make changzhou-dify-workflow-sync-apply
```

只有显式运行 `make changzhou-dify-workflow-sync-apply` 才会写 Dify 草稿。`make changzhou-dify-workflow-sync-dry-run` 默认不写远程 Dify。

写入后必须复跑：

```bash
make changzhou-dify-workflow-lint
make changzhou-dify-readiness-gate CHANGZHOU_DIFY_MIMIRQ_BASE_URL="$CHANGZHOU_DIFY_MIMIRQ_BASE_URL"
```

---

## 6. 回滚

如果 `sync-apply` 后 Dify App 表现异常，先保留现场 artifacts，再用 backup 回滚。

1. 找到写入前 backup：

```bash
ls -lh /tmp/changzhou_gov_dify_workflow_current_draft_backup.json
```

2. 将 backup 作为 workflow JSON 做 dry-run，确认 payload：

```bash
CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT=/tmp/changzhou_gov_dify_workflow_current_draft_backup.json \
CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT=/tmp/changzhou_gov_dify_workflow_rollback_dry_run.json \
make changzhou-dify-workflow-sync-dry-run
```

3. 确认后再显式 apply 回滚：

```bash
CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT=/tmp/changzhou_gov_dify_workflow_current_draft_backup.json \
CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT=/tmp/changzhou_gov_dify_workflow_rollback_apply.json \
make changzhou-dify-workflow-sync-apply
```

4. 回滚后复跑 readiness gate。

---

## 7. 常见失败定位

| 失败位置 | 优先看 | 处理方向 |
| --- | --- | --- |
| `knowledge_map.failed_conditions` 非空 | `/tmp/changzhou_gov_dify_knowledge_map_check.json` | 修 `.env` 的 Dify knowledge map、区县 route、dataset ids 或 `plugin_refs` |
| `mimirq_direct.hit_at_1 < 1.0` | `/tmp/changzhou_gov_dify_mimirq_direct_gate.json` | 查插件切块、metadata、入库数据、索引和 MimirQ 检索策略 |
| `console_auth.passed=false` | `/tmp/dify_console_check.json` | 用 `DIFY_CONSOLE_EMAIL` 和 `DIFY_CONSOLE_PASSWORD_FILE` 重新 `make dify-console-login` |
| `external_probe.boundary.verdict != dify_external_boundary_ok` | `/tmp/changzhou_gov_dify_external_probe.json` | 查 Dify external endpoint 是否指向可达的 MimirQ URL，避免 localhost/错误主机 |
| `full_gate.preflight.case_input_violations > 0` | `/tmp/changzhou_gov_dify_full_gate_summary.json` | 给 golden cases 补 `dify_inputs.areaName` |
| `generated_answer_policy_clean_rate < 1.0` | `/tmp/changzhou_gov_dify_full_gate_answers.json` | 查 Dify prompt 是否泄漏模板控制语，重新跑 workflow lint/sync |
| `route_mismatch_cases > 0` | `/tmp/changzhou_gov_dify_full_gate_trace.json` | 查 Dify workflow 区域分支是否使用 Start.areaName 或等价确定性路由 |
