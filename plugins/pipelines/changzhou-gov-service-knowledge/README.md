# 常州政务服务知识插件

样例数据包：

```text
/path/to/gov-service-knowledge
```

插件不依赖这个绝对路径。生产入库时按知识库内文件的相对目录、文件名和内容特征分流 handler。
同结构的政务服务知识包可以复用同一个插件。

插件引用：

```text
plugin:changzhou-gov-service-knowledge@1.0.0:governance
plugin:changzhou-gov-service-knowledge@1.0.0:chunk
plugin:changzhou-gov-service-knowledge@1.0.0:kg
```

标准声明：

```text
metadata_schema.json
retrieval_text_schema.json
golden_rules.json
processing_templates.json
```

`processing_templates.json` 记录本业务包的治理模板归属。常州政务、公积金、不动产、应急局等专项规则只在该插件包内维护，平台内置治理模板库保持业务中立。

## 规则

- `01政务服务事项知识/*事项清单.txt`
  - 按 `[事项名称：...]` 与 `==##########==` 治理成事项记录。
  - 短事项一事项一块，长事项按字段组拆分。
  - KG 按切块生成确定性事件，实体包括 `ServiceItem`、`District`、`Material`、`Channel`、`Location`、`Contact`、`Url`。

- `02高效办成一件事/一件事指南.txt`
  - 按 `[xxx“一件事”]` 和分隔符治理成一件事指南。
  - 按业务章节切成 `related_services`、`process`、`materials`、`conditions`、`notes` 等 section chunk。
  - chunk metadata 保留 `case_key`、`section_type`、`related_services`、`materials`、`urls`。
  - KG 生成 `OneThingCase`、`Keyword`、`ServiceItem`、`Material`、`Url` 实体。

- `02高效办成一件事/一件事操作指引.txt`
  - 按 `--##########--` 或 `xxx“一件事”操作指引` 分段。
  - 每个操作指引形成独立业务记录，再按 `operation_entry`、`operation_steps`、`operation_notes`、`operation_url` 等 section chunk 切块。
  - chunk metadata 保留 `case_key`、`section_type`、`operation_steps`、`urls`、`step_no`。
  - KG 生成 `OneThingCase`、`OperationStep`、`Url` 实体。

- `03常州市常见问题`、`04专题常见问答`、`06各区常见问题`
  - 按 `问题/答案/来源部门` 解析为 QA。
  - 兼容 `关键字`、`相似问`、`相似问法`、答案内 URL，并写入 `keywords`、`aliases`、`urls`、`source_topic`。
  - 兼容 Excel 解析后的 markdown 表格，按 `问题/问答标题`、`答案/问答答案`、`问答提供部门` 等列治理成 QA。
  - 每个 QA 默认一块，长答案按段落切分。
  - KG 生成 `Question`、`Department`、`District`、`Keyword`、`Url`、`GovKnowledgeTopic`、`SourceSheet` 实体，并保留相似问法为别名实体。

- `05业务部门常见问题/不动产知识库/不动产法规汇编`
  - 按分隔符治理成长文法规记录。
  - 按章节/条款/长度切成 `regulation_section`。

- `05业务部门常见问题/*/*.xlsx`
  - 兼容部门 Excel 表格 FAQ，按 `问题/问答标题`、`答案/问答答案` 治理成 QA。
  - 保留 `类目路径`、`关键词`、`适用区域`、`办事链接`、`来源部门` 到 metadata。
  - KG 生成 `BusinessCategory`、`Keyword`、`Region`、`Url`、`Department` 等实体。

- `05业务部门常见问题/*.docx`
  - 兼容“问题行 + 答：”格式的松散 FAQ 文档。
  - 使用文档主题和中间标题形成 `category_path`，避免整份部门文档退化成大块长文。

## Dify 知识库映射

MimirQ 的 Dify external knowledge adapter 支持平台通用的 `knowledge_id -> dataset_ids`
映射。简单场景可以直接配置成数据集 ID 或 ID 列表；需要按查询临时扩展数据集时，
可以配置 `query_routes`，不需要把政务区县逻辑写死在平台代码里。

