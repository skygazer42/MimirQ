import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const GRAPH_FILES = [
  'use-graph-page-state.ts',
  'use-graph-page-actions.ts',
  'use-graph-node-operations.ts',
  'use-graph-entity-resolution.ts',
  'use-graph-interaction-modes.ts',
  'use-graph-data-loading.ts',
  '_components/graph-page-header.tsx',
  '_components/graph-node-detail-panel.tsx',
] as const

describe('graph production data sources', () => {
  it('only allows live backend data or user-uploaded graph files', () => {
    for (const file of GRAPH_FILES) {
      const src = fs.readFileSync(path.resolve(__dirname, file), 'utf8')

      expect(src, file).not.toContain("'mock'")
      expect(src, file).not.toContain('"mock"')
    }
  })
})
