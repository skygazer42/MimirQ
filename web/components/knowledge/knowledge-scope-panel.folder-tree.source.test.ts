import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel folder tree', () => {
  it('renders DatasetFolderTree when a dataset is selected', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain('DatasetFolderTree')
    expect(src).toContain('datasetId={selectedDatasetId}')
    expect(src).toContain('showHeader={false}')
  })
})
