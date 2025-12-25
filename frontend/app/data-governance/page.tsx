'use client'

/**
 * 数据治理页面
 * 流程：解析 → 数据治理 → 切块 → 入库
 */
import { Navbar } from '@/components/navbar'
import { DataGovernancePanel } from '@/components/data-governance-panel'

export default function DataGovernancePage() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden">
        <DataGovernancePanel />
      </main>
    </div>
  )
}
