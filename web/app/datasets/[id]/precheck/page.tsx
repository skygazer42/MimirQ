'use client'

import dynamic from 'next/dynamic'
import { PageLoading } from '@/components/ui/page-loading'

const DatasetPrecheckPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => (
    <PageLoading
      className="min-h-dvh bg-background"
      message="正在加载预检洞察..."
      srMessage="Loading dataset precheck insights"
    />
  ),
})

export default function DatasetPrecheckPage() {
  return <DatasetPrecheckPageClient />
}
