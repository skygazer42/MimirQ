# MimirQ 前端 UI/UX/工程质量深度审计

> 审计日期：2026-03-24
> 基于对 web/ 目录下 366 个源文件（~139,000 行）的系统性分析

---

## 一、做得好的地方（值得保留的优势）

### 设计系统：A 级

- **shadcn/ui + Radix UI + CVA**：54 个基础 UI 组件，变体管理规范
- **HSL 语义色彩体系**：完整的 CSS 变量 + 暗色模式，每个语义色都有 light/dark 对应值
- **自动化守卫**：
  - `scripts/check-design-tokens.mjs` — 禁止原始 Tailwind 颜色类（`bg-white`、`text-cyan-400`）
  - `scripts/check-native-dialogs.mjs` — 禁止 `confirm()`/`prompt()`
  - a11y 测试文件强制使用原生 `<button>` 而非 `div[role="button"]`
- **页面布局组合系统**：`PageScaffold` / `PageHeader` / `PageBody` / `PageContainer` 在 27+ 页面中统一使用

### 无障碍（Accessibility）：A- 级

- `motion-reduce:animate-none` 覆盖 103 个文件（347 处）
- Sidebar 有完整的焦点管理（`inert`、Escape 关闭、焦点恢复）
- `IconButton` 强制要求 `label` prop，自动渲染 `aria-label` + `sr-only`
- `aria-current="page"` 在导航激活项上
- `aria-live="polite"` + `role="status"` 在加载状态上
- Cmd+K 命令面板（基于 `cmdk`）

### 状态管理：A- 级

- 清晰的三层分离：
  - 服务端数据 → TanStack React Query（10s stale time，智能重试）
  - 复杂持久化客户端状态 → Zustand（localStorage + IndexedDB，含迁移逻辑）
  - 配置/偏好 → React Context（含跨 tab 同步）

### 依赖健康度：A- 级

- Next.js 16、React 19、TypeScript 5.9、Vitest 4.1 — 全部最新
- 无 moment.js、无完整 lodash、无过时框架
- OpenAPI 类型自动生成（`openapi-typescript`）+ 契约校验脚本

---

## 二、严重问题（Critical）

### 2.1 巨型组件（God Components）

**影响**：可维护性、bundle 大小、首屏性能

| 文件 | 行数 | useState 数 | useEffect 数 |
|------|------|------------|-------------|
| `lib/api-client.ts` | **4,261** | - | - |
| `components/parsing/parsing-page.tsx` | **2,883** | 大量 | 大量 |
| `app/graph/page.tsx` | **2,872** | **69** | **11** |
| `components/evidence/evidence-suite-workbench.tsx` | **2,579** | 大量 | 大量 |
| `app/settings/page.tsx` | **2,356** | **22** | 大量 |
| `components/document-detail-dialog.tsx` | 1,909 | - | - |
| `components/ragviz/similarity-workbench.tsx` | 1,715 | - | - |
| `app/datasets/[id]/profile/page.tsx` | 1,659 | - | - |
| `app/datasets/[id]/ingestion/page.tsx` | 1,446 | - | - |
| `app/datasets/[id]/precheck/page.tsx` | 1,436 | **28** | - |

`graph/page.tsx` 的 69 个 `useState` 尤其触目惊心——这是一个试图管理图谱渲染、搜索、筛选、布局切换、统计面板、RAG trace 集成等所有逻辑的超级组件。

**建议**：
- `api-client.ts` → 按领域拆分（documents、datasets、knowledge、evidence、evaluation 等模块）
- 页面组件 → 提取 custom hooks（`useGraphState`、`useGraphLayout`）+ 子组件拆分
- 设定规范：单文件不超过 500 行

### 2.2 无表单库、无客户端校验

**影响**：数据质量、用户体验

全项目 **零** `react-hook-form`、`formik`、`zod`、`yup` 使用。所有表单用原始 `useState` 管理。

典型案例——`datasets/[id]/db-catalog/page.tsx` 的数据库同步表单用了 **13 个独立 useState**：
```
syncHost, syncPort, syncDatabase, syncUsername, syncPassword,
syncIncludeSchemas, syncIncludeTables, syncMaxTables,
syncProfileEnabled, syncSubmitting, syncError, syncConnectorId, syncOpen
```

- 无字段级错误提示
- 无必填指示
- 无客户端校验（port 类型检查是唯一的运行时校验）
- 密码字段成功后被清空但无 UX 反馈

**建议**：
- 引入 `react-hook-form` + `zod` 组合
- 从最复杂的表单开始迁移（settings、db-catalog、ingestion）
- 建立 `FormField` / `FormItem` / `FormMessage` 等 shadcn/ui 表单组件

### 2.3 无嵌套 Loading/Error 边界

**影响**：用户体验、错误恢复

- **全 app 仅 1 个 `loading.tsx`**（根级别）：46 个页面共享同一个骨架屏
- **全 app 仅 1 个 `error.tsx`**（根级别）：任何页面崩溃 → 整个 app 显示错误页，失去所有导航上下文
- 仅 2 个页面使用 `<Suspense>`（`history` 和 `evaluations`）
- error.tsx 只 `console.error`，**无 Sentry/DataDog 等错误上报**

