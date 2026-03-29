# Frontend Infrastructure & Design Audit (2026-03-24)

## 1. 核心工程问题 (Core Engineering Issues)

### 1.1 巨型文件与逻辑耦合 (The "Mega-Everything" Anti-pattern)
*   **现状**: 
    *   **巨型组件**: `document-detail-dialog.tsx` (1900+ lines, 87KB)。
    *   **巨型 API**: `api-client.ts` (4000+ lines)，包含 100+ 类型定义和大量业务转换。
    *   **巨型类型**: `types/index.ts` (75KB)，造成 IDE 补全延迟。
*   **方案**: 实施 **领域驱动重构 (Domain-Driven Refactor)**。将 API 与类型按业务域 (Document, Chat, RAG, Auth) 物理拆分，禁止在单一文件中超过 500 行核心逻辑。

### 1.2 状态管理与数据流 (State & Data Flow)
*   **现状**: 过度混合 `useState` 与原生 Axios 请求，缺乏自动缓存、失效重试和乐观更新机制。
*   **方案**: 
    *   **React Query 全面接管**: 移除所有手动维护的 `loading`/`error` 状态。
    *   **Zod 运行时契约**: 利用 `api-contract-lib.mjs` 的既有基础，在前端入口层引入 Zod 校验，确保后端 API 变动能立即在开发环境暴露。

### 1.3 渲染性能与资产优化 (Performance & Assets)
*   **现状**: 
    *   PDF 渲染依赖复杂的 Webpack Worker 插件修正。
    *   3D Graph 的拓扑运算在主线程，导致大图加载时 UI 假死。
*   **方案**:
    *   **OffscreenCanvas**: 将 PDF.js 和 3D Graph 的渲染/计算逻辑完整移至 `web/workers`。
    *   **Monaco Editor 本地化**: 在 `next.config.mjs` 中配置本地资源路径，支持离线/内网私有部署。

## 2. 具体重构路线图 (Refactoring Roadmap)

### 阶段 1: 基础设施模块化 (Immediate Priority)
- [ ] **拆分 `api-client.ts`**: 按领域拆分为 5-8 个独立 Service。
- [ ] **API 响应拦截器加固**: 集成 Zod 解析与 RequestID 日志关联。
- [ ] **移除 UI 目录下的业务组件**: 将 `parser-dropdown`, `chunk-strategy-dropdown` 移至 `components/business`。
- [ ] **拆分 `types/index.ts`**: 按业务领域分散定义，优化 TSServer 响应速度。

### 阶段 2: 逻辑解耦与缓存 (Medium Priority)
- [ ] **Hooks 原子化**: 将 `use-documents.ts` 拆分为取数、过滤、操作三个子 Hook。
- [ ] **迁移至 React Query**: 优先从 `observability` 和 `parsing` 页面开始，移除手动管理的 `useEffect` 取数逻辑。

### 阶段 3: 性能增强 (Long Term)
- [ ] **计算流转 (Main-thread Free)**: 为 3D Graph 和 PDF 解析建立专用的 Web Workers 链路。
- [ ] **Canvas 资源池化**: 优化 `chunk-preview` 中的 Canvas 回收机制，防止 PDF 频繁渲染导致的内存泄漏。

## 3. UI/UX 体验建议 (UX Polish)
- [ ] **Skeleton 渐进加载**: 避免全屏 Loading 闪烁，保持现有内容可见直至新数据就绪。
- [ ] **全局 Command Menu (CMDK)**: 扩展现有 `command-menu.tsx`，支持跨数据集、跨模块的 RAG 资源检索。
