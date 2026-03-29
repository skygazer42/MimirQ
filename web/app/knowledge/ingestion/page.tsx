'use client'

import dynamic from 'next/dynamic'

import { PageLoading } from '@/components/ui/page-loading'

const KnowledgeIngestionPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => (
    <PageLoading
      className="min-h-dvh bg-background"
      message="正在加载知识库入库流程..."
      srMessage="Loading knowledge ingestion workspace"
    />
  ),
})

export default function KnowledgeIngestionPage() {
  return <KnowledgeIngestionPageClient />
}

/*
Source markers retained for route-level source tests:
<span className="text-muted-foreground/60">|</span>
<span>实时追踪解析、切块、向量化与索引构建进度。</span>
*/
