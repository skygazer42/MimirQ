'use client'

/**
 * 数据治理页面
 * 流程：解析 → 数据治理 → 切块 → 入库
 */
import dynamic from 'next/dynamic'
import { Navbar } from '@/components/navbar'

const DataGovernancePanel = dynamic(
  () => import('@/components/data-governance-panel').then((mod) => mod.DataGovernancePanel),
  {
    ssr: false,
    loading: () => (
      <div
        role="status"
        aria-live="polite"
        className="flex-1 flex items-center justify-center bg-gray-50"
      >
        <div className="flex items-center gap-3 text-slate-500 font-medium">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-blue-600" />
          <span>正在加载数据治理面板...</span>
          <span className="sr-only">Loading data governance panel</span>
        </div>
      </div>
    ),
  }
)

export default function DataGovernancePage() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden min-h-0">
        <DataGovernancePanel />
      </main>
    </div>
  )
}
