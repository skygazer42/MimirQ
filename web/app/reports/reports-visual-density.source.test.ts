import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readSource(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('reports visual density', () => {
  it('uses compact Ocean report surfaces', () => {
    const page = readSource('page-client.tsx')
    const tokens = readSource('report-tokens.ts')
    const atoms = readSource('components/report-atoms.tsx')
    const controls = readSource('components/reports-control-panel.tsx')

    expect(page).toContain(
      "cn(KNOWLEDGE_OPS_BACKGROUND_CLASS, 'bg-info/[0.035]')"
    )
    expect(page).toContain('className="space-y-3 px-4 py-3 md:px-6 md:py-4"')
    expect(tokens).toContain(
      "'rounded-2xl border border-info/15 bg-background/72 p-3 shadow-none'"
    )
    expect(tokens).toContain(
      "'grid overflow-hidden rounded-2xl border border-info/15 bg-info/15 shadow-none md:grid-cols-3 2xl:grid-cols-6'"
    )
    expect(atoms).toContain('bg-background/72 px-2.5 py-1.5')
    expect(atoms).toContain('flex min-w-0 items-baseline gap-1.5')
    expect(atoms).toContain('bg-background/72 px-3 py-2')
    expect(atoms).not.toContain('bg-card/95 px-4 py-3.5')
    expect(controls).toContain(
      'rounded-2xl border border-info/15 bg-background/72 p-2.5'
    )
    expect(controls).toContain(
      'grid gap-2 md:grid-cols-2 xl:grid-cols-[1.25fr_1.1fr_0.85fr_auto]'
    )
    expect(readSource('components/reports-page-hero.tsx')).toContain(
      'className="sm:col-span-2 xl:col-span-1"'
    )
  })

  it('does not stretch sparse report cards into oversized panels', () => {
    const dashboard = readSource('components/reports-dashboard.tsx')
    const panels = readSource('components/report-panels.tsx')

    expect(dashboard).toContain('<section className="space-y-3">')
    expect(dashboard.match(/grid items-start gap-2\.5/g)?.length).toBe(2)
    expect(panels.match(/grid grid-cols-2 gap-1\.5/g)?.length).toBe(2)
    expect(panels).not.toContain('<EmptyState')
    expect(panels).not.toContain('bg-[linear-gradient(120deg')
    expect(panels).toContain('className="h-[180px]" minHeight={180}')
    expect(panels).toContain('className="h-[160px]" minHeight={160}')
  })
})
