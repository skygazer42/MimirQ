# MimirQ：20 个优化任务（已执行）

> 目标：提升本地开发体验、接口一致性、启动性能、可观测性与前端交互体验。

## 已完成清单（20/20）

1. ✅ 增加后端一键启动的 `docker/docker-compose.yml`（`docker/docker-compose.yml`）
2. ✅ 增加后端 `Makefile`，统一常用命令（`Makefile`）
3. ✅ 增加/修正 `.dockerignore`（根目录 + 前后端），减少构建上下文、加速镜像构建（`.dockerignore`、`.dockerignore`、`web/.dockerignore`）
4. ✅ 修正 `.gitignore`，确保 `.dockerignore` 被纳入版本控制（`.gitignore`）
5. ✅ 更新根目录 `README.md`：统一 `docker compose` 用法、补充访问地址与启动说明（`README.md`）

6. ✅ 后端默认鉴权模式改为 `AUTH_MODE=header`，与前端 `X-User-ID/X-Tenant-ID` 默认行为一致（`app/core/config.py`）
7. ✅ 更新后端 `docker/.env.example`：默认 `AUTH_MODE=header`，补充 `SECRET_KEY` 说明（`docker/.env.example`）

8. ✅ BM25 启动期建索引改为可选，并增加上限保护，避免大数据量冷启动卡死（`app/main.py`）
9. ✅ 增加 BM25 启动期建索引配置项（开关 + 最大 chunks），便于按环境调优（`app/core/config.py`）

10. ✅ Rate Limit 支持 Chat 专用限流参数（避免被全局限流误伤）并在主应用注入（`app/api/middleware/rate_limit.py`、`app/main.py`）
11. ✅ 运行时迁移改为“单条 DDL best-effort”，并补充关键索引，减少线上迁移失败风险与常用查询成本（`app/core/migrations.py`）

12. ✅ 修复 KG 默认 tenant 类型：确保写入 PG UUID 列时为 `uuid.UUID`（`app/rag/kg/models.py`）
13. ✅ 增加 KG 图谱响应 Schema，统一前端可视化数据结构（`app/rag/kg/schemas.py`）
14. ✅ 新增 KG 图谱接口 `GET /api/v1/kg/graph`，带 ACL 过滤与数据量上限（`app/rag/kg/api/routes.py`、`app/api/v1/__init__.py`）

15. ✅ 统一数据集列表接口返回结构（`{total, items}`）并支持分页；同时避免 PARTIAL_MEMBERS 的 N+1 查询（`app/api/v1/datasets.py`、`app/api/schemas/dataset.py`）

16. ✅ 前端 Graph 优先拉取后端 KG 图谱，失败自动 fallback 到 mock，保证页面可用（`web/services/graph-service.ts`）
17. ✅ 前端补齐 RAG 调试 API（retrieve/prompt preview）类型与 client 方法（`web/types/index.ts`、`web/lib/api-client.ts`）
18. ✅ Knowledge 页面接入真实检索预览：展示 query_for_retrieval / citations / metrics，并补充错误提示（`web/app/knowledge/page.tsx`）

19. ✅ 统一上传文件 accept 列表（PDF/TXT/MD/Word/Excel/CSV/HTML/JSON），避免前后端支持不一致（`web/components/sidebar.tsx`、`web/components/manual-upload-dialog.tsx`、`web/components/chunk-preview.tsx`、`web/app/knowledge/page.tsx`、`web/app/parsing/page.tsx`）

20. ✅ 前端全局挂载 Sonner Toaster、替换 `alert()` 为 toast，并增加 Graph → Chat 的预填跳转；新增“数据集”管理页与侧边栏入口（`web/app/layout.tsx`、`web/components/sonner-toaster.tsx`、`web/app/graph/page.tsx`、`web/components/chat-area.tsx`、`web/app/datasets/page.tsx`、`web/components/navbar.tsx`）

## 测试/校验（补充）

- ✅ 增加后端单元测试与 pytest 配置（`pytest.ini`、`tests/`）
- ✅ 前端补齐 `pnpm-lock.yaml` 缺失的 eslint 依赖以通过 `next lint`（`web/pnpm-lock.yaml`）

