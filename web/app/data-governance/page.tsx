'use client'

/**
 * 数据治理页面
 * 流程：解析 → 数据治理 → 切块 → 入库
 */
import dynamic from 'next/dynamic'
import { Navbar } from '@/components/navbar'
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
    <div className="flex h-screen overflow-hidden bg-white font-sans selection:bg-cyan-500/20 selection:text-cyan-600">
      {/* Ambient Background */}
      <div className="fixed inset-0 z-0 pointer-events-none">
        <div className="absolute top-[-20%] left-[-10%] w-[800px] h-[800px] bg-cyan-500/5 rounded-full blur-[120px] animate-pulse-subtle" />
        <div className="absolute bottom-[-10%] right-[-20%] w-[600px] h-[600px] bg-blue-600/5 rounded-full blur-[120px] animate-pulse-subtle" style={{ animationDelay: '2s' }} />
      </div>

      <Navbar />

      <main className="relative z-10 flex-1 flex flex-col overflow-hidden min-h-0">
        <DataGovernancePanel />
      </main>
    </div>
  )
}