常州“小畅”工作流里，`changzhou_city_service` 是本级兜底检索节点。由于 Dify
固定工作流的区县参数提取可能失败，查询里出现明确区县词时，MimirQ 会先查对应区县
数据集，再查本级兜底数据集：

```json
{
  "changzhou_city_service": {
    "dataset_ids": ["<city-dataset-id>"],
    "query_routes": [
      {
        "terms": ["新北区", "新北"],
        "dataset_ids": ["<xinbei-service-item-dataset-id>", "<xinbei-qa-dataset-id>"],
        "mode": "prepend"
      }
    ]
  }
}
```

`mode=prepend` 表示把命中的区县数据集放在本级库前面；`append` 表示追加；
`replace` 表示只查路由命中的数据集。该配置应写入系统设置中的
`DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON`，插件只负责生成可检索的 chunk、metadata、
KG 和 Golden，不持有生产数据集 ID。

上线前可先跑本地静态校验，避免缺区县 route 时才在远端 Dify trace 里暴露：

```bash
make changzhou-dify-knowledge-map-check
```

该检查会验证 `changzhou_city_service` 至少配置了本级数据集，且 7 个区县
（新北区、经开区、天宁区、武进区、溧阳市、金坛区、钟楼区）都有完整
`query_routes` 别名和非空数据集，同时检查对应的
`changzhou_<区县>_service` knowledge id 存在。它只读取配置并输出计数/失败条件，
不会打印完整生产数据集映射。

## 本地测试

```bash
python scripts/pipeline_plugin_runner.py test plugins/pipelines/changzhou-gov-service-knowledge \
  --input plugins/pipelines/changzhou-gov-service-knowledge/sample.json \
  --stage governance \
  --stage chunk \
  --stage kg
```

脚本或 manifest 改动后需要重新运行测试，否则系统会把插件标记为 `stale`，前端不能选择执行。
测试报告还会生成 `golden_draft` 摘要；当前样例应生成 20 条 Golden 草稿问题。
如果该字段缺失或 `passed=false`，系统会把插件标记为 `golden_missing`。

导出完整 Golden 草稿：

```bash
python scripts/pipeline_plugin_runner.py golden-draft plugins/pipelines/changzhou-gov-service-knowledge \
  --input plugins/pipelines/changzhou-gov-service-knowledge/sample.json \
  --dataset-id 00000000-0000-0000-0000-000000000000 \
  --out /tmp/changzhou-gov-service-knowledge.golden.json
```

导出的 JSON 是 `mimirq.regression_cases.v1`，但带有 `review_only=true`。
其中 `document_id/chunk_id` 是本地样例生成的占位 ID，只用于审查和 CI fixture。
生产导入 Golden 必须先把文件入库，再通过后端 `pipeline/plugins/golden-draft/import` 从真实切片生成并导入。
Golden case 的 `extra` 会保留 `plugin_id/plugin_version/plugin_ref/plugin_package_hash`
和 `expected_metadata`，后续评估异常时可以追踪到具体插件版本与包内容。

## 固定 Golden 评估

固定评估集：

```text
plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json
```

每个 case 可以携带 `dify_inputs`，用于给固定 Dify workflow 的 START 变量传值，
例如 `"dify_inputs": {"areaName": "经开区"}`。这只影响真实 Dify App
答案采集，不改变 MimirQ 检索评估。

只评估 MimirQ Dify external knowledge 检索与证据可回答性：

```bash
make changzhou-dify-mimirq-direct-gate
```

该命令只直打 MimirQ `/api/v1/integrations/dify/retrieval`，不依赖 Dify Console
登录态；token 默认从 `.env` 的 `DIFY_EXTERNAL_KNOWLEDGE_API_KEY` 或
`DIFY_EXTERNAL_KNOWLEDGE_API_KEYS` 读取，不会出现在命令行。默认输出
`/tmp/changzhou_gov_dify_mimirq_direct_gate.json`。

采集固定 Dify App workflow 的真实生成答案，不修改 workflow：

```bash
python scripts/changzhou_gov_collect_dify_answers.py \
  --base-url https://dify.example.com:5001/v1 \
  --api-key-file /tmp/dify_remote_app_api_key.json \
  --mode chat \
  --out /tmp/changzhou_gov_dify_answers.json
```

