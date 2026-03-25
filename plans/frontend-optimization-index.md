# MimirQ 前端优化 — 实施计划索引

> 基于 `plans/frontend-audit.md` 审查报告，按影响度 × 实施难度排序的 4 批实施计划。

## 计划文件

| 文件 | 批次 | 内容 | Task 数 |
|------|------|------|---------|
| [`batch-1-security-performance.md`](./batch-1-security-performance.md) | 第一批 | 安全 + 性能 | 3 |
| [`batch-2-architecture.md`](./batch-2-architecture.md) | 第二批 | 架构治理 | 3 |
| [`batch-3-code-quality.md`](./batch-3-code-quality.md) | 第三批 | 代码质量 | 4 |
| [`batch-4-long-term.md`](./batch-4-long-term.md) | 第四批 | 长期改善 | 5 |

## 实施顺序与依赖关系

```
第一批（独立，可并行）
├── Task 1.1: 修复图片 Auth Token 泄露
├── Task 1.2: 移动全局 CSS 和 Provider
└── Task 1.3: 大型库按需加载 (recharts)

第二批（部分有依赖）
├── Task 2.1: 拆分 api-client.ts ←── Task 2.3E (extractRateLimitDetail) 一起做
├── Task 2.2: 统一 TanStack Query（依赖 2.1 完成后的 API 模块）
└── Task 2.3: 消除代码重复（A-F 子项独立）

第三批（依赖第二批）
├── Task 3.1: 拆分大型组件（独立于其他）
├── Task 3.2: 拆分大型 Hooks（与 2.2 Query 迁移协同）
├── Task 3.3: 类型安全提升（与 2.1 类型移动协同）
└── Task 3.4: 补充 loading.tsx / error.tsx（依赖 2.3B RouteError 组件）

第四批（独立，随时可做）
├── Task 4.1: 删除遗留代码
├── Task 4.2: 测试覆盖提升
├── Task 4.3: 可访问性改善
├── Task 4.4: 国际化准备
└── Task 4.5: 其他小项
```

## 每批次预估 PR 策略

- **第一批**：3 个独立 PR，可同时 review
- **第二批**：建议 2 个 PR（2.1+2.3E 合并；2.2+2.3 其余合并）
- **第三批**：建议 4 个 PR（每个 Task 一个）
- **第四批**：建议按子项提 PR，避免单次变更过大

## 验证命令

每个 PR 合并前必须通过：

```bash
cd web
pnpm lint        # ESLint
pnpm typecheck   # TypeScript
pnpm test        # Vitest
pnpm build       # Next.js build
```
