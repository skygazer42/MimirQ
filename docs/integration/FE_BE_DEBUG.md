# 前后端联调（20 个任务清单）

本清单面向 `frontend/`（Next.js）与 `backend/`（FastAPI）联调，目标是把“能跑”提升到“可用 + 可排障”。

## 快速启动

- Docker（推荐）：先启动后端 `cd backend; docker compose up -d --build`，再启动前端 `cd frontend; pnpm install; pnpm dev`
  - 后端：`http://localhost:8000/docs`
  - 前端：`http://localhost:3000`
- 本地开发（不推荐混用 Conda/系统 Python 时请注意环境一致性）
  - 后端：`cd backend; python -m pip install -r requirements.txt; uvicorn app.main:app --reload`
  - 前端：`cd frontend; pnpm install; pnpm dev`

## 最小联调流程（建议照这个走一遍）

1. 启动后端：`cd backend; docker compose up -d --build`
2. 启动前端：`cd frontend; pnpm dev`
2. 打开前端：`http://localhost:3000`，观察左下角 `Backend：OK`
3. 上传文档：进入「知识库」页上传 PDF/TXT/MD，等待状态变为 `completed`
4. 聊天验证：回到「对话」页提问，确认能看到 citations（包含页码/相似度/图片）
5. 历史续聊：进入「问答历史」页，选中会话 -> 点「继续对话」，确认能回到 `/?conversation=...` 并加载历史消息

## 常见问题速查

- **401 未授权**：前端需要 `X-User-ID`，用 `frontend/.env.local.example` 配好 `NEXT_PUBLIC_USER_ID`，或设置 localStorage `mimirq_user_id`
- **400 Invalid tenant id**：检查 `NEXT_PUBLIC_TENANT_ID` / localStorage `mimirq_tenant_id` 是否是合法 UUID
- **CORS**：后端 `.env` 的 `CORS_ORIGINS` 需包含 `http://localhost:3000`
- **图片不显示**：确认后端 `MINIO_ENABLED=true`，并能访问 `GET /api/v1/documents/image-url/{img_id}`
- **Next build 报 EPERM .next/trace**：用 `NEXT_DIST_DIR=.next_build pnpm build`（已支持可配置 distDir）

## 20 个任务（计划 + 执行）

1. [x] 统一并补齐本地联调环境变量（前端 `.env.local.example`、后端 `.env.example`）
2. [x] 新增后端健康检查接口（`GET /api/v1/health`）
3. [x] 前端增加后端连通性指示（health ping + UI）
4. [x] SSE 错误事件补齐 `request_id`（前后端便于关联日志）
5. [x] Graph 快捷通道也纳入 try/except（SSE 统一返回 error 事件）
6. [x] 前端 `useChat` 支持从 `done` 事件回填 `conversation_id`
7. [x] 前端后续消息复用 `conversation_id`（避免每条消息新建会话）
8. [x] `/?conversation=...` 打开时自动加载会话消息（History -> Chat 可续聊）
9. [x] “新对话”行为统一（清空会话 + URL + 本地状态）
10. [x] Chat 请求参数 TS 类型对齐后端（`structured_output`/`structured_preset`/`rag_config.*`）
11. [x] 增加 Chat RAG 参数面板（top_k/threshold/retrieval_mode）
12. [x] 支持 `retrieval_mode` 别名（`fulltext/bm25` -> `keyword`）保证前后端兼容
13. [x] 支持 Chat 侧 `use_graph` 开关（非流式 graph runner）
14. [x] 支持 Chat 侧 `structured_output` 开关（并展示 structured 结果）
15. [x] SSE 解析健壮化（容忍 `\\r\\n`、空行、部分数据）
16. [x] 前端统一 API 错误处理（401/400/500 友好提示）
17. [x] 统一 citations/img_url 拼接策略（前端 `toAbsoluteBackendUrl` + 后端返回相对路径约定）
18. [x] 增加最小端到端验证脚本/步骤（上传文档 -> 聊天 -> 历史回放）
19. [x] 后端/前端构建与类型检查（`python -m compileall`、`next build`）
20. [x] 记录联调常见问题与排查路径（CORS、Header、MinIO、Milvus/Postgres）
