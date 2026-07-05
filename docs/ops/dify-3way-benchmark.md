# Dify 三路 800 题对比测试

本说明用于复现 3 个 Dify App 的同题对比评测：原生 Dify 知识库、Dify HTTP 接入 MimirQ、Dify 外部知识库接入 MimirQ。

## App 映射

| 系统标签 | Dify App ID | 类型 |
| --- | --- | --- |
| `dify_native_kb` | `00000000-0000-0000-0000-000000000001` | 原生 Dify 知识库 |
| `dify_http_mimirq` | `00000000-0000-0000-0000-000000000002` | HTTP 接入 MimirQ，可回写证据 |
| `dify_external_mimirq` | `00000000-0000-0000-0000-000000000003` | Dify External Knowledge 接入 MimirQ |

默认 App API 地址为 `https://dify.example.com:5001/v1`。页面工作流地址 `https://dify.example.com:3000/brainai/app/.../workflow` 不是 App API 调用地址。

## 已生成数据

生成命令：

```bash
python scripts/dify_3way_benchmark.py \
  --generate-only \
  --out-dir artifacts/dify_3way_benchmark \
  --target-count 800
```

当前产物：

| 文件 | 用途 |
| --- | --- |
| `artifacts/dify_3way_benchmark/cases_800.json` | 800 条问题，包含 QA、混合问题、模拟用户问题等 8 类问题 |
| `artifacts/dify_3way_benchmark/truth_manifest.json` | 每题对应的原始依据、来源记录、必答维度和证据 clause |
| `artifacts/dify_3way_benchmark/apps.json` | 三个 App 的脱敏配置 |
| `artifacts/dify_3way_benchmark/key_requirements.json` | 三个 App 的 key 准备清单、可接受 key 名称和可复制模板 |

当前 800 题分布：

| 类型 | 数量 |
| --- | ---: |
| `mixed` | 100 |
| `qa` | 100 |
| `simulated_user` | 100 |
| `mixed_followup` | 100 |
| `plain_user` | 100 |
| `noisy_user` | 100 |
| `operator_check` | 100 |
| `short_user` | 100 |

## Key 文件格式

远程 Dify 三路测试需要 App API key。把 key 写入本地临时文件，例如 `/tmp/dify_3way_app_keys.json`：

```json
{
  "dify_native_kb": { "api_key": "app-xxx" },
  "dify_http_mimirq": { "api_key": "app-xxx" },
  "dify_external_mimirq": { "api_key": "app-xxx" }
}
```

如果某个 App 需要走 Dify workflow API，可额外指定 `mode`：

```json
{
  "dify_http_mimirq": { "api_key": "app-xxx", "mode": "workflow" }
}
```

`mode` 默认为 `chat`，对应 `/chat-messages`；`workflow` 对应 `/workflows/run`；也可写 `auto` 让脚本先探测两个端点。因为这 3 个页面地址都是 `/workflow`，如果不确定 App API 应该走哪种接口，建议命令里加 `--auto-mode`。

也支持用 App ID 作为 key：

```json
{
  "00000000-0000-0000-0000-000000000001": "app-xxx",
  "00000000-0000-0000-0000-000000000002": "app-xxx",
  "00000000-0000-0000-0000-000000000003": "app-xxx"
}
```

脚本不会把真实 key 写入 `apps.json`、run 文件或对比报告。

如果不确定要填哪些 key，先运行任意一次 `--generate-only` 或 `--preflight`，查看输出目录里的 `key_requirements.json`。其中 `template` 字段可直接作为 `/tmp/dify_3way_app_keys.json` 的骨架，把 `app-xxx` 替换成真实 App API key 即可。

## 跑完整 800×3

建议先做 App API 预检，只打第一题，确认三路 key、endpoint 和返回结构可用：

```bash
python scripts/dify_3way_benchmark.py \
  --out-dir artifacts/dify_3way_benchmark_remote_preflight \
  --target-count 800 \
  --limit 1 \
  --app-key-file /tmp/dify_3way_app_keys.json \
  --auto-mode \
  --timeout 60 \
  --preflight
```

`--auto-mode` 会先生成 `mode_resolution_report.json`，记录每个 App 试过的 `/chat-messages` 和 `/workflows/run` 端点，并把后续 preflight/full run 使用的模式写回 `apps.json`。预检结果写入 `preflight_report.json`。如果 `summary.all_ready=true`，再做小样本烟测。`--sample-per-type 2` 会从 8 类问题各取 2 条，共 16 条，比单纯取前 N 条更能覆盖 QA、混合问题和模拟用户问题：

```bash
python scripts/dify_3way_benchmark.py \
  --out-dir artifacts/dify_3way_benchmark_remote_smoke \
  --target-count 800 \
  --sample-per-type 2 \
  --app-key-file /tmp/dify_3way_app_keys.json \
  --auto-mode \
  --concurrency 2 \
  --timeout 180 \
  --resume
```

确认三路都返回后再跑完整：

```bash
python scripts/dify_3way_benchmark.py \
  --out-dir artifacts/dify_3way_benchmark_remote_full \
  --target-count 800 \
  --app-key-file /tmp/dify_3way_app_keys.json \
  --auto-mode \
  --concurrency 3 \
  --timeout 180 \
  --resume \
  --write-bundle \
  --strict-complete
```

