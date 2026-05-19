#!/usr/bin/env python3
"""Generate docs-site/docs tree (Chinese). Run from repo root: python scripts/docs/bootstrap_handbook.py"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs-site" / "docs"


def write(rel: str, body: str) -> None:
    p = DOCS / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.rstrip() + "\n", encoding="utf-8")


def category(path: str, label: str, pos: int) -> None:
    write(
        path,
        json.dumps({"label": label, "position": pos, "collapsed": False}, ensure_ascii=False, indent=2)
        + "\n",
    )


def md(path: str, title: str, body: str, sidebar_label: str | None = None, pos: int | None = None) -> None:
    fm = ["---"]
    if sidebar_label:
        safe = sidebar_label.replace('"', '\\"')
        fm.append(f'sidebar_label: "{safe}"')
    if pos is not None:
        fm.append(f"sidebar_position: {pos}")
    fm.append("---")
    header = "\n".join(fm) + "\n\n"
    write(path, header + f"# {title}\n\n{body.strip()}\n")


def tmpl_block(
    *,
    scope: str,
    perspective: str,
    extra: str = "",
) -> str:
    return f"""
## 概述

本页属于 **{scope}** 域的 **{perspective}** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

{extra}

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
""".strip()


def pilot_backend_datasets() -> None:
    category("backend/_category_.json", "后端视角", 1)
    category("backend/datasets/_category_.json", "数据集与目录", 2)

    md(
        "backend/welcome.md",
        "后端视角总览",
        tmpl_block(scope="全站", perspective="后端", extra="从此侧栏进入各业务域的后端契约、模块与配置说明。"),
        "总览",
        1,
    )

    blocks = [
        (
            "overview",
            "概述与边界",
            "说明数据集、分类、预检、画像、健康度、DB Catalog、表（TAG）等能力边界；非目标：不在此重复 OpenAPI 全量字段表。",
        ),
        (
            "api-index",
            "API 参考索引",
            "按 OpenAPI `tag` 对齐：在 Redoc 中筛选 **datasets** 及相关路径；关键 path 包括 `GET/POST /datasets/`、`GET /datasets/{{id}}`、`PATCH /datasets/{{id}}`、`DELETE /datasets/{{id}}` 等。",
        ),
        (
            "schemas",
            "请求与响应要点",
            "创建/更新数据集时的名称、描述、可见性、分类绑定等字段；分页列表的 `skip`/`limit` 与统一错误包格式。其余字段请直接查 `web/openapi.json` 或 Redoc。",
        ),
        (
            "state-jobs",
            "状态与任务",
            "数据集元数据与关联任务（若有异步预检/画像）在 UI 与 API 之间的刷新策略；长耗时操作建议轮询任务状态端点（以 OpenAPI 为准）。",
        ),
        (
            "permissions",
            "权限与安全",
            "租户隔离、数据集 ACL、管理端与普通用户可见性差异；勿在客户端伪造 `X-Tenant-ID`。",
        ),
        (
            "troubleshooting",
            "排障",
            "典型：列表为空（权限/租户）、更新 409（并发修改）、删除失败（仍存在文档绑定）。结合后端日志与 `docs/integration/FE_BE_DEBUG.md` 定位。",
        ),
        (
            "testing",
            "测试",
            "pytest 中与 datasets 相关的 API 用例；`scripts/api_smoke.py` 中涉及数据集的操作 ID（若有）。",
        ),
        (
            "precheck",
            "预检（Precheck）",
            "预检结果如何影响入库与质量门禁；相关 REST 路径以 OpenAPI 标签为准。",
        ),
        (
            "profile",
            "画像（Profile）",
            "数据集画像指标与存储；对接检索配置时的注意点。",
        ),
        (
            "health",
            "健康度（Health）",
            "健康检查聚合指标与健康策略在 API 层的暴露。",
        ),
        (
            "db-catalog",
            "DB Catalog",
            "外部数据库目录同步与元数据模型概要。",
        ),
        (
            "tables-tag",
            "表与 TAG",
            "表级资源与 TAG 维度的查询、绑定关系。",
        ),
    ]
    for i, (slug, title, detail) in enumerate(blocks, start=1):
        md(
            f"backend/datasets/{slug}.md",
            f"数据集 — {title}",
            tmpl_block(scope="数据集", perspective="后端", extra=detail),
            title,
            i,
        )


def pilot_backend_documents() -> None:
    category("backend/documents/_category_.json", "文档与入库", 3)
    blocks = [
        ("overview", "概述与边界", "上传、列表、状态、分块、解析文本、删除；连接器与入库 Run 见 ingestion 小节。"),
        ("api-index", "API 参考索引", "OpenAPI 标签 **documents**；含 `POST /documents/upload`、`GET /documents/{{id}}/status`、分块与解析内容等路径。"),
        ("schemas", "请求与响应要点", "multipart 上传、文档状态机 pending/processing/completed/failed；分页与错误码。"),
        ("state-jobs", "状态与任务", "解析与索引流水线异步阶段；轮询间隔与超时建议。"),
        ("permissions", "权限与安全", "文档级 ACL、租户隔离；敏感文件类型策略。"),
        ("troubleshooting", "排障", "卡住：解析器/队列/对象存储；参见部署与 observability 文档。"),
        ("testing", "测试", "API 与解析相关的 pytest / smoke 指针。"),
        ("connectors", "连接器", "外部源同步概念与配置入口（契约见 OpenAPI）。"),
        ("ingestion-runs", "入库 Run", "一次入库运行的生命周期与可观测字段。"),
        ("pipeline", "流水线阶段", "解析 → 分块 → 向量/索引各阶段在 API/元数据中的体现。"),
    ]
    for i, (slug, title, detail) in enumerate(blocks, start=1):
        md(
            f"backend/documents/{slug}.md",
            f"文档 — {title}",
            tmpl_block(scope="文档与入库", perspective="后端", extra=detail),
            title,
            i,
        )


def pilot_frontend_datasets() -> None:
    category("frontend/_category_.json", "前端视角", 1)
    category("frontend/datasets/_category_.json", "数据集与目录", 2)
    md(
        "frontend/welcome.md",
        "前端视角总览",
        tmpl_block(scope="全站", perspective="前端", extra="Next.js 路由、`web/lib/api/*` 调用与 UI 状态从此侧栏进入。"),
        "总览",
        1,
    )
    blocks = [
        ("overview", "用户路径与入口", "`web/app/datasets/**` 下列表、详情、预检、画像、健康、DB Catalog、表、工作流等页面；权限可见性随 RBAC 变化。"),
        ("api-client", "web/lib/api 模块", "`web/lib/api/datasets.ts` 等模块中的封装函数与类型；与 OpenAPI 字段对齐方式。"),
        ("state-ui", "状态与加载", "SWR/React Query（若使用）、乐观更新、分页与空态。"),
        ("errors", "错误处理", "统一 `ApiError` / toast；未知错误码参见仓库内 extract-errors 技能说明。"),
        ("feature-flags", "功能开关", "与 `@gate` / feature flag 相关的页面显隐。"),
        ("troubleshooting", "排障", "浏览器 Network、对比后端响应与 `docs/integration/FE_BE_DEBUG.md`。"),
        ("testing", "测试", "前端 lint/typecheck/ui-check；Playwright（若有）用例指针。"),
        ("precheck-ui", "预检界面", "预检结果展示与重试入口。"),
        ("profile-ui", "画像界面", "指标卡片与下钻。"),
        ("health-ui", "健康度界面", "健康策略与告警展示。"),
        ("catalog-ui", "DB Catalog 界面", "连接与对象浏览。"),
        ("tables-ui", "表 / TAG 界面", "表级操作与 TAG 过滤。"),
    ]
    for i, (slug, title, detail) in enumerate(blocks, start=1):
        md(
            f"frontend/datasets/{slug}.md",
            f"数据集（前端）— {title}",
            tmpl_block(scope="数据集", perspective="前端", extra=detail),
            title,
            i,
        )


def pilot_frontend_documents() -> None:
    category("frontend/documents/_category_.json", "文档与入库", 3)
    blocks = [
        ("overview", "用户路径与入口", "文档列表、上传、详情、解析预览；知识入库相关页面。"),
        ("api-client", "web/lib/api 模块", "`web/lib/api/documents.ts`、`connectors.ts`、`pipeline.ts` 等。"),
        ("state-ui", "状态与进度", "上传进度、文档状态轮询、取消。"),
        ("errors", "错误处理", "大文件、MIME、权限错误在 UI 的呈现。"),
        ("ingestion-ui", "入库 Run 界面", "运行历史与日志入口。"),
        ("troubleshooting", "排障", "CORS、Token、SSE（若涉及预览流）。"),
        ("testing", "测试", "组件与契约测试建议。"),
        ("connectors-ui", "连接器配置", "表单字段与校验。"),
    ]
    for i, (slug, title, detail) in enumerate(blocks, start=1):
        md(
            f"frontend/documents/{slug}.md",
            f"文档（前端）— {title}",
            tmpl_block(scope="文档与入库", perspective="前端", extra=detail),
            title,
            i,
        )


def pilot_integration() -> None:
    category("integration/_category_.json", "集成视角", 1)
    md(
        "integration/welcome.md",
        "集成与联调总览",
        tmpl_block(
            scope="全站",
            perspective="集成 / E2E",
            extra="端到端序列、环境变量、典型故障症状与定位路径；与仓库 `docs/integration/` 对齐。",
        ),
        "总览",
        1,
    )
    md(
        "integration/datasets/e2e.md",
        "数据集 — 典型 E2E 序列",
        """
