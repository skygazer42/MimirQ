'use client'

import dynamic from 'next/dynamic'
import { useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useEffect, useState } from 'react'

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
  const showMonitor = searchParams.get('mode') === 'execution-monitor'
  const [visitedOperation, setVisitedOperation] = useState(!showMonitor)

  useEffect(() => {
    if (!showMonitor) setVisitedOperation(true)
  }, [showMonitor])

  return (
    <AppFrame>
      <div className="flex h-full min-h-0 flex-col bg-transparent">
        {(!showMonitor || visitedOperation) && (
          <div className="h-full min-h-0" hidden={showMonitor}>
            <OperationPageClient active={!showMonitor} />
          </div>
        )}
        {showMonitor && <ExecutionMonitorPageClient />}
      </div>
    </AppFrame>
  )
}

function KnowledgeIngestionLoading() {
  const t = useTranslations('KnowledgeIngestionPage')

  return (
    <PageLoading className="min-h-dvh bg-background" message={t('loadingMessage')} srMessage={t('loadingSrMessage')} />
  )
}