用同一套 key points 评估生成答案：

```bash
DIFY_EXTERNAL_KNOWLEDGE_API_KEY=... \
python scripts/changzhou_gov_golden_eval.py \
  --answers /tmp/changzhou_gov_dify_answers.json \
  --min-hit-at-1 1 \
  --min-answer-grounding-rate 1 \
  --min-answer-key-point-recall 1 \
  --min-generated-answer-grounding-rate 1 \
  --min-generated-answer-key-point-recall 1 \
  --min-generated-answer-context-supported-rate 1 \
  --min-generated-answer-policy-clean-rate 1 \
  --max-generated-answer-fallback-rate 0 \
  --out /tmp/changzhou_gov_golden_eval_with_answers.json
```

门禁不通过时脚本返回退出码 `3`，用于 CI 或发布前本地检查。

评估输出包含三层指标：

- `hit_at_1` / `hit_at_3` / `mrr`：检索排序是否命中正确 chunk。
- `answer_grounding_rate` / `answer_key_point_recall`：top-k 证据是否足够回答。
- `generated_answer_grounding_rate` / `generated_answer_key_point_recall`：真实生成答案是否覆盖关键答案点。
- `generated_answer_policy_clean_rate`：真实生成答案是否避免泄漏内部模板/提示词约束。
- `generated_answer_fallback_rate`：真实生成答案是否退回“小畅只能答复...”兜底话术。

生成答案评分会规范化标点、emoji、空白和 `【字段名】` 这类 Dify 模板格式，避免把
`办理地点：...` 与 `📍【办理地点】：...` 误判为不同内容；但事实未出现的关键点
仍会计入 `missing_key_points`。

MimirQ Dify external knowledge adapter 会在返回给 Dify 的 records 里临时前置
`答案要点`，把结构化 QA 的 `答案` 或事项字段里的 `办理地点/收费情况/咨询方式`
放到原始证据前面，降低 Dify 生成时遗漏关键字段的概率。该前置内容不写回 chunk，
也不改变向量库原文。对事项类记录，只有事项名或别名与用户 query 明确匹配时才会
生成问题/答案式前置，避免弱相关事项被 Dify 过度展开。

当证据中存在“类型/类别/方式/入口”等枚举上下文，并紧跟 `1.`、`1、`、`（1）`
等编号选项时，adapter 还会临时前置 `必答要点`，要求 Dify 生成答案保留这些选项名。
这用于防止固定 Dify workflow 在概括长 QA 时漏掉实质选项，例如“卖旧置换更新补贴”
和“报废置换更新补贴”。触发条件是通用文本结构和查询意图，不写死常州或补贴词。

### Dify workflow 诊断口径

`changzhou_gov_collect_dify_answers.py` 会在 answers[] 中保留 Dify 返回的
`conversation_id`、`message_id`、`task_id` 等非敏感运行标识，方便去 Dify
Console Logs 追踪。不要把 App API Key、Console Token、Authorization header
写入报告或提交到代码库。

如果 public API 没有直接返回 `workflow_run_id`，可用 Console API 查询：

```text
GET /console/api/apps/{app_id}/messages/{message_id}
GET /console/api/apps/{app_id}/workflow-runs/{workflow_run_id}/node-executions
```

也可以直接生成节点级诊断报告：

```bash
python scripts/changzhou_gov_dify_trace_report.py \
  --answers /tmp/changzhou_gov_dify_answers.json \
  --app-id 00000000-0000-0000-0000-000000000003 \
  --storage-state /tmp/dify_console_storage_state.json \
  --out /tmp/changzhou_gov_dify_trace_report.json
```

报告中的 `empty_retrieval_cases` 表示 Dify workflow 内部知识检索节点全部返回空，
`fallback_cases` 表示最终进入兜底答案节点。`node_route_mismatch_cases` 表示 case
已传 `dify_inputs.areaName`，但 Dify workflow 节点标题仍显示走了本级节点，例如期望
`经开区政务服务知识检索` 却执行 `常州市政务服务知识检索`。如果该节点返回的证据
标题已经由 MimirQ `query_routes` 纠偏到目标区县，则计入 `route_compensated_cases`，
不算最终失败。`route_mismatch_cases` 表示节点和实际证据都没有命中目标区县，
readiness gate 会在 trace 阶段失败。

