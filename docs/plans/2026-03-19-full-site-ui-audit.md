# 全站 UI 审计报告与优化方案

> 基于 2026-03-19 全部前端页面代码审计 + interface-design / baseline-ui skill 原则。
> 覆盖 30+ 页面、13 个全局 UI 组件、设计令牌体系。
> 目标：识别系统性问题并给出可落地的优化路径，不推翻现有架构。

---

## 一、全局设计系统审计

### 1.1 色彩体系

**现状**：globals.css 定义了 cyan primary、violet accent、success/warning/info/destructive 语义色、teal/orange/rose/indigo 扩展色。AppBackground 有微妙的双色光晕 + 网格纹理。

**问题**：
- `--secondary`、`--muted` 在 light mode 下是同一个 HSL 值 (`210 40% 96.1%`)，视觉上没有层次区分
- 多个页面使用原始 Tailwind `sky-*` / `slate-*` 类而非 semantic token（如 evaluations 用 `text-sky-600`、governance 用 `bg-sky-50`），绕过了设计系统
- Chart 组件普遍使用硬编码 hex 色值（如 `#22c55e`, `#ef4444`），不跟随主题/暗色模式
- StatCard 的 `sky` / `blue` / `cyan` 三个名称在视觉上几乎无法区分

**建议**：
- 将 `--secondary` 与 `--muted` 区分（secondary 可略深 2-3%）
- 全局 lint 规则禁止在业务组件中直接使用 `sky-*`、`slate-*`，强制使用 semantic token
- 创建 `--chart-1` 到 `--chart-8` 系列 CSS variable，Chart 组件统一引用
- StatCard 移除视觉重复的 `sky`/`blue` 名称，合并为 `info`

### 1.2 间距与圆角

**现状**：Tailwind 默认间距 + 两个自定义圆角 token (`--radius: 0.75rem`, `--radius-xl: 1rem`)。

**问题**：
- PageScaffold compact 模式 header 用 `px-4 md:px-6`，但 toolbar/body 用 `px-6 md:px-8`，导致微妙的水平错位
- Card 用 `rounded-lg`，Panel 用 `rounded-xl`，按钮用 `rounded-xl`，Empty State 用 `rounded-3xl`——四种圆角在同一页面共存
- 无全局 "page gutter" token，每个 scaffold 层独立硬编码

**建议**：
- 统一 page gutter：定义 `--page-gutter: 1.5rem` (md: 2rem)，scaffold 各层统一引用
- 圆角统一为两档：`rounded-lg` (containers/cards) + `rounded-xl` (interactive elements/buttons)
- EmptyState 的 `rounded-3xl` 降级为 `rounded-xl` 与 Panel 对齐

### 1.3 排版层级

**现状**：compact 模式标题 `text-lg/xl`，CardTitle `text-base`，正文 `text-sm`，辅助 `text-xs`。

**问题**：
- 缺少全局 Type Scale 定义（每个组件独立决定字号）
- Badge/标签常用 `text-[10px]`（非标准 Tailwind 级），与 `text-xs` (12px) 形成 2px 微跳
- 部分页面的 help text 用 `text-[11px]`，另一些用 `text-xs`，不统一
- 没有 heading 的 responsive 规则（compact mode 标题在手机和桌面只差一档）

**建议**：
- 建立 5 级 type scale：Page Title (xl) / Section Title (base/medium) / Body (sm) / Caption (xs) / Micro (2xs)
- 将 `text-[10px]` 和 `text-[11px]` 统一为 `text-xs` (12px)
- 在 globals.css 中定义 `.type-section`、`.type-caption` 等语义类

### 1.4 深度策略

**现状**：混用了三种深度策略：
- borders-only（Card、Panel）
- subtle shadows（`shadow-soft`、`shadow-strong`）
- glass/blur（navbar、PageHeader icon、glass-card）

**问题**：interface-design skill 明确说"Pick ONE approach and commit"。当前三种混用导致视觉"温度"不统一——部分区域像 IDE（clean border），部分像 macOS（frosted glass），部分像 SaaS（subtle shadow）。

**建议**：
- 主策略选 **borders-only + subtle shadow**（与当前 Card/Panel 一致）
- `backdrop-blur-xl` 仅保留在 navbar 和 popover/dialog 层，不在 PageHeader icon 和 glass-card 上使用
- 移除 `.glass` 和 `.glass-card` utility，或将其限定为 overlay 场景

---

## 二、逐页审计

### 核心页面

