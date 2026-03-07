# Connectors（连接器）与 Connector Runs

本指南介绍 MimirQ 的连接器（Connectors）能力：把“从外部数据源批量导入文档/目录信息”的过程，抽象成一次可追踪、可取消、可重试的 **Connector Run**。

适用场景：

- 批量导入多个 URL / 站点抓取（web crawl）
- 导入 GitHub Repo 内的文档文件（README/markdown/pdf 等）
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

- `url_batch`：支持 `supports_resume`，并利用 URL 列表去重做轻量增量保护。
- `github_repo`：支持 `supports_incremental + supports_resume`；后续 run 会用 Git blob SHA manifest 跳过未变化文件。
- `confluence_space`：支持 `supports_incremental`；后续 run 会基于 `last_modified` cursor 拉取更新页面。
- `web_crawl` / `drive_files` / `minio_bucket`：当前仍以 `supports_resume` 为主，解决中断续跑，不把它们宣称为真正源增量。

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

### 5.3 `github_repo`：GitHub Repo 导入

用途：通过 GitHub API 列出仓库文件，再用 `raw.githubusercontent.com` 拉取内容入库。

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

### 5.6 `mysql_catalog` / `sqlserver_catalog`：数据库目录（Catalog）同步

用途：同步 schema/table/column 的目录信息，并可选做 **安全画像**（聚合统计）用于治理与检索侧“理解数据形态”。

安全边界（重要）：

- 该 connector 目标是 **目录与聚合**，不直接导出原始行数据
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
    "profile_enabled": true
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
    "profile_enabled": true
  }
}
```
