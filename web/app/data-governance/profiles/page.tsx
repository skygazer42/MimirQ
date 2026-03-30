'use client'

import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'

import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const GovernanceProfilesPage = dynamic(
  () =>
    import('@/components/governance-profiles/governance-profiles-page').then(
      (mod) => mod.GovernanceProfilesPage
    ),
  {
    ssr: false,
    loading: () => <GovernanceProfilesRouteLoading />,
  }
)

export default function GovernanceProfilesRoutePage() {
  return (
    <AppFrame>
      <GovernanceProfilesPage />
    </AppFrame>
  )
}

function GovernanceProfilesRouteLoading() {
  const t = useTranslations('GovernanceProfilesRoutePage')

  return <PageLoading message={t('loading.message')} srMessage={t('loading.srMessage')} />
}
