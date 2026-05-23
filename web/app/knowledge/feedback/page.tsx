'use client'

import dynamic from 'next/dynamic'

import { PageLoading } from '@/components/ui/page-loading'

const FeedbackTriagePageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => (
    <PageLoading
      className="min-h-dvh bg-background"
      message="正在加载反馈分析中心..."
      srMessage="Loading feedback analytics workbench"
    />
  ),
})

export default function FeedbackTriagePage() {
  return <FeedbackTriagePageClient />
}
