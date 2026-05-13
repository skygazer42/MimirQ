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

  it('wires graph drill-down selection and dataset-scoped cluster palette rendering', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'dataset-kg-workbench-page.tsx'), 'utf8')

    expect(src).toContain("import { applyClusterPalette } from '@/lib/graph-cluster-palette'")
    expect(src).toContain('const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | null>(null)')
    expect(src).toContain('const graphPaletteSeed = useMemo(() => datasetId || effectivePipelineHash || null')
    expect(src).toContain('const graphPreviewData = useMemo(() => {')
    expect(src).toContain('return applyClusterPalette({')
    expect(src).toContain('paletteSeed: graphPaletteSeed')
    expect(src).toContain('clusterResult: graphClusterResult')
    expect(src).toContain('<GraphViewer')
    expect(src).toContain('data={graphPreviewData}')
    expect(src).toContain('onNodeClick={(node) => {')
    expect(src).toContain('setSelectedGraphNodeId(nodeId)')
    expect(src).toContain('selectedNodeId={selectedGraphNodeId}')
    expect(src).toContain('onBackgroundClick={() => setSelectedGraphNodeId(null)}')
    expect(src).toContain('Node drill-down')
    expect(src).toContain('selectedNodeDetail')
    expect(src).toContain('degree=')
    expect(src).toContain('cluster=')
  })

  it('loads the scoped document range through TanStack Query instead of a local loadDocs helper', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'dataset-kg-workbench-page.tsx'), 'utf8')

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain('queryKey: datasetId')
    expect(src).toContain('queryKeys.datasets.detail(datasetId)')
    expect(src).toContain('queryKeys.documents.list({')
    expect(src).not.toContain('const loadDocs = useCallback(async (query?: string) => {')
    expect(src).not.toContain('setDocs(Array.isArray(list.items) ? list.items : [])')
    expect(src).not.toContain('setDocsTotal(Number(list.total || 0))')
  })
})
