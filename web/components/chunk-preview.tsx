/**
 * ChunkPreview - 入口文件（重构后）
 * 原 1059 行巨型组件已拆分为模块化结构
 *
 * 新结构：
 * - chunk-preview/
 *   ├── types.ts (类型定义)
 *   ├── constants.ts (常量)
 *   ├── context.tsx (状态管理)
 *   ├── utils/
 *   │   └── file-scanner.ts (工具函数)
 *   └── components/
 *       ├── empty-state.tsx (空状态页面)
 *       ├── chunk-card.tsx (切片卡片)
 *       └── workbench/
 *           ├── index.tsx (主工作台)
 *           ├── top-bar.tsx (顶部栏)
 *           ├── sidebar.tsx (左侧配置栏)
 *           └── preview/
 *               ├── original-preview.tsx (原文预览)
 *               └── chunk-list.tsx (切片列表)
 */
export { ChunkPreview, ChunkPreview as default } from './chunk-preview/index'
export type { ChunkPreviewProps, ChunkPreviewFileItem } from './chunk-preview/types'
