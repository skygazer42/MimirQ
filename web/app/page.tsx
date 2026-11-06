/**
 * 首页 - 对话界面（服务端读取 searchParams，再交给客户端组件渲染）
 */
import { ChatPageClient } from '@/components/chat-page-client'

type HomeSearchParams = {
  conversation?: string
  prompt?: string
  autorun?: string
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
  const params = await searchParams
  return (
    <ChatPageClient
      initialConversationId={params?.conversation}
      initialPrompt={params?.prompt}
      initialAutoSendPrompt={params?.autorun === '1' || params?.autorun === 'true'}
      initialOpenRagSettings={params?.rag === '1' || params?.rag === 'true'}
      initialDocumentId={params?.doc}
      initialChunkId={params?.chunk}
      initialHighlightStart={params?.start}
      initialHighlightEnd={params?.end}
    />
  )
}
