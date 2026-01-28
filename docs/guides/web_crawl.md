# 网站抓取（站点级 Connector）

MimirQ 提供 `web_crawl` 连接器，用于从一个或多个站点种子 URL 开始抓取页面链接，并批量入库（每个 URL 作为一个文档）。

与单条 URL 导入相比：

- 支持 **站点级抓取**（BFS，受 `max_pages/max_depth` 限制）
- 支持 **登录态/认证抓取**（Cookie / Bearer / Basic）
- 抓取与入库过程会记录为一次 `Connector Run`，可查看统计与错误

## 安全说明（重要）

- 该功能复用 URL 导入的 SSRF 防护：只允许 http/https，默认禁止私网/回环/.local，重定向默认关闭。
- **认证信息（cookie/token/password）会被加密存储在 connector_runs.config 中，并在 API 响应里脱敏**。

## API

### 1) 列出可用连接器

- `GET /api/v1/connectors`

### 2) 创建一次站点抓取运行

- `POST /api/v1/connectors/runs`

请求示例：

```bash
curl -X POST "http://localhost:8000/api/v1/connectors/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "connector_id": "web_crawl",
    "dataset_id": "00000000-0000-0000-0000-000000000000",
    "config": {
      "start_urls": ["https://example.com/docs/"],
      "max_pages": 50,
      "max_depth": 3,
      "same_host_only": true,
      "include_patterns": ["^https://example\\\\.com/docs/"],
      "exclude_patterns": ["\\\\.png$", "\\\\?download=1$"],
      "auth": { "type": "cookie", "cookie": "your_cookie_here" },
      "parser_backend": "auto",
      "chunk_strategy": "langchain_recursive",
      "access": { "mode": "inherit" }
    }
  }'
```

说明：

- `auth.type` 支持：`none|cookie|bearer|basic`
- `include_patterns/exclude_patterns` 为正则表达式（大小写不敏感）；用于控制抓取范围
- `parser_backend/chunk_strategy/pipeline` 与 URL 导入一致，对每个 URL 生效

### 3) 查看运行列表/详情

- `GET /api/v1/connectors/runs`
- `GET /api/v1/connectors/runs/{run_id}`

### 4) 取消运行

- `POST /api/v1/connectors/runs/{run_id}/cancel`

