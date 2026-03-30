'use client'

import { useCallback, useEffect } from 'react'
import { useSearchParams } from 'next/navigation'

import { AppFrame } from '@/components/app-frame'
import { ChatArea } from '@/components/chat-area'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { useRouter } from '@/i18n/navigation'
import { useDocumentView } from '@/store/document-view'

export function ChatPageClient({
  initialConversationId,
  initialPrompt,
  initialAutoSendPrompt,
  initialOpenRagSettings,
  initialDocumentId,
  initialChunkId,
  initialHighlightStart,
  initialHighlightEnd,
}: Readonly<{
  initialConversationId?: string
  initialPrompt?: string
  initialAutoSendPrompt?: boolean
  initialOpenRagSettings?: boolean
  initialDocumentId?: string
  initialChunkId?: string
  initialHighlightStart?: string
  initialHighlightEnd?: string
}>) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { openDocument } = useDocumentView()

  const handleConversationId = useCallback(
    (conversationId: string) => {
      const id = (conversationId || '').trim()
      if (!id) return
      if (id === (initialConversationId || '')) return
      router.replace(`/?conversation=${encodeURIComponent(id)}`)
    },
    [router, initialConversationId]
  )

  // If we used `?rag=1` to open the popover, clean it up so the URL stays stable.
  useEffect(() => {
    if (!initialOpenRagSettings) return
    if (!searchParams?.get('rag')) return
    const params = new URLSearchParams(searchParams.toString())
    params.delete('rag')
    const qs = params.toString()
    router.replace(qs ? `/?${qs}` : '/')
  }, [initialOpenRagSettings, router, searchParams])

  // Deep link: open document viewer from query params (used by "copy link" actions).
  useEffect(() => {
    const docId = (initialDocumentId || '').trim()
    if (!docId) return
    const chunkId = (initialChunkId || '').trim() || undefined
    const start = initialHighlightStart == null ? Number.NaN : Number.parseInt(String(initialHighlightStart), 10)
    const end = initialHighlightEnd == null ? Number.NaN : Number.parseInt(String(initialHighlightEnd), 10)
    const range =
      Number.isFinite(start) && Number.isFinite(end) && end > start ? { start, end } : undefined
    openDocument(docId, chunkId, range)
  }, [initialDocumentId, initialChunkId, initialHighlightStart, initialHighlightEnd, openDocument])

  return (
    <AppFrame
      rightPanel={<DocumentViewerPanel />}
      withDocumentViewerPadding
    >
      <ChatArea
        initialConversationId={initialConversationId}
        initialPrompt={initialPrompt}
        initialAutoSendPrompt={initialAutoSendPrompt}
        initialOpenRagSettings={initialOpenRagSettings}
        onConversationId={handleConversationId}
      />
    </AppFrame>
  )
}
