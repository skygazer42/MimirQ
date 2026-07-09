'use client'

import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'

import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { AppFrame } from '@/components/app-frame'
import { KNOWLEDGE_OPS_BACKGROUND_CLASS } from '@/components/ui/knowledge-ops-hero'
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
    <NavigationVisibilityGate moduleKey="governanceProfiles" pageName="治理配置">
      <AppFrame>
        <div className={KNOWLEDGE_OPS_BACKGROUND_CLASS}>
          <GovernanceProfilesPage />
        </div>
      </AppFrame>
    </NavigationVisibilityGate>
  )
}

function GovernanceProfilesRouteLoading() {
  const t = useTranslations('GovernanceProfilesRoutePage')

  return <PageLoading message={t('loading.message')} srMessage={t('loading.srMessage')} />
}