| 页面 | 主要问题 | 优先级 | 建议 |
|------|---------|--------|------|
| **对话页** (chat-area) | 消息区 `max-w-4xl` vs 输入区 `max-w-3xl` 宽度不对齐；RAG 设置在 popover 里信息密度过高 | P1 | 统一 `max-w-3xl`；RAG 设置增加"快捷预设"卡片，高级选项折叠 |
| **知识库** (knowledge-page) | 控件过多（scope/folder/status/lifecycle/sort/view/batch）首屏压力大 | P2 | 将 scope/folder 合并为一个 combo picker；默认折叠高级筛选 |
| **数据集** (datasets-page) | 表格布局基本合理；分类树在窄屏隐藏且无替代入口 | P1 | 窄屏增加分类下拉选择器；行 hover 时 kebab 菜单在触屏设备始终可见 |
| **数据治理** (data-governance) | 右侧 4 个等宽 tab 在窄屏挤压；中英文混杂；文件注释编码损坏 | P2 | Tab 改为 horizontal scroll 或 dropdown；修复编码 |
| **解析** (parsing) | Orange icon 使用原始 Tailwind `text-orange` 而非 `text-orange` token；sidebar 窄屏隐藏后 queue 不可发现 | P2 | 确认 token 对齐；窄屏增加浮动 queue badge |
| **设置** (settings) | 超长单列滚动无导航；中英混杂 | P1 | 增加左侧固定 anchor nav（或 ScrollSpy TOC） |
| **评估** (evaluations) | 所有 StatCard 同色 `sky`；指标缺少语义色 | P2 | 按指标分配不同色（faithfulness=success, relevancy=info, precision=teal） |

### 数据集子页面

| 页面 | 主要问题 | 优先级 | 建议 |
|------|---------|--------|------|
| **预检扫描** (precheck) | 工具栏 7 个等权重 outline 按钮可能溢出；Chart 硬编码色 | P2 | 按钮分主次 + overflow menu；Chart 改用 CSS var |
| **数据画像** (profile) | 极长滚动（多个 histogram）无内页导航 | P1 | 增加 anchor nav 或 tab 分组（概览/切块/解析/历史） |
| **入库策略** (ingestion) | 规则列表行内 4 个操作按钮密集 | P3 | 折叠次要操作到 kebab menu |
| **Workflow** (workflow) | 全英文字符串；dialog 圆角不统一 | P3 | i18n 对齐；统一 dialog 为 `sm:rounded-2xl` |
| **表格/TAG** (tables) | 描述区的 pulse 动画无语义 | P3 | 移除装饰性 pulse |
| **KG 工作台** (dataset-kg) | Skeleton 使用 `w-4/5`（无效 Tailwind 宽度） | P2 | 修复为 `w-[80%]` |
| **KG 诊断** (kg-diagnostics) | 大量 JSON textarea 未折叠 | P2 | 默认折叠 JSON，显示摘要指标 |
| **KG 快照** (kg-snapshots) | 三重 copy+export+textarea 重复 | P3 | 合并为一个"导出 bundle"操作 |
| **消融实验** (ablations) | 表单极密；排行榜用自定义 grid 非 `<table>`——弱 accessibility | P2 | 增加预设快填；改用语义 `<table>` |

### 辅助/管理页面

| 页面 | 主要问题 | 优先级 | 建议 |
|------|---------|--------|------|
| **Prompts** (prompts) | KG 配置区与模板列表无层级分隔 | P2 | 配置区折叠或改为 tab |
| **诊断** (diagnostics) | 缺少 AppFrame 包裹；JSON 墙 | P1 | 加 AppFrame；JSON 默认折叠 |
| **观测** (observability) | `JSON.stringify` 直接渲染数据 | P2 | 改为 bar breakdown 或 table |
| **报告** (reports) | Chart 硬编码 hex；无聚焦感 | P2 | Chart 改 token；增加概览 tab |
| **历史** (history) | 设计较好（master-detail）；删除按钮仅 hover 可见 | P3 | 删除用 always-visible icon |
| **审计** (audit) | 筛选框无 Label（WCAG 问题）；placeholder-only | P1 | 增加 `<Label>` |
| **用量** (usage) | 英文列标题 vs 中文页标题 | P3 | 统一语言 |
| **隔离队列** (quarantine) | 操作按钮仅 hover 可见（触屏不友好） | P2 | 主操作始终可见或 kebab |
| **入库监控** (ingestion monitor) | `Search` icon 用于"存储量"——语义错误 | P2 | 换 `Database` / `HardDrive` icon |
| **反馈分析** (feedback) | 假指标 "~1.2s"；rating filter 失效 | P1 | 移除假数据；修复 filter |
| **访问审查** (access-review) | 多个 StatCard 同 icon | P3 | 每个指标用不同 icon |
| **组管理** (groups) | 英文 Card 标题 vs 中文页标题 | P3 | 统一 |
| **RBAC** (rbac) | 每行独立 save——高风险操作无全局确认 | P2 | 改为 dirty state + 统一 save |
| **治理 Profiles** (governance-profiles) | 基本合理 | P3 | 长列表考虑虚拟化 |
| **Common Lines** (common-lines) | 基本合理 | P3 | 候选列表改为 table 视图 |
| **Chunk Preview** (chunk-preview) | 基本合理（WorkbenchScaffold） | P3 | 确认 PipelineRail z-index 不遮挡 |

