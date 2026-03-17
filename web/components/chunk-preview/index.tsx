/**
 * ChunkPreview - 主入口组件（重构后）
 * 将 1059 行巨型组件拆分为模块化结构
 *
 * Notes:
 * - A/B compare UI will surface per-run `metadata.hierarchy_basis` (when present) to avoid comparing incompatible bases.
 */
'use client'

import { ChunkPreviewProvider, useChunkPreview } from './context'
import { EmptyState } from './components/empty-state'
import { Workbench } from './components/workbench'
import type { ChunkPreviewProps } from './types'

// 内部组件：根据文件列表状态决定渲染内容
function ChunkPreviewContent() {
  const { fileList } = useChunkPreview()

  // 空状态：显示上传页面
  if (fileList.length === 0) {
    return <EmptyState />
  }

  // 有文件：显示工作台
  return <Workbench />
}

// 导出组件：带 Context Provider
export function ChunkPreview(props: Readonly<ChunkPreviewProps>) {
  return (
    <ChunkPreviewProvider onConfirm={props.onConfirm} onClose={props.onClose}>
      <ChunkPreviewContent />
    </ChunkPreviewProvider>
  )
}

export default ChunkPreview
