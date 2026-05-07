import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieval ablations visual layout', () => {
  it('matches the three-card ablation workspace reference', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieval-ablations-page.tsx'), 'utf8')

    expect(src).toContain('function AblationDatasetCard')
    expect(src).toContain('function AblationLeaderboardEmptyState')
    expect(src).toContain('function AblationDiffEmptyState')
    expect(src).toContain('scale-[0.9]')
    expect(src).toContain('w-[111.111%]')
    expect(src).toContain('h-[111.111%]')
    expect(src).toContain('grid-cols-[390px_420px_minmax(0,1fr)]')
    expect(src).toContain('rounded-2xl border border-slate-200 bg-white')
    expect(src).toContain('shadow-[0_8px_24px_rgba(15,23,42,0.05)]')
    expect(src).toContain('aria-label="刷新消融实验数据"')
    expect(src).toContain('等待生成 Diff')
    expect(src).toContain('选择基线 Run（Base）')
    expect(src).toContain('选择候选 Run（Target）')
    expect(src).toContain('ablation-empty-illustration')
    expect(src).not.toContain("leftSidebarCollapsed ? 'w-0 overflow-hidden opacity-0 border-r-0' : 'w-[304px] opacity-100'")
    expect(src).not.toContain("leaderboardCollapsed ? 'w-0 overflow-hidden opacity-0 border-r-0 pointer-events-none' : 'w-[340px] opacity-100 xl:w-[360px]'")
  })
})
