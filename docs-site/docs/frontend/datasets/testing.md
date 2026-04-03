---
sidebar_label: "测试"
sidebar_position: 7
---

# 数据集 — 测试

## 测试框架

| 工具 | 用途 | 配置 |
|------|------|------|
| **Vitest** | 单元测试 / 组件测试 | `vitest.config.ts` |
| **pnpm test** | 运行全部测试 | CI 中执行 |
| **pnpm typecheck** | TypeScript 类型检查 | `tsconfig.json` |
| **pnpm lint** | ESLint 静态检查 | `.eslintrc` |

## 数据集模块测试文件

| 测试文件 | 覆盖范围 |
|----------|----------|
| `datasets-page.source.test.ts` | DatasetsPage 组件核心逻辑 |
| `datasets-page.entry.test.ts` | 页面入口渲染 |
| `datasets.header.source.test.ts` | 数据集页头部 |
| `category-tree.test.ts` | 分类树增删改查、拖拽 |
| `category-multi-select.source.test.ts` | 分类多选组件 |
| `dataset-kg-workbench-page.source.test.ts` | KG 工作台页 |

## 测试模式

- **Source Test** (`*.source.test.ts`): 导入源码模块，mock API 层，验证业务逻辑
- **Behavior Test** (`*.test.ts`): 更偏集成，测试组件交互行为
- **API Mock**: 通过 `vi.mock('@/lib/api')` 统一 mock API 模块

## Mock 示例

```typescript
// 典型 API mock 写法
vi.mock('@/lib/api', () => ({
  datasetApi: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    get: vi.fn().mockResolvedValue({ id: 'test-id', name: 'Test' }),
  },
}));
```

:::info
运行数据集相关测试：`pnpm test -- --grep datasets`
:::

:::tip
编写新测试时优先使用 Source Test 模式。Source Test 直接导入被测模块，执行速度更快且更容易定位问题。
:::

## 运行方式

```bash
# 运行所有数据集测试
pnpm test -- --grep datasets

# 运行单个测试文件
pnpm test -- category-tree.test.ts

# 带覆盖率运行
pnpm test -- --coverage --grep datasets
```

## 相关链接

- [排障](./troubleshooting) — 测试失败排查
- [后端 · 数据集测试](../../backend/datasets/testing.md) — 后端测试策略
