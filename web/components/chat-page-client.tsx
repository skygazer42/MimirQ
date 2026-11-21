'use client'

import { useCallback, useEffect } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'

import { AppFrame } from '@/components/app-frame'
import { ChatArea } from '@/components/chat-area'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { useRouter } from '@/i18n/navigation'
import { useDocumentView } from '@/store/document-view'

function clearConsumedChatParams(pathname: string, consumedParams: Readonly<Record<string, string>>) {
  const url = new URL(window.location.href)
  if (url.pathname !== pathname) return
  for (const [key, value] of Object.entries(consumedParams)) {
    if (url.searchParams.get(key) !== value) return
    url.searchParams.delete(key)
  }
  window.history.replaceState(null, '', url)
}

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
  initialHighlightStart?: number
  initialHighlightEnd?: number
}>) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const promptParam = searchParams.get('prompt')
  const autorunParam = searchParams.get('autorun')
  const ragParam = searchParams.get('rag')
  const prompt = promptParam === initialPrompt ? initialPrompt : undefined
  const shouldAutoSendPrompt = initialAutoSendPrompt === true && (autorunParam === '1' || autorunParam === 'true')
  const shouldOpenRagSettings = initialOpenRagSettings === true && (ragParam === '1' || ragParam === 'true')
  const openDocument = useDocumentView((state) => state.openDocument)

  const handleConversationId = useCallback(
    (conversationId: string) => {
      if (conversationId === initialConversationId) return
      const url = new URL(window.location.href)
      if (url.pathname !== pathname || url.searchParams.get('conversation') !== (initialConversationId ?? null)) return
      url.searchParams.set('conversation', conversationId)
      router.replace(`/${url.search}${url.hash}`)
    },
    [router, pathname, initialConversationId],
  )

  const handlePromptConsumed = useCallback(() => {
    if (prompt === undefined || !shouldAutoSendPrompt) return
    clearConsumedChatParams(pathname, { prompt, autorun: autorunParam })
  }, [pathname, prompt, shouldAutoSendPrompt, autorunParam])

  useEffect(() => {
    if (shouldOpenRagSettings) clearConsumedChatParams(pathname, { rag: ragParam })
  }, [pathname, shouldOpenRagSettings, ragParam])

  useEffect(() => {
    if (initialDocumentId === undefined) return
    const range =
      initialHighlightStart !== undefined &&
      initialHighlightEnd !== undefined &&
      initialHighlightEnd > initialHighlightStart
        ? { start: initialHighlightStart, end: initialHighlightEnd }
        : undefined
    openDocument(initialDocumentId, initialChunkId, range)
  }, [initialDocumentId, initialChunkId, initialHighlightStart, initialHighlightEnd, openDocument])

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding>
      <ChatArea
        initialConversationId={initialConversationId}
        initialPrompt={prompt}
        initialAutoSendPrompt={shouldAutoSendPrompt}
        initialOpenRagSettings={shouldOpenRagSettings}
        onConversationId={handleConversationId}
        onPromptConsumed={handlePromptConsumed}
      />
    </AppFrame>
  )
}
