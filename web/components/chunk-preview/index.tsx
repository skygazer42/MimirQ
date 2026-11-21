'use client'

import { ChunkPreviewProvider } from './context'
import { Workbench } from './components/workbench'
import type { ChunkPreviewProps } from './types'

export type { ChunkPreviewProps, ChunkPreviewFileItem } from './types'

export function ChunkPreview({ onConfirm, onClose }: Readonly<ChunkPreviewProps>) {
  return (
    <ChunkPreviewProvider onConfirm={onConfirm} onClose={onClose}>
      <Workbench />
    </ChunkPreviewProvider>
  )
}
