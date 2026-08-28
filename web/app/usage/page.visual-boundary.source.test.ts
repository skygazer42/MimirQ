// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('usage page visual boundary contract', () => {
  it('keeps the usage overview on the flat boundary baseline', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src,
      "const USAGE_PANEL_CLASS = 'overflow-hidden rounded-xl border border-info/20 bg-background/78 shadow-none'"
    )
    expectSourceToContain(src,
      "const USAGE_SURFACE_CLASS = 'rounded-xl border border-info/20 bg-background/70'"
    )
    expectSourceToContain(src, 'bodyClassName="bg-info/[0.035] !pb-3"')
    expectSourceToContain(src, "indigo: 'bg-info/60'")
    expectSourceToContain(src, "blue: 'border-info/25 bg-info/[0.09] text-info'")
    expectSourceNotToContain(src, 'border-accent/10')
    expectSourceNotToContain(src, 'text-accent fill-current')
    expectSourceNotToContain(src, 'Ambient background glow')
    expectSourceNotToContain(src, 'blur-[120px]')
    expectSourceNotToContain(src, 'blur-[100px]')
    expectSourceNotToContain(src, 'backdrop-blur-xl')
    expectSourceNotToContain(src, 'rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner')
  })

  it('keeps ranking concise while paginating the complete cost attribution list', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src, '>TOP 10</span>')
    expectSourceToContain(src, '按 dataset_id 归因 · {formatWindow(')
    expectSourceToContain(src, 'value={summary?.by_dataset?.length ?? 0}')
    expectSourceToContain(src, 'paginateUsageRows(costRows, costPage)')
    expectSourceToContain(src, '{paginatedCostRows.map((r) => {')
    expectSourceToContain(src, 'aria-label="成本归因上一页"')
    expectSourceToContain(src, 'aria-label="成本归因下一页"')
  })

  it('uses color to distinguish values from labels without tinting every heading', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src, "blue: 'text-info'")
    expectSourceToContain(src, "green: 'text-success'")
    expectSourceToContain(src, "slate: 'text-foreground/80'")
    expectSourceToContain(src, "info: 'border-border/65 bg-background/62 text-info'")
    expectSourceToContain(src, 'font-semibold text-info/90')
    expectSourceToContain(src, 'font-semibold text-info')
    expectSourceNotToContain(src, 'tracking-[-0.04em] text-foreground bg-clip-text')
  })

  it('uses empty table states instead of leaving a large blank page footer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src, 'bodyClassName="bg-info/[0.035] !pb-3"')
    expectSourceToContain(src, 'className="relative z-10 flex flex-col gap-4 pb-0"')
    expectSourceToContain(src, 'function UsageEmptyTableRow(')
    expectSourceToContain(src, "className=\"h-40 px-5 text-center\"")
    expectSourceToContain(src, 'title="暂无数据集用量记录"')
    expectSourceToContain(src, 'title="暂无成本归因记录"')
  })
})
