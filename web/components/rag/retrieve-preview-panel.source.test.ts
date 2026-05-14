import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieve preview panel source', () => {
  it('uses direct citation fields in table rows and String directly for matched terms', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('terms.filter(Boolean).slice(0, 24).map(String)')
    expect(src).toContain("const chunkId = String(hit.chunk_id || '')")
    expect(src).toContain("const clause = String(hit.policy_clause_number || '')")
    expect(src).toContain("const pathStr = String(hit.policy_path_str || '')")
    expect(src).toContain("role.startsWith('hierarchy_')")
    expect(src).toContain('family_hit')
    expect(src).toContain('expanded')
  })

  it('avoids any-casts in retrieval detail rendering', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).not.toContain('as any')
    expect(src).not.toContain(': any')
    expect(src).not.toContain('Record<string, any>')
  })

  it('adds a document-viewer open action with hover/focus prefetch for retrieval hits', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('useDocumentView')
    expect(src).toContain('prefetchDocumentView')
    expect(src).toContain('const prefetchedHitTargetsRef = useRef<Set<string>>(new Set())')
    expect(src).toContain('const handlePrefetchHitDocument = useCallback')
    expect(src).toContain('const handleOpenHitInDocumentViewer = useCallback')
    expect(src).toContain('onMouseEnter={() => handlePrefetchHitDocument(hit)}')
    expect(src).toContain('onFocus={() => handlePrefetchHitDocument(hit)}')
    expect(src).toContain("label=\"在文档查看器中打开\"")
    expect(src).toContain('getDocumentPreviewAnchorFromCitation')
    expect(src).toContain('openDocument(documentId, chunkId, range, {')
    expect(src).toContain('previewAnchor: getDocumentPreviewAnchorFromCitation(hit)')
  })

  it('applies a staggered row-entry animation with reduced-motion safety', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('const staggerDelayMs = Math.min(idx, 10) * 40')
    expect(src).toContain('style={{ animationDelay: `${staggerDelayMs}ms` }}')
    expect(src).toContain('animate-in fade-in-0 slide-in-from-bottom-1 duration-300')
    expect(src).toContain('motion-reduce:animate-none')
  })

  it('uses semantic warning tokens for family-hit emphasis instead of hard-coded amber classes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('bg-warning/10 text-warning border border-warning/20')
    expect(src).not.toContain('amber-500')
    expect(src).not.toContain('text-amber-')
  })

  it('wires retrieval workbench utility buttons to real inline actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('const [advancedParamsOpen, setAdvancedParamsOpen] = useState(false)')
    expect(src).toContain('const [fullHistoryOpen, setFullHistoryOpen] = useState(false)')
    expect(src).toContain('aria-controls={RETRIEVAL_ADVANCED_PANEL_ID}')
    expect(src).toContain('onClick={() => setAdvancedParamsOpen((open) => !open)}')
    expect(src).toContain('aria-controls={RETRIEVAL_HISTORY_PANEL_ID}')
    expect(src).toContain('onClick={() => setFullHistoryOpen((open) => !open)}')
    expect(src).toContain('onClick={handleClearRecentQueries}')
    expect(src).toContain('当前会话历史')
  })

  it('uses blue tokenized range controls instead of native black sliders', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('const RETRIEVAL_RANGE_INPUT_CLASS =')
    expect(src).toContain('[&::-webkit-slider-thumb]:border-sky-300')
    expect(src).toContain('bg-info/80')
    expect(src).toContain('style={{ width: `${scoreThresholdPercent}%` }}')
    expect(src).toContain('style={{ width: `${alphaPercent}%` }}')
    expect(src).not.toContain('accent-primary')
  })

  it('uses a light blue-white workbench surface instead of a gray retrieval background', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('const RETRIEVAL_PANEL_SURFACE_CLASS =')
    expect(src).toContain('const RETRIEVAL_CONTROL_SURFACE_CLASS =')
    expect(src).toContain("bg-[#F8FBFF]/75")
    expect(src).toContain('border-sky-100/75 bg-white/[0.94]')
    expect(src).not.toContain('bg-background/40')
    expect(src).not.toContain('bg-background/92')
  })

  it('uses a custom semantic retrieval mark instead of the generic sparkles icon', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('function SemanticRetrievalMark()')
    expect(src).toContain('aria-label="语义检索图标"')
    expect(src).toContain('<SemanticRetrievalMark />')
    expect(src).toContain('data-semantic-node="query"')
    expect(src).toContain('data-semantic-node="evidence"')
    expect(src).not.toContain('Sparkles')
  })
})
