# Connectors（连接器）与 Connector Runs

本指南介绍 MimirQ 的连接器（Connectors）能力：把“从外部数据源批量导入文档/目录信息”的过程，抽象成一次可追踪、可取消、可重试的 **Connector Run**。

适用场景：

- 批量导入多个 URL / 站点抓取（web crawl）
- 导入 GitHub Repo 内的文档文件（README/markdown/pdf 等）
- 导入 Jira Cloud 项目中的 issues / comments（企业知识库常见高价值源）
- 导入 Google Drive 分享链接指向的文件
- 从 MinIO/S3 Bucket 批量导入对象文件
- 从 MySQL / SQLServer 同步 schema/table/column 目录（Catalog）与安全画像（仅聚合统计，不外发原始行）

> 单条 URL 导入请看：[url_ingest.md](./url_ingest.md)。

## 1) 核心概念

- **Connector**：一个导入器（例如 `web_crawl`、`github_repo`）。
- **Connector Config**：可选的“持久化配置 + 定时任务”（cron），用于周期性同步。
- **Connector Run**：一次实际执行（会记录状态、统计、错误、产出 document_ids）。

## 2) API 概览

### 2.1 列出可用连接器

- `GET /api/v1/connectors`

返回的是静态 registry（后端内置），包含：

- `id`：连接器标识（创建 run 时使用）
- `supports_incremental`：是否支持真正的源增量（后续 run 会基于源侧 cursor/hash/更新时间只处理 changed/new 项）
- `supports_resume`：是否支持对失败/取消 run 做 best-effort 续跑（checkpoint resume，不等价于源增量）

### 2.1.1 `supports_resume` vs `supports_incremental`

这两个能力要分开理解：

- `supports_resume=true`：表示可以对某个失败/取消的 run 调用 `POST /api/v1/connectors/runs/{run_id}/resume`，从上次 checkpoint 继续做完剩余工作。它解决的是“这个 run 还没做完”。
- `supports_incremental=true`：表示保存的 connector state 可以跨 run 表达“源系统已经同步到了哪里”，后续 run 会自动只处理 changed/new 源项，甚至可能出现 **no-op rerun**（源侧没有变化，run 很快完成且不重复入库）。

当前内置 connector 的同步语义：

- `url_batch`：支持 `supports_incremental + supports_resume`；主要提供 URL 级别的轻量增量保护（去重/断点续跑）。
- `github_repo`：支持 `supports_incremental + supports_resume`；后续 run 会用 Git blob SHA manifest 跳过未变化文件，并在检测到 tracked path 已从仓库消失时剪掉 stale manifest entry。
- `confluence_space`：支持 `supports_incremental`；后续 run 会基于 `last_modified` cursor 拉取更新页面。
- `jira_project`：支持 `supports_incremental`；后续 run 会基于 issue `updated` cursor 只拉取新变更 issue，并默认使用 `jira_ticket` chunker。
- `web_crawl`：支持 `supports_incremental + supports_resume`；当前增量 token 以 URL 清单 hash 为主，支持 removed URL reconcile（soft-disable）。
- `drive_files`：支持 `supports_incremental + supports_resume`；使用 source manifest token（优先 version/modifiedTime/file_id）做 changed/new 判定，并支持 removed path reconcile（soft-disable）。
- `minio_bucket`：支持 `supports_incremental + supports_resume`；使用对象 token（etag/last_modified/size）做 changed/new 判定，并支持 removed path reconcile（soft-disable）。

### 2.1.2 Saved State Contract

`connector_configs.state` 现在不仅保存 connector-specific cursor，还会保存一个稳定、可审计的 envelope：

- `state_schema_version`：state schema 版本号
- `state_revision`：每次 state 持久化递增的 revision
- `state_recorded_at`：最近一次写入 state 的 UTC 时间
- `state_audit`：一个有界历史（默认保留最近 10 次），记录 revision、run_id、status 和被更新的 state keys

同时继续保留 connector-specific 顶层字段，便于执行器直接读取，例如：

- `cursor`
- `last_modified`
- `source_manifest`
- `total_files` / `total_urls` / `total_objects`

这让执行器不需要解析深层 envelope，同时运维侧仍然可以审计 state 演进。

### 2.2 校验配置（预检）

- `POST /api/v1/connectors/validate`

用途：在 UI 中做“连通性检查 / 参数校验”，避免 run 创建后才失败。

### 2.3 运行（Runs）

- `POST /api/v1/connectors/runs`：创建一次 run
- `GET /api/v1/connectors/runs`：列表
- `GET /api/v1/connectors/runs/{run_id}`：详情
- `POST /api/v1/connectors/runs/{run_id}/cancel`：取消（best-effort）

### 2.4 配置与定时（Configs）

如果你希望周期性增量同步，可使用 Configs：

