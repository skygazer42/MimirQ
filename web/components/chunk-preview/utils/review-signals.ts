import type { ChunkPreviewItem } from '@/types'

import { getChunkRole } from './metadata'

export function computeRoleIndices(chunks: readonly ChunkPreviewItem[]) {
  const parents = new Set<number>()
  const children = new Set<number>()
  for (const chunk of chunks) {
    const role = getChunkRole(chunk)
    if (role === 'parent') parents.add(chunk.index)
    if (role === 'child') children.add(chunk.index)
  }
  return { parents, children }
}
