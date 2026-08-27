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
})
