# RAGFlow / DeepDoc 图片 → MinIO → RAG 正文渲染（20 条任务清单）

目标：文档解析（DeepDoc / MinerU / MarkItDown）产出的图片不再以 base64 长驻内容或 metadata，而是上传到 MinIO；检索命中后在 citations 中返回 `img_id/img_url/has_image`，并在**回答正文**中可渲染图片。

## 任务清单（20）

1. [x] 准备 MinIO（本地或集群）并确认可访问（endpoint/AK/SK）。
2. [x] 在后端 `.env` 配置 `MINIO_ENABLED=true` + `MINIO_ENDPOINT/MINIO_*`。
3. [x] 若用 `docker/docker-compose.yml`，把后端服务环境变量补齐 `MINIO_ENDPOINT_DOCKER=mimirq-minio:9000` 等。
4. [x] 修复/增强 DeepDoc 解析适配：输出“文本 Document + 图片 Document”。
5. [x] DeepDoc 图片 Document 的 metadata 统一为 `doc_type_kwd=image` + `image=<PIL.Image>`（供后续上传）。
6. [x] 在切块阶段将 `metadata["image"]` 上传到 MinIO，并写回 `metadata["img_id"]`。
7. [x] 处理“内嵌 data URI 图片”：解析 Markdown/HTML，上传到 MinIO，替换为 `/api/v1/documents/image-url/{img_id}`。
8. [x] 从 chunk 内容中反向提取 `img_id`（当图片已被替换成 URL、但不在 metadata 中）。
9. [x] 文档级聚合记录 `documents.metadata.img_ids`（避免 ZIP/asset 资源删除遗漏）。
10. [x] 删除文档时优先使用 `documents.metadata.img_ids` 做 MinIO 清理（并兼容逐 chunk 清理）。
11. [x] 放开 MinerU 本地 ZIP 模式：`MINERU_ENABLED=true` + `MINERU_LOCAL_SERVER_URL=...` 时无需 `MINERU_API_TOKEN`。
12. [x] MinerU 本地 ZIP 模式解析时传入正确的 `dataset_id/document_id`（用于 MinIO 路径）。
13. [ ] MarkItDown 若输出“图片文件路径（非 data URI）”，补齐对应图片文件收集与上传逻辑（若你遇到这种格式再做）。
14. [x] 检索侧补齐：向量检索结果 metadata 裁剪时，回查 DB 补 `img_id/page/source`。
15. [x] citations 中透出 `img_id/img_url/has_image`（供前端引用卡片展示）。
16. [x] 回答正文追加图片：当 citations 带图时，在回答末尾追加 Markdown 图片（最多 3 张，避免刷屏）。
17. [ ] 约定图片展示策略：只显示“命中的图片块”，还是“命中段落里出现图片 URL 的块”。
18. [ ] 为历史文档做一次“重处理/重入库”（否则旧 chunk 没有 `img_id`）。
19. [ ] 加监控与告警：MinIO put/get 失败率、预签名 URL 失败率、对象数量增长。
20. [ ] 安全与权限：`/api/v1/documents/image-url/{img_id}` 是否需要租户鉴权/签名校验（按你的安全需求决定）。

## 相关代码入口（便于你定位）

- DeepDoc 解析适配：`app/parsing/parsers/deepdoc_parser.py`
- 切块阶段上传/替换/绑定：`app/parsing/processors/processor.py`
- MinerU 本地 ZIP 支持：`app/services/mineru_service.py`、`app/parsing/factory.py`
- 向量检索 metadata 回查补齐：`app/storage/search/hybrid_retriever.py`
- 图片 URL API：`app/api/v1/documents.py`
- 正文渲染（Markdown img）：`web/components/chat-area.tsx`