---

## 三、跨页面系统性问题

### 3.1 中英文混杂

约 60% 的页面存在 title 用中文但 badge/placeholder/column 用英文的情况。建议：
- 面向用户的所有文案统一使用 `next-intl` 的 `t()` 函数
- Badge 文案也走 i18n，不硬编码英文

### 3.2 Hover-only 操作（触屏不友好）

至少 8 个页面的行操作依赖 `opacity-0 group-hover:opacity-100`。在触屏设备上用户无法触发 hover，功能不可达。建议：
- 主操作（如删除、编辑）始终可见为一个 kebab `MoreHorizontal` icon
- 或在移动端检测 `@media (hover: none)` 时默认显示

### 3.3 Chart 色彩不跟随主题

reports/precheck/profile/health 等页面的 Recharts 使用硬编码 hex。暗色模式下可能对比度不足或刺眼。建议：
- 在 globals.css 定义 `--chart-1` 到 `--chart-8`（light/dark 各一套）
- Recharts `stroke` / `fill` 统一引用 `hsl(var(--chart-N))`

### 3.4 JSON 墙

diagnostics / kg-diagnostics / kg-snapshots / ablations 等页面大量直接渲染 JSON textarea。建议：
- 默认折叠 JSON，显示结构化摘要（key-value table 或 stat cards）
- 提供"展开原始 JSON"按钮，高级用户按需查看

### 3.5 Settings 无内页导航

settings 页是一个超长单列，用户靠滚动记忆定位。建议：
- 左侧增加固定的 anchor nav（分类：通用/模型/RAG/集成/治理/运行时）
- 使用 IntersectionObserver 做 ScrollSpy 高亮当前区域

---

## 四、优先级排序

### P0 — 阻断级/基础体验

1. 反馈页假指标移除 + rating filter 修复
2. 审计页筛选框增加 Label（WCAG 合规）
3. 诊断页增加 AppFrame 包裹

### P1 — 高价值改进

4. Settings 页增加 anchor nav
5. 统一 page gutter（header/toolbar/body 水平对齐）
6. Chat 消息区与输入区宽度对齐
7. 数据画像页增加内页导航
8. 全局 hover-only 操作触屏兼容

### P2 — 产品感提升

9. Chart 色彩 token 化
10. JSON 墙默认折叠
11. 统一圆角为两档
12. StatCard 语义色分配
13. 移除不必要的 glass/blur
14. RBAC 页改为 dirty state + 统一 save
15. 隔离队列/入库监控操作按钮始终可见

### P3 — 打磨

16. 中英文统一
17. 移除装饰性 pulse 动画
18. Skeleton 宽度修复
19. 历史页删除按钮可见性
20. 各页面 icon 语义对齐

---

## 五、与顶尖 RAG 前端的差距总结

| 维度 | MimirQ 现状 | Dify / RAGFlow 水平 | Linear / Vercel 水平 |
|------|------------|---------------------|---------------------|
| 色彩一致性 | Token 体系完整但执行不严（绕过 token 直接用 Tailwind palette） | 较差（admin 模板感） | 极严格（monochrome + 1 accent） |
| 信息密度 | 工作台类页面偏高（多控件首屏堆叠） | 类似 | 精确控制（渐进披露） |
| 深度策略 | 混用 border + shadow + glass | 多为 border-only | 单一策略严格执行 |
| i18n | 部分页面混杂 | 较好 | N/A |
| 触屏兼容 | hover-only 操作多 | 类似问题 | 所有操作始终可达 |
| 内页导航 | 长页面无 TOC/anchor | 部分有 | 必备 |
| 数据可视化 | 硬编码色 + 原始 JSON | 类似 | Token 化 + 结构化摘要 |

**核心差距不在功能多少，而在执行一致性。** Token 体系已经建好，但 30+ 页面中约 40% 绕过了 token 直接用原始 Tailwind 类，导致视觉上"有设计系统但不像一个系统"。
