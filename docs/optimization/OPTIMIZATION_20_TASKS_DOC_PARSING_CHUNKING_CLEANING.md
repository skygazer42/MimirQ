# 文档解析 / 清洗 / 切块 / 知识图谱：20 项后端优化清单

> 说明：仓库 `docs/README.md` 里引用了本文件路径，但此前文件缺失。这里补齐一份“可执行”的 20 项优化清单，重点围绕 **知识图谱（KG）**、**文档解析**、**切块**（含治理/清洗与元数据）进行落地。  
> 设计原则：默认行为尽量保持兼容；新增能力优先通过配置开关启用；所有变更配套测试与文档说明。

## A. 知识图谱（KG）核心链路（1–10）

1. [x] **抽取并发**：按 `max_concurrency` 对 chunk 级 LLM 抽取并发执行（带并发闸门）
2. [x] **失败隔离**：单个 chunk 抽取失败不影响整批（记录失败原因与计数）
3. [x] **批量 Embedding**：对事件/实体文本做去重后批量 embedding（可配置 batch size）
4. [x] **实体名归一化**：NFKC + 空白折叠 + 端点标点裁剪 + casefold（提升去重与召回一致性）
5. [x] **实体类型归一化**：中英同义类型映射到 canonical（例如 Person/Organization/Location/Date…）
6. [x] **事件内去重**：同一事件内按（type, normalized_name）去重实体，合并描述/角色（保守）
7. [x] **输出约束**：对每 chunk 的事件数、每事件实体数做上限保护（避免异常膨胀）
8. [x] **引用增强**：事件 `references` 增补 page/start_char/end_char/chunk_key 等信息（更利于溯源）
9. [x] **索引元数据**：事件/实体向量索引写入更完整的 metadata（tenant/document/chunk 绑定）
10. [x] **可观测性**：抽取阶段输出结构化 metrics（chunk/event/entity 计数、耗时、失败数）

## B. KG API / 图谱投影性能（11–14）

11. [x] **图谱查询降载**：`/kg/graph` 在 SQL 层先做 top-entity 预筛选（减少 join 行数）
12. [x] **共现边防爆**：实体共现边生成增加预算与剪枝（避免组合爆炸）
13. [x] **节点搜索体验**：节点搜索支持更稳健的大小写/空白处理与 kind 过滤
14. [x] **统计口径一致**：`stats` 输出与过滤后的 nodes/links 一致（并补测试）

## C. 文档解析与管线编排（15–17）

15. [x] **取消检查复用**：统一 cancel-check 逻辑（避免三处重复实现与行为漂移）
16. [x] **解析产物清理**：解析子进程/外部解析器产物目录 best-effort 安全清理（tenant 内）
17. [x] **容器可运行性**：补齐 `docker/start_backend.sh`（修复 Dockerfile 入口缺失）

## D. 切块与元数据（18–20）

18. [x] **Chunk 去重（可选）**：同文档内对“完全相同内容”的文本 chunk 去重（排除 image/table 等资产）
19. [x] **Chunk 元数据增强**：为每个 chunk 写入 `chunk_key`、`content_hash`、`content_len` 等稳定字段
20. [x] **测试覆盖**：为 KG 归一化、chunk 去重、chunk 元数据注入补充单测（并跑全量 pytest）

## 落地映射（文件/开关）

- **KG 抽取**：`app/rag/kg/extraction/extractor.py`、`app/rag/kg/extraction/processor.py`、`app/rag/kg/extraction/parser.py`
- **KG 图谱 API**：`app/rag/kg/api/routes.py`（`/kg/graph`、节点搜索与 stats 口径）
- **解析/管线**：`app/parsing/processors/processor.py`、`app/parsing/subprocess_*`（取消检查与产物清理）
- **切块后处理**：`app/parsing/processors/processor.py`（chunk 去重、chunk metadata 注入）
- **配置项**：`app/core/config.py`（新增 KG 抽取与 chunk 后处理相关开关与阈值）
- **测试**：`tests/`（新增单测文件，覆盖归一化与去重/metadata）

---

## 第二阶段（21–40）：KG / 解析 / 切块进阶优化清单

> 目标：在不破坏默认兼容性的前提下，进一步降低 KG 抽取与图谱 API 的成本/延迟，提升可观测性与可运维性，并增强切块/解析链路的“兜底能力”。

### A. KG 抽取与索引（21–30）

