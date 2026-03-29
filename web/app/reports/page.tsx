'use client'

import dynamic from 'next/dynamic'

import { PageLoading } from '@/components/ui/page-loading'

const ReportsCenterPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => (
    <PageLoading
      className="min-h-dvh bg-background"
      message="正在加载报告中心..."
      srMessage="Loading reports center"
    />
  ),
})

export default function ReportsCenterPage() {
  return <ReportsCenterPageClient />
}