如果 answers 报告里出现 `error_kind=missing_start_variable`，例如
`missing_variable=areaName`，失败边界在 Dify workflow 入参，不在 MimirQ 检索。
当前固定“小畅” workflow 的 Start 节点虽然把 `areaName` 标为非必填，但后续节点会
直接引用 `#1711528914102.areaName#`；因此生产调用 `/v1/chat-messages` 时仍需要在
`inputs` 中传入 `areaName`，或者在 Dify workflow 内给该变量默认值/兜底分支。缺少该
变量时，Dify 会直接返回 `HTTP 400 invalid_param`，请求不会进入 MimirQ 检索链路。

可以用 workflow lint 直接检查这类“标为非必填但后续直接引用”的 Start 变量，也会扫描
LLM prompt 是否包含可能泄漏到用户答案里的模板控制语句：

```bash
python scripts/changzhou_gov_dify_workflow_lint.py \
  --app-id 00000000-0000-0000-0000-000000000003 \
  --cases plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json \
  --storage-state /tmp/dify_console_storage_state.json \
  --out /tmp/changzhou_gov_dify_workflow_lint.json \
  --patched-workflow-out /tmp/changzhou_gov_dify_workflow_sanitized.json
```

传入 `--cases` 后，报告会额外输出 `case_input_violations`，用于在调用 Dify 前发现
golden/boundary case 是否漏传 `dify_inputs.areaName`。`--case-inputs-only` 只把 case
缺入参作为失败退出码，仍会在报告里保留 workflow 本身的隐性必填警告。
报告中的 `prompt_template_leak_warnings` 用于发现 Dify LLM 节点 prompt 里把
“必须按顺序包含以下标题”“知识库内容中有...输出此部分内容”等内部模板说明写进
system prompt 的问题；这些词一旦被模型照抄，会让 `generated_answer_policy_clean_rate`
失败。`--patched-workflow-out` 只写本地 JSON，不会修改远程 Dify workflow，可用于导入前审查。
报告中的 `area_route_warnings` 用于发现另一类隐患：case 已传 `areaName`，但区域
条件分支没有直接使用 Start 变量，而是使用 LLM/parameter-extractor 的派生区域值。
当前“小畅” workflow 的静态风险是 `区域条件分支` 读取
`1742969146738.region`，不是 `1711528914102.areaName`；因此即使入参完整，区域
提取器失败时仍可能落到市本级知识检索节点。

推荐用 full gate 串起完整远程验证：case 入参 preflight -> Dify 真实回答采集 ->
MimirQ 直查 golden eval -> Dify workflow trace。
命令需要 `DIFY_EXTERNAL_KNOWLEDGE_API_KEY` 环境变量，或显式传入 `--mimirq-token`。

```bash
python scripts/changzhou_gov_dify_full_gate.py \
  --app-id 00000000-0000-0000-0000-000000000003 \
  --cases plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json \
  --dify-base-url https://dify.example.com:5001/v1 \
  --dify-api-key-file /tmp/dify_remote_app_api_key.json \
  --storage-state /tmp/dify_console_storage_state.json \
  --mimirq-base-url http://127.0.0.1:8000 \
  --out /tmp/changzhou_gov_dify_full_gate.json \
  --summary-out /tmp/changzhou_gov_dify_full_gate_summary.json
```

该 gate 默认要求 `hit_at_3=1.0`、直接证据关键点召回 `1.0`、生成答案关键点召回
`1.0`、生成答案 policy clean 率 `1.0`、生成答案 fallback 率 `0`，并要求 Dify trace 无空检索/兜底/trace 错误。
`--summary-out` 只保留各阶段结论、关键指标和 artifact 路径，适合留档或发给团队快速确认。
如果 gate 提前失败，summary 只列出已经实际写出的阶段 artifact，不会生成空的 answers/eval/trace 报告。
如需跑更宽松的边界套件，可以显式传入 `--min-hit-at-3`、
`--min-generated-answer-key-point-recall`、`--min-generated-answer-policy-clean-rate`、`--max-generated-answer-fallback-rate`
等阈值覆盖默认 gate。