21. [x] **增量抽取**：基于 `chunk.content_hash` 跳过“未变化且 prompt 选择一致”的 chunks（可开关）
22. [x] **单 chunk 超时**：LLM 抽取支持 per-chunk timeout（超时按失败隔离，不拖死整批）
23. [x] **上下文上限可配**：KG 抽取 prompt 的 `context` 最大字符数可配置
24. [x] **上下文窗口**：可选在抽取时加入邻近 chunks 作为背景上下文（不改变归属 chunk_id）
25. [x] **回写文档元信息**：抽取完成后写入 `kg_event_count/kg_skipped_chunks/kg_failed_chunks/kg_extracted_at`
26. [x] **hash 兜底**：chunk metadata 缺少 `content_hash` 时，使用规范化内容计算
27. [x] **prompt 一致性**：prompt_template 选择变化时，强制重抽（不走“未变化跳过”）
28. [x] **向量 metadata 更完整**：KG event/entity 向量索引 metadata 补齐 `chunk_key/content_hash/start/end`
29. [x] **图谱/expand SQL 预筛**：graph/expand 都在 SQL 层做 top-entity 预筛，减少 join 行
30. [x] **共现边参数化**：每个事件参与共现计算的 entity 数上限支持 settings 配置

### B. 切块与资产（31–36）

31. [x] **chunk 元数据兜底**：持久化前强制补齐 `chunk_key/content_hash/content_len`
32. [x] **chunk 上限保护**：新增 `MAX_CHUNKS_PER_DOCUMENT`（0=不限），超限截断并记录原因
33. [x] **MinIO chunk_key 统一**：MinIO 上传使用 `chunk_key`（默认回退 chunk_index），避免漂移
34. [x] **BM25 metadata 补齐**：BM25 侧也补齐 `content_hash/chunk_key/content_len` 便于排障
35. [x] **去重可观测性**：chunk 去重/截断写入 metrics 与 doc_metadata 计数
36. [x] **安全边界**：对内联图片/解析产物路径继续保持 tenant 目录隔离与清理安全

### C. 解析子进程安全与稳健（37–40）

37. [x] **payload 体积上限**：subprocess payload JSON 写盘前做 size 限制（避免 OOM/磁盘爆）
38. [x] **result 体积上限**：读取 result.json 前做 size 限制（避免异常输出拖垮主进程）
39. [x] **测试覆盖**：为增量抽取/超时/上限/size guard 增加单测
40. [x] **文档对齐**：标记完成项、补开关说明与推荐默认值

### 阶段二新增/相关配置（默认值）

- KG 抽取增量/上下文/超时：
  - `KG_EXTRACT_SKIP_UNCHANGED_CHUNKS=false`：仅当 `replace_existing=true` 且（`content_hash` + prompt selector）一致时跳过未变化 chunk
  - `KG_EXTRACT_CHUNK_TIMEOUT_SEC=0`：单 chunk 超时（0=禁用）
  - `KG_EXTRACT_CONTEXT_WINDOW_CHUNKS=0`：邻近 chunk 上下文窗口（0=禁用）
  - `KG_EXTRACT_CONTEXT_MAX_CHARS=8000`：prompt context 截断上限
  - `KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT=60`：共现边计算时每事件参与实体数上限（0=不限制，仍受整体 max_links/max_entity_links 预算约束）

- 切块与索引兜底：
  - `MAX_CHUNKS_PER_DOCUMENT=0`：每文档最大 chunk 数（0=不限）
  - `CHUNK_DEDUP_ENABLED=false`：同文档内“完全重复文本”chunk 去重开关

- 解析子进程安全：
  - `SUBPROCESS_PAYLOAD_MAX_BYTES=2000000`：payload JSON 上限（0=禁用）
  - `SUBPROCESS_RESULT_MAX_BYTES=50000000`：result JSON 上限（0=禁用）

---

## 第三阶段（41–60）：KG / 解析 / 切块 进一步优化清单

> 目标：把“高频线上坑”兜到底：图片资产跨进程可用、超大文档可控、KG 抽取更稳健（短块跳过/重试/一致性）、subprocess 日志不炸盘，并补齐相应测试与文档。

### A. 切块截断与可观测性（41–46）

41. [x] **截断策略可配**：新增 `MAX_CHUNKS_PER_DOCUMENT_STRATEGY`（head | asset_uniform）
42. [x] **资产优先截断**：`asset_uniform` 优先保留 image/table 等资产 chunks，并保留首块
43. [x] **均匀采样文本块**：在资产之外对文本块做均匀采样补齐至上限（避免只保留开头）
44. [x] **截断统计增强**：`doc_metadata.chunk_postprocess` 记录 strategy/asset_kept/asset_total
45. [x] **metrics 增强**：`ingest.chunk_truncate` 增补 strategy/asset_kept 等字段
46. [x] **单测覆盖**：截断策略选择逻辑单测（asset_uniform/head）

