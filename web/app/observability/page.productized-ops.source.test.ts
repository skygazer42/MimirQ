import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('observability page productized operations', () => {
  it('mounts the advanced observability operations panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { ObservabilityOpsPanel } from '@/components/observability/observability-ops-panel'")
    expect(src).toContain('<ObservabilityOpsPanel')
  })
})
