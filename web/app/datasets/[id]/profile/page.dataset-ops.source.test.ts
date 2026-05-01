import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset profile operations', () => {
  it('mounts dataset export, clone, precheck and table operations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { DatasetOpsPanel } from '@/components/datasets/dataset-ops-panel'")
    expect(src).toContain('<DatasetOpsPanel')
  })
})