### B. 资产图片跨进程上传（47–52）

47. [x] **image_path 上传**：支持 `metadata.image_path`（subprocess 落盘）在主进程上传到 MinIO
48. [x] **路径安全校验**：`image_path` 必须位于当前 tenant 的 `UPLOAD_DIR/{tenant}` 目录内
49. [x] **图片体积上限**：新增 `MINIO_IMAGE_MAX_BYTES`（0=禁用），超限跳过并清理字段
50. [x] **上传后清理文件**：上传成功后 best-effort `unlink(image_path)`，避免磁盘堆积
51. [x] **元数据清理**：上传后移除 `image_path`/残留 image 字段，避免 JSON 过大或不可序列化
52. [x] **单测覆盖**：image_path 上传/安全校验/清理行为单测

### C. KG 抽取稳健性与一致性（53–58）

53. [x] **短块跳过**：新增 `KG_EXTRACT_MIN_CHARS`，对低信息短块跳过抽取并计数
54. [x] **单 chunk 重试**：新增 `KG_EXTRACT_CHUNK_MAX_RETRIES` + `KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC`
55. [x] **引用补齐 content_len**：event `references` 补 `content_len`（优先用 chunk metadata，缺失则计算）
56. [x] **回写 tenant 过滤**：writeback document metadata 时同时按 tenant_id 过滤（安全）
57. [x] **回写字段扩展**：写入 `kg_skipped_short_chunks/kg_retry_chunks`（保守：新增字段不破坏兼容）
58. [x] **单测覆盖**：重试/短块跳过/tenant 过滤至少覆盖其中两项

### D. Subprocess 日志与磁盘安全（59–60）

59. [x] **log 体积上限**：新增 `SUBPROCESS_LOG_MAX_BYTES`，运行中超限终止并抛 `worker_log_too_large`
60. [x] **单测+文档对齐**：log guard 单测 + 清单勾选 + 配置说明补齐

### 阶段三新增/相关配置（默认值）

- 切块截断：
  - `MAX_CHUNKS_PER_DOCUMENT=0`（阶段二已引入，仍默认关闭）
  - `MAX_CHUNKS_PER_DOCUMENT_STRATEGY=head`

- 图片资产（MinIO）：
  - `MINIO_IMAGE_MAX_BYTES=0`（0=不限制；建议线上设置一个合理上限）

- KG 抽取稳健性：
  - `KG_EXTRACT_MIN_CHARS=0`（0=不跳过短块）
  - `KG_EXTRACT_CHUNK_MAX_RETRIES=0`（0=不重试）
  - `KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC=0.5`

- 解析子进程安全：
  - `SUBPROCESS_LOG_MAX_BYTES=20000000`

---

## 第四阶段（61–80）：KG Search / API / 可观测性优化清单

> 目标：控制 KG search（recall/expand/rerank）成本与返回体积，增强可观测性与稳健性；同时把 KG API 的文档范围上限做成可配置的“统一阀门”。

### A. KG Search 可观测性与返回体积（61–68）

61. [x] **clue 上限配置**：新增 `KG_SEARCH_MAX_CLUES`（0=禁用）并在 Tracker 中生效
62. [x] **clue 丢弃计数**：Tracker 记录 `clues_dropped` 并透出到 search `stats`
63. [x] **合并裁剪**：KGSearcher 合并 `expand+rerank` clues 时统一裁剪，避免大响应
64. [x] **阶段耗时 metrics**：recall/expand/rerank 各自耗时记录到 metrics logger（开关控制）
65. [x] **候选计数 metrics**：记录 keys/events/clues/doc_count 等关键计数（不记录 query 文本）
66. [x] **空结果口径**：空候选/空 events 时仍返回稳定的 stats 字段（便于前端渲染）
67. [x] **rerank 输入上限**：新增 `KG_SEARCH_MAX_RERANK_CANDIDATES`（0=禁用），rerank 前截断 event_ids
68. [x] **SearchConfig 对齐**：使用 `rerank.max_key_recall_results/max_query_recall_results` 对 recall 事件候选做上限

### B. Expand 预算与稳健性（69–74）

69. [x] **UUID 归一化**：`find_events_by_entities` 使用 `_as_uuid_list` 去重/过滤非法 UUID
70. [x] **SQL 去重**：`find_events_by_entities` 使用 `group_by` + `order_by count` 返回唯一事件（避免 join 重复）
71. [x] **discover set**：Expand 使用 set 跟踪 discovered_event_ids，避免 O(n) membership
72. [x] **min_events_per_hop 生效**：每 hop 新事件不足阈值则停止后续 hop（避免低收益扩展）
73. [x] **expand 总事件上限**：扩展后 event_ids 做上限保护（复用 rerank 输入上限）
74. [x] **clue node 统一**：Expand 的 event->entity clue 使用 `Tracker.build_event_node/build_entity_node`

