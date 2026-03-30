/**
 * 对话历史页面
 */
import HistoryPageClient from './page-client'

import { getServerHistoryPageData } from '@/lib/server-history-page-data'

type HistorySearchParams = {
  id?: string
}

export default async function HistoryPage({
  searchParams,
}: Readonly<{
  searchParams?: Promise<HistorySearchParams>
}>) {
  const sp = await searchParams
  const initialData = await getServerHistoryPageData(sp?.id)

  return <HistoryPageClient {...initialData} />
}
