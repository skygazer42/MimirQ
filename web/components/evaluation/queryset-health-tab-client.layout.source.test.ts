import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('queryset health tab dashboard layout', () => {
  it('keeps the health dashboard compact and design-aligned', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'queryset-health-tab-client.tsx'), 'utf8')

    expect(src).toContain('function QuerysetChartEmptyState')
    expect(src).toContain('function buildQuerysetTrendSkeleton')
    expect(src).toContain('formatDateTick')
    expect(src).toContain('chartDisplayData')
    expect(src).toContain('dateLabel')
    expect(src).toContain('XAxis dataKey="dateLabel"')
    expect(src).toContain("replace('/', '-')")
    expect(src).toContain('暂无数据')
    expect(src).toContain('当前筛选条件下暂无趋势数据')
    expect(src).toContain('min-h-[205px]')
    expect(src).toContain('h-[145px]')
    expect(src).toContain('如何解读差异')
    expect(src).toContain('grid-cols-[minmax(0,1fr)_minmax(320px,0.72fr)]')
    expect(src).toContain('max-h-[190px]')
    expect(src).toContain('暂无运行记录')
    expect(src).not.toContain('min-h-[220px]')
    expect(src).not.toContain('min-h-[280px]')
    expect(src).not.toContain('h-[160px]')
    expect(src).not.toContain('h-[200px]')
  })
})
