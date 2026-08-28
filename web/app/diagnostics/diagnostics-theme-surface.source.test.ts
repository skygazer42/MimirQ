// Source contract check only; behavior stays covered by the management smoke suite.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const source = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

describe('diagnostics Ocean theme surface', () => {
  it('keeps the diagnostics canvas and primary panels in the Ocean surface family', () => {
    expect(source).toContain('bodyClassName="bg-info/[0.035] pt-4 pb-6"')
    expect(source).toContain(
      "'rounded-2xl border border-info/20 bg-background/78 p-4 shadow-none'"
    )
    expect(source).toContain(
      'rounded-xl border border-border/70 bg-background/82 px-3 py-3 shadow-none'
    )
  })

  it('uses semantic status fills instead of white status capsules', () => {
    expect(source).not.toContain('bg-card/85 text-success')
    expect(source).not.toContain('bg-card/85 text-warning')
    expect(source).not.toContain('bg-card/85 text-destructive')
    expect(source).toContain('border-success/25 bg-success/10 text-success')
    expect(source).toContain('border-warning/25 bg-warning/10 text-warning')
  })

  it('keeps the guide flat and selected diagnostic dimensions blue', () => {
    expect(source).toContain(
      'rounded-2xl border border-info/20 bg-background/68 p-2 shadow-none'
    )
    expect(source).toContain(
      'grid divide-y divide-border/60 lg:grid-cols-[1.1fr_1fr_1fr] lg:divide-x lg:divide-y-0'
    )
    expect(source).toContain(
      'className="flex gap-3 px-3 py-2.5 lg:first:pl-2 lg:last:pr-2"'
    )
    expect(source).toContain(
      "'border-info/30 bg-info/[0.075]'"
    )
    expect(source).not.toContain(
      'flex gap-3 rounded-xl border border-border/80 bg-card/75 px-3 py-2.5'
    )
  })

  it('waits for a wide desktop before enabling the twelve-column workbench', () => {
    expect(source.match(/xl:grid-cols-12/g)).toHaveLength(2)
    expect(source).not.toContain('lg:grid-cols-12')
    expect(source).not.toContain("'lg:col-span-")
  })
})
