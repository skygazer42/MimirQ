---
sidebar_label: "测试"
sidebar_position: 7
---

# 文档管理 — 测试

## 测试文件索引

| 测试文件 | 覆盖范围 |
|----------|----------|
| `knowledge-page.left-panel.test.ts` | 左侧筛选面板 |
| `knowledge-page.left-panel.scope.test.ts` | Scope 筛选逻辑 |
| `knowledge-documents-panel.source.test.ts` | 文档列表核心逻辑 |
| `knowledge-documents-panel.batch-delete.source.test.ts` | 批量删除 |
| `knowledge-documents-panel.row-actions.source.test.ts` | 行操作菜单 |
| `knowledge-page.embedded-workbench.source.test.ts` | 嵌入式工作台 |
| `manual-upload-dialog.source.test.ts` | 手动上传弹窗 |
| `document-detail-dialog.source.test.ts` | 文档详情弹窗 |
| `document-viewer-panel.source.test.ts` | 文档查看器 |
| `document-viewer-panel.safe-area.test.ts` | 查看器安全区域 |

## 测试模式

- **Source Test**: 导入源码模块、mock API，测试业务逻辑
- **Safe-area Test**: 测试响应式布局在不同尺寸下的表现
- **Behavior Test**: 测试用户交互流程

## Mock 策略

```typescript
// 典型 documentApi mock
vi.mock('@/lib/api', () => ({
  documentApi: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    get: vi.fn().mockResolvedValue({ id: 'doc-1', status: 'completed' }),
    batchDelete: vi.fn().mockResolvedValue({ success: 2, failed: 0 }),
  },
}));
```

## 运行方式

```bash
# 运行文档相关测试
pnpm test -- --grep knowledge

# 运行单个文件
pnpm test -- knowledge-documents-panel.source.test.ts
```

:::info
文档模块测试密度较高，单文件如 `knowledge-documents-panel` 有多个独立测试文件分别覆盖不同功能维度。
:::

:::tip
新增组件时建议同步编写 Source Test，确保核心逻辑有覆盖。测试命名规范：`{component-name}.source.test.ts`。
:::

## 相关链接

- [排障](./troubleshooting) — 测试失败排查
- [后端 · 文档测试](../../backend/documents/testing.md) — 后端测试策略
