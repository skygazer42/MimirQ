'use client'

import { useCallback } from 'react'
import { useRouter } from 'next/navigation'

import { Navbar } from '@/components/navbar'
import { ChatArea } from '@/components/chat-area'

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
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar />
      <main className="flex-1 flex flex-col overflow-hidden">
        <ChatArea
          initialConversationId={initialConversationId}
          initialPrompt={initialPrompt}
          onConversationId={handleConversationId}
        />
      </main>
    </div>
  )
}
