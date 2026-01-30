'use client'

import dynamic from 'next/dynamic'

import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const GovernanceCommonLinesPage = dynamic(
  () =>
    import('@/components/governance-common-lines/governance-common-lines-page').then(
      (mod) => mod.GovernanceCommonLinesPage
    ),
  {
    ssr: false,
    loading: () => <PageLoading message="正在加载 Common Lines 学习..." srMessage="Loading common lines learning page" />,
  }
)

export default function GovernanceCommonLinesRoutePage() {
  return (
    <AppFrame>
      <GovernanceCommonLinesPage />
    </AppFrame>
  )
}