- `GET /api/v1/connectors/configs`
- `POST /api/v1/connectors/configs`
- `PUT /api/v1/connectors/configs/{config_id}`
- `DELETE /api/v1/connectors/configs/{config_id}`
- `POST /api/v1/connectors/configs/{config_id}/run`：用该 config 触发一次 run

## 3) 安全说明（重要）

### 3.1 URL/抓取类连接器的 SSRF 防护

URL 类连接器（`url_batch` / `web_crawl` / `github_repo` / `drive_files` / `minio_bucket`）会复用 URL ingest 的 SSRF 防护策略（只允许 http/https、默认禁止私网/回环/.local、默认不跟随重定向、限制下载大小与超时等）。

具体开关与建议见：[url_ingest.md](./url_ingest.md)。

### 3.2 Secrets 存储与脱敏

连接器配置中的敏感字段（例如 cookie/token/password）会：

- 在数据库中以 **加密形式**写入 `connector_runs.config` / `connector_configs.config`
- 在 API 响应里 **脱敏**（redacted），避免泄漏

## 4) 通用配置字段（所有连接器共用的“入库参数”）

大多数连接器在其 `config` 中都支持这些字段（对每个导入到系统的文档生效）：

- `parser_backend`：解析器后端（`auto` / 其它）
- `chunk_strategy`：切分策略（例如 `langchain_recursive`）
- `pipeline`：DocumentPipelineOptions（治理/切分参数等）
- `access`：Document ACL（inherit/only_me/partial_members 等，取决于后端支持）
- `source_acl`：**源权限继承**（Source ACL → Document ACL，按 tenant groups 映射；默认关闭）

这些字段与文件上传、URL 导入保持一致，便于复用既有 pipeline 配置。

关于 `source_acl` 的详细运维说明、external_id 映射约定、示例与排障见：
- [docs/guides/connector_acl_inheritance.md](./connector_acl_inheritance.md)

## 5) 内置连接器清单与示例

下面示例都使用同一套 run API：

```bash
curl -X POST "http://localhost:8000/api/v1/connectors/runs" \
  -H "Content-Type: application/json" \
  -d '{ ... }'
```

### 5.1 `url_batch`：URL 批量导入

用途：把多个 http(s) URL 作为多个文档入库。

示例：

```json
{
  "connector_id": "url_batch",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "urls": ["https://example.com/a.pdf", "https://example.com/b.html"],
    "parser_backend": "auto",
    "chunk_strategy": "langchain_recursive",
    "pipeline": { "chunk_merge_small_min_chars": 200 },
    "access": { "mode": "inherit" }
  }
}
```

### 5.2 `web_crawl`：站点抓取（网站爬取）

用途：从一个或多个 `start_urls` 出发，抓取站点链接并批量入库（每个 URL 作为一个文档）。

示例（带 include/exclude 与 cookie 登录态）：

```json
{
  "connector_id": "web_crawl",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "start_urls": ["https://example.com/docs/"],
    "max_pages": 50,
    "max_depth": 3,
    "same_host_only": true,
    "use_sitemaps": true,
    "respect_robots": false,
    "include_patterns": ["^https://example\\\\.com/docs/"],
    "exclude_patterns": ["\\\\.png$", "\\\\?download=1$"],
    "auth": { "type": "cookie", "cookie": "your_cookie_here" },
    "parser_backend": "auto",
    "chunk_strategy": "langchain_recursive"
  }
}
```

更完整说明见：[web_crawl.md](./web_crawl.md)。

增量 freshness 语义（当前实现）：

- `web_crawl` 支持 manifest-based incremental（`supports_incremental=true`）。
- 每个 source 使用 **内容感知 sync token**：
  - 优先：`content_type + body_sha256`（同 URL 但正文变化也会命中增量）
  - 回退：`url_sha256`（无正文场景）
- 为兼容旧 state，系统支持旧 token 的平滑迁移：旧 manifest 首次运行会先按 presence-only 处理，随后把 state 升级为内容感知 token。
- 对于历史存在但本次 crawl 未发现的 URL，会进入 removed reconcile，记录 `removed_paths` / `removed_paths_reconciled` / `removed_documents_disabled` 并执行 soft-disable。

增量示例（`run.stats`）：

```json
{
  "mode": "incremental",
  "delta_urls": 3,
  "skipped_unchanged": 47,
  "removed_paths": 2,
  "removed_paths_reconciled": 2,
  "removed_documents_disabled": 2
}
```

增量示例（`connector_configs.state.source_manifest`）：

```json
{
  "https://example.com/docs/a": "web_crawl|text/html|body:7e1b...c0",
  "https://example.com/docs/b": "web_crawl|application/pdf|body:1f45...9a"
}
```

### 5.3 `github_repo`：GitHub Repo 导入

用途：通过 GitHub API 列出仓库文件，再用 `raw.githubusercontent.com` 拉取内容入库。