### C. KG API 限流与一致性（75–78）

75. [x] **API 文档ID上限可配**：新增 `KG_API_MAX_DOCUMENT_IDS` 并替换 `routes.py` 常量
76. [x] **请求模型放开**：`KGSearchRequest.document_ids` 去掉硬编码 `max_length=500`，由后端统一限流
77. [x] **统一 limit 来源**：所有调用 `_resolve_allowed_documents` 的 endpoints 统一使用同一 limit
78. [x] **错误信息一致**：超限返回统一 `"Too many document_ids (max X)"` 并覆盖测试

### D. 测试与文档（79–80）

79. [x] **单测覆盖**：clue cap / UUID 归一 / min_events_per_hop / API limit 至少覆盖 3 项
80. [x] **文档对齐**：标记完成项并补充配置默认值/推荐值

### 阶段四新增/相关配置（默认值）

- KG search：
  - `KG_SEARCH_MAX_CLUES=2000`（0=禁用）
  - `KG_SEARCH_MAX_RERANK_CANDIDATES=500`（0=禁用）
  - `KG_SEARCH_METRICS_ENABLED=false`（需同时开启 `ENABLE_METRICS_LOG=true` 才会写入 JSONL）

- KG API：
  - `KG_API_MAX_DOCUMENT_IDS=500`（统一约束 `/kg/graph` 与 `/kg/search` 等接口的 document_ids 范围）

---

## 第五阶段（81–90）：KG Search 性能 / 超时 / 响应体积优化清单

> 目标：进一步降低 KG search 端到端延迟与外部调用次数，增强超时可控性，并继续压缩 clues 相关响应体积（可开关、可截断）。

81. [x] **query embedding 复用**：recall 生成一次 embedding，rerank 复用避免二次调用
82. [x] **全链路超时**：新增 `KG_SEARCH_TIMEOUT_SEC`（0=禁用），超时返回 504（API 层）
83. [x] **clues 总开关**：新增 `KG_SEARCH_CLUES_ENABLED`，关闭时不生成 clues（节省 CPU/内存）
84. [x] **node 文本截断**：新增 `KG_SEARCH_NODE_TEXT_MAX_CHARS`，对 clue node 的 content/description 截断
85. [x] **expand 早停**：当已达到 `KG_SEARCH_MAX_RERANK_CANDIDATES` 时提前停止后续 hop
86. [x] **PageRank 构图优化**：用 entity->events 方式构图，避免 O(n^2) 交集
87. [x] **PageRank 迭代优化**：稀疏传播计算，避免每轮 O(n^2) 扫描
88. [x] **RRF recall 排序优化**：仅对候选集合排序并加稳定 tie-breaker（更快更稳）
89. [x] **单测覆盖**：覆盖 embedding 复用 / 超时 / 截断 / 早停 至少 3 项
90. [x] **文档对齐**：勾选完成项并补充默认值/推荐值

### 阶段五新增/相关配置（默认值）

- KG search：
  - `KG_SEARCH_TIMEOUT_SEC=0`（0=禁用；建议线上按 SLA 设置）
  - `KG_SEARCH_CLUES_ENABLED=true`
  - `KG_SEARCH_NODE_TEXT_MAX_CHARS=400`（0=禁用）

- KG rerank：
  - （无新增配置）

---

## 第六阶段（91–110）：后端减法（去冗余 / 去多余防御）清单

> 目标：减少重复校验、重复 cap 与无意义的 try/except；删除冗余字段/日志/配置，让 KG API / KG Search 代码更短、更清晰、依赖更少。

### A. KG API 去冗余（91–96）

91. [x] **去重 member 校验**：移除 routes 中重复 `DatasetService.ensure_member`（统一由 document_access 层兜底）
92. [x] **limit 收敛**：`_resolve_allowed_documents` 删除 `limit` 参数（统一读取 `KG_API_MAX_DOCUMENT_IDS`）
93. [x] **去无意义 try/except**：`_stable_group_for` 移除无必要的异常吞掉逻辑
94. [x] **删除不可达/重复分支**：`delete_kg_for_document` 移除重复 document/dataset 校验与不可达 `allowed` 检查
95. [x] **search 端点减法**：`/kg/search` 去除重复 member 校验（由 `_resolve_allowed_documents` 负责）
96. [x] **extract 端点减法**：`/kg/documents/{id}/extract` 只保留必要的 document+dataset 校验（去掉额外的 filter_allowed_document_ids 依赖）

