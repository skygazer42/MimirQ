/**
 * ChunkPreview - 主入口组件（重构后）
 * 将 1059 行巨型组件拆分为模块化结构
 *
 * Notes:
 * - A/B compare UI will surface per-run `metadata.hierarchy_basis` (when present) to avoid comparing incompatible bases.
 */
'use client'

import { ChunkPreviewProvider } from './context'
import { Workbench } from './components/workbench'
import type { ChunkPreviewProps } from './types'

// 导出组件：带 Context Provider
export function ChunkPreview(props: Readonly<ChunkPreviewProps>) {
  return (
    <ChunkPreviewProvider onConfirm={props.onConfirm} onClose={props.onClose}>
      <Workbench />
    </ChunkPreviewProvider>
  )
}

export default ChunkPreview
