'use client'

import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'

import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const GovernanceCommonLinesPage = dynamic(
  () =>
    import('@/components/governance-common-lines/governance-common-lines-page').then(
      (mod) => mod.GovernanceCommonLinesPage
    ),
  {
    ssr: false,
    loading: () => <GovernanceCommonLinesRouteLoading />,
  }
)

export default function GovernanceCommonLinesRoutePage() {
  return (
    <NavigationVisibilityGate moduleKey="commonLines" pageName="样板行发现">
      <AppFrame>
        <GovernanceCommonLinesPage />
      </AppFrame>
    </NavigationVisibilityGate>
  )
}

function GovernanceCommonLinesRouteLoading() {
  const t = useTranslations('GovernanceCommonLinesRoutePage')

  return <PageLoading message={t('loading.message')} srMessage={t('loading.srMessage')} />
}
