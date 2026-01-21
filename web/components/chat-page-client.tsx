'use client'

import { useCallback } from 'react'
import { useRouter } from 'next/navigation'

import { AppFrame } from '@/components/app-frame'
import { ChatArea } from '@/components/chat-area'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'

export function ChatPageClient({
  initialConversationId,
  initialPrompt,
}: {
  initialConversationId?: string
  initialPrompt?: string
}) {
  const router = useRouter()

  const handleConversationId = useCallback(
    (conversationId: string) => {
      const id = (conversationId || '').trim()
      if (!id) return
      if (id === (initialConversationId || '')) return
      router.replace(`/?conversation=${encodeURIComponent(id)}`)
    },
    [router, initialConversationId]
  )

  return (
    <AppFrame
      rightPanel={<DocumentViewerPanel />}
      withDocumentViewerPadding
      mainClassName="transition-all duration-300 ease-in-out"
    >
      <ChatArea
        initialConversationId={initialConversationId}
        initialPrompt={initialPrompt}
        onConversationId={handleConversationId}
      />
    </AppFrame>
  )
}
