'use client'

import dynamic from 'next/dynamic'
import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const GovernanceProfilesPage = dynamic(
  () =>
    import('@/components/governance-profiles/governance-profiles-page').then(
      (mod) => mod.GovernanceProfilesPage
    ),
  {
    ssr: false,
    loading: () => <PageLoading message="正在加载治理 Profiles..." srMessage="Loading governance profiles page" />,
  }
)

export default function GovernanceProfilesRoutePage() {
  return (
    <AppFrame>
      <GovernanceProfilesPage />
    </AppFrame>
  )
}

