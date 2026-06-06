# 常州政务服务知识插件

样例数据包：

```text
/data/temp50/20260522政务服务智能客服知识
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

## 本地测试

```bash
python scripts/pipeline_plugin_runner.py test plugins/pipelines/changzhou-gov-service-knowledge \
  --input plugins/pipelines/changzhou-gov-service-knowledge/sample.json \
  --stage governance \
  --stage chunk \
  --stage kg
```

脚本或 manifest 改动后需要重新运行测试，否则系统会把插件标记为 `stale`，前端不能选择执行。
测试报告还会生成 `golden_draft` 摘要；当前样例应生成 7 条 Golden 草稿问题。
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
