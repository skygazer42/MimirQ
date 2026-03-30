# AI RAG Knowledge Base UI/UX Enhancement Plan

## 1. 视觉系统对齐 (Visual Alignment)

### 1.1 AI-Native 风格重塑
- [x] **极简 Chrome 设计**: 移除冗余的边框 and 背景色。侧边栏使用 `bg-sidebar` 并增加 `backdrop-blur-xl`。
- [ ] **设计令牌一致性**: 强制所有颜色引用 `hsl(var(--primary))`，确保深色模式下 AI 特色紫色 (#6366F1) 的对比度。
- [ ] **排版升级**: 采用 `Geist` 或类似现代无衬线字体，增大 `h1` 字号，增加 1.75 倍行高以提升长文本阅读体验。

## 3. 性能与极速感 (Perceived Performance)

### 3.1 渲染策略优化
- [x] **OffscreenCanvas 离线渲染**: 将重型 3D 计算和 PDF 预渲染移出主线程，确保用户在数据处理时滚动依然丝滑。

## 4. 自动化审计 (Automated Audit)