### B. KG Search 去冗余（97–103）

97. [x] **Tracker 减负**：去掉未使用的 `config` 成员与构造参数
98. [x] **结构字段减法**：`RecallResult` 移除冗余 `original_query`
99. [x] **丢弃计数减法**：`RecallResult/ExpandResult` 移除 `clues_dropped` 字段与跨阶段透传
100. [x] **clues cap 单点化**：`KGSearcher` 删除二次 clues cap（统一由 Tracker 控制）
101. [x] **candidate cap 单点化**：`KGSearcher` 删除 rerank 前二次 candidate cap（统一在 recall/expand 上限）
102. [x] **recall 上限统一**：recall 阶段对齐 `KG_SEARCH_MAX_RERANK_CANDIDATES`（避免后置截断）
103. [x] **expand 早停**：expand 达到候选上限即停止后续 hop（减少 DB 压力）

### C. Rerank / 配置 减法（104–108）

104. [x] **删除边预算配置**：PageRank 构图去掉边预算开关（候选上限已足够）
105. [x] **配置面收敛**：删除 `KG_PAGERANK_MAX_EDGES` 配置项
106. [x] **返回字段减法**：PageRank stats 去掉 `edges/edges_capped`（减少无必要返回冗余）
107. [x] **日志减法**：移除 KG search 相关模块未使用的 logger/get_logger
108. [x] **stats 精简**：search response stats 只保留必要的 `candidates/clues/timing` 等核心字段

### D. 测试与验证（109–110）

109. [x] **单测对齐**：更新/补齐单测以匹配精简后的接口/数据结构
110. [x] **全量验证**：`pytest -q` 全绿

---

## 第七阶段（111–130）：整体后端优化（减法优先）清单

> 目标：不局限 KG，优先做减法（去冗余、去不必要的防御性代码、去 N+1），让 API/Service/Core 工具层更短更清晰、DB/CPU 更省。

### A. API 层去冗余（111–114）

111. [x] **RAG 预览去重 member 校验**：`/retrieve-preview` 与 `/prompt-preview` 移除重复 `ensure_member`（由 document_access 兜底）
112. [x] **RAG 预览 import 减法**：随去重移除 `DatasetService` 未使用 import
113. [x] **Chat 创建会话去重 member 校验**：`/conversations` 移除重复 `ensure_member`（由 document_access 兜底）
114. [x] **tenant 解析异常收敛**：UUID 解析只捕获 `ValueError`（避免吞掉非预期异常）

### B. Services 层减法与性能（115–121）

115. [x] **pipeline flag 简化**：`_resolve_flag` 简化为单表达式（保持“只能禁用不能强启用”的语义）
116. [x] **pipeline 数值解析异常收敛**：`_coerce_int/_coerce_float` 只捕获 `TypeError/ValueError`
117. [x] **DatasetPermissionService 参数减法**：移除未使用 `operator_id` 参数并更新调用点
118. [x] **partial member 去重/清洗**：更新 partial members 时先去重/去空白，避免触发唯一约束错误
119. [x] **partial member 校验去 N+1**：用 1 次查询校验 `member_ids` 是否都在 tenant 中
120. [x] **partial member 批量替换**：`delete(synchronize_session=False)` + `add_all` 替代逐条写入
121. [x] **UserService 异常收敛**：UUID 解析只捕获 `ValueError`（`get_by_id/ensure_default_membership`）

### C. Core/Utils 层减法（122–129）

122. [x] **bcrypt 校验异常收敛**：`verify_password` 只捕获 `TypeError/ValueError`
123. [x] **token count 提取减法**：`total_token_count_from_response` 用 `getattr/type-check` 替代多层 try/except
124. [x] **JSON 解析异常收敛**：`parse_json_from_text` 仅捕获 `ValueError`（避免吞掉非 JSON 类异常）
125. [x] **HTTP/2 可选依赖异常收敛**：可选 `h2` import 仅捕获 `ImportError`
126. [x] **http2 enable 逻辑简化**：去掉冗余 bool 包装与中间变量
127. [x] **Retry-After 解析异常收敛**：只捕获 `TypeError/ValueError`
128. [x] **上传清理减法**：`_safe_unlink` 使用 `unlink(missing_ok=True)` 并仅 suppress `OSError`
129. [x] **子进程清理减法**：subprocess runner 用 `unlink(missing_ok=True)` 并收敛异常范围（close/cleanup）

### D. 测试与验证（130）

130. [ ] **全量验证**：`pytest -q` 全绿
