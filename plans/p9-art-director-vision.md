# MimirQ: P9 Art Director & Architect Vision (2026-03-24)

## 1. 视觉哲学：AI-Native Minimalism

### 1.1 空间与层次 (Depth & Layering)
- [ ] **Surface-First Design**: 移除所有 `border-border`，改用 `bg-secondary/50` 和 `shadow-soft` 进行区域划分。界面应感觉是由多个悬浮的层级组成的。
- [ ] **Contextual Chrome**: 只有当鼠标悬浮或特定交互时才显示操作按钮（如“删除”、“重试”）。保持常态下的“极致干净”。
- [ ] **Geist Typography**: 统一使用更具 modern 态的 `Geist` 字体栈，利用 1.7-1.8 倍行高，将“阅读知识库”变成一种享受。

### 1.2 呼吸感动效 (Breathing Interactions)
- [ ] **Layout Transitions**: 在切换“图谱”与“列表”视图时，利用 Framer Motion 的 `layoutId` 实现元素平滑飞行，而非硬切。
- [ ] **Staggered Entry**: 搜索结果列表应采用交错式入场动画（Staggered Fade-in），给用户一种“正在检索并逐步呈现”的韵律感。

## 2. P9 架构标准：零技术债演进

### 2.1 彻底重构巨型文件 (The "Big Split")
- [ ] **Service Domain Separation**: 废除 4000 行的 `api-client.ts`。按照 **Domain-Driven Design (DDD)** 拆分为 `services/doc/*`, `services/rag/*`, `services/auth/*`。
- [ ] **Registry Pattern**: 为 Parser 和 Chunking 策略建立注册表模式，避免在 UI 代码中出现大量的 `switch-case` 逻辑。

### 2.2 React 19 & Next.js 16 极致利用
- [ ] **Server Actions & Actions API**: 将所有的表单提交（如标签编辑、权限修改）迁移至 React Actions，利用 `useFormStatus` 处理 Loading 态，彻底告别手动的 `setIsLoading(true/false)`。
- [ ] **Optimistic UI**: 针对点赞、收藏、标签修改，全面引入 `useOptimistic`，实现“零延迟”交互感。

## 3. RAG 专家级体验 (Expert RAG UX)

### 3.1 语义联动 (Semantic Linkage)
- [ ] **Integrated Doc Viewer**: 消息区引用的切片 [1] 悬浮时，侧边栏直接展示 PDF 缩略图并定位到高亮行。
- [ ] **Graph-to-Context**: 在 3D 图谱中选中节点，对话框自动预填“总结一下该文档的核心观点”，将可视化与交互完全打通。

### 3.2 Command-First Workflow
- [ ] **Vim-Inspired Shortcuts**: 为专业用户提供 `g d` (Go to Documents), `g c` (Go to Chat), `f s` (Find Slice) 等极速操作路径。
- [ ] **Smart Command Bar**: 升级 `cmdk` 面板，支持“自然语言指令”（例如：输入“把上周上传的 PDF 全部归档”直接触发批量操作）。

## 4. 基础设施可观测性
- [ ] **Frontend Trace Integration**: 在前端日志中记录每一个复杂计算（如图谱拓扑）的耗时，上报至后端监控平台，将可观测性做到用户端。
