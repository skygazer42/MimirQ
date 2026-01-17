'use client'

import { useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { cn } from '@/lib/utils'

import { Navbar } from '@/components/navbar'
import { ChatArea } from '@/components/chat-area'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { useDocumentView } from '@/store/document-view'

export function ChatPageClient({
  initialConversationId,
  initialPrompt,
}: {
  initialConversationId?: string
  initialPrompt?: string
}) {
  const router = useRouter()
  const { isOpen } = useDocumentView()

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
    <div className="flex h-screen overflow-hidden bg-background">
      <Navbar />
      <main 
        className={cn(
            "flex-1 flex flex-col overflow-hidden transition-all duration-300 ease-in-out",
            isOpen ? "mr-[40vw] xl:mr-[40vw] lg:mr-[500px]" : "mr-0"
        )}
      >
        <ChatArea
          initialConversationId={initialConversationId}
          initialPrompt={initialPrompt}
          onConversationId={handleConversationId}
        />
      </main>
      <DocumentViewerPanel />
    </div>
  )
}
