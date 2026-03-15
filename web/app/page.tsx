/**
 * 首页 - 对话界面（服务端读取 searchParams，再交给客户端组件渲染）
 */
import { ChatPageClient } from '@/components/chat-page-client'

type HomeSearchParams = {
  conversation?: string
  prompt?: string
  rag?: string
  doc?: string
  chunk?: string
  start?: string
  end?: string
}

export default async function Home({
  searchParams,
}: Readonly<{
  // Next.js 16 types this as a Promise in app router PageProps.
  searchParams?: Promise<HomeSearchParams>
}>) {
  const sp = await searchParams
  return (
    <ChatPageClient
      initialConversationId={sp?.conversation}
      initialPrompt={sp?.prompt}
      initialOpenRagSettings={sp?.rag === '1' || sp?.rag === 'true'}
      initialDocumentId={sp?.doc}
      initialChunkId={sp?.chunk}
      initialHighlightStart={sp?.start}
      initialHighlightEnd={sp?.end}
    />
  )
}