增量同步行为补充：

- `source_manifest` 会保存已成功处理的 `path -> blob_sha` 映射，后续 run 用它跳过未变化文件。
- 如果某个 tracked path 已不再出现在当前仓库树中，run stats 和保存的 state 会把该 path 从 manifest 中剪掉。
- 对于这类 removed path，系统会按 `doc_metadata.source_url` 对应的 connector-managed 文档做 **soft-disable**，而不是 hard delete。
- 删除对账只作用于由同一个 `github_repo` connector 创建过的文档，不会误伤手工上传或其他 connector 写入的文档。

示例（私有仓库/提高限额可用 Bearer token）：

```json
{
  "connector_id": "github_repo",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "repo": "owner/repo",
    "branch": "main",
    "max_files": 50,
    "include_extensions": [".md", ".txt", ".pdf"],
    "auth": { "type": "bearer", "token": "ghp_xxx" },
    "parser_backend": "auto",
    "chunk_strategy": "langchain_recursive"
  }
}
```

### 5.4 `drive_files`：Google Drive 文件导入（分享链接）

用途：从 Google Drive 文件分享链接中解析 file_id，构造直链下载入库（仅文件，不支持文件夹）。

示例：

```json
{
  "connector_id": "drive_files",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "urls": ["https://drive.google.com/file/d/<file_id>/view?usp=sharing"],
    "parser_backend": "auto",
    "chunk_strategy": "langchain_recursive"
  }
}
```

增量 freshness 语义（Wave B）：

- `drive_files` 现在支持 manifest-based incremental（`supports_incremental=true`）。
- 每个 source 记录稳定 sync token，优先使用 `version + modifiedTime + file_id`；缺失时退化到 URL/file_id hash。
- 后续 run 会对比历史 `source_manifest`，仅处理 changed/new 项，并统计：
  - `mode`（`full` / `incremental`）
  - `delta_urls`
  - `skipped_unchanged`
  - `source_manifest`
- 对于历史存在但本次缺失的 Drive path，会进入 removed reconcile：
  - `removed_paths`
  - `removed_paths_reconciled`
  - `removed_documents_disabled`
  - 执行 soft-disable（不做 hard delete）

运维建议：

- 首次 run 预期是 `mode=full`；第二次起应主要看到 `mode=incremental`。
- 若 `delta_urls` 长期异常偏高，优先检查上游是否频繁改写 `modifiedTime/version`。

增量示例（`source_manifest`）：

```json
{
  "https://drive.google.com/file/d/FILE_A/view": "drive_files|version:12|modified:2026-03-11T08:10:00Z|id:FILE_A",
  "https://drive.google.com/file/d/FILE_B/view": "drive_files|version:3|modified:2026-03-09T02:00:00Z|id:FILE_B"
}
```

### 5.5 `minio_bucket`：MinIO/S3 Bucket 导入

用途：列出 bucket 对象，生成 presigned URL 拉取并入库。

注意：

- 需要 `MINIO_ENABLED=true`，并配置 MinIO 相关环境变量
- 需要 URL ingest SSRF 允许访问 MinIO endpoint（通常要求部署在受控网络、或配置 allowlist/WAF）

示例：

```json
{
  "connector_id": "minio_bucket",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "bucket": "mimirq",
    "prefix": "kb/",
    "max_objects": 50,
    "include_extensions": [".pdf", ".md", ".txt"],
    "presign_expiry_sec": 3600,
    "parser_backend": "auto",
    "chunk_strategy": "langchain_recursive"
  }
}
```

增量 freshness 语义（Wave B）：

- `minio_bucket` 支持 manifest-based incremental（`supports_incremental=true`）。
- 每个 object 使用稳定 token（`etag` + `last_modified` + `size`，按可用性组合）；后续 run 基于 `source_manifest` 仅处理 changed/new 对象，并统计 `mode` / `delta_objects` / `skipped_unchanged`。
- scope 变化（例如 bucket/prefix/include 规则变化）会触发 scope hash 变化，并重置旧 manifest，避免跨 scope 的脏增量。
- 对于历史存在但本次缺失的 object key，会进入 removed reconcile，记录 `removed_paths` / `removed_paths_reconciled` / `removed_documents_disabled` 并执行 soft-disable。

增量示例（`source_manifest`）：

```json
{
  "kb/handbook/a.pdf": "minio_bucket|etag:8d5f...aa|last_modified:2026-03-10T12:10:00Z|size:2097152",
  "kb/handbook/b.md": "minio_bucket|etag:11af...8e|last_modified:2026-03-09T01:20:00Z|size:18291"
}
```

### 5.6 `jira_project`：Jira Cloud Project 导入

用途：从 Jira Cloud 项目按 issue 粒度同步工单，并把 issue 描述、关键字段、评论渲染成结构化 HTML 文档入库。

