import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports charts', () => {
  it('uses measured chart frames instead of Recharts ResponsiveContainer warnings', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'")
    expect(src).toContain('<SafeResponsiveChart')
    expect(src).not.toContain('ResponsiveContainer')
  })
})
