import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('GovernanceOpsPanel source', () => {
  it('surfaces stale documents and chunk preset delete APIs explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-ops-panel.tsx'), 'utf8')

    expect(src).toContain('governanceApi.listStaleDocumentsByDataset')
    expect(src).toContain('chunkPresetApi.delete')
  })
})
