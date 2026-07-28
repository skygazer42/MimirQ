# 企业知识流水线设计准则

本文定义 MimirQ 从数据评估到生产发布的长期设计边界：平台是通用 RAG 内核与质量闭环，业务差异通过插件包进入系统。目标不是让某个业务“跑通一次”，而是让每个业务都能用同一套平台合约完成解析、治理、切块、索引、检索、评测和发布。

## 交付起点：先评估数据，再选择技术

企业知识库交付不应从框架或向量库选型开始。先从客户资料中抽取有代表性的样本，形成可复现的数据画像和解析基线：

- 统计文件类型、页数、语言，以及可编辑文本与扫描页的比例。
- 统计图片、表格、公式、多栏版式、页眉页脚和跨页结构的密度。
- 用同一批样本比较候选解析器的内容完整性、阅读顺序、结构保留、吞吐和失败率。
- 估算 CPU / GPU、存储、人工校验和异常返工成本，作为容量规划与交付报价的依据。
- 在正式入库前固定验收样本和阈值，避免上线后只凭问答观感判断解析质量。

解析器没有脱离数据集的“全局最优”。候选起点可以按文档特征划分：

- 复杂版式、扫描件和 OCR 场景可比较 [MinerU](https://opendatalab.github.io/MinerU/) 与 [DeepDoc](https://github.com/infiniflow/ragflow/tree/main/deepdoc)。
- 公式、表格、版面结构密集的 PDF 或多格式资料可将 [Docling](https://docling-project.github.io/docling/) 纳入基准。
- 数字原生 Office、HTML、CSV 或纯文本可先用 [MarkItDown](https://github.com/microsoft/markitdown) 等轻量转换路径建立基线。
- 资源受限或内容结构简单时，应优先验证轻量内置解析器，而不是默认启用最重的视觉模型。

以上是评测候选，不是硬编码路由。最终选择必须落入 dataset 或 pipeline 配置，并保存解析器版本、参数、原始文件、结构化输出和质量证据。高风险资料应保留人工校验与修订环节，校验后的内容再进入治理和切块。

## 1. 平台边界

平台只消费标准合约，不理解业务字段含义。`app/` 内的 API、检索、索引、报告、评测和 Dify adapter 必须保持业务中立。

插件负责治理、切块、metadata、KG 事件、retrieval hints 和 Golden rules。业务规则、同义词、记录拆分、字段解释、标题/别名组织、评测样例生成都应放在 `plugins/pipelines/<plugin>/` 的 manifest、contract files、plugin code 或 plugin-owned tests 中。

禁止把业务排序、业务回答、文件路径识别、地区/部门/产品线等业务语义写入平台运行时代码。平台可以提供通用执行器、校验器、存储结构和可观测性，但不能 hard-code 某个业务如何被召回。

## 2. 入库资产链路

入库链路必须可拆分、可审计、可重跑：

```text
解析 -> 治理 -> 切块 -> metadata views -> 向量/BM25 -> KG -> Golden gate -> 发布
```

每个阶段都应该有明确输入、输出、状态和失败原因：

- 解析阶段只负责把原始文件变成可处理内容，不承载业务规则。
- 治理阶段清洗、规范化、拆记录和补业务 metadata，由插件持有业务逻辑。
- 切块阶段决定证据粒度，必须保留 provenance、record identity、display/evaluable/indexed metadata views。
- 索引阶段只消费标准 chunk 与 metadata views，不能猜业务字段。
- KG 阶段只消费 chunk 与 plugin KG events，不能绕过 chunk evidence。
- Golden gate 在发布前证明检索能拿到答案依据，而不是证明 LLM 能编出答案。

任何写库、写索引、写 KG 或写 dataset metadata 的动作都必须是显式命令。默认的本地报告、预览、导出和 readiness 汇总应尽量保持只读；如果必须写入，命令名、文档和测试都要暴露这个副作用。

## 3. Metadata 合约

业务字段必须声明在 `metadata_schema.json`。平台只读取 schema flags 和平台 views：

- `filterable: true` 进入 `_indexed_metadata`，用于过滤、向量库 pushdown 和候选裁剪。
- `display: true` 进入 `_display_metadata`，用于 UI、citation 和报告摘要。
- `evaluable: true` 进入 `_evaluable_metadata`，用于 Golden regression 和 expected metadata 命中率。
- `record_identity` 定义业务记录边界，用于去重、合并、召回折叠和评测聚合。

平台字段保持稳定，插件字段保持可扩展。插件不能声明或覆盖 `dataset_id`、`document_id`、`chunk_id`、`source`、`parser_backend`、`resolved_chunk_strategy` 等平台字段，也不能直接写 `_indexed_metadata`、`_display_metadata`、`_evaluable_metadata`、`_record_identity` 等内部 views。

metadata 的设计原则是“召回可用、引用可解释、评测可验证”。如果一个字段会影响过滤、排序、展示或 Golden 判断，它就必须进入对应 schema flag，而不是藏在 chunk 正文或未声明 JSON 中。

## 4. KG 使用边界

KG 是召回增强和解释层，不是业务 fast path。KG 可以做三件事：

- Query expansion：从高置信实体或别名扩展候选查询，降低漏召回。
- Chunk injection：把 KG 事件指向的 evidence chunk 注入候选池，增加覆盖。
- Ranking features：给 rerank/LTR 提供低基数、可解释的结构化特征。

KG 不应该直接返回最终答案，也不应该跳过 vector/BM25/rerank 的统一候选流程。启用 KG 前后必须能用 KG-off/KG-on 对比证明：hit、effective context、metadata match 不下降，noise rate 不超过阈值。

KG 事件必须保留 evidence provenance。没有 chunk 证据的实体关系只能作为待审查结构，不能作为生产召回增强的强信号。

## 5. Retrieval 与 Rerank

检索目标是“问题有答案时，候选 evidence 中出现正确依据”。回答生成不能作为 retrieval 质量通过的证据。

平台 retrieval pipeline 应保持统一：

- Dataset scope 是第一边界，所有集成入口都必须显式限定可检索 dataset。
- Vector、BM25、sparse、KG expansion 都只是候选来源，最终进入统一候选池。
- Plugin `retrieval_policy.json` 只能声明 query expansion fields、filter fields、boost fields、anchor fields、rerank features 和 fallback hints。
- Adapter 和 retriever 只能通过通用 retrieval policy helper 消费这些 hints，不能写业务条件分支。
- Rerank 可以重排候选，但不应该隐藏召回失败；召回不足要通过 Golden gate、trace 和 audit 暴露。

命中率判断应看 retrieved chunks 是否含有答案依据，而不是看某个分类、FAQ 或 workflow 分支是否被命中。不同内容类型可以由插件设置 metadata 和 retrieval hints，但平台不应按业务类型写死路由。

## 6. Golden Gate 与发布

每个业务插件都应该维护或生成 Golden cases。Golden gate 至少要覆盖：

- `hit_at_1`、`hit_at_3`、MRR/NDCG 等排序质量。
- `expected_metadata_hit_rate` 和 `expected_metadata_recall`，证明召回结果命中插件声明的业务字段。
- `effective_context_rate`，证明返回内容确实包含可用依据。
- `noise_rate`，证明 TopK 没有被无关内容污染。
- KG-on/off 对比，证明 KG 增强没有引入明显噪声。

发布条件应绑定 dataset、plugin ref、plugin package hash、retrieval profile、thresholds 和生成时间。任何离线报告、readiness summary 或 delivery pack 都应该能追溯到这些 evidence，而不是依赖口头判断。

## 7. 集成边界

Dify 是兼容适配层，不承载业务排序或业务回答逻辑。Dify、Chat、Evidence API 和其他外部调用方都应该只传入 query、dataset scope、top_k、metadata filters 和必要上下文；MimirQ 返回 evidence chunks、score、source、metadata 和 trace。

如果外部系统需要多个知识库，应该传入 MimirQ dataset id 列表或由 external knowledge map 映射到 dataset scope。业务插件仍然通过 dataset 绑定和 plugin refs 发挥作用，而不是在 adapter 内写特殊处理。

集成质量用两类证据衡量：

- Boundary evidence：外部系统确实调用到 MimirQ，并且 dataset scope、knowledge map、trace、鉴权和网络路径正确。
- Retrieval evidence：MimirQ direct gate 与外部 workflow gate 看到的证据一致，且通过同一套 Golden threshold。

## 8. 变更守护

任何影响 RAG 质量的改动都必须回答四个问题：

- 是否改变了解析、治理、切块、metadata views、索引、KG 或 retrieval policy？
- 是否引入了业务专用逻辑到平台代码？
- 是否有 Golden/regression/report 证据证明召回质量没有下降？
- 是否有显式 rollback 路径，包括关闭插件、关闭 KG、切回 retrieval profile 或恢复旧 thresholds？

推荐验证顺序：

```bash
pytest tests/test_pipeline_plugin_boundary.py tests/test_pipeline_plugin_closed_loop_docs.py -q
pytest tests/test_pipeline_plugin_chunk_report.py tests/test_pipeline_plugin_golden_drafts.py -q
pytest tests/test_retrieval_plugin_policy.py tests/test_conditional_rerank.py -q
```

生产交付前还应运行对应业务插件的 corpus closed-loop smoke、Golden retrieval gate、KG-on/off compare gate，以及 dataset report / retrieval audit 导出。平台设计的最终目标是：业务可以越来越复杂，但核心 RAG 平台仍然通过同一套合约、同一套评测和同一套证据发布。
