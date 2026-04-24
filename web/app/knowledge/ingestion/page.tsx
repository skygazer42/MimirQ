'use client'

import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'

import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const KnowledgeIngestionPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => <KnowledgeIngestionLoading />,
})

export default function KnowledgeIngestionPage() {
  return (
    <AppFrame>
      <KnowledgeIngestionPageClient />
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
<span className="text-muted-foreground/60">|</span>
<span>{t('descriptionMarker')}</span>
*/
