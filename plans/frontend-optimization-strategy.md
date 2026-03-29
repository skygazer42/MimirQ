# Frontend Optimization Strategy & Roadmap (2026-03-24)

## 1. 架构治理：消除单体膨胀 (Architecture & Decoupling)

### 1.1 API 客户端模块化 (Service-Oriented Refactor)
*   **现状**: `api-client.ts` (4000+行) 过于臃肿，混合了传输、转换、类型定义。
*   **建议**: 
    *   **领域拆分**: 将其拆分为 `services/document.ts`, `services/rag.ts`, `services/knowledge.ts` 等。
    *   **运行时契约**: 在 Service 层引入 **Zod** 进行数据解析，确保后端返回的动态 JSON 100% 符合前端 TypeScript 定义。
    *   **逻辑上移**: 将 `api-client.ts` 中的业务转换（如 `normalizeGovernanceProfile`）移至对应的 Service 或专门的 Transformer 函数中。

### 1.2 巨型组件拆解 (Component Decomposition)
*   **现状**: `DocumentDetailDialog` (1.9k lines) 和 `DocumentViewerPanel` (68KB) 严重超负荷。
*   **建议**:
    *   **Smart/Dumb 模式**: 主组件只负责数据流分发，UI 拆分为 `MetadataTab`, `VersionHistory`, `ChunkList` 等独立原子组件。
    *   **Slot 组合模式**: 使用 React 19 的组件组合特性，将复杂的弹窗内容通过 `children` 或自定义 `slots` 注入，减少单一文件的复杂度。

### 1.3 逻辑 Hook 原子化 (Atomic Hooks)
*   **现状**: `use-chat.ts` (17KB) 和 `use-documents.ts` (15KB) 逻辑过重。
*   **建议**: 拆分为三层 Hook：
    1.  **Data Hooks**: 纯粹封装 `useQuery` / `useMutation`。
    2.  **Filter/State Hooks**: 管理 UI 筛选、排序、分页状态。
    3.  **Action Hooks**: 处理业务操作逻辑（如“批量重试入库”）。

## 2. 性能突破：释放主线程 (Performance & Concurrency)

### 2.1 计算任务分流 (Web Worker Offloading)
*   **重点**: 
    *   **3D 图谱**: 将 `react-force-graph-3d` 的力导向布局计算 (Force-directed layout) 移至 Web Worker。
    *   **文本 Diff**: 在评估对比页面，将长文本差异计算移至 Worker。
    *   **Markdown 清洗**: 大规模 Markdown 预览时的正则清洗任务异步化。

### 2.2 资产与 Bundle 优化 (Bundle Guard)
*   **策略**: 
    *   **延迟加载**: 强制对 `three.js`, `plotly.js`, `monaco-editor` 实施 `next/dynamic` 配合 `ssr: false`。
    *   **本地化资源**: 移除所有外部 CDN 依赖（如 Lottie 动画、Monaco Worker），确保内网部署环境的极速加载。

## 3. 开发者体验：提升反馈速度 (DX Enhancement)

### 3.1 优化 HMR 与 类型检查
*   **策略**: 
    *   **拆分 `types/index.ts`**: 将 75KB 的类型定义按模块分散，解决 VS Code 补全延迟 (TSServer lag)。
    *   **引入 `barrels` 优化**: 规范化 `index.ts` 的 re-export 路径，减少构建工具对无用模块的扫描。

## 4. 顶级 UX 对齐：RAG 体验天花板 (UX/UI Polish)

### 4.1 语义联动交互 (Semantic Context Sync)
*   **功能**:
    *   **引用溯源高亮**: 点击 AI 回复中的引用标记，PDF 预览器自动滚动至对应页码并执行黄色高亮。
    *   **双向定位**: 在文档预览中点击某个切片，左侧对话框自动定位至引用该切片的回答。

### 4.2 全局命令中心 (Command-K Hub)
*   **功能**: 扩展 `command-menu.tsx`，支持 `/` 操作（如：`/upload` 直接唤起上传，`/stats` 切换监控视图），对齐 Linear/Raycast 级交互体验。

### 4.3 极致流畅感 (Fluidity)
*   **功能**:
    *   **Token 级渐进淡入**: 优化打字机效果，结合 Framer Motion 实现字符级的透明度淡入，而非简单的字符跳动。
    *   **骨架屏一致性**: 确保所有数据密集型页面（图谱、列表、报表）拥有像素级对齐的骨架预加载态。
