import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const CHART_PAGES = [
  'precheck/page-client.tsx',
  'profile/page-client.tsx',
  'health/page-client.tsx',
] as const

describe('dataset chart containers', () => {
  it('uses guarded chart containers to avoid zero-width mount warnings', () => {
    for (const relativePath of CHART_PAGES) {
      const src = fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
      const chartContainerCount = src.match(/<SafeResponsiveChart/g)?.length ?? 0

      expect(src, relativePath).toContain("import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'")
      expect(chartContainerCount, relativePath).toBeGreaterThan(0)
      expect(src, relativePath).not.toContain('<ResponsiveContainer')
    }
  })
})
