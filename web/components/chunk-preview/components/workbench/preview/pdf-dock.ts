import { readClientStorage } from '@/lib/client-storage'
import type { ChunkPreviewResponse } from '@/types'

export const ORIGINAL_PREVIEW_MODE_STORAGE_KEY = 'mimirq_chunk_preview_original_preview_mode_v1'

export type OriginalPreviewMode = 'raw' | 'rendered' | 'editor' | 'pdf'

export function isPdfOriginalFile(
  preview: Pick<ChunkPreviewResponse, 'file_type'> | null,
  file: Pick<File, 'name'> | null,
): boolean {
  if (preview?.file_type.toLowerCase() === 'pdf') return true
  return file !== null && file.name.toLowerCase().endsWith('.pdf')
}

export function getStoredOriginalPreviewMode(): OriginalPreviewMode | null {
  const raw = readClientStorage(ORIGINAL_PREVIEW_MODE_STORAGE_KEY)
  if (raw === null) return null
  const mode = raw.trim()
  if (mode === 'raw' || mode === 'rendered' || mode === 'editor' || mode === 'pdf') return mode
  return null
}

export function shouldRevealPdfPreviewOnChunkSelect({
  nextIndex,
  showOriginalPanel,
  isPdf,
  preferredPreviewMode,
}: Readonly<{
  nextIndex: number | null
  showOriginalPanel: boolean
  isPdf: boolean
  preferredPreviewMode: OriginalPreviewMode | null
}>): boolean {
  return nextIndex !== null && !showOriginalPanel && isPdf && preferredPreviewMode === 'pdf'
}
