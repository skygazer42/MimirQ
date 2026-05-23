import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph page state source', () => {
  it('defaults edge labels off so 3D graph dragging starts on the lightweight path', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-graph-page-state.ts'), 'utf8')

    expect(src).toContain('const [showEdgeLabels, setShowEdgeLabels] = useState(false)')
  })

  it('keeps dataset_id inside graph scope params so dataset routes cannot silently degrade to tenant-global KG queries', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-graph-page-state.ts'), 'utf8')

    expect(src).toContain('const dataset_id = scope.datasetId || undefined')
    expect(src).toContain('return { document_ids, dataset_id, pipeline_hash }')
  })
})
