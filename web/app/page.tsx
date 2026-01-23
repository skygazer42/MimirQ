/**
 * 首页 - 对话界面（服务端读取 searchParams，再交给客户端组件渲染）
 */
import { ChatPageClient } from '@/components/chat-page-client'

export default function Home({
  searchParams,
}: {
  searchParams?: {
    conversation?: string
    prompt?: string
    rag?: string
    doc?: string
    chunk?: string
  }
}) {
  return (
    <ChatPageClient
      initialConversationId={searchParams?.conversation}
      initialPrompt={searchParams?.prompt}
      initialOpenRagSettings={searchParams?.rag === '1' || searchParams?.rag === 'true'}
      initialDocumentId={searchParams?.doc}
      initialChunkId={searchParams?.chunk}
    />
  )
}
