import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('rag trace panel source', () => {
  it('prefetches citation targets on hover and focus before opening document viewer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('prefetchDocumentView')
    expect(src).toContain('const prefetchedTraceCitationTargetsRef = React.useRef')
    expect(src).toContain('const prefetchTraceCitationTarget = React.useCallback')
    expect(src).toContain('RAG_TRACE_LAST_TARGETS_STORAGE_KEY')
    expect(src).toContain('rememberOpenedTraceCitationTarget')
    expect(src).toContain('重新打开最近证据')
    expect(src).toContain('onMouseEnter={() => prefetchTraceCitationTarget(documentId, chunkId)}')
    expect(src).toContain('onFocus={() => prefetchTraceCitationTarget(documentId, chunkId)}')
    expect(src).toContain('onMouseEnter={() => prefetchTraceCitationTarget(docId, chunkId || undefined)}')
    expect(src).toContain('onFocus={() => prefetchTraceCitationTarget(docId, chunkId || undefined)}')
  })

  it('renders compare suggestions and evidence drift summaries for diff-centric debugging', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('buildTraceDiffCandidateOptions')
    expect(src).toContain('buildTraceCitationDiff')
    expect(src).toContain('Trace 对比候选')
    expect(src).toContain('Evidence Drift')
    expect(src).toContain('新增证据（B）')
    expect(src).toContain('丢失证据（A）')
    expect(src).toContain('分数漂移')
    expect(src).toContain('setDiffOtherRequestId(candidate.requestId)')
  })
})
