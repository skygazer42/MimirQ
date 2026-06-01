import { readClientStorage } from '@/lib/client-storage'

export const ORIGINAL_PREVIEW_MODE_STORAGE_KEY = 'mimirq_chunk_preview_original_preview_mode_v1'

const VALID_PREVIEW_MODES = new Set(['raw', 'rendered', 'editor', 'pdf'] as const)

export type OriginalPreviewMode = 'raw' | 'rendered' | 'editor' | 'pdf'

export function getStoredOriginalPreviewMode(): OriginalPreviewMode | null {
  if (globalThis.window === undefined) return null
  const raw = (readClientStorage(ORIGINAL_PREVIEW_MODE_STORAGE_KEY) || '').trim()
  if (!raw || !VALID_PREVIEW_MODES.has(raw as OriginalPreviewMode)) return null
  return raw as OriginalPreviewMode
}

export function getInitialOriginalPreviewMode(isPdf: boolean): OriginalPreviewMode {
  return getStoredOriginalPreviewMode() ?? (isPdf ? 'pdf' : 'raw')
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
  return nextIndex != null && !showOriginalPanel && isPdf && preferredPreviewMode === 'pdf'
}
