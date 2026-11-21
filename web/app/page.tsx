import { ChatPageClient } from '@/components/chat-page-client'

type SearchParamValue = string | string[] | undefined

function firstSearchParam(value: SearchParamValue): string | undefined {
  return Array.isArray(value) ? value[0] : value
}

function isEnabledSearchParam(value: SearchParamValue): boolean {
  return value === '1' || value === 'true'
}

function readHighlightOffset(value: SearchParamValue): number | undefined {
  const text = firstSearchParam(value)?.trim()
  if (text === undefined || !/^\d+$/.test(text)) return undefined
  const offset = Number(text)
  return Number.isSafeInteger(offset) ? offset : undefined
}

export default async function Home({
  searchParams,
}: Readonly<{ searchParams: Promise<Record<string, SearchParamValue>> }>) {
  const params = await searchParams
  const prompt = typeof params.prompt === 'string' ? params.prompt : undefined

  return (
    <ChatPageClient
      initialConversationId={firstSearchParam(params.conversation)}
      initialPrompt={prompt}
      initialAutoSendPrompt={prompt !== undefined && isEnabledSearchParam(params.autorun)}
      initialOpenRagSettings={isEnabledSearchParam(params.rag)}
      initialDocumentId={firstSearchParam(params.doc)}
      initialChunkId={firstSearchParam(params.chunk)}
      initialHighlightStart={readHighlightOffset(params.start)}
      initialHighlightEnd={readHighlightOffset(params.end)}
    />
  )
}
