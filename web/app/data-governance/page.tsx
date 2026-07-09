'use client'

/**
 * 数据治理页面
 * 流程：解析 → 数据治理 → 切块 → 入库
 */
import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'

import { AppFrame } from '@/components/app-frame'
import { KNOWLEDGE_OPS_BACKGROUND_CLASS } from '@/components/ui/knowledge-ops-hero'
import { PageLoading } from '@/components/ui/page-loading'

const DataGovernancePanel = dynamic(
  () => import('@/components/data-governance-panel').then((mod) => mod.DataGovernancePanel),
  {
    ssr: false,
    loading: () => <DataGovernancePageLoading />,
  }
)

export default function DataGovernancePage() {
  return (
    <AppFrame>
      <div className={KNOWLEDGE_OPS_BACKGROUND_CLASS}>
        <DataGovernancePanel />
      </div>
    </AppFrame>
  )
}

function DataGovernancePageLoading() {
  const t = useTranslations('DataGovernancePage')

  return <PageLoading message={t('loading.message')} srMessage={t('loading.srMessage')} />
}
