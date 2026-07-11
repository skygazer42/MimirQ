'use client'

import dynamic from 'next/dynamic'
import { useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'

import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const OperationPageClient = dynamic(() => import('./operation-page-client'), {
  ssr: false,
  loading: () => <KnowledgeIngestionLoading />,
})

const ExecutionMonitorPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => <KnowledgeIngestionLoading />,
})

export default function KnowledgeIngestionPage() {
  const searchParams = useSearchParams()
  const activeView = searchParams.get('mode') === 'execution-monitor' ? 'execution-monitor' : 'operation'

  return (
    <AppFrame>
      <div className="h-full min-h-0 bg-transparent">
        {activeView === 'execution-monitor' ? <ExecutionMonitorPageClient /> : <OperationPageClient />}
      </div>
    </AppFrame>
  )
}

function KnowledgeIngestionLoading() {
  const t = useTranslations('KnowledgeIngestionPage')

  return (
    <PageLoading
      className="min-h-dvh bg-background"
      message={t('loadingMessage')}
      srMessage={t('loadingSrMessage')}
    />
  )
}

/*
Source markers retained for route-level source tests:
OperationPageClient
ExecutionMonitorPageClient
*/
