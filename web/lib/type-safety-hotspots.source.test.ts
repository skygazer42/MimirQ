import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8')
}

describe('type safety hotspots', () => {
  it('keeps chat formatting and chat area metadata filters on unknown-safe objects', () => {
    const formatter = read('hooks/use-chat-formatter.ts')
    const chatArea = read('components/chat-area.tsx')

    expect(formatter).not.toContain('metadata_filter?: Record<string, any> | null')
    expect(chatArea).not.toContain('metadata_filter?: Record<string, any> | null')
    expect(chatArea).not.toContain('icon: any')
  })

  it('keeps auth proxy routes free of any-based JSON helpers and error catches', () => {
    const exchangeRoute = read('app/api/oidc/exchange/route.ts')
    const logoutRoute = read('app/api/oidc/logout/route.ts')
    const refreshRoute = read('app/api/oidc/refresh/route.ts')
    const samlRoute = read('app/api/saml/acs/route.ts')

    expect(exchangeRoute).not.toContain('function jsonNoStore(data: any')
    expect(exchangeRoute).not.toContain('catch (e: any)')
    expect(logoutRoute).not.toContain('function jsonNoStore(data: any')
    expect(refreshRoute).not.toContain('function jsonNoStore(data: any')
    expect(refreshRoute).not.toContain('catch (e: any)')
    expect(samlRoute).not.toContain('function jsonNoStore(data: any')
  })

  it('keeps core chat types on unknown-safe payloads', () => {
    const types = read('types/index.ts')

    expect(types).not.toContain('data: any')
    expect(types).not.toContain('structured_data?: any')
    expect(types).not.toContain('next?: any')
    expect(types).not.toContain('metadata_filter?: Record<string, any>')
    expect(types).not.toContain('metrics: Record<string, any>')
  })

  it('keeps ragviz similarity result payloads on unknown-safe objects', () => {
    const types = read('types/index.ts')
    const start = types.indexOf('export interface RagvizSimilarityMatrixResult {')
    const end = types.indexOf('export interface RagvizSimilarityCalculateResponse {')
    const ragvizBlock = start >= 0 && end > start ? types.slice(start, end) : types

    expect(ragvizBlock).not.toContain('x_data: Record<string, any>[]')
    expect(ragvizBlock).not.toContain('y_data: Record<string, any>[]')
    expect(ragvizBlock).not.toContain('metadata: Record<string, any>')
  })

  it('keeps chunk preview payload types on unknown-safe objects', () => {
    const types = read('types/index.ts')
    const start = types.indexOf('export interface ParsedSegment {')
    const end = types.indexOf('export interface ChunkPreviewResponse {')
    const chunkPreviewBlock = start >= 0 && end > start ? types.slice(start, end) : types

    expect(chunkPreviewBlock).not.toContain('metadata?: Record<string, any>')
    expect(chunkPreviewBlock).not.toContain('payload: Record<string, any>')
    expect(chunkPreviewBlock).not.toContain('strategy_params?: Record<string, any>')
    expect(chunkPreviewBlock).not.toContain('meta?: Record<string, any>')
    expect(chunkPreviewBlock).not.toContain('patch?: Record<string, any>')
  })

  it('keeps connector and ingestion run payloads on unknown-safe objects', () => {
    const types = read('types/index.ts')
    const start = types.indexOf('export interface ConnectorRunOut {')
    const end = types.indexOf('export interface ConnectorConfigCreateRequest {')
    const connectorRunBlock = start >= 0 && end > start ? types.slice(start, end) : types

    expect(connectorRunBlock).not.toContain('config?: Record<string, any>')
    expect(connectorRunBlock).not.toContain('stats?: Record<string, any>')
    expect(connectorRunBlock).not.toContain('diff: Record<string, any>')
  })

  it('keeps regression payload types on unknown-safe objects', () => {
    const types = read('types/index.ts')
    const start = types.indexOf('export interface RegressionRun {')
    const end = types.indexOf('// ==================== RAGViz（相似度热力图） ====================')
    const regressionBlock = start >= 0 && end > start ? types.slice(start, end) : types

    expect(regressionBlock).not.toContain('params: Record<string, any>')
    expect(regressionBlock).not.toContain('summary: Record<string, any>')
    expect(regressionBlock).not.toContain('citations: any[]')
    expect(regressionBlock).not.toContain('scores: Record<string, any>')
    expect(regressionBlock).not.toContain('meta?: Record<string, any>')
    expect(regressionBlock).not.toContain('before?: any')
    expect(regressionBlock).not.toContain('after?: any')
    expect(regressionBlock).not.toContain('base_params: Record<string, any>')
    expect(regressionBlock).not.toContain('target_params: Record<string, any>')
  })

  it('keeps ragviz evidence workbench free of any-casts', () => {
    const src = read('components/ragviz/evidence-workbench.tsx')

    expect(src).not.toContain('data: any')
    expect(src).not.toContain('as any')
    expect(src).not.toContain(': any')
    expect(src).not.toContain('Record<string, any>')
  })

  it('keeps the current utility cleanup batch on unknown-safe helper types', () => {
    const openApiHelpers = read('types/openapi-helpers.ts')
    const documentChunks = read('lib/document-chunks.ts')
    const evidenceSuggestions = read('lib/evidence-suggestions.ts')
    const evidenceWhyMissed = read('lib/evidence-why-missed.ts')
    const localSearch = read('hooks/use-local-search.ts')
    const graphAlgorithms = read('lib/graph-algorithms.ts')
    const scimApi = read('lib/api/scim.ts')
    const documentDetailDialog = read('components/document-detail-dialog.tsx')
    const datasetProfilePage = read('app/datasets/[id]/profile/page-client.tsx')
    const graphViewer = read('components/graph/graph-viewer.tsx')
    const graph3d = read('components/graph/force-graph-3d.tsx')
    const graph2dWrapper = read('components/graph/force-graph-2d-wrapper.tsx')

    expect(openApiHelpers).not.toContain('Record<string, any>')
    expect(openApiHelpers).not.toContain('Record<number, any>')
    expect(documentChunks).not.toContain('Record<string, any>')
    expect(evidenceSuggestions).not.toContain('as any')
    expect(evidenceWhyMissed).not.toContain('as any')
    expect(evidenceWhyMissed).not.toContain(': any')
    expect(localSearch).not.toContain('[key: string]: any')
    expect(graphAlgorithms).not.toContain('as any')
    expect(scimApi).not.toContain('payload: any')
    expect(scimApi).not.toContain('Promise<any>')
    expect(documentDetailDialog).not.toContain(': any')
    expect(datasetProfilePage).not.toContain(': any')
    expect(graphViewer).not.toContain(': any')
    expect(graph3d).not.toContain(': any')
    expect(graph2dWrapper).not.toContain(': any')
  })

  it('keeps static skeleton maps off index keys in the remaining hotspot views', () => {
    const graphCanvas = read('app/graph/_components/graph-canvas.tsx')
    const feedbackPage = read('app/knowledge/feedback/page.tsx')
    const ingestionPage = read('app/knowledge/ingestion/page-client.tsx')
    const similarityWorkbench = read('components/ragviz/similarity-workbench.tsx')

    expect(graphCanvas).not.toContain('key={index}')
    expect(feedbackPage).not.toContain('key={index}')
    expect(ingestionPage).not.toContain('key={index}')
    expect(similarityWorkbench).not.toContain('key={index}')
  })

  it('keeps chunk preview shared types and review/export helpers on unknown-safe objects', () => {
    const previewTypes = read('components/chunk-preview/types.ts')
    const reviewSignals = read('components/chunk-preview/utils/review-signals.ts')
    const exportUtils = read('components/chunk-preview/utils/export.ts')

    expect(previewTypes).not.toContain('metadata?: Record<string, any>')
    expect(previewTypes).not.toContain('chunkOverrides: Record<number, { content?: string; metadata?: Record<string, any>; disabled?: boolean; updatedAt?: number }>')
    expect(previewTypes).not.toContain('updateChunkOverride: (index: number, override: { content?: string; metadata?: Record<string, any> }) => void')

    expect(reviewSignals).not.toContain('as Record<string, any>')
    expect(reviewSignals).not.toContain("(c.metadata as any)?.chunk_role")

    expect(exportUtils).not.toContain('preview as any')
    expect(exportUtils).not.toContain('[] as any[]')
    expect(exportUtils).not.toContain('Record<string, any>')
    expect(exportUtils).not.toContain('(v as any)?.disabled')
    expect(exportUtils).not.toContain('(mergedAll as any).review_signals')
    expect(exportUtils).not.toContain('const report = chunkPreviewToReviewReport(preview, overrides, options) as any')
    expect(exportUtils).not.toContain('const flagged = chunks.filter((c: any)')
  })

  it('keeps chunk preview state and auto-tune flows off any-based preview overrides', () => {
    const context = read('components/chunk-preview/context.tsx')
    const autoTune = read('components/chunk-preview/components/chunk-auto-tune-dialog.tsx')

    expect(context).not.toContain('Record<number, { content?: string; metadata?: Record<string, any>; disabled?: boolean; updatedAt?: number }>')
    expect(context).not.toContain('const sha = (previewData as any)?.file_sha256 as string | undefined')
    expect(context).not.toContain('[] as any[]')
    expect(context).not.toContain('override: { content?: string; metadata?: Record<string, any> }')
    expect(context).not.toContain('(cur as any).disabled')
    expect(context).not.toContain('const { disabled: _omit, ...rest } = cur as any')

    expect(autoTune).not.toContain('(previewData as any)?.file_sha256')
    expect(autoTune).not.toContain('const s: any = res?.stats')
    expect(autoTune).not.toContain('quality: (res as any)?.quality_gate ?? null')
    expect(autoTune).not.toContain('catch (err: any)')
  })

  it('keeps chunk preview comparison/search helpers free of any-casts', () => {
    const coverageHeatmap = read('components/chunk-preview/utils/coverage-heatmap.ts')
    const retrievalSearch = read('components/chunk-preview/utils/retrieval-search.ts')
    const abDiff = read('components/chunk-preview/utils/ab-diff.ts')

    expect(coverageHeatmap).not.toContain("(c.metadata as any)?.chunk_role")
    expect(coverageHeatmap).not.toContain('(c as any)?.start_index')

    expect(retrievalSearch).not.toContain('const idx = Number((c as any)?.index)')
    expect(retrievalSearch).not.toContain('const results = index.search(q) as any[]')

    expect(abDiff).not.toContain('function safeNum(value: any)')
    expect(abDiff).not.toContain('(aStats as any).avg')
    expect(abDiff).not.toContain('(c as any)?.tokens_est')
  })

  it('keeps chunk preview semantic/pdf workbench views free of any-casts', () => {
    const chunkList = read('components/chunk-preview/components/workbench/preview/chunk-list.tsx')
    const semanticHeatmapMini = read('components/chunk-preview/components/workbench/preview/semantic-quality-heatmap-mini.tsx')
    const pdfPreview = read('components/chunk-preview/components/workbench/preview/pdf-preview.tsx')
    const chunkCard = read('components/chunk-preview/components/chunk-card.tsx')

    expect(chunkList).not.toContain('(v as any)?.content')
    expect(chunkList).not.toContain('(v as any)?.metadata')
    expect(chunkList).not.toContain('(v as any)?.disabled')
    expect(chunkList).not.toContain('const meta = (c.metadata || {}) as Record<string, any>')
    expect(chunkList).not.toContain('const q = (meta.semantic_quality || {}) as Record<string, any>')

    expect(semanticHeatmapMini).not.toContain('((chunk as any)?.metadata || {}) as Record<string, any>')

    expect(pdfPreview).not.toContain('const previewChunks = previewData?.chunks as any')
    expect(pdfPreview).not.toContain('previewChunks.map((chunk: any, index: number)')

    expect(chunkCard).not.toContain('((chunk.metadata as any)?.semantic_quality || null)')
    expect(chunkCard).not.toContain('Boolean((chunk.metadata as any)?.needs_review || semanticQuality?.needs_review)')
  })

  it('keeps chunk preview comparison and top bar helpers free of any-casts', () => {
    const topBar = read('components/chunk-preview/components/workbench/top-bar.tsx')
    const compareDialog = read('components/chunk-preview/components/chunk-compare-dialog.tsx')
    const rerankerSim = read('components/chunk-preview/utils/reranker-sim.ts')

    expect(topBar).not.toContain('(acc, o: any) =>')
    expect(topBar).not.toContain('pipelineCtx.updateOption(k as any, v as any)')
    expect(topBar).not.toContain('.catch((err: any)')
    expect(topBar).not.toContain('catch (e: any)')

    expect(compareDialog).not.toContain('const meta = (c as any)?.metadata')
    expect(compareDialog).not.toContain("typeof (meta as any).hierarchy_basis === 'string'")

    expect(rerankerSim).not.toContain('Number((c as any)?.index)')
  })

  it('keeps chunk preview original-text inspector/viewers off any-based metadata access', () => {
    const chunkInspector = read('components/chunk-preview/components/chunk-inspector-dialog.tsx')
    const originalPreview = read('components/chunk-preview/components/workbench/preview/original-preview.tsx')
    const originalPreviewMonaco = read('components/chunk-preview/components/workbench/preview/original-preview-monaco.tsx')

    expect(chunkInspector).not.toContain('buildEmbeddingText(content: string, meta: Record<string, any> | null')
    expect(chunkInspector).not.toContain('onSave: (payload: { content: string; metadata: Record<string, any> }) => void')
    expect(chunkInspector).not.toContain('null as Record<string, any> | null')
    expect(chunkInspector).not.toContain('catch (e: any)')

    expect(originalPreview).not.toContain('(globalThis as any).requestIdleCallback')
    expect(originalPreview).not.toContain('(globalThis as any).cancelIdleCallback')
    expect(originalPreview).not.toContain('.catch((err: any) => {')
    expect(originalPreview).not.toContain('const meta = (c.metadata ? { ...(c.metadata as any) } : null) as Record<string, any> | null')
    expect(originalPreview).not.toContain('chunks={displayChunks as any}')
    expect(originalPreview).not.toContain('catch (err: any)')

    expect(originalPreviewMonaco).not.toContain('useRef<any>(null)')
    expect(originalPreviewMonaco).not.toContain('const decos: any[] = []')
    expect(originalPreviewMonaco).not.toContain('editor.onMouseDown((e: any) =>')
  })

  it('keeps the remaining chunk preview sidebar and ingestion detail flows off any-casts', () => {
    const sidebarClient = read('components/chunk-preview/components/workbench/sidebar-client.tsx')
    const ingestionDetails = read('components/chunk-preview/components/ingestion-preview-details-dialog.tsx')

    expect(sidebarClient).not.toContain('previewData?.stats?.histogram as any')
    expect(sidebarClient).not.toContain('serverBins.map((b: any) =>')
    expect(sidebarClient).not.toContain('const last = histogramData[histogramData.length - 1] as any')
    expect(sidebarClient).not.toContain('(previewData?.params as any)?.strategy_params')
    expect(sidebarClient).not.toContain('.catch((err: any) =>')
    expect(sidebarClient).not.toContain('const patch = selectedDataset.pipeline as any')
    expect(sidebarClient).not.toContain('pipelineCtx.updateOption(k as any, v as any)')
    expect(sidebarClient).not.toContain('(selectedDataset.pipeline as any).governance_enabled')
    expect(sidebarClient).not.toContain('catch (err: any)')
    expect(sidebarClient).not.toContain('pipelineCtx.updateOption(k as any, v)')
    expect(sidebarClient).not.toContain('const patch: Record<string, any> = {')
    expect(sidebarClient).not.toContain('formatter={(value: any) =>')
    expect(sidebarClient).not.toContain('labelFormatter={(_label: any, payload: any) => {')
    expect(sidebarClient).not.toContain('(item as any)?.target')
    expect(sidebarClient).not.toContain('const next: any = {}')
    expect(sidebarClient).not.toContain('(p as any)?.title')

    expect(ingestionDetails).not.toContain('onApplyPipelinePatch?: (patch: Record<string, any>) => void')
    expect(ingestionDetails).not.toContain('(c.pii_hits as any)')
    expect(ingestionDetails).not.toContain('reduce((acc: number, v: any)')
    expect(ingestionDetails).not.toContain('(preview?.clean?.issues as any)')
    expect(ingestionDetails).not.toContain('steps.map((s: any, idx: number) =>')
    expect(ingestionDetails).not.toContain('onApplyPipelinePatch(patch as any)')
    expect(ingestionDetails).not.toContain('issues.map((it: any, idx: number) =>')
    expect(ingestionDetails).not.toContain('(exp as any)?.snapshot ?? exp')
  })
})
