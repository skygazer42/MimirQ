import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('rag trace panel source', () => {
  it('prefetches citation targets on hover and focus before opening document viewer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('prefetchDocumentView')
    expect(src).toContain('const prefetchedTraceCitationTargetsRef = React.useRef')
    expect(src).toContain('const prefetchTraceCitationTarget = React.useCallback')
    expect(src).toContain('onMouseEnter={() => prefetchTraceCitationTarget(documentId, chunkId)}')
    expect(src).toContain('onFocus={() => prefetchTraceCitationTarget(documentId, chunkId)}')
    expect(src).toContain('onMouseEnter={() => prefetchTraceCitationTarget(docId, chunkId || undefined)}')
    expect(src).toContain('onFocus={() => prefetchTraceCitationTarget(docId, chunkId || undefined)}')
  })
})
