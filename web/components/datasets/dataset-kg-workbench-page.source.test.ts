import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Dataset KG workbench perceived-performance wiring', () => {
  it('adds progressive loading shells and worker-backed graph cluster summaries', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'dataset-kg-workbench-page.tsx'), 'utf8')

    expect(src).toContain('DocsLoadingSkeleton')
    expect(src).toContain('GraphPreviewSkeleton')
    expect(src).toContain('SearchResultsSkeleton')
    expect(src).toContain('PageLoading')
    expect(src).toContain("new URL('../../workers/graph-clustering.worker.ts', import.meta.url)")
    expect(src).toContain('const [graphClusterResult, setGraphClusterResult] = useState<GraphClusterResult | null>(null)')
    expect(src).toContain('clusters={graphClusterResult.clusterCount}')
  })
})
