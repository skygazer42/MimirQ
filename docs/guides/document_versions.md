# 文档版本（Pipeline Versions）

MimirQ 支持按 `pipeline_hash` 管理同一文档的“处理版本”（切块/清洗/解析配置变化后形成的新版本）。这类能力通常用于：

- 运维回滚：快速切回旧版本的切块与检索结果（无需重新解析 / 重新向量化）
- 对比调参：对比不同 pipeline 配置下的切块质量与召回表现
- 清理历史：删除非激活版本，降低存储与索引负担

## 关键概念

- `pipeline_hash`：一次文档处理流程（解析/治理/切块/Embedding 等配置）的哈希标识。
- `doc_pipeline_key`：内部键，通常形如 `"{document_id}:{pipeline_hash}"`，用于把 chunk 与版本绑定。
- 激活版本（active）：用于检索与引用（citations）的版本。切换激活版本不会触发重新处理，只是改变“读”的指向。

## 前端如何使用

在「知识库」页面打开某个文档的详情弹窗：

- 右下角点击「版本」：查看所有版本、复制 `pipeline_hash`、执行“激活/删除”。
- 切块列表顶部（桌面端）：可直接选择“查看版本”，在不激活的情况下预览某个版本的切块。

## API 使用方法

### 1) 列出版本

- `GET /api/v1/documents/{document_id}/versions`

返回包含：

- `active_pipeline_hash`：当前激活版本
- `items[]`：每个版本的 `pipeline_hash`、chunk 数量、时间范围、是否 active

### 2) 激活（回滚到）某个版本

- `POST /api/v1/documents/{document_id}/versions/{pipeline_hash}/activate`

说明：

- 不会重新解析 / 重新入库 / 重新向量化
- 仅当目标版本已存在 chunks 时才允许激活
- 通常需要对文档所属数据集具备写权限

### 3) 删除某个版本（非激活版本）

- `DELETE /api/v1/documents/{document_id}/versions/{pipeline_hash}`

说明：

- 当前激活版本不可删除（请先激活其他版本）
- 文档正在 processing 且该版本为当前 in-progress 版本时，会拒绝删除

### 4) 按版本查看切块

推荐使用分页接口（适合大文档）：

- `GET /api/v1/documents/{document_id}/chunks?skip=0&limit=200&pipeline_hash=...`

调试/排障场景可跨版本查看：

- `GET /api/v1/documents/{document_id}/chunks?all_versions=true`

## 常见问题

### 为什么切换激活版本不触发重新处理？

版本切换主要用于“读路径”回滚/对比（检索与引用），避免高成本的重新解析与重新向量化。

### 什么时候会产生多个版本？

当同一文档在不同的 pipeline 配置下被处理（例如切块策略/参数、治理规则、解析后端等发生变化），会形成不同的 `pipeline_hash` 版本。是否保留历史版本取决于后端 ingest 策略与配置。

