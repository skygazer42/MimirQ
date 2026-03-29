'use client'

import dynamic from 'next/dynamic'
import { PageLoading } from '@/components/ui/page-loading'

const DatasetHealthPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => (
    <PageLoading
      className="min-h-dvh bg-background"
      message="正在加载数据集健康状况..."
      srMessage="Loading dataset health overview"
    />
  ),
})

export default function DatasetHealthPage() {
  return <DatasetHealthPageClient />
}
