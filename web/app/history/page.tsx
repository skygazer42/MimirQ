/**
 * 对话历史页面
 */
import HistoryPageClient from './page-client'

type HistorySearchParams = {
  id?: string
}

export default async function HistoryPage({
  searchParams,
}: Readonly<{
  searchParams?: Promise<HistorySearchParams>
}>) {
  const sp = await searchParams
  return <HistoryPageClient initialConversationId={sp?.id || null} />
}
