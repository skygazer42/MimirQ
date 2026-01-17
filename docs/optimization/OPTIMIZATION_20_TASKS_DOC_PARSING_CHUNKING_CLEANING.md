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
