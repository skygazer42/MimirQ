# AI RAG Knowledge Base UI/UX Enhancement Plan

## 1. 视觉系统对齐 (Visual Alignment)

### 1.1 AI-Native 风格重塑
- [ ] **极简 Chrome 设计**: 移除冗余的边框 and 背景色。侧边栏使用 `bg-sidebar` 并增加 `backdrop-blur-xl`。
- [ ] **设计令牌一致性**: 强制所有颜色引用 `hsl(var(--primary))`，确保深色模式下 AI 特色紫色 (#6366F1) 的对比度。
- [ ] **排版升级**: 采用 `Geist` 或类似现代无衬线字体，增大 `h1` 字号，增加 1.75 倍行高以提升长文本阅读体验。

### 1.2 高级微动效 (Micro-interactions)
- [ ] **流式文本渲染**: 优化 `cinematic-typewriter`，增加 Token 级的 `opacity` 淡入效果，减少字符跳动。
- [ ] **平滑布局转换**: 使用 Framer Motion 的 `layout` 属性，在“列表视图”与“图谱视图”切换时提供连续的视觉反馈。

## 2. 知识交互深度 (Deep Knowledge Interaction)

### 2.1 文档级联预览 (Cascading Preview)
- [ ] **双栏关联视图**: 在 `chunk-preview` 中，点击切片应在右侧保持原文档的 PDF 视窗，并实现 **“Scroll-to-View”** 自动定位。
- [ ] **语义锚点高亮**: AI 引用内容在 PDF 预览中应使用黄色高亮标记，并支持点击引用反向定位文档位置。

### 2.2 交互式知识图谱 (Interactive Graph)
- [ ] **节点下钻 (Drill-down)**: 点击图谱节点不再仅是悬浮，而是平滑过渡到该文档的“详情面板”。
- [ ] **聚类视觉**: 针对不同数据集，在 3D 空间中使用不同的粒子颜色和引力常量，增强领域区分感。

## 3. 性能与极速感 (Perceived Performance)

### 3.1 渲染策略优化
- [ ] **OffscreenCanvas 离线渲染**: 将重型 3D 计算和 PDF 预渲染移出主线程，确保用户在数据处理时滚动依然丝滑。

## 4. 自动化审计 (Automated Audit)
- [ ] **a11y & Contrast Check**: 运行自动化对比度检查，确保所有 AI 生成的淡紫色文本符合 WCAG AA 标准。
