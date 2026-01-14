# Knowledge Graph (知识图谱)

MimirQ 的 Knowledge Graph（KG）以“事件（Event）—实体（Entity）”为核心结构：
- 从文档切片（chunk）中抽取事件（title/summary/content + 引用/extra）。
- 识别并归一化实体（name/type/normalized_name）。
- 建立事件↔实体关系，用于图谱可视化与 KG recall/搜索。

## 开启与配置

### 关键环境变量
- `KG_ENABLED=true`：启用 KG 功能（API/Graph 页面/抽取等）。
- `KG_EXTRACT_REPLACE_EXISTING=true`：重复抽取同一文档时，替换旧事件（避免重复写入）。
- `KG_EXTRACT_PRUNE_ORPHAN_ENTITIES=true`：替换/删除事件后，清理无任何事件关联的“孤立实体”。

### 抽取 Prompt 选择
KG 抽取支持 3 种选项（按优先级从高到低）：
1) 请求参数 `prompt_template_id` / `prompt_template_key` / `prompt_ab_experiment_key`
2) Settings 中的 `extract_prompt_*` 配置
3) 内置默认提示词

前端路径：`/settings` → KG 抽取提示词配置（包含“替换旧事件 / 清理孤立实体”开关）。

## 抽取流程（推荐）
1) 上传并完成文档处理（status=completed）
2) 触发抽取：
   - UI：文档详情弹窗 → `抽取 KG`（默认异步）
   - API：`POST /kg/documents/{document_id}/extract?async=true`
3) 图谱查看：`/graph`（Live 模式）

### 异步 vs 同步
- `async=true`：入队任务（需要 `TASK_QUEUE_ENABLED=true`），API 返回 `202`，并在文档 metadata 写入 `kg_task_id`。
- `async=false`：直接执行抽取（兼容旧行为）。

## 图谱 API（常用）
- `GET /kg/graph`：拉取图谱投影（支持文档 scope）。
  - `include_entity_links=true`：启用“实体-实体共现”边（基于共享事件数）。
  - `min_shared_events`：共现阈值（默认 2）。
  - `max_entity_links`：共现边上限（避免图过密）。
- `GET /kg/graph/expand?node_id=...`：按节点扩展邻居（同样支持共现边参数）。
- `GET /kg/stats`：轻量统计（events/entities/links/type breakdown）。
- `GET /kg/graph/export`：导出 GraphML（便于 Gephi/Cytoscape 等外部工具）。
- `GET /kg/events/{event_id}`：事件详情（含实体列表，受文档权限约束）。
- `GET /kg/entities/{entity_id}`：实体详情（含最近事件与邻居实体，受文档权限约束）。
- `DELETE /kg/documents/{document_id}`：删除文档对应 KG 事件（可选清理孤立实体）。

## 前端图谱（/graph）
- Live：从后端实时加载（支持导出 GraphML）。
- File：支持导入 `.graphml/.xml` 本地文件进行可视化。
- 交互：
  - “实体连线”开关：开启/关闭实体共现边。
  - `Co≥N`：循环调整共现阈值。
  - 侧边栏 `KG Detail`：点击节点查看实体/事件详情（Live 模式）。

## 权限与隔离
KG API 默认按 tenant + 文档权限进行过滤：
- `document_ids` 会进行去重与可访问性校验。
- KG 节点搜索/详情接口会限制到“当前可访问文档”的事件/实体集合，避免跨数据集/跨文档泄漏。

