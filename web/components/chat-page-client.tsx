'use client'

import { useCallback, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { AppFrame } from '@/components/app-frame'
import { ChatArea } from '@/components/chat-area'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { useDocumentView } from '@/store/document-view'

export function ChatPageClient({
  initialConversationId,
  initialPrompt,
  initialOpenRagSettings,
  initialDocumentId,
  initialChunkId,
}: {
  initialConversationId?: string
  initialPrompt?: string
  initialOpenRagSettings?: boolean
  initialDocumentId?: string
  initialChunkId?: string
}) {
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
    openDocument(docId, chunkId)
  }, [initialDocumentId, initialChunkId, openDocument])

  return (
    <AppFrame
      rightPanel={<DocumentViewerPanel />}
      withDocumentViewerPadding
      mainClassName="transition-all duration-300 ease-in-out"
    >
      <ChatArea
        initialConversationId={initialConversationId}
        initialPrompt={initialPrompt}
        initialOpenRagSettings={initialOpenRagSettings}
        onConversationId={handleConversationId}
      />
    </AppFrame>
  )
}