为什么优先补 Jira：

- 在企业知识库场景里，Jira 通常比 Notion/Slack/SharePoint 更直接承载“需求、缺陷、决策、交付状态”等高价值知识
- 当前系统已经内置 `jira_ticket` chunker，因此首个企业 SaaS connector 做 Jira 的实现成本和检索质量都更优

当前范围与边界：

- 聚焦 **Jira Cloud 项目 issue 同步**，不是完整 Jira 平台镜像
- 支持 `sync_mode=auto|full|incremental`
- 默认 `chunk_strategy="jira_ticket"`，以更好地按 Summary / Description / Comments 等段落切分
- 可选拉取 comments；ACL 继承基于 issue security level 与 comment visibility 的 best-effort 外部映射
- 可选 `custom_fields`：显式 allowlist 额外拉取并渲染到文档里的自定义字段（例如 `customfield_10016`）
- 可选 `include_linked_artifacts`：从 issue 描述/评论里提取 URL 并作为子文档入库（受 `max_*_linked_artifacts` 限制；默认关闭）

示例：

```json
{
  "connector_id": "jira_project",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
	  "config": {
	    "base_url": "https://example.atlassian.net",
	    "project_key": "PLAT",
	    "jql": "statusCategory != Done",
	    "auth": { "type": "basic", "username": "bot@example.com", "password": "jira_api_token" },
	    "sync_mode": "auto",
	    "max_issues": 200,
	    "page_size": 50,
	    "include_comments": true,
	    "max_comments_per_issue": 20,
	    "custom_fields": ["customfield_10016"],
	    "include_linked_artifacts": false,
	    "max_linked_artifacts_per_issue": 10,
	    "max_total_linked_artifacts": 200,
	    "parser_backend": "auto",
	    "chunk_strategy": "jira_ticket",
	    "source_acl": { "mode": "inherit", "fallback_mode": "partial_members" }
	  }
	}
	```

运维提示：

- `base_url` 应填站点根 URL，例如 `https://<site>.atlassian.net`
- `basic` 模式通常使用 Atlassian 账号邮箱 + API token
- `customfield_XXXXX` 的 ID 通常可通过 Jira 管理后台字段配置或 `GET /rest/api/3/field` 查到（仅需把需要的字段加入 allowlist）
- 若启用 `source_acl`，建议先准备好与 Jira security level / role / group 对应的 `tenant_groups.external_id`

### 5.7 `mysql_catalog` / `sqlserver_catalog`：数据库目录（Catalog）同步

用途：同步 schema/table/column 的目录信息，并可选做 **安全画像**（聚合统计）用于治理与检索侧“理解数据形态”。
在 Wave C 中，额外支持可控的 **DB 行级 sidecar**（用于 TAG 召回），默认关闭。

安全边界（重要）：

- 默认目标仍是 **目录与聚合**，不导出原始行数据
- 若明确开启 row sync，会以严格上限抽取行快照写入 `dbrows` sidecar（供 TAG 查询）
- 密码会被加密存储，API 会脱敏

MySQL 示例：

```json
{
  "connector_id": "mysql_catalog",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "host": "127.0.0.1",
    "port": 3306,
    "database": "mydb",
    "username": "user",
    "password": "pass",
    "include_schemas": ["public"],
    "include_tables": ["orders", "users"],
    "max_tables": 200,
    "profile_enabled": true,
    "row_sync_enabled": true,
    "row_sync_max_tables": 20,
    "row_sync_max_rows_per_table": 50,
    "row_sync_max_cols": 50
  }
}
```

SQLServer 示例：

```json
{
  "connector_id": "sqlserver_catalog",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "host": "127.0.0.1",
    "port": 1433,
    "database": "mydb",
    "username": "sa",
    "password": "pass",
    "max_tables": 200,
    "profile_enabled": true,
    "row_sync_enabled": true,
    "row_sync_max_tables": 20,
    "row_sync_max_rows_per_table": 50,
    "row_sync_max_cols": 50
  }
}
```

行级 sidecar 开启条件：

- 全局开关：`DB_CATALOG_ROW_SYNC_ENABLED=true`
- 连接器配置：`row_sync_enabled=true`

行级 sidecar 上限（全局）：

- `DB_CATALOG_ROW_SYNC_MAX_TABLES`（每次 run 最多抽取多少张表）
- `DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE`（每张表最多抽多少行）
- `DB_CATALOG_ROW_SYNC_MAX_COLS`（每张表最多保留多少列）

连接器 run 结束后，可在 `run.stats` / `connector_configs.state` 看到：

- `total_tables`：本次 row snapshot 的表数
- `source_manifest`：`source_table -> source_sync_token`（用于增量对账和可追溯）
- `row_sidecar.document_id`：写入的 `dbrows` sidecar 文档
