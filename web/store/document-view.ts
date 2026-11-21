import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { getClientStorage } from '@/lib/client-storage'
import { AUTH_SCOPE_CHANGED_EVENT, DOCUMENT_VIEW_STORAGE_KEY, getAuthCacheScope } from '@/lib/auth-storage'
import type { DocumentPreviewAnchor } from '@/lib/document-preview-anchor'
import { sanitizeDocumentPreviewAnchor } from '@/lib/document-preview-anchor'

export type HighlightRange = { start: number; end: number }
export type DocumentViewTab = 'preview' | 'text' | 'chunks'
export type DocumentTextMode = 'cleaned' | 'original'
export type DocumentViewSourceContext = {
  kind: 'chat-citation'
  messageId: string
  documentId: string
  chunkId?: string | null
  documentName?: string | null
  chunkContent?: string | null
  chunkIndex?: number | null
  pageNumber?: number | null
}
type DocumentViewResumeTarget = {
  documentId: string
  chunkId?: string | null
  highlightRange?: HighlightRange | null
  previewAnchor?: DocumentPreviewAnchor | null
  activeTab?: DocumentViewTab
  sourceContext?: DocumentViewSourceContext | null
}

export type DocumentViewLayout = {
  activeTab?: DocumentViewTab
  isExpanded?: boolean
  panelWidthPx?: number
  textMode?: DocumentTextMode
  chunksScrollTop?: number
  textScrollTop?: number
}

type DocumentViewState = {
  authScope: string
  isOpen: boolean
  documentId: string | null
  highlightChunkId: string | null
  highlightRange: HighlightRange | null
  previewAnchor: DocumentPreviewAnchor | null
  sourceContext: DocumentViewSourceContext | null
  activeTab: DocumentViewTab
  documentLayouts: Record<string, DocumentViewLayout>
  lastOpenedTarget: DocumentViewResumeTarget | null

  openDocument: (
    documentId: string,
    chunkId?: string,
    range?: Partial<HighlightRange>,
    options?: {
      previewAnchor?: Partial<DocumentPreviewAnchor> | null
      activeTab?: DocumentViewTab
      sourceContext?: DocumentViewSourceContext | null
    },
  ) => void
  closeDocument: () => void
  reopenLastDocument: () => void
  setHighlightChunk: (chunkId: string | null) => void
  setHighlightRange: (range: HighlightRange | null) => void
  setActiveTab: (tab: DocumentViewTab) => void
  getDocumentLayout: (documentId: string | null | undefined) => DocumentViewLayout | null
  setDocumentLayout: (documentId: string, patch: Partial<DocumentViewLayout>) => void
}

const DEFAULT_ACTIVE_TAB: DocumentViewTab = 'preview'
export const MIN_DOCUMENT_VIEWER_PANEL_WIDTH = 360
export const MAX_DOCUMENT_VIEWER_PANEL_WIDTH = 1800
const MAX_SOURCE_CONTEXT_TEXT_CHARS = 20_000
const VALID_TABS = new Set<string>(['preview', 'text', 'chunks'])
const VALID_TEXT_MODES = new Set<string>(['cleaned', 'original'])

const noopStorage = {
  getItem: (_name: string) => null,
  setItem: (_name: string, _value: string) => {},
  removeItem: (_name: string) => {},
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function normalizeId(id: unknown): string | null {
  if (typeof id !== 'string') return null
  const normalized = id.trim()
  return normalized ? normalized : null
}

function sanitizeScrollTop(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  return Math.max(0, value)
}

function sanitizePanelWidthPx(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const width = Math.round(value)
  return width >= MIN_DOCUMENT_VIEWER_PANEL_WIDTH && width <= MAX_DOCUMENT_VIEWER_PANEL_WIDTH ? width : undefined
}

function sanitizeHighlightRange(range: unknown): HighlightRange | null {
  if (!isRecord(range)) return null
  const start = range.start
  const end = range.end
  return typeof start === 'number' &&
    Number.isInteger(start) &&
    start >= 0 &&
    typeof end === 'number' &&
    Number.isInteger(end) &&
    end > start
    ? { start, end }
    : null
}

function normalizeOptionalText(value: unknown, maxChars = MAX_SOURCE_CONTEXT_TEXT_CHARS): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  if (!normalized) return null
  return normalized.length > maxChars ? normalized.slice(0, maxChars) : normalized
}

function readOptionalInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) ? value : null
}

function isDocumentViewTab(tab: unknown): tab is DocumentViewTab {
  return typeof tab === 'string' && VALID_TABS.has(tab)
}

function sanitizeDocumentViewTab(tab: unknown): DocumentViewTab | undefined {
  return isDocumentViewTab(tab) ? tab : undefined
}

function sanitizeSourceContext(
  sourceContext: unknown,
  activeDocumentId: string | null,
): DocumentViewSourceContext | null {
  if (!isRecord(sourceContext) || sourceContext.kind !== 'chat-citation') return null

  const messageId = normalizeId(sourceContext.messageId)
  const documentId = normalizeId(sourceContext.documentId)
  if (messageId === null || documentId === null || documentId !== activeDocumentId) return null

  return {
    kind: 'chat-citation',
    messageId,
    documentId,
    chunkId: normalizeId(sourceContext.chunkId),
    documentName: normalizeOptionalText(sourceContext.documentName, 300),
    chunkContent:
      typeof sourceContext.chunkContent === 'string'
        ? sourceContext.chunkContent.slice(0, MAX_SOURCE_CONTEXT_TEXT_CHARS)
        : null,
    chunkIndex: readOptionalInteger(sourceContext.chunkIndex),
    pageNumber: readOptionalInteger(sourceContext.pageNumber),
  }
}

function buildResumeTarget(
  documentId: string | null,
  activeTab: DocumentViewTab,
  chunkId: string | null,
  highlightRange: HighlightRange | null,
  previewAnchor: DocumentPreviewAnchor | null,
  sourceContext: DocumentViewSourceContext | null,
): DocumentViewResumeTarget | null {
  if (documentId === null) return null

  return {
    documentId,
    chunkId,
    highlightRange,
    previewAnchor,
    activeTab,
    ...(sourceContext ? { sourceContext } : {}),
  }
}

function sanitizeResumeTarget(target: unknown): DocumentViewResumeTarget | null {
  if (!isRecord(target)) return null

  const documentId = normalizeId(target.documentId)
  if (!documentId) return null
  const sourceContext = sanitizeSourceContext(target.sourceContext, documentId)

  return {
    documentId,
    chunkId: normalizeId(target.chunkId),
    highlightRange: sanitizeHighlightRange(target.highlightRange),
    previewAnchor: sanitizeDocumentPreviewAnchor(target.previewAnchor),
    activeTab: sanitizeDocumentViewTab(target.activeTab),
    ...(sourceContext ? { sourceContext } : {}),
  }
}

function sanitizeDocumentLayoutPatch(patch: unknown): Partial<DocumentViewLayout> {
  const next: Partial<DocumentViewLayout> = {}
  if (!isRecord(patch)) return next

  if (isDocumentViewTab(patch.activeTab)) next.activeTab = patch.activeTab
  if (typeof patch.isExpanded === 'boolean') next.isExpanded = patch.isExpanded
  const panelWidthPx = sanitizePanelWidthPx(patch.panelWidthPx)
  if (panelWidthPx !== undefined) next.panelWidthPx = panelWidthPx
  if (typeof patch.textMode === 'string' && VALID_TEXT_MODES.has(patch.textMode)) {
    next.textMode = patch.textMode as DocumentTextMode
  }

  const chunksScrollTop = sanitizeScrollTop(patch.chunksScrollTop)
  if (chunksScrollTop !== undefined) next.chunksScrollTop = chunksScrollTop

  const textScrollTop = sanitizeScrollTop(patch.textScrollTop)
  if (textScrollTop !== undefined) next.textScrollTop = textScrollTop

  return next
}

function mergeDocumentLayout(current: DocumentViewLayout | undefined, patch: unknown): DocumentViewLayout | null {
  const sanitizedPatch = sanitizeDocumentLayoutPatch(patch)
  const next = current ? { ...current, ...sanitizedPatch } : { ...sanitizedPatch }

  return Object.keys(next).length > 0 ? next : null
}