如果某次中断，重复同一命令即可续跑；已有结果会复用。若完整的 `run_*.json` 已经存在，即使当前机器没有对应 App API key，`--resume` 也会复用历史结果重新生成报告，不会把已有结果覆盖成空的 `missing_api_key`。若要重跑失败样本：

```bash
python scripts/dify_3way_benchmark.py \
  --out-dir artifacts/dify_3way_benchmark_remote_full \
  --target-count 800 \
  --app-key-file /tmp/dify_3way_app_keys.json \
  --auto-mode \
  --concurrency 3 \
  --timeout 180 \
  --resume \
  --retry-failures \
  --write-bundle \
  --strict-complete
```

如果三路 `run_*.json` 已经存在，只想离线重新生成评分、审计表和 Markdown，不触发任何远程调用，也不改写 run 文件：

```bash
python scripts/dify_3way_benchmark.py \
  --out-dir artifacts/dify_3way_benchmark_remote_full \
  --target-count 800 \
  --report-only \
  --write-bundle \
  --strict-complete
```

## 报告解读

完整运行后重点看：

| 文件 | 用途 |
| --- | --- |
| `run_dify_native_kb.json` | 原生 Dify 知识库逐题结果 |
| `run_dify_http_mimirq.json` | HTTP 接入 MimirQ 逐题结果 |
| `run_dify_external_mimirq.json` | External Knowledge 接入 MimirQ 逐题结果 |
| `key_requirements.json` | App API key 准备清单；缺 key 时优先看这个文件 |
| `mode_resolution_report.json` | 使用 `--auto-mode` 时生成，记录 chat/workflow 端点探测和最终选中的 API 模式 |
| `comparison_report.json` | 机器可读总评、逐题评分、pairwise 对比 |
| `comparison_report.md` | 可读排行榜和摘要 |
| `summary_for_sharing.md` | 可直接转发的短摘要，包含完整性、排行榜、准确率结构和优先排查样本 |
| `audit_review.jsonl` | 逐题逐系统审计行，包含原始证据条款、缺失项、判定标签、答案预览 |
| `audit_review.csv` | 与 `audit_review.jsonl` 同内容的表格版，方便筛选抽查 |
| `artifact_manifest.json` | 产物清单，包含关键文件路径、大小和 SHA256，方便归档或校验 |
| `dify_3way_benchmark_bundle.zip` | 使用 `--write-bundle` 时生成的交付包，包含报告、审计表、run 文件和 manifest |

评分基于原始题目中的 `evidence_clauses`、`subquestions` 和检索/回答文本做确定性匹配，不使用 LLM 裁判。

`comparison_report.md` 会额外生成中文结论摘要、“优势汇总”、“审计判定分布”、“按问题类型看优势”、“按业务维度看优势”和“Top 问题样本”表。机器可读版本中对应字段为 `advantage_summary`、`audit_verdict_summary`、`case_type_advantage`、`dimension_advantage` 和 `top_issue_cases`，可直接查看总体第一、类型/维度胜出最多的系统、各系统准确/部分准确/证据不足/无答案的分布、QA/混合问题/模拟用户问题等类型下哪个系统表现更好、办理地点/办理时间/办件类型等业务维度下哪个系统更强，以及最值得优先排查的低分样本。

最终全量报告必须满足 `comparison_report.json` 中 `completion_status.complete_3way_800=true`。如果使用 `--strict-complete`，三路未跑满 800 题或有系统被跳过时脚本会返回非 0，避免把 smoke 或缺 key 报告误当最终结论。

人工抽查优先看 `audit_review.csv`：

| 字段 | 含义 |
| --- | --- |
| `verdict` | 基于原始证据 clause 的判定：准确、部分准确、证据不足、无答案 |
| `score_reason` | 中文判定理由，说明缺了哪些原始证据、子问题或是否存在错证据 |
| `expected_answer_basis` | 从原始数据抽取的标准答案依据摘要 |
| `native_evidence_preview` | 原始题目/证据条款摘要，用来人工对照系统答案 |
| `required_evidence_terms` | 原始数据里本题必须命中的证据条款 |
| `missing_evidence_clause_ids` | 检索证据缺失的条款 ID |
| `missing_subquestion_ids` | 必答子问题缺失项 |
| `answer_preview` | 系统答案预览 |
| `top_record_preview` | 第一条检索证据预览 |

主要指标：

| 指标 | 含义 |
| --- | --- |
| `mean_answer_clause_coverage` | 回答覆盖原始证据 clause 的比例 |
| `mean_answer_subquestion_coverage` | 回答覆盖必答子问题的比例 |
| `mean_evidence_coverage` | 检索证据覆盖原始答案依据的比例 |
| `mean_wrong_evidence_rate` | 检索结果中未命中本题依据的比例 |
| `mean_latency_ms` | 平均延迟 |

## 当前状态

本地已经生成 800 题和 truth manifest，并验证脚本支持断点续跑。

当前无法完成远程三路全量对比的唯一硬阻塞是：本机未发现这 3 个 Dify App 的 App API key。缺 key 时脚本会生成 skipped run 文件，并在 `comparison_report.json` 的 `summary.skipped_systems` 中列出被跳过系统。
