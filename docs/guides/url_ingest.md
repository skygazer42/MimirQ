# URL 导入（连接器骨架）

本功能用于让后端 **拉取远程 URL 内容**，然后走与“文件上传”一致的解析/治理/切块/索引流程入库。

## 启用开关

默认关闭。请在后端 `.env` 中开启：

```bash
URL_INGEST_ENABLED=true
```

可选配置（建议按环境收紧）：

```bash
# 最大下载字节数（默认回落到 MAX_FILE_SIZE）
URL_INGEST_MAX_BYTES=50000000

# 拉取超时（秒）
URL_INGEST_TIMEOUT_SEC=30

# SSRF 防护：默认禁止私网/回环/链路本地 IP（强烈建议保持 false）
URL_INGEST_ALLOW_PRIVATE_IPS=false

# SSRF 防护：默认不跟随重定向（建议保持 false）
URL_INGEST_FOLLOW_REDIRECTS=false
```

## API 说明

接口：

- `POST /api/v1/documents/upload-url`

请求体（JSON）：

```json
{
  "url": "https://example.com/doc.pdf",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "filename": "可选：覆盖文件名（影响扩展名识别与展示）.pdf",
  "parser_backend": "auto",
  "chunk_strategy": "langchain_recursive",
  "pipeline": {
    "governance_enabled": true,
    "chunk_merge_small_min_chars": 200,
    "chunk_strategy_params": { "child_ratio": 0.25, "min_child_size": 300 }
  }
}
```

示例（curl）：

```bash
curl -X POST "http://localhost:8000/api/v1/documents/upload-url" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/page.html",
    "parser_backend": "auto",
    "chunk_strategy": "separator",
    "pipeline": { "chunk_strategy_params": { "separator_preset": "paragraph" } }
  }'
```

## 文件类型判定规则

后端会按以下优先级推断扩展名（决定可否入库与走哪个解析器）：

1) `filename`（如果传了）  
2) URL path 的文件名后缀（如 `/a/b/c.pdf`）  
3) `Content-Type`（仅部分类型做映射）  

若无法推断扩展名但 `Content-Type` 为 `text/*`，会回落为 `.txt`；否则返回“不支持的 content-type”。

## SSRF 与安全说明（强烈建议阅读）

此功能按“连接器骨架”的安全基线实现，默认策略偏保守：

- 仅允许 `http://` / `https://`
- 默认阻止 `localhost`、回环地址与 `.local` 域名
- 会做 DNS 解析并检查解析得到的 IP：默认只允许 **公网可路由** IP（`URL_INGEST_ALLOW_PRIVATE_IPS=false`）
- 默认不跟随重定向（避免“跳转到私网”绕过）
- 采用流式下载并强制大小上限：超过上限返回 `413`

如果你必须抓取内网资源：

1) 仅在受控网络/可信租户环境开启 `URL_INGEST_ALLOW_PRIVATE_IPS=true`  
2) 强烈建议同时通过网关/WAF/allowlist 限制可访问域名与路径  
3) 仍建议保持 `URL_INGEST_FOLLOW_REDIRECTS=false`，避免重定向链路带来的绕过风险

## 常见问题

- 返回 `URL ingestion is disabled`：未开启 `URL_INGEST_ENABLED=true`
- 返回 `url host is not allowed`：命中 SSRF 防护（私网/回环/.local/blocked host）
- 返回 `remote file too large`：超过 `URL_INGEST_MAX_BYTES` / `MAX_FILE_SIZE`

