# Global UI Consistency + API Integration (Design Notes)

**Date:** 2026-02-04

## Goal

在不大改信息架构/整体布局的前提下（中等力度），统一全局交互与视觉基线：
- 导航（Navbar）选中态/可达性更清晰
- 全局浮层/固定元素遵守 safe-area，避免遮挡
- 常用控件（SearchInput / EmptyState / Button / Popover / DropdownMenu）在圆角、阴影、聚焦态上更一致
- 跟后端接口联调：本地 docker backend 可一键拉起，前端能稳定 ping 通健康/就绪接口

## Direction (Interface Design)

**Who:** 主要是工程师/数据团队在本地或内网环境使用的“知识库 + RAG 工具台”，操作频率高、信息密度中等、对可预期与稳定反馈敏感。

**Feel:** 冷静、克制、工具感（Calm & Precise）。不追求强装饰，强调清晰层级与稳定交互。

**Signature:** “token-first surfaces” —— 统一用语义 token（`bg-card/bg-background/border-border/shadow-soft/shadow-strong`）构建层级，交互反馈只做必要、短促（<=200ms），避免花哨动效。

**Rejecting defaults:**
- 拒绝不带 safe-area 的 fixed 浮层按钮（移动端/有刘海设备易遮挡）
- 拒绝 Popover/Dropdown 使用杂乱阴影等级（`shadow-md`/`shadow-lg` 混用）导致层级不稳定
- 拒绝散落的“自定义搜索框”实现（重复 icon/clear/focus 逻辑），统一到 `SearchInput`

## Baseline UI Constraints

- token 优先；不引入渐变、紫色/多色渐变、发光作为主可点击暗示
- 不新增动画（除非必要）；仅动 `transform/opacity`；交互反馈 <= 200ms；尊重 `prefers-reduced-motion`
- 固定元素必须考虑 `env(safe-area-inset-*)`
- 空状态必须给出明确下一步行动（可通过 `EmptyState` children 提供）

## Backend Integration Notes

- 以 `make init && make up` 拉起 FastAPI + 依赖（Postgres/Milvus/Redis/MinIO）
- 用 `pnpm -C web run api-ping` 校验 `GET /api/v1/health`、`/health/ready`、`/meta`

