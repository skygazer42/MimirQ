# 第四批：长期改善

> 对应审查项 #10（遗留代码）、#11（测试）、#12（可访问性）、#13（i18n）、#14（其他小项）

---

## Task 4.1 — 删除遗留代码（#10）

### A. 删除 `hooks/use-parsed-files.ts`

**现状**：
- `hooks/use-parsed-files.ts` — 128 行，旧版本
- `store/use-parsed-files-store.ts` — 343 行，Zustand 版本，功能更完整

**引用检查结果**：
经代码搜索确认：**零个生产代码文件**引用 `hooks/use-parsed-files`。唯一的引用在 `lib/security-hotspots.source.test.ts` 测试文件中。所有生产组件均已迁移到 `store/use-parsed-files-store.ts`。

**操作**：
1. ~~检查每个引用文件~~ → 已确认无生产引用
2. 删除 `hooks/use-parsed-files.ts`
3. 更新 `lib/security-hotspots.source.test.ts` 中的引用（如有必要）

### B. 合并或扩展 `services/` 目录

**现状**：`web/services/` 仅含 `graph-service.ts` 和 `graph-service.source.test.ts`。

**选项**：
- **方案 A**：将 `graph-service.ts` 移到 `lib/graph-service.ts`，删除 `services/` 目录
- **方案 B**：保留 `services/` 目录，后续将 api-client 拆分出的部分业务逻辑放入

**建议**：方案 A，保持代码库简洁。

### C. 修复 Tailwind content 无效路径

**文件**：`web/tailwind.config.ts`

content 配置中存在两个无效路径：
- `'./src/**/*.{ts,tsx}'` — 项目无 `src/` 目录，应删除
- `'./pages/**/*.{ts,tsx}'` — 项目使用 App Router（`app/` 目录），无 `pages/` 目录，应删除

仅保留有效的 content 路径（`./app/**`, `./components/**`, `./lib/**` 等）。

### D. 删除重复的 blink keyframe

搜索 `blink` keyframe 在 `tailwind.config.ts` 和 `globals.css` 中的定义，仅保留一处。

### 验证点

- `pnpm typecheck && pnpm lint && pnpm test && pnpm build`

---

## Task 4.2 — 测试覆盖提升（#11）

### 现状

- Hooks 仅 2/12 有测试（`use-auth`, `use-documents`）
- Stores 仅 1 个测试文件
- Contexts 仅 1 个测试
- 覆盖率阈值：statements 40%, branches 30%
- Vitest 环境为 `node`（非 `jsdom`）

### 优先补充的测试

#### A. `use-chat.ts` 行为测试

```
hooks/__tests__/use-chat.test.ts
```

测试用例：
- 发送消息后正确更新消息列表
- SSE 流式接收 token 事件正确拼接
- 网络错误时正确触发 error 回调
- AbortController 超时取消
- 非流式 fallback 路径

#### B. `use-documents.ts` 行为测试补充

现有测试可能为结构检查，补充：
- 上传成功/失败场景
- 批量上传进度跟踪
- 轮询状态更新

#### C. API client 单元测试

拆分后的 API 模块更容易测试：
- 每个 API namespace 的基本请求格式
- 错误处理（429 rate limit、401 unauthorized）
- SSE 流解析

#### D. Query key 工厂测试

```
lib/__tests__/query-keys.test.ts
```

确保 query key 格式正确、不冲突。

### 考虑将 Vitest 环境切换为 jsdom

如需测试包含 React hooks 的行为（`renderHook`），需要 DOM 环境：

```ts
// vitest.config.ts
export default defineConfig({
  test: {
    environment: 'jsdom', // 或使用 per-file 注释 // @vitest-environment jsdom
  },
})
```

### 验证点

- `pnpm test` — 所有新测试通过
- 覆盖率不低于现有阈值

---

## Task 4.3 — 可访问性改善（#12）

### 优先修复项

#### A. 表格添加 aria 标签

