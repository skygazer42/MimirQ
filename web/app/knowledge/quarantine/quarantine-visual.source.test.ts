import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readComponent(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('quarantine visual contract', () => {
  it('uses ruled page actions and flat quick action framing', () => {
    const src = readComponent('page.tsx')

    expect(src).toContain('className="h-8 gap-2 rounded-lg border border-foreground/10 bg-background px-4 text-[12px] font-medium text-primary shadow-none hover:bg-primary/10"')
    expect(src).toContain('className="h-8 gap-2 rounded-lg border border-foreground/10 bg-background px-3.5 text-[12px] font-medium text-info shadow-none hover:bg-info/[0.08]"')
    expect(src).toContain('className="flex h-8 items-center gap-2 rounded-md border border-foreground/10 bg-background/70 px-2.5"')
    expect(src).toContain('className="flex h-full flex-col rounded-lg border border-foreground/10 bg-background p-4 shadow-none"')
    expect(src).not.toContain('rounded-[1.2rem]')
    expect(src).not.toContain('backdrop-blur-sm')
    expect(src).not.toContain('shadow-[0_20px_48px_-40px_rgba(15,23,42,0.2)]')
  })

  it('removes decorative blur bubbles from empty, summary, and review sub-surfaces', () => {
    const emptyState = readComponent('components/quarantine-empty-state.tsx')
    const summaryCards = readComponent('components/summary-cards.tsx')
    const reviewDrawer = readComponent('components/quarantine-review-drawer.tsx')
    const detailPanel = readComponent('components/quarantine-detail-panel.tsx')

    expect(emptyState).toContain('className="mb-2 flex size-11 items-center justify-center rounded-lg border border-foreground/10 bg-background/70"')
    expect(emptyState).not.toContain('blur-2xl')
    expect(emptyState).not.toContain('absolute left-1 top-7 size-1.5 rounded-full')
    expect(emptyState).not.toContain('shadow-[0_16px_30px_-22px_hsl(var(--primary)/0.8)]')

    expect(summaryCards).toContain('rounded-lg border bg-background px-3.5 py-3 shadow-none')
    expect(summaryCards).toContain('border-foreground/10')
    expect(summaryCards).toContain('rounded-lg border border-foreground/10 bg-background p-3.5 shadow-none')
    expect(summaryCards).toContain('rounded-lg border border-foreground/10 bg-background px-3 py-2')
    expect(summaryCards).not.toContain('bg-[radial-gradient(')
    expect(summaryCards).not.toContain('backdrop-blur-sm')
    expect(summaryCards).not.toContain('hover:-translate-y-0.5')

    expect(reviewDrawer).toMatch(/border-l border-foreground\/15[^"']*bg-background[^"']*shadow-none[^"']*backdrop-blur-none/)
    expect(reviewDrawer).toContain('border-b border-foreground/15 bg-background px-6 py-6')
    expect(reviewDrawer).toContain('border-t border-foreground/15 bg-background p-6')
    expect(reviewDrawer).not.toContain('backdrop-blur-xl')
    expect(reviewDrawer).not.toContain('backdrop-blur-md')

    expect(detailPanel).toContain('rounded-lg border border-foreground/10 bg-background/70 p-4')
    expect(detailPanel).toContain('rounded-lg border border-warning/30 bg-warning/5 p-4')
    expect(detailPanel).not.toContain('shadow-[0_0_8px_rgba(245,158,11,0.5)]')
  })

  it('keeps the bottom panels flush by assigning spare height to the audit canvas', () => {
    const page = readComponent('page.tsx')
    const auditCanvas = readComponent(
      '../../../components/knowledge/quarantine/quarantine-audit-canvas.tsx'
    )

    expect(page).toContain(
      "'relative flex h-full min-h-0 flex-col overflow-hidden'"
    )
    expect(page).toContain(
      'bodyClassName="relative z-10 flex w-full max-w-none flex-1 flex-col px-2 pb-4 md:px-3 xl:px-4"'
    )
    expect(page).toContain(
      'bodyContainerClassName="flex min-h-0 max-w-none flex-1 flex-col"'
    )
    expect(page).toContain(
      '<div className="flex min-h-0 flex-1 flex-col gap-4">'
    )
    expect(page).toContain('className="min-h-[25.5rem] flex-1"')

    expect(auditCanvas).toContain('className?: string')
    expect(auditCanvas).toContain(
      "'flex min-h-0 flex-col overflow-hidden rounded-[1.2rem]"
    )
    expect(auditCanvas).toContain(
      'className="min-h-[10.5rem] flex-1 overflow-x-auto"'
    )
    expect(auditCanvas).toContain(
      'className="h-full w-full table-fixed border-collapse text-left"'
    )
  })
})
