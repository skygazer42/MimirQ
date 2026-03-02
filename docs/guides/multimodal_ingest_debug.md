# 多模态（图片/表格）Ingest 与 Debug 指南

本指南覆盖 Wave19 多模态 RAG 的常见运维/调试路径：如何让系统产生 **image/table evidence**，以及当引用/渲染异常时应该看哪里。

目标：
- 更快定位“为什么没召回图片/表格证据”
- 更快定位“图片引用有了但前端渲染不出来”
- 在不泄露 PII 的前提下完成可复现的排障

---

## 1. 功能地图（你在看什么）

MimirQ 的多模态证据大体分两类：

1. **图片证据（Image citations）**
   - Ingest 时将图片/figure 的 OCR/caption 等文本侧信息写入 chunk（用于可读 evidence）
   - 同时将图片侧向量写入 CLIP 索引（用于检索）
   - Chat/Retrieve 时把 image hits 注入检索候选，最终以 citations 形式返回 `img_id/img_url`

2. **表格证据（Table citations）**
   - Ingest 时将表格资产写入 table store（结构化）
   - Query 时可通过 TAG（Text-to-SQL）对表格做安全查询（不直接暴露原始表）
   - citations 可能来自 TAG 的结果摘要或表格相关 chunk

---

## 2. 开关与依赖（最常见的“没生效”原因）

### 图片相关

- `IMAGE_EMBEDDING_ENABLED`
  - 开启图片 embedding 索引与检索注入逻辑
- `SHOW_IMAGE_IN_ANSWER`
  - 开启后，chat 最终答案可能会附加“Related Images” Markdown（仅非 structured output）
- `IMAGE_APPEND_MAX`
  - 允许追加到答案里的图片数量上限（0 表示不追加）

### 表格相关（TAG）

- 参考 `docs/guides/table_tag.md`
  - TAG 本质是受控的“表格资产检索/查询”通道，不应该默认把原始行返回到普通读者

### MinIO（图片/文档对象存储）

- `MINIO_ENABLED`
  - 图片引用（`/api/v1/documents/image-url/{img_id}`）依赖 MinIO
  - 如果未启用 MinIO，多模态引用的 `img_id` 仍可能存在，但 `img_url` 无法加载
- `MINIO_DOCUMENTS_ENABLED`
  - 影响文档源文件是否走 MinIO；与图片是否可用是两条独立开关

---

## 3. 证据是否“被召回”：先看检索链路

推荐顺序：

1. **Retrieve Preview Panel**
   - 用 “Retrieve”/“Evidence” 工具页查看实际召回的 citations
   - 图片证据通常会带 `has_image=true` 与 `img_url`

2. **RAG Trace**
   - 查看 per-query 的检索耗时、渠道计数、rerank skip reason 等
   - 如果你看到 `retrieval_role=image` 或 `hit_type=image/tag`，说明多模态通道已经参与

3. **Evidence Viewer（Wave19-T067）**
   - 从 citations 直接打开“证据查看器”，可看到图片预览、chunk/page/span、pipeline_hash 等溯源信息
   - 这一步用于回答：“这张图/这个表到底来自哪个文档、哪一页、哪个 chunk”

---

## 4. 图片能否“被渲染”：再看资产服务

图片引用一般走两条后端路由：

1. `GET /api/v1/documents/image/{image_id}`
   - 本地文件系统存储的图片（preview-time 或 legacy）
   - 该接口支持 ETag + Cache-Control（适合缩略图）

2. `GET /api/v1/documents/image-url/{img_id}`
   - MinIO 存储的图片（推荐路径）
   - Wave19-T069 之后，该接口会直接 proxy 返回 bytes，并支持 `Range: bytes=...`（避免大图全量下载）

如果前端渲染异常，优先在浏览器 Network 中确认：
- 返回码是否为 200/206
- `Content-Type` 是否为 `image/jpeg`
- 是否返回了 `Cache-Control` / `ETag` / `Accept-Ranges`

---

## 5. 安全/合规注意事项

- citations 图片 URL 在前端会做 “same-origin + 路径 allowlist” 检查，防止把 token 泄露到第三方域名。
- `image-url` 这类接口默认允许 `<img src>` 场景：
  - 在 `AUTH_MODE=header` 的非生产环境下可匿名访问（便于本地调试）
  - 在生产环境建议强制鉴权（避免外链/爬虫直接抓取敏感资产）

---

## 6. 常见问题（FAQ）

### Q1: 为什么 chat 有 citations，但没有图片预览？

排查：
- citation 是否带 `img_url`（不是只有 `img_id`）
- `MINIO_ENABLED` 是否启用
- 前端安全 URL 解析是否拒绝了非后端域名（这属于预期保护）

### Q2: 为什么图片/表格证据没被召回？

排查：
- 是否启用了相应通道（`IMAGE_EMBEDDING_ENABLED` / TAG）
- 是否存在 dataset 权限/文档 ACL 过滤（security trimming）
- `RETRIEVAL_TOP_K` 是否过小，导致通道结果被融合/多样性 cap 截断

