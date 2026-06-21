import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset profile operations', () => {
  it('keeps maintenance operations out of the dataset profile page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain("import { DatasetOpsPanel } from '@/components/datasets/dataset-ops-panel'")
    expect(src).not.toContain('<DatasetOpsPanel')
    expect(src).not.toContain("id=\"prof-operations\"")
    expect(src).not.toContain("label: '运维导出'")
  })
})
