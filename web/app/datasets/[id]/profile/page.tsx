'use client'

import dynamic from 'next/dynamic'

import { PageLoading } from '@/components/ui/page-loading'

const DatasetProfilePageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => (
    <PageLoading
      className="min-h-dvh bg-background"
      message="正在加载数据集画像..."
      srMessage="Loading dataset profile"
    />
  ),
})

export default function DatasetProfilePage() {
  return <DatasetProfilePageClient />
}
