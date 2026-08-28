import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const sidebar = fs.readFileSync(
  path.resolve(__dirname, 'components/workbench/sidebar-client.tsx'),
  'utf8'
)
const strategyDropdown = fs.readFileSync(
  path.resolve(__dirname, '../business/chunk-strategy-dropdown.tsx'),
  'utf8'
)
const pipelineOptions = fs.readFileSync(
  path.resolve(__dirname, '../pipeline-options-panel.tsx'),
  'utf8'
)
const chunkPreset = fs.readFileSync(
  path.resolve(__dirname, 'components/chunk-preset-panel.tsx'),
  'utf8'
)

describe('chunk preview sidebar controls', () => {
  it('preserves strategy, preset, chunk size and overlap updates', () => {
    expect(sidebar).toContain('updateSettings({ strategy: value')
    expect(sidebar).toContain("strategy: 'qa_pairs', chunkSize: 800, chunkOverlap: 120")
    expect(sidebar).toContain('updateSettings({ chunkSize: nextSize, chunkOverlap: nextOverlap })')
    expect(sidebar).toContain(
      'updateSettings({ chunkOverlap: clampInt(n, 0, overlapMax) })'
    )
  })

  it('uses a flat theme surface and shrink-safe numeric control rows', () => {
    expect(sidebar).toContain(
      'className="[&>button]:border-info/20 [&>button]:bg-info/[0.035] [&>button]:shadow-none [&>button:hover]:bg-info/[0.06]"'
    )
    expect(sidebar).not.toContain(
      'className="rounded-xl border border-border/50 bg-background/40 p-1 shadow-sm"'
    )
    expect(sidebar).toContain(
      'className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2"'
    )
    expect(sidebar).toContain(
      '<SidebarPanel tone="emerald" className="relative overflow-hidden p-0">'
    )
    expect(sidebar).toContain(
      'data-chunk-size-control="true"'
    )
    expect(sidebar).toContain(
      'data-chunk-overlap-control="true"'
    )
    expect(sidebar).not.toContain(
      'space-y-4 rounded-xl border border-info/12 bg-background/55 p-2.5 shadow-none'
    )
    expect(sidebar).not.toContain(
      'space-y-2.5 rounded-xl border border-info/12 bg-background/55 p-2.5 shadow-none'
    )
    expect(sidebar).not.toContain(
      'shrink-0 rounded-md border border-info/15 bg-info/[0.04]'
    )
    expect(sidebar).not.toContain('rounded bg-primary/8')
    expect(sidebar).toContain(
      'className="h-8 w-24 min-w-0 max-w-full rounded-md border-input/80 bg-background/70 text-[11px] font-medium font-mono shadow-none focus-visible:border-info/50 focus-visible:ring-info/20'
    )
    expect(sidebar).toContain(
      'className="h-8 w-24 min-w-0 max-w-full rounded-md border-input/80 bg-background/70 text-[11px] font-medium font-mono shadow-none focus-visible:border-info/50 focus-visible:ring-info/20"'
    )
  })

  it('keeps helper copy readable and uses one brand accent', () => {
    expect(sidebar).toContain(
      'className="text-[10px] font-semibold uppercase tracking-[0.14em] text-foreground'
    )
    expect(sidebar).toContain(
      'className="flex flex-wrap items-center gap-1.5 pt-1 text-[10px] font-medium'
    )
    expect(sidebar).toContain(
      'className="text-[10px] font-medium tracking-[0.08em] text-muted-foreground"'
    )
    expect(sidebar).toContain(
      'text-[10px] font-medium text-muted-foreground/75'
    )
    expect(sidebar).toContain('bg-info/20 accent-info')
    expect(sidebar).not.toContain('border-success/25 bg-success/5')
    expect(sidebar).not.toContain('bg-success/15 accent-primary')
    expect(sidebar).not.toContain(
      'text-[8px] font-medium uppercase tracking-[0.14em] text-muted-foreground/65'
    )
  })

  it('themes the portal dropdown surface without changing selection behavior', () => {
    expect(sidebar).toContain('surface="ocean"')
    expect(strategyDropdown).toContain("surface?: 'default' | 'ocean'")
    expect(strategyDropdown).toContain("surface = 'default'")
    expect(strategyDropdown).toContain("surface === 'ocean'")
    expect(strategyDropdown).toContain(
      "'border-info/30 bg-[linear-gradient(hsl(var(--info)/0.10),hsl(var(--info)/0.10)),linear-gradient(hsl(var(--popover)),hsl(var(--popover)))] text-popover-foreground shadow-strong'"
    )
    expect(strategyDropdown).toContain("'bg-info/[0.10]'")
    expect(strategyDropdown).toContain("'hover:bg-info/[0.06]'")
    expect(strategyDropdown).toContain('onChange(option.value)')
  })

  it('uses a restrained three-weight scale and a 10px caption floor', () => {
    expect(sidebar).not.toMatch(/\bfont-(?:black|bold)\b/)
    expect(sidebar).not.toMatch(
      /text-\[(?:7\.5|8|8\.5|9|9\.5)px\]/
    )
    expect(strategyDropdown).not.toMatch(
      /text-\[(?:7\.5|8|8\.5|9|9\.5)px\]/
    )
    expect(sidebar).toContain('font-medium')
    expect(sidebar).toContain('font-semibold')
  })

  it('uses role-based icon sizes and prevents flex shrink', () => {
    expect(sidebar).toContain('SIDEBAR_LEAD_ICON_FRAME_CLASS')
    expect(sidebar).toContain(
      "'relative flex size-6 shrink-0 items-center justify-center rounded-lg border shadow-none'"
    )
    expect(sidebar).toContain("SIDEBAR_LEAD_ICON_CLASS = 'size-3.5 shrink-0'")
    expect(sidebar).toContain(
      "'flex size-5 shrink-0 items-center justify-center rounded-md border shadow-none'"
    )
    expect(sidebar).toContain("SIDEBAR_COMPACT_ICON_CLASS = 'size-3 shrink-0'")
    expect(sidebar).toContain('className="mr-2 size-4 shrink-0')
    expect(sidebar).not.toContain(
      '<Filter className="h-3 w-3 text-primary"'
    )

    expect(strategyDropdown).toContain(
      "const resolvedIconFrameSize = surface === 'ocean' ? 'size-6' : 'size-8'"
    )
    expect(strategyDropdown).toContain(
      "'grid shrink-0 place-items-center rounded-md'"
    )

    expect(pipelineOptions).toContain(
      'compact ? "size-6" : "size-7"'
    )
    expect(pipelineOptions).toContain(
      'compact ? "size-3.5" : "size-4"'
    )
    expect(pipelineOptions).toContain(
      'onCheckedChange={(value) => handleChecked(item.key, value)}'
    )

    expect(chunkPreset).toContain(
      'className="flex size-6 shrink-0 items-center justify-center rounded-lg border'
    )
    expect(chunkPreset).not.toContain(
      'className="flex h-7 w-7 shrink-0 items-center justify-center'
    )
    expect(chunkPreset).toContain('onClick={() => detachPromise(onSave())}')
  })
})