如果需要区分“workflow 分支没进正确节点”和“Dify external knowledge runtime
调用 MimirQ 失败”，用同一套 fixed golden cases 做边界对照：

```bash
python scripts/changzhou_gov_dify_external_knowledge_probe.py \
  --cases plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json \
  --external-api-id 00000000-0000-0000-0000-000000000004 \
  --storage-state /tmp/dify_console_storage_state.json \
  --out /tmp/changzhou_gov_dify_external_probe.json \
  --timeout 60 \
  --top-k 5
```

该报告会读取 Dify Console 中 external knowledge API 的 endpoint 和 api key，
再分别调用 Dify dataset `external-hit-testing` 与 MimirQ `/retrieval` 直查。
报告只保留 endpoint、dataset、命中数量和首条标题，不输出或保存 api key。
`boundary.verdict=dify_external_boundary_ok` 表示 endpoint 配置非 loopback、
本机直连 MimirQ 正常、Dify dataset hit-testing 也正常；这时如果 workflow 仍空召回，
问题已经不在 external knowledge endpoint 边界。
endpoint 可以是 Dify 后端可访问的内网 IP、域名或反向代理地址；`localhost` /
`127.0.0.1` / `::1` 会被 gate 判定为不可用于远端 Dify 回调。
`dify_runtime_empty_but_mimirq_direct_ok` 表示同一个 case 在 Dify 数据集召回测试为空，
但同一 endpoint/key 直打 MimirQ 有结果，失败边界在 Dify external knowledge runtime
到 MimirQ endpoint 之间，通常优先检查 Dify worker/container 的网络、代理与
`NO_PROXY` 配置。

如果 `dify_hit_nonempty > 0` 且 `mimirq_direct_nonempty > 0`，但 workflow trace
仍然显示 `empty_retrieval_cases > 0`，失败边界已经不在 MimirQ endpoint。
Dify 1.11 的 workflow external retrieval 分支会读取 external dataset 的持久化
`retrieval_model` 参数；如果 external dataset 详情只展示默认
`external_retrieval_model`，但未实际持久化，workflow 节点可能在毫秒级返回空数组，
且节点状态仍是 `succeeded`。此时在 Dify Console 中保存该 external dataset 的
`external_retrieval_model`（例如 `top_k=10, score_threshold=0,
score_threshold_enabled=false`），并保留原 `external_knowledge_id` /
`external_knowledge_api_id` 绑定，再重新跑 trace。

此时不要先改 workflow。优先在 Dify 后端运行环境执行以下只读检查：

```bash
# 在 Dify api/worker 容器或 systemd 进程环境里检查代理。
env | grep -iE 'http_proxy|https_proxy|all_proxy|no_proxy'

# 用 Dify external knowledge API 配置里的 api key 测同一 endpoint。
curl --noproxy '*' -sS \
  -H 'Authorization: Bearer <DIFY_EXTERNAL_KNOWLEDGE_API_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{"knowledge_id":"changzhou_新北区_service","query":"新北区社保卡补卡在哪里办理","retrieval_setting":{"top_k":5,"score_threshold":0}}' \
  http://192.0.2.6:8000/api/v1/integrations/dify/retrieval
```

如果 `--noproxy '*'` 有结果，但 Dify 页面/Console hit-testing 仍为空，
需要把 Dify api/worker 的 `NO_PROXY/no_proxy` 加上 `192.168.0.0/16,192.0.2.6`
并重启 Dify 后端运行进程。若容器内 curl 本身无法连通，则需要给 Dify 所在主机或容器
提供能访问 MimirQ 的地址（同网段 LAN 地址、反向代理地址或部署后的 MimirQ 服务地址）。

当前远程 Dify 固定 workflow 曾经的失败模式是：MimirQ golden 检索 gate 通过，
Dify dataset `external-hit-testing` 也通过，但 Dify workflow 内部知识检索节点
毫秒级返回空数组，随后进入 `兜底回复`。根因是 external dataset 的
`external_retrieval_model` 未持久化到 workflow 实际读取的检索参数；保存 9 个
MimirQ external dataset 的检索参数后，节点 trace 恢复为非空，兜底率降为 0。
