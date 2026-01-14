/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'

export function Workbench() {
  return (
    <div className="relative flex flex-col h-full bg-[#F8FAFC] text-slate-900 font-sans overflow-hidden">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(14,165,233,0.18),transparent_55%),radial-gradient(circle_at_top_right,rgba(99,102,241,0.12),transparent_50%),radial-gradient(circle_at_bottom_left,rgba(59,130,246,0.12),transparent_55%)]" />
        <div className="absolute inset-0 opacity-[0.04] bg-[radial-gradient(#0f172a_1px,transparent_1px)] [background-size:18px_18px]" />
      </div>
      <div className="relative z-10 flex flex-col h-full">
      {/* 顶部栏 */}
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧配置栏 */}
        <Sidebar />

        {/* 主区域：原文 vs 预览 */}
        <main className="flex-1 flex overflow-hidden bg-slate-50/60">
          {/* 左侧原文 */}
          <OriginalPreview />

          {/* 右侧切片 */}
          <ChunkList />
        </main>
      </div>
      </div>
    </div>
  )
}
