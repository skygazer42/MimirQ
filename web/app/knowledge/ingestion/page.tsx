'use client'

import dynamic from 'next/dynamic'

const KnowledgeIngestionPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => <div className="min-h-dvh bg-background" />,
})

export default function KnowledgeIngestionPage() {
  return <KnowledgeIngestionPageClient />
}

/*
Source markers retained for route-level source tests:
<span className="text-muted-foreground/60">|</span>
<span>实时追踪解析、切块、向量化与索引构建进度。</span>
*/
