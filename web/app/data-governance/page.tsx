'use client'

/**
 * 数据治理页面
 * 流程：解析 → 数据治理 → 切块 → 入库
 */
import dynamic from 'next/dynamic'
import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const DataGovernancePanel = dynamic(
  () => import('@/components/data-governance-panel').then((mod) => mod.DataGovernancePanel),
  {
    ssr: false,
    loading: () => <PageLoading message="正在加载数据治理面板..." srMessage="Loading data governance panel" />,
  }
)

export default function DataGovernancePage() {
  return (
    <AppFrame>
      <DataGovernancePanel />
    </AppFrame>
  )
}