`app/evaluations/page.tsx` 中的 `<table>` 添加：
```tsx
<table aria-label="评测结果列表">
```

搜索所有 `<table` 标签，确保都有 `aria-label` 或 `<caption>`。

#### B. Tab 组件使用正确的 ARIA 角色

搜索使用 `<Button>` 实现 tab 切换的地方，替换为正确的 ARIA 模式：

```tsx
<div role="tablist">
  <button role="tab" aria-selected={active === 'a'} ...>Tab A</button>
  <button role="tab" aria-selected={active === 'b'} ...>Tab B</button>
</div>
<div role="tabpanel">...</div>
```

> 注：如果使用 shadcn/ui 的 Tabs 组件，确认其已内置正确的 ARIA 角色。

### 已有良好实践（保持）

- skip link
- `aria-live="polite"` skeleton
- `inert` focus trapping
- `motion-reduce` 支持

---

## Task 4.4 — 国际化准备（#13）

### 现状

- 无 i18n 框架
- 中文字符串硬编码在组件中
- 部分错误信息是英文

### 最小化方案（不引入 i18n 框架）

1. **新建 `web/lib/messages.ts`** — 集中管理用户可见字符串：

```ts
export const messages = {
  common: {
    loading: '加载中...',
    error: '发生错误',
    retry: '重试',
    cancel: '取消',
    save: '保存',
    delete: '删除',
    confirm: '确认',
    backToHome: '返回首页',
  },
  auth: {
    loginRequired: '请先登录',
    loginFailed: '登录失败',
    // ...
  },
  documents: {
    uploadSuccess: '上传成功',
    uploadFailed: '上传失败',
    deleteConfirm: '确认删除此文档？',
    // ...
  },
  // ... 按领域组织
} as const
```

2. 逐步将硬编码字符串替换为 `messages.xxx.xxx` 引用
3. 统一中英文不一致的错误信息

> 此任务工作量大，建议作为持续改进项，不在一个 PR 中完成。

---

## Task 4.5 — 其他小项（#14）

### A. `lib/event-bus.ts` 类型安全

将 `payload: any` 改为类型安全的泛型 map：

```ts
type EventMap = {
  'document:uploaded': { documentId: string }
  'chat:message': { conversationId: string; messageId: string }
  // ...
}

class TypedEventBus {
  emit<K extends keyof EventMap>(event: K, payload: EventMap[K]): void { ... }
  on<K extends keyof EventMap>(event: K, handler: (payload: EventMap[K]) => void): () => void { ... }
}
```

### B. ESLint Hooks 规则

检查 `.eslintrc.json` 或 `eslint.config.js` 中被禁用的 3 条 React Hooks 规则，评估是否可以逐步启用并修复违规代码。

### C. `lib/auth-headers.ts:31` 默认 demo 用户

```ts
// 当前：无 JWT 时 X-User-ID 默认 'demo'
// 风险：生产环境不应有默认用户 ID
```

**操作**：添加环境变量检查，仅在开发模式下使用默认值：

```ts
const defaultUserId = process.env.NODE_ENV === 'development' ? 'demo' : undefined
```

### D. blink keyframe 去重

（已在 Task 4.1D 中处理）

### 验证点

- `pnpm typecheck && pnpm lint && pnpm test && pnpm build`

---

## 验证清单（全部批次完成后）

```bash
cd web
pnpm lint          # 无新 ESLint 错误
pnpm typecheck     # TypeScript 编译通过
pnpm test          # 所有测试通过
pnpm build         # Next.js 构建成功
```

手动验证关键页面：
- [ ] 首页对话 — 消息发送/接收/流式
- [ ] 知识库列表 — 文档上传/删除
- [ ] 文档解析 — 文件上传/解析/预览
- [ ] 图谱可视化 — 图谱加载/搜索/展开
- [ ] 设置页 — 各 section 保存
- [ ] Evaluations — 列表/详情
