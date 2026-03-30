'use client'

import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'

import { PageLoading } from '@/components/ui/page-loading'

const ReportsCenterPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => <ReportsLoading />,
})

export default function ReportsCenterPage() {
  return <ReportsCenterPageClient />
}

function ReportsLoading() {
  const t = useTranslations('Reports')

  return (
    <PageLoading
      className="min-h-dvh bg-background"
      message={t('loadingPage')}
      srMessage={t('loadingPageSr')}
    />
  )
}
