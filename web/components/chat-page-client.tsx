'use client'

import { useCallback, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { AppFrame } from '@/components/app-frame'
import { ChatArea } from '@/components/chat-area'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'

export function ChatPageClient({
  initialConversationId,
  initialPrompt,
  initialOpenRagSettings,
}: {
  initialConversationId?: string
  initialPrompt?: string
  initialOpenRagSettings?: boolean
}) {
  const router = useRouter()
  const searchParams = useSearchParams()

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