**建议**：
- 为 `datasets/[id]/`、`graph/`、`knowledge/` 等路由段添加 `loading.tsx` 和 `error.tsx`
- 在重要页面内使用 `<Suspense>` + `ErrorBoundary` 实现局部加载/错误
- 集成错误上报服务

### 2.4 全页面客户端渲染

**影响**：首屏性能、SEO

- **46 个页面中 45 个是 `'use client'`**（直接或通过 re-export）
- 唯一的 Server Component 是根 `page.tsx`
- 零 Server-Side Rendering、零 Streaming、零 Progressive Enhancement
- 意味着所有页面 JS 必须下载+解析后才能渲染

**建议**：
- 评估哪些页面可以改为 Server Component 或混合模式
- 至少为数据展示页面（settings、observability、usage）启用 SSR
- 利用 Next.js 16 的 RSC streaming 能力

---

## 三、高优先级问题（High）

### 3.1 国际化（i18n）完全缺失

**影响**：开源后的国际化扩展

- **零 i18n 基础设施**：无 `next-intl`、`react-i18next`、`formatjs`
- **所有用户可见文字硬编码为中文**：
  - 导航："知识库"、"上传文档"、"快速搜索文档..."
  - 状态："等待"、"处理中"、"已完成"、"失败"
  - 对话框："删除文档？"、"此操作不可撤销"
  - 时间："天前"、"小时前"、"分钟前"、"刚刚"
- `html lang="zh-CN"` 硬编码

**建议**：
- 作为开源项目，至少需要中英文双语支持
- 推荐引入 `next-intl`（与 Next.js App Router 集成最好）
- 这是工作量很大的一项（需提取数百个字符串），建议尽早开始

### 3.2 移动端适配不足

**影响**：移动端用户体验

- 46 个页面文件中仅 **137 处**响应式类（`sm:`、`md:`、`lg:`）
- 无共享 `useMediaQuery` hook（各组件各自实现 `window.matchMedia`，断点不一致）
- 数据密集型页面（graph、db-catalog、tables、similarity-workbench）**零移动端适配**
- 图谱可视化、SQL 查询界面、分屏布局在小屏上会溢出或不可用

**建议**：
- 建立共享 `useMediaQuery` / `useIsMobile` hook
- 对核心页面（chat、knowledge、datasets 列表）优先做响应式
- 对工具型页面（graph、similarity）接受"桌面端优先"但加友好提示

### 3.3 缺失的空状态

**影响**：用户体验一致性

有 `EmptyState` 组件但多个页面未使用：

| 页面 | 现状 |
|------|------|
| `settings/page.tsx` | 设置加载失败时无提示 |
| `settings/rbac/page.tsx` | 显示纯文本"没有成员或无权限" |
| `settings/groups/page.tsx` | 显示纯文本"暂无组（或无权限）" |
| `audit/page.tsx` | 无审计日志时无空状态 |
| `usage/page.tsx` | 使用数据为空时无空状态 |
| `diagnostics/page.tsx` | 无空状态 |
| `prompts/page.tsx` | 提示词列表为空时无空状态 |

### 3.4 无面包屑导航

**影响**：深层路由的用户定位

- 全项目无面包屑组件
- 深层路由如 `/datasets/abc123/precheck` 用户无法感知位置层级
- 数据集子页面有返回按钮，但知识库子页面没有
- 通过深链接进入时完全丧失导航上下文

---

## 四、中等优先级问题（Medium）

### 4.1 加载状态不一致

| 模式 | 使用页面 |
|------|---------|
| `Skeleton` 占位符 | observability、access-review |
| `RefreshCw` + `animate-spin` 图标 | graph、reports、history、settings |
| 空白等待（无任何加载提示） | 部分 datasets 子页面 |
| `Loader2` 旋转图标 | 少数组件 |

**建议**：标准化为 `Skeleton`（页面初次加载）+ `Loader2`（操作中）两种模式

### 4.2 Bundle 大小隐患

| 库 | 估计大小 | 动态加载？ | 文件 |
|----|---------|-----------|------|
| `plotly.js-dist-min` | ~1MB | **否** ⚠️ | `similarity-workbench.tsx` |
| `three` + 周边 | ~600KB | 是 ✅ | graph 组件 |
| `monaco-editor` | ~2MB | 是 ✅ | preview 组件 |
| `pdfjs-dist` | ~400KB | 否 ⚠️ | 文档查看器 |
| `tsparticles` (3 包) | ~200KB | 待查 | `particle-background.tsx`（仅装饰） |
| `@codesandbox/sandpack-react` | ~500KB | 待查 | 使用情况不明 |

### 4.3 React Query 使用率过低

- 全项目仅 **8 个文件**使用 `useQuery`/`useMutation`
- 大部分数据获取仍是 `useEffect` + 直接 `apiClient` 调用
- 缺乏：自动缓存失效、请求去重、后台刷新、乐观更新

### 4.4 重复路由

- `/evaluation` 和 `/evaluations` 指向同一页面（re-export 而非 redirect）
- 对 SEO 和用户理解造成混淆