```mermaid
sequenceDiagram
  participant U as 用户/客户端
  participant FE as Next.js
  participant API as FastAPI /api/v1
  participant DB as PostgreSQL
  U->>FE: 打开数据集列表
  FE->>API: GET /datasets/
  API->>DB: 查询可见数据集
  DB-->>API: rows
  API-->>FE: JSON
  FE-->>U: 渲染列表
```

## 环境变量

对齐后端 `.env` 与前端 `NEXT_PUBLIC_*`（参见仓库 `docs/deployment` 与 Settings 页说明）。

## 排障入口

- [FE_BE_DEBUG.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
- [API_CONTRACT.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
""".strip(),
        "数据集 E2E",
        2,
    )
    md(
        "integration/documents/e2e.md",
        "文档 — 典型 E2E 序列",
        """
```mermaid
sequenceDiagram
  participant U as 用户
  participant FE as Next.js
  participant API as FastAPI
  participant Store as 对象存储
  U->>FE: 选择文件上传
  FE->>API: POST /documents/upload (multipart)
  API->>Store: 保存对象
  API-->>FE: document id + pending
  loop 轮询
    FE->>API: GET /documents/{id}/status
    API-->>FE: processing / completed
  end
```

## 契约检查

上传字段名、Content-Type 与 OpenAPI 一致；异常体格式见 API 文档索引。
""".strip(),
        "文档 E2E",
        3,
    )
    write("integration/generated/.gitkeep", "")


def ops_pages() -> None:
    category("ops/_category_.json", "运维视角", 1)
    md(
        "ops/welcome.md",
        "运维总览",
        tmpl_block(
            scope="运维",
            perspective="Ops",
            extra="健康检查、元数据、可观测性、部署与 Runbook；深链仓库 `docs/deployment/runbook.md`。",
        ),
        "总览",
        1,
    )
    md(
        "ops/health-probes.md",
        "健康检查与探针",
        "`GET /health`、`GET /health/ready`；与 K8s 探针配置对齐。",
        "健康探针",
        2,
    )
    md(
        "ops/observability.md",
        "可观测性",
        "日志、指标、Tracing 入口；与 `web/lib/api/observability.ts` 及管理页对应。",
        "可观测性",
        3,
    )
    md(
        "ops/deployment.md",
        "部署与 Runbook",
        "参见 [runbook.md](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/runbook.md) 与 Docker/Helm 说明。",
        "部署",
        4,
    )
    md(
        "ops/settings-meta.md",
        "设置与 Meta API",
        "系统设置、功能开关、meta 端点；生产变更需变更流程。",
        "设置 / Meta",
        5,
    )


def phase2_backend_stubs() -> None:
    category("backend/more/_category_.json", "其余业务域（概要）", 99)
    stubs = [
        ("platform", "平台与账号", "Auth、Groups、RBAC、SCIM、Usage、Audit。"),
        ("parsing", "解析与切块", "Parsing Workspace、解析器运维；链到 `docs/guides`。"),
        ("retrieval", "检索与 RAG", "检索配置、RAGViz、LTR；链到 retrieval 相关 guides。"),
        ("chat", "对话与模板", "Chat、Prompt / RAG 配置模板。"),
        ("evidence", "证据与可解释性", "Evidence Workbench、Capsules、Reports。"),
        ("kg", "知识图谱", "KG API 与 Web 图谱页。"),
        ("evaluations", "评测与反馈", "Evaluations、Feedback、Ablations。"),
        ("governance", "治理与合规", "Governance、隔离与数据治理面板。"),
    ]
    for i, (slug, title, detail) in enumerate(stubs, start=1):
        md(
            f"backend/more/{slug}.md",
            title,
            tmpl_block(scope=title, perspective="后端", extra=detail + " 详细子页将随版本迭代补充。"),
            title,
            i,
        )


def phase2_frontend_stubs() -> None:
    category("frontend/more/_category_.json", "其余业务域（概要）", 99)
    stubs = [
        ("platform", "平台与账号", "登录、设置、审计与用量页面路由概要。"),
        ("parsing", "解析工作台", "`web/app` 下解析/预览相关路由。"),
        ("retrieval", "检索与 RAG", "检索调试与可视化入口。"),
        ("chat", "对话", "聊天区组件与模板选择。"),
        ("evidence", "证据工作台", "证据与报告页面。"),
        ("kg", "知识图谱", "图谱诊断与数据集 KG 工作台。"),
        ("evaluations", "评测", "评测列表与实验。"),
        ("governance", "治理", "治理与通用行页面。"),
    ]
    for i, (slug, title, detail) in enumerate(stubs, start=1):
        md(
            f"frontend/more/{slug}.md",
            title,
            tmpl_block(scope=title, perspective="前端", extra=detail),
            title,
            i,
        )


def phase2_integration_stubs() -> None:
    category("integration/more/_category_.json", "更多集成场景", 99)
    md(
        "integration/more/rag-flow.md",
        "RAG 端到端数据流",
        "从入库、索引到对话检索的序列图占位；可扩展为与 `docs/architecture.md` 一致的 Mermaid。",
        "RAG 数据流",
        1,
    )
    md(
        "integration/more/auth-flow.md",
        "认证与租户上下文",
        "JWT 与 Header 调试模式；租户注入与越权案例简述。",
        "认证 / 租户",
        2,
    )
    category("integration/scenarios/_category_.json", "场景速查（占位扩展）", 40)
    scenarios = [
        ("s01-upload-chat", "上传后对话", "最小路径：注册/登录 → 上传 → 等状态 → chat stream。"),
        ("s02-dataset-rag", "数据集绑定 RAG", "创建数据集、绑定文档、对话时指定数据集上下文。"),
        ("s03-precheck-block", "预检拦截", "预检失败时的 API 与 UI 反馈。"),
        ("s04-retrieval-debug", "检索调试", "explain / trace 与 FE_BE_DEBUG 路径。"),
        ("s05-kg-trigger", "触发 KG 抽取", "抽取任务与图谱查询的先后关系。"),
        ("s06-evidence-export", "证据导出", "Evidence → Report 链路概要。"),
        ("s07-eval-job", "评测任务", "创建评测、拉取指标、回归门槛。"),
        ("s08-feedback-loop", "反馈闭环", "Hardcase → Evidence 草稿。"),
        ("s09-governance-quarantine", "治理与隔离", "隔离区与审批流在 API 层的触点。"),
        ("s10-scim-sync", "SCIM 同步", "IdP 与租户用户同步注意点。"),
        ("s11-usage-audit", "用量与审计", "usage 与 audit 日志对账。"),
        ("s12-parsing-workspace", "解析工作台", "解析预览与解析器选择。"),
        ("s13-pipeline-preview", "管道预览", "分块/清洗预览与落库差异。"),
        ("s14-multi-tenant", "多租户隔离", "Header 与 JWT 下的租户边界测试清单。"),
        ("s15-sse-reconnect", "SSE 重连", "流式对话断线重连与幂等。"),
    ]
    for i, (slug, title, detail) in enumerate(scenarios, start=1):
        md(
            f"integration/scenarios/{slug}.md",
            f"场景 — {title}",
            tmpl_block(scope="集成", perspective="E2E", extra=detail),
            title,
            i,
        )


def integration_patterns_real() -> None:
    """Named integration reference pages (replaces former p01–p40 placeholders)."""
    category("integration/patterns/_category_.json", "集成模式速查", 50)

    def page(slug: str, title: str, sidebar: str, pos: int, extra: str) -> None:
        body = tmpl_block(scope="集成", perspective="联调模式", extra=extra)
        md(f"integration/patterns/{slug}.md", title, body, sidebar, pos)

    page(
        "errors-4xx-5xx",
        "HTTP 4xx/5xx 与错误体",
        "错误码与响应体",
        1,
        """
## 阅读顺序

1. 看 **HTTP 状态码** 与响应 JSON 中的业务 `code` / `detail`（以 OpenAPI `ErrorResponse` 或实际返回为准）。
2. 对照 [FE_BE_DEBUG](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md) 中的 Network / 后端日志路径。

## 常见映射（经验）

| 症状 | 优先怀疑 |
|------|----------|
| 401 | 未带或过期 `Authorization: Bearer`；时钟漂移 |
| 403 | 租户/数据集 ACL；功能开关 |
| 404 | 路径或资源 ID 错误；租户下不可见 |
| 409 | 并发更新、唯一约束、非法状态迁移 |
| 422 | Pydantic 校验失败；检查请求体字段名与类型 |
| 429 / 503 | 限流或依赖不可用；退避重试 |

## 前端

未知业务码时参考仓库内 **extract-errors** 技能，避免静默吞错。
""".strip(),
    )
    page(
        "auth-modes",
        "认证方式：JWT 与 Header 调试",
        "认证",
        2,
        """
## JWT（推荐）

- 登录/注册见 OpenAPI **auth** 分组；后续请求头：`Authorization: Bearer <access_token>`。
- Token 过期：刷新策略以前端实现与 OpenAPI 为准。

## Header 调试模式（仅开发）

- 部分部署允许 `X-User-ID` / `X-Tenant-ID` 等（见后端中间件与 [API_CONTRACT](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)）。
- **禁止**在生产客户端伪造租户头；生产务必走正式认证。

## 联调检查清单

- [ ] `Content-Type: application/json`（JSON 接口）
- [ ] Bearer 前缀与空格
- [ ] 与 Redoc 示例字段名一致（蛇形/驼峰以前端生成类型为准）
""".strip(),
    )
    page(
        "tenant-headers",
        "租户与可见性边界",
        "租户 / 可见性",
        3,
        """
## 原则

- 多租户下，资源列表与单资源 GET 均受 **租户 + ACL** 约束；404 有时表示「不可见」而非不存在。

## 联调

- 用同一 Token 分别请求列表与详情，确认 `dataset_id` / `document_id` 属于当前租户。
- 管理端与普通用户可见集合可能不同；对照 OpenAPI 上 **依赖与 scope 说明**。

## 文档

- [API_CONTRACT.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
""".strip(),
    )
    page(
        "pagination",
        "列表分页与查询参数",
        "分页",
        4,
        """
## 常见约定

- 多数列表支持 `skip`、`limit`（或 `offset`/`page`，以 OpenAPI 为准）。
- 默认值与上限以 Redoc 中参数说明为准；超出上限可能 422。

## 前端

- 表格翻页时避免在路由中丢失 `limit`；大页 deep link 注意 URL 长度。

## 集成测试

- 断言总数与当前页条数；空列表与最后一页边界。
""".strip(),
    )
    page(
        "multipart-upload",
        "上传：multipart 与预签名",
        "上传",
        5,
        """
## multipart

- 文档上传常用 `multipart/form-data`；字段名须与 OpenAPI **documents** 一致（如 `file`）。
- 体积限制受反向代理与后端配置双重约束。

## 预签名 / 批量

- 若使用 `upload-url`、`batch-upload` 等路径，按 OpenAPI 顺序：申请 URL → 直传对象存储 → 回调/确认（见具体 operation）。

## 排障

- 415 / 400：MIME 与字段名；参见 [FE_BE_DEBUG](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)。
""".strip(),
    )
    page(
        "sse-streaming",
        "SSE 与流式对话",
        "SSE / 流式",
        6,
        """
## 约定

- 流式对话多为 **SSE**（`text/event-stream`）；浏览器用 `EventSource` 或 fetch 流式读取。
- 代理层需 **禁用缓冲**（如 nginx `proxy_buffering off`），否则客户端迟迟收不到分片。

## 客户端

- 实现 **AbortController** 或等价取消，避免页面切换后仍占用连接。
- 断线重连：记录 last event id（若服务端支持）或幂等地新建会话（产品策略为准）。

## 相关

- 仓库 `docs/API.md` 拆分文中「SSE」章节；OpenAPI **chat** 分组。
""".strip(),
    )
    page(
        "idempotency-retries",
        "重试、幂等与重复提交",
        "重试 / 幂等",
        7,
        """
## 重试

- **仅对幂等或带幂等键的请求重试**：GET、PUT 覆盖、显式 `Idempotency-Key`（若 API 支持）。
- POST 创建类默认 **非幂等**；盲目重试可能导致重复资源。

## 退避

- 429/503 使用指数退避 + 抖动；设置最大重试次数。

## 与 UI

- 提交按钮 loading 防双击；失败后可安全重试的场景在集成文档中写明。
""".strip(),
    )
    page(
        "env-matrix",
        "环境变量索引（导读）",
        "环境变量导读",
        8,
        """
## 后端

- 根目录 [`.env.example`](https://github.com/skygazer42/MimirQ/blob/main/.env.example) 是完整环境变量模板；本地启动可复制为 `.env`，部署说明见 [docker_compose](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md)。

## 前端

- `NEXT_PUBLIC_*` 在 [web/lib/env](https://github.com/skygazer42/MimirQ/tree/main/web/lib) 及相关构建说明中消费；修改后需重新构建。

## 联调

- 同一浏览器会话中，前端 base URL 与后端实际 origin 必须一致，避免 CORS 与错误端口。
""".strip(),
    )
    page(
        "openapi-contract-check",
        "OpenAPI 与前端调用对照",
        "契约对照",
        9,
        """
## SSOT

- **路径与模型** 以 `web/openapi.json` / Redoc 为准；前端 `web/lib/api/*.ts` 应对齐生成的类型与 path。

## 日常检查

- 改后端路由后执行 `make openapi-export` 与前端 `gen:api-types`（以 Makefile / package.json 脚本为准）。
- 自动化对照见 [API_CONTRACT.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)。

## 手册内矩阵

- [FE/BE 对照矩阵（自动生成）](../generated/fe-be-matrix.mdx)
""".strip(),
    )
    page(
        "observability-requests",
        "请求关联：日志与排障",
        "可观测性",
        10,
        """
## 后端

- 关注结构化日志中的 `request_id` / 租户 / 用户字段（以后端实现为准）。

## 前端

- 在开发环境对失败请求记录 **path + status + 响应体摘要**（注意脱敏）。

## 运维

- 健康检查：`GET /api/v1/health`、`GET /api/v1/health/ready`（见 OpenAPI **health**）；与 K8s 探针配置对齐。
""".strip(),
    )


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    pilot_backend_datasets()
    pilot_backend_documents()
    pilot_frontend_datasets()
    pilot_frontend_documents()
    pilot_integration()
    ops_pages()
    phase2_backend_stubs()
    phase2_frontend_stubs()
    phase2_integration_stubs()
    integration_patterns_real()
    print("Wrote handbook under", DOCS)


# NOTE: 手册正文以 Git 中 docs-site/docs 为 SSOT；本脚本用于脚手架/重置。
# 重新运行 main() 会覆盖由本文件生成的页面；核心域深度内容请在提交后优先直接编辑 Markdown。


if __name__ == "__main__":
    main()
