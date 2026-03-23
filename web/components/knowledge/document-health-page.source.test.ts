import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('DocumentHealthPage source wiring', () => {
  it('loads the health card through the API client and renders the main sections', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-health-page.tsx'), 'utf8')

    expect(src).toContain('documentApi.health')
    expect(src).toContain('解析 → 分块 → KG → 检索命中')
    expect(src).toContain('ENABLE_METRICS_LOG=true')
  })
})