### 4.5 代码重复

- `lib/api-client.ts` 和 `lib/api-errors.ts` 都有 `extractRateLimitDetail` 实现
- 4 个 Context Provider 遵循几乎相同的模式但未抽象
- 多个 workbench 组件（chunk-preview、evidence-suite、similarity、dataset-kg）结构相似但未统一

---

## 五、安全问题

### 5.1 JWT 存储在 localStorage ⚠️

- `lib/auth-storage.ts` line 34, 43：Token 存在 `localStorage`
- 任何 XSS 都可读取 token
- **建议**：迁移到 `httpOnly` cookie

### 5.2 硬编码 demo 用户 fallback

- `lib/auth-headers.ts` line 31：`headers['X-User-ID'] = userId || 'demo'`
- 无 token 时请求以 `demo` 身份发送
- 开发便利但生产环境有风险

### 5.3 好的安全实践（保持）

- 零 `dangerouslySetInnerHTML` ✅
- 零 `@ts-ignore` ✅
- `rehype-sanitize` 处理 markdown 渲染 ✅
- `poweredByHeader: false` ✅
- 远程图片限制为 localhost/backend ✅

---

## 六、测试覆盖

- **185 个测试文件** / 366 个源文件 ≈ 50.5% 文件覆盖率
- **无覆盖率配置或门槛强制**（vitest.config.ts 无 `coverage` 配置）
- 关键大文件**零测试**：
  - `document-detail-dialog.tsx`（1,909 行）
  - `similarity-workbench.tsx`（1,715 行）
  - `pipeline-options-panel.tsx`（1,191 行）
  - `graph-viewer.tsx`（594 行）
  - 全部 4 个 Context Provider
- **无 axe-core 等运行时 a11y 审计**（现有 a11y 测试是源码级模式检查）

---

## 七、类型安全

| 指标 | 数值 | 评价 |
|------|------|------|
| `strict: true` | ✅ | 好 |
| `@ts-ignore` | **0** | 优秀 |
| `@ts-expect-error` | **0** | 优秀 |
| `as any` | 62 处 / 30 文件 | 中等 |
| `: any` | 73 处 / 20 文件 | 中等 |
| 总 `any` 相关 | ~186 处 / 50 文件 | 139K 行中可接受，但应逐步消除 |

最严重的 `any` 集中在：
- `app/datasets/[id]/profile/page.tsx`（14 处）
- `app/datasets/[id]/db-catalog/page.tsx`（9 处）
- `lib/graph-edge-display.ts`（10 处 `as any`）

---

## 八、总评与行动建议

### 评分卡

| 维度 | 评分 | 关键发现 |
|------|------|---------|
| 设计系统 | **A** | shadcn/ui + 自动化守卫，行业一流 |
| 色彩/主题 | **A** | 完整 HSL token + 暗色模式 |
| 无障碍 | **A-** | 焦点管理、reduced-motion、a11y 测试 |
| 状态管理 | **A-** | 三层分离清晰 |
| 依赖健康 | **A-** | 全部最新 |
| 排版 | **B+** | 系统字体 + text-balance/text-pretty |
| 类型安全 | **B+** | strict + 零 ts-ignore，但 186 处 any |
| API 层 | **B** | OpenAPI codegen 好，但主文件 4261 行 |
| 测试 | **B-** | 50% 覆盖，大文件零测试 |
| 安全 | **B-** | localStorage JWT + demo fallback |
| Bundle | **B-** | plotly 未懒加载，装饰组件过重 |
| 组件拆分 | **C** | 4 个 2000+ 行巨型组件 |
| 表单处理 | **C-** | 零表单库，13-useState 表单 |
| i18n | **F** | 完全缺失 |
| 移动端 | **C** | 核心页面可用但工具页面不可用 |
| 加载/错误边界 | **C** | 全 app 共享 1 个 loading + 1 个 error |

### 优先行动清单

| 序号 | 行动 | 工作量 | 影响 |
|------|------|--------|------|
| 1 | 拆分 `api-client.ts`（4,261 行）为领域模块 | 3-5 天 | 可维护性 |
| 2 | 拆分 4 个巨型页面组件 | 5-7 天 | 可维护性 + 性能 |
| 3 | 引入 react-hook-form + zod，迁移核心表单 | 3-5 天 | 用户体验 + 数据质量 |
| 4 | 添加嵌套 loading.tsx / error.tsx + Suspense | 2-3 天 | 用户体验 |
| 5 | JWT 从 localStorage 迁移到 httpOnly cookie | 2-3 天 | 安全 |
| 6 | 引入 next-intl，提取中英文字符串 | 2-3 周 | 国际化 |
| 7 | Plotly 动态加载 + 清理装饰依赖 | 1 天 | 性能 |
| 8 | 添加 vitest coverage 配置 + 门槛 | 1 天 | 质量保障 |
| 9 | 建立面包屑组件 + 共享 useMediaQuery | 2-3 天 | 导航 + 响应式 |
| 10 | 集成 Sentry 等错误上报 | 1 天 | 可观测性 |
