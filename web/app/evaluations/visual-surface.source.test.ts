// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readSource(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('analysis and observability surfaces stay crisp', () => {
  it('keeps evaluation stage surfaces free of blur-heavy floating cards and decorative gradients', () => {
    const src = readSource('./page.tsx')

    expect(src).not.toContain('backdrop-blur')
    expect(src).not.toContain('shadow-lg')
    expect(src).not.toContain('shadow-xl')
    expect(src).not.toContain('shadow-md')
    expect(src).not.toContain('bg-[linear-gradient(90deg,hsl(var(--card)),hsl(var(--info)/0.08))]')
    expect(src).not.toContain('bg-[linear-gradient(135deg,hsl(var(--card)),hsl(var(--muted)/0.55),hsl(var(--info)/0.12))]')
    expect(src).not.toContain('bg-[linear-gradient(180deg,hsl(var(--muted)/0.34),hsl(var(--card)))]')
    expect(src).not.toContain('bg-[linear-gradient(135deg,hsl(var(--info)/0.08),hsl(var(--primary)/0.07),hsl(var(--info)/0.10))]')
    expect(src).not.toContain('shadow-[0_10px_28px_hsl(var(--primary)/0.12)]')
  })

  it('keeps reports and diagnostics panels on flat surfaces', () => {
    const reportsControlSrc = readSource('../reports/components/reports-control-panel.tsx')
    const reportTokensSrc = readSource('../reports/report-tokens.ts')
    const diagnosticsSrc = readSource('../diagnostics/page-client.tsx')

    expect(reportsControlSrc).not.toContain('backdrop-blur')
    expect(reportsControlSrc).not.toContain('shadow-[0_18px_44px_-36px_rgba(15,23,42,0.35)]')
    expect(reportsControlSrc).not.toContain('shadow-[0_24px_70px_-28px_rgba(15,23,42,0.38)]')

    expect(reportTokensSrc).not.toContain('shadow-[0_16px_36px_-30px_rgba(15,23,42,0.28)]')
    expect(reportTokensSrc).not.toContain('shadow-[0_12px_24px_-14px_rgba(2,132,199,0.8)]')
    expect(reportTokensSrc).not.toContain('shadow-[0_18px_42px_-34px_rgba(15,23,42,0.35)]')

    expect(diagnosticsSrc).not.toContain(
      'bg-[linear-gradient(135deg,hsl(var(--primary)/0.10),hsl(var(--card))_48%,hsl(var(--accent)/0.08))]'
    )
    expect(diagnosticsSrc).not.toContain('shadow-[0_10px_24px_hsl(var(--primary)/0.05)]')
    expect(diagnosticsSrc).not.toContain('shadow-[0_10px_24px_hsl(var(--primary)/0.18)]')
  })

  it('keeps evaluation workspace surfaces in the Ocean color family', () => {
    const src = readSource('./page.tsx')

    expect(src).toContain(
      'relative flex flex-1 flex-col overflow-hidden bg-info/[0.035]'
    )
    expect(src).toContain(
      'overflow-hidden rounded-2xl border border-info/15 bg-background/72 shadow-none'
    )
    expect(src).toContain(
      'overflow-hidden rounded-[28px] border border-info/15 bg-background/78 shadow-none'
    )
    expect(src).toContain(
      'rounded-2xl border border-info/15 bg-background/70 px-3.5 py-3 shadow-none'
    )
    expect(src).toContain(
      'flex min-h-[620px] flex-col rounded-2xl border border-info/15 bg-background/78 shadow-none xl:h-full xl:min-h-0'
    )
    expect(src).toContain(
      'flex min-h-[420px] flex-col overflow-hidden rounded-2xl border border-info/15 bg-background/78 p-3 shadow-none xl:h-full xl:min-h-0'
    )
    expect(src).toContain(
      'rounded-2xl border border-dashed border-info/20 bg-info/[0.025] p-4'
    )
    expect(src).not.toContain(
      'overflow-hidden rounded-[28px] border border-info/20 bg-card shadow-none'
    )
    expect(src).not.toContain(
      'flex min-h-0 max-h-[calc(100vh-246px)] flex-col rounded-2xl border border-info/20 bg-card shadow-none'
    )
  })

  it('extends every evaluation workbench to the remaining viewport height', () => {
    const src = readSource('./page.tsx')

    expect(src).toContain('bodyClassName="flex flex-col !pt-0 !pb-0"')
    expect(src).toContain(
      'bodyContainerClassName="flex min-h-0 max-w-none flex-1 flex-col"'
    )
    expect(src).toContain(
      "cn('grid min-h-[610px] gap-3 xl:flex-1', conversationDesktopGridClass)"
    )
    expect(src).toContain(
      'flex min-h-[610px] min-w-0 flex-col gap-3 xl:min-h-0'
    )
    expect(src).toContain(
      'flex min-h-[610px] flex-1 flex-col overflow-hidden rounded-xl border border-info/15 bg-background/78 p-2.5 shadow-none'
    )
    expect(src).toContain(
      'flex min-h-[610px] flex-1 flex-col rounded-xl border border-info/15 bg-background/78 p-3 shadow-none'
    )
    expect(src).not.toContain('h-[calc(100vh-255px)]')
    expect(src).not.toContain('max-h-[calc(100vh-246px)]')
  })

  it('aligns Golden and queryset-health workbenches with Ocean surfaces', () => {
    const pageSrc = readSource('./page.tsx')
    const regressionSrc = readSource('../../components/evaluation/regression-tab.tsx')
    const healthSrc = readSource('../../components/evaluation/queryset-health-tab-client.tsx')
    const testCaseManagerSrc = readSource('../../components/test-case-manager.tsx')

    expect(pageSrc).toContain("badge: '回归基线'")
    expect(pageSrc).toContain("badge: '健康监测'")
    expect(pageSrc).toContain('label={activeTabMeta.badge}')

    expect(regressionSrc).toContain(
      'rounded-[28px] border border-info/15 bg-background/72 shadow-none'
    )
    expect(regressionSrc).toContain(
      'flex flex-col bg-background/72 rounded-2xl border border-info/15'
    )
    expect(regressionSrc).toContain(
      "embedded && 'rounded-[28px] border-info/15 bg-background/72'"
    )
    expect(regressionSrc).not.toContain('bg-[radial-gradient(')
    expect(regressionSrc).not.toContain(
      'shadow-[0_16px_40px_rgba(15,23,42,0.04)]'
    )
    expect(testCaseManagerSrc).not.toContain('bg-[#fffef9]')
    expect(testCaseManagerSrc).toContain(
      "dense\n            ? 'border-info/15 bg-info/[0.025] px-3 py-3'"
    )

    expect(healthSrc).toContain(
      'rounded-2xl border-info/15 bg-background/72 shadow-none'
    )
    expect(healthSrc).toContain(
      'rounded-2xl bg-background/70 px-4 py-3 text-center shadow-none ring-1 ring-info/15'
    )
    expect(healthSrc).not.toContain(
      'rounded-2xl border-border/60 bg-card shadow-none'
    )
  })
})
