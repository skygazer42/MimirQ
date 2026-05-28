import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieval ablations visual layout', () => {
  it('matches the three-card ablation workspace reference', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'retrieval-ablations-page.tsx'),
      'utf8'
    )

    expect(src).toContain('function AblationDatasetCard')
    expect(src).toContain('function AblationLeaderboardEmptyState')
    expect(src).toContain('function AblationDiffEmptyState')
    expect(src).toContain('scale-[0.9]')
    expect(src).toContain('w-[111.111%]')
    expect(src).toContain('h-[111.111%]')
    expect(src).toContain('grid-cols-[390px_minmax(0,1fr)_360px]')
    expect(src).toContain('grid-cols-[minmax(0,1fr)_360px]')
    expect(src).toContain('order-3 flex min-h-0 flex-col')
    expect(src).toContain('relative order-2 min-w-0')
    expect(src).toContain('absolute right-0 z-20 translate-x-1/2')
    expect(src).toContain('rounded-2xl border border-slate-200 bg-card')
    expect(src).toContain('shadow-[0_8px_24px_rgba(15,23,42,0.05)]')
    expect(src).toContain('aria-label="刷新消融实验数据"')
    expect(src).toContain('等待生成差异对比')
    expect(src).toContain('选择基线运行')
    expect(src).toContain('选择候选运行')
    expect(src).toContain('bg-info text-white shadow-sm')
    expect(src).toContain('bg-info px-1.5 py-0.5 text-[9px] font-medium text-white')
    expect(src).toContain('bg-info px-4 text-[13px] text-white')
    expect(src).toContain('差异对比工作区')
    expect(src).toContain('实验排行')
    expect(src).toContain('ablation-empty-illustration')
    expect(src).not.toContain('bg-foreground text-background shadow-sm')
    expect(src).not.toContain('bg-slate-950 px-4 text-[13px] text-info-foreground')
    expect(src).not.toContain('Leaderboard / 实验排行')
    expect(src).not.toContain('Diff Workspace / 基线 vs 候选')
    expect(src).not.toContain('Diff Delta')
    expect(src).not.toContain('BASE')
    expect(src).not.toContain('TARGET')
    expect(src).not.toContain(
      "leftSidebarCollapsed ? 'w-0 overflow-hidden opacity-0 border-r-0' : 'w-[304px] opacity-100'"
    )
    expect(src).not.toContain(
      "leaderboardCollapsed ? 'w-0 overflow-hidden opacity-0 border-r-0 pointer-events-none' : 'w-[340px] opacity-100 xl:w-[360px]'"
    )
  })
})