function restoreDocumentLayouts(value: unknown): Record<string, DocumentViewLayout> {
  if (!isRecord(value)) return {}

  const entries: Array<[string, DocumentViewLayout]> = []
  for (const [key, rawLayout] of Object.entries(value)) {
    const id = normalizeId(key)
    const layout = mergeDocumentLayout(undefined, rawLayout)
    if (id !== null && layout !== null) entries.push([id, layout])
  }
  return Object.fromEntries(entries)
}

function mergePersistedDocumentView(persisted: unknown, current: DocumentViewState): DocumentViewState {
  const authScope = getAuthCacheScope()
  if (!isRecord(persisted) || persisted.authScope !== authScope) return current

  const documentId = normalizeId(persisted.documentId)
  return {
    ...current,
    authScope,
    isOpen: persisted.isOpen === true && documentId !== null,
    documentId,
    highlightChunkId: normalizeId(persisted.highlightChunkId),
    highlightRange: sanitizeHighlightRange(persisted.highlightRange),
    previewAnchor: sanitizeDocumentPreviewAnchor(persisted.previewAnchor),
    sourceContext: sanitizeSourceContext(persisted.sourceContext, documentId),
    activeTab: sanitizeDocumentViewTab(persisted.activeTab) ?? DEFAULT_ACTIVE_TAB,
    documentLayouts: restoreDocumentLayouts(persisted.documentLayouts),
    lastOpenedTarget: sanitizeResumeTarget(persisted.lastOpenedTarget),
  }
}

function readDocumentLayout(
  documentLayouts: Record<string, DocumentViewLayout>,
  documentId: string,
): DocumentViewLayout | undefined {
  return Object.hasOwn(documentLayouts, documentId) ? documentLayouts[documentId] : undefined
}

function patchDocumentLayouts(
  documentId: string | null,
  documentLayouts: Record<string, DocumentViewLayout>,
  patch: Partial<DocumentViewLayout>,
) {
  if (documentId === null) return documentLayouts

  const layout = mergeDocumentLayout(readDocumentLayout(documentLayouts, documentId), patch)
  if (layout !== null) return { ...documentLayouts, [documentId]: layout }

  const nextLayouts = { ...documentLayouts }
  delete nextLayouts[documentId]
  return nextLayouts
}

