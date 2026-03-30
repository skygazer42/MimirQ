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
    expect(src).toContain('t("panel.topCitations.reopenRecent")')
    expect(src).toContain('t("panel.toasts.openedCitationDocument")')
    expect(src).toContain('t("panel.toasts.reopenedRecentEvidence")')
    expect(src).toContain('onMouseEnter={() => prefetchTraceCitationTarget(documentId, chunkId)}')
    expect(src).toContain('onFocus={() => prefetchTraceCitationTarget(documentId, chunkId)}')
    expect(src).toContain('onMouseEnter={() => prefetchTraceCitationTarget(docId, chunkId || undefined)}')
    expect(src).toContain('onFocus={() => prefetchTraceCitationTarget(docId, chunkId || undefined)}')
  })

  it('renders compare suggestions and evidence drift summaries for diff-centric debugging', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('buildTraceDiffCandidateOptions')
    expect(src).toContain('buildTraceCitationDiff')
    expect(src).toContain("useTranslations('RagTrace')")
    expect(src).toContain('t("panel.compareCandidates.title")')
    expect(src).toContain('t("panel.compareCandidates.description")')
    expect(src).toContain('t("panel.compare.requestIdA")')
    expect(src).toContain('t("panel.compare.requestIdB")')
    expect(src).toContain('t("panel.compare.requestIdBPlaceholder")')
    expect(src).toContain('t("panel.compare.action")')
    expect(src).toContain('t("panel.evidenceDrift.title")')
    expect(src).toContain('t("panel.evidenceDrift.description")')
    expect(src).toContain('t("panel.evidenceDrift.addedTitle")')
    expect(src).toContain('t("panel.evidenceDrift.removedTitle")')
    expect(src).toContain('t("panel.evidenceDrift.scoreShiftTitle")')
    expect(src).toContain('setDiffOtherRequestId(candidate.requestId)')
  })

  it('keeps expert trace internals on sidebar-tinted surfaces instead of the older border-heavy cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft')
    expect(src).toContain('border-sidebar-border/60 bg-sidebar/45 px-3 py-3 text-xs text-muted-foreground')
    expect(src).toContain('border-sidebar-border/70 bg-sidebar/55 px-3 py-2 text-left transition-colors')
  })
})
