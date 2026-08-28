import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const panel = fs.readFileSync(
  path.resolve(__dirname, 'data-governance-panel.tsx'),
  'utf8'
)

describe('data governance theme surface', () => {
  it('uses the shared theme background without independent glow layers', () => {
    expect(panel).toContain(
      'className="pointer-events-none absolute inset-0 bg-background"'
    )
    expect(panel).not.toContain('circle_at_16%_12%')
    expect(panel).not.toContain("bg-[url('/grid.svg')]")
    expect(panel).not.toContain('-left-24 top-16 h-64 w-64')
    expect(panel).not.toContain('-right-24 -top-16 h-72 w-72')
  })

  it('keeps the existing governance layout and generated icon intact', () => {
    expect(panel).toContain('data-governance-empty-workbench="true"')
    expect(panel).toContain(
      'src="/page-title-icons/data-governance.png"'
    )
    expect(panel).toContain('xl:grid-cols-[minmax(0,1fr)_420px]')
  })

  it('uses a balanced large-screen intake workbench proportion', () => {
    expect(panel).toContain(
      'relative flex flex-1 items-start justify-center overflow-x-hidden overflow-y-auto p-4 md:p-6 xl:items-center xl:overflow-hidden'
    )
    expect(panel).toContain('max-w-[1440px]')
    expect(panel).toContain(
      'grid min-h-[clamp(600px,68vh,650px)] items-stretch gap-6 xl:grid-cols-[minmax(0,1fr)_420px]'
    )
    expect(panel).toContain(
      'flex h-full min-h-[560px] flex-col justify-center'
    )
    expect(panel).toContain(
      'flex h-full flex-col justify-center gap-7 py-6 lg:py-8'
    )
    expect(panel).not.toContain('max-w-6xl')
    expect(panel).not.toContain('space-y-5 py-2 lg:py-4')
    expect(panel).not.toContain('lg:grid-cols-[minmax(0,1fr)_360px]')
    expect(panel).not.toContain(
      'inset-x-8 top-8 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--primary)/0.32),transparent)]'
    )
    expect(panel).not.toContain('border-y border-dashed border-primary/24')
    expect(panel).not.toContain(
      'absolute inset-x-4 top-4 h-px bg-primary/18 opacity-70'
    )
  })
})