export const useDocumentView = create<DocumentViewState>()(
  persist(
    (set, get) => ({
      authScope: getAuthCacheScope(),
      isOpen: false,
      documentId: null,
      highlightChunkId: null,
      highlightRange: null,
      previewAnchor: null,
      sourceContext: null,
      activeTab: DEFAULT_ACTIVE_TAB,
      documentLayouts: {},
      lastOpenedTarget: null,

      openDocument: (rawDocumentId, chunkId, range, options) =>
        set((state) => {
          const documentId = normalizeId(rawDocumentId)
          if (!documentId) return state

          const highlightChunkId = normalizeId(chunkId)
          const highlightRange = sanitizeHighlightRange(range)
          const previewAnchor = sanitizeDocumentPreviewAnchor(options?.previewAnchor)
          const sourceContext = sanitizeSourceContext(options?.sourceContext, documentId)
          const preferredActiveTab = sanitizeDocumentViewTab(options?.activeTab)
          const savedLayout = readDocumentLayout(state.documentLayouts, documentId)
          let activeTab = savedLayout?.activeTab ?? DEFAULT_ACTIVE_TAB
          if (preferredActiveTab !== undefined) activeTab = preferredActiveTab
          else if (highlightChunkId !== null || highlightRange !== null) activeTab = 'text'
          const lastOpenedTarget = buildResumeTarget(
            documentId,
            activeTab,
            highlightChunkId,
            highlightRange,
            previewAnchor,
            sourceContext,
          )

          return {
            isOpen: true,
            documentId,
            highlightChunkId,
            highlightRange,
            previewAnchor,
            sourceContext,
            activeTab,
            documentLayouts: patchDocumentLayouts(documentId, state.documentLayouts, { activeTab }),
            lastOpenedTarget,
          }
        }),

      closeDocument: () =>
        set({
          isOpen: false,
          documentId: null,
          highlightChunkId: null,
          highlightRange: null,
          previewAnchor: null,
          sourceContext: null,
        }),

      reopenLastDocument: () =>
        set((state) => {
          const lastOpenedTarget = state.lastOpenedTarget
          if (!lastOpenedTarget) return state

          const savedLayout = readDocumentLayout(state.documentLayouts, lastOpenedTarget.documentId)
          const activeTab = lastOpenedTarget.activeTab ?? savedLayout?.activeTab ?? DEFAULT_ACTIVE_TAB

          return {
            isOpen: true,
            documentId: lastOpenedTarget.documentId,
            highlightChunkId: lastOpenedTarget.chunkId ?? null,
            highlightRange: lastOpenedTarget.highlightRange ?? null,
            previewAnchor: lastOpenedTarget.previewAnchor ?? null,
            sourceContext: lastOpenedTarget.sourceContext ?? null,
            activeTab,
            documentLayouts: patchDocumentLayouts(lastOpenedTarget.documentId, state.documentLayouts, { activeTab }),
            lastOpenedTarget: {
              ...lastOpenedTarget,
              activeTab,
            },
          }
        }),

      setHighlightChunk: (chunkId) =>
        set((state) => {
          const highlightChunkId = normalizeId(chunkId)
          const previewAnchor =
            highlightChunkId !== null && highlightChunkId === state.highlightChunkId ? state.previewAnchor : null
          return {
            highlightChunkId,
            highlightRange: null,
            previewAnchor,
            lastOpenedTarget:
              buildResumeTarget(
                state.documentId,
                state.activeTab,
                highlightChunkId,
                null,
                previewAnchor,
                state.sourceContext,
              ) ?? state.lastOpenedTarget,
          }
        }),

      setHighlightRange: (range) =>
        set((state) => {
          const highlightRange = sanitizeHighlightRange(range)
          return {
            highlightRange,
            lastOpenedTarget:
              buildResumeTarget(
                state.documentId,
                state.activeTab,
                state.highlightChunkId,
                highlightRange,
                state.previewAnchor,
                state.sourceContext,
              ) ?? state.lastOpenedTarget,
          }
        }),

      setActiveTab: (tab) =>
        set((state) => ({
          activeTab: tab,
          documentLayouts: patchDocumentLayouts(state.documentId, state.documentLayouts, { activeTab: tab }),
          lastOpenedTarget:
            buildResumeTarget(
              state.documentId,
              tab,
              state.highlightChunkId,
              state.highlightRange,
              state.previewAnchor,
              state.sourceContext,
            ) ?? state.lastOpenedTarget,
        })),

      getDocumentLayout: (documentId) => {
        const id = normalizeId(documentId)
        if (!id) return null
        return readDocumentLayout(get().documentLayouts, id) ?? null
      },

      setDocumentLayout: (documentId, patch) =>
        set((state) => {
          const id = normalizeId(documentId)
          if (!id) return state

          return { documentLayouts: patchDocumentLayouts(id, state.documentLayouts, patch) }
        }),
    }),
    {
      name: DOCUMENT_VIEW_STORAGE_KEY,
      storage: createJSONStorage(() => getClientStorage() ?? noopStorage),
      partialize: (state) => ({
        authScope: state.authScope,
        isOpen: state.isOpen,
        documentId: state.documentId,
        highlightChunkId: state.highlightChunkId,
        highlightRange: state.highlightRange,
        previewAnchor: state.previewAnchor,
        sourceContext: state.sourceContext,
        activeTab: state.activeTab,
        documentLayouts: state.documentLayouts,
        lastOpenedTarget: state.lastOpenedTarget,
      }),
      merge: mergePersistedDocumentView,
    },
  ),
)

globalThis.window?.addEventListener(AUTH_SCOPE_CHANGED_EVENT, () => {
  useDocumentView.setState({
    authScope: getAuthCacheScope(),
    isOpen: false,
    documentId: null,
    highlightChunkId: null,
    highlightRange: null,
    previewAnchor: null,
    sourceContext: null,
    activeTab: DEFAULT_ACTIVE_TAB,
    documentLayouts: {},
    lastOpenedTarget: null,
  })
  useDocumentView.persist.clearStorage()
})
