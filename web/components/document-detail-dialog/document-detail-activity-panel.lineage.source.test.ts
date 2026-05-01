import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document detail chunk lineage integration', () => {
  it('connects chunk lineage controls in the chunk list', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-detail-activity-panel.tsx'), 'utf8')

    expect(src).toContain('lineageApi.getChunkLineage')
    expect(src).toContain('查看 Chunk 血缘')
  })
})
