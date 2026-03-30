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
    expect(src).toContain('t("panel.topCitations.title")')
    expect(src).toContain('t("panel.topCitations.reopenRecent")')
    expect(src).toContain('t("panel.topCitations.reopenRecentTitle")')
    expect(src).toContain('t("panel.topCitations.empty")')
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

  it('moves fusion simulator copy into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('t("panel.fusionSimulator.title")')
    expect(src).toContain('t("panel.fusionSimulator.description")')
    expect(src).toContain('t("panel.fusionSimulator.presetBalanced")')
    expect(src).toContain('t("panel.fusionSimulator.presetVector")')
    expect(src).toContain('t("panel.fusionSimulator.presetLexical")')
    expect(src).toContain('t("panel.fusionSimulator.simulatedTitle")')
    expect(src).toContain('t("panel.fusionSimulator.simulatedDescription")')
  })

  it('moves trace shell toasts, empty states, and header actions into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('t("panel.toasts.bundleDownloaded")')
    expect(src).toContain('t("panel.errors.bundleDownloadFailed")')
    expect(src).toContain('t("panel.errors.diffSameRequest")')
    expect(src).toContain('t("panel.errors.diffLoadFailed")')
    expect(src).toContain('t("panel.errors.traceLoadFailed")')
    expect(src).toContain('t("panel.states.notEnabledTitle")')
    expect(src).toContain('t("panel.states.notEnabledDescription")')
    expect(src).toContain('t("panel.states.emptyTitle")')
    expect(src).toContain('t("panel.states.emptyHint")')
    expect(src).toContain('t("panel.states.emptyFollowup")')
    expect(src).toContain('t("panel.actions.refresh")')
    expect(src).toContain('t("panel.header.title")')
    expect(src).toContain('t("panel.header.keyboardHint")')
    expect(src).toContain('t("panel.actions.downloadBundleTitle")')
    expect(src).toContain('t("panel.actions.downloadBundle")')
    expect(src).toContain('t("panel.actions.compareTitle")')
    expect(src).toContain('t("panel.actions.compare")')
  })

  it('moves pipeline timeline and channel section copy into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('t("panel.pipelineSummary.retrieve")')
    expect(src).toContain('t("panel.pipelineSummary.reranker")')
    expect(src).toContain('t("panel.pipelineSummary.citations")')
    expect(src).toContain('t("panel.timeline.title")')
    expect(src).toContain('t("panel.timeline.description")')
    expect(src).toContain('t("panel.timeline.metricsUnavailable")')
    expect(src).toContain('t("panel.timeline.quickEvidence")')
    expect(src).toContain('t("panel.timeline.documentLevelEvidence")')
    expect(src).toContain('t("panel.timeline.unavailable")')
    expect(src).toContain('t("panel.channels.title")')
    expect(src).toContain('t("panel.channels.focusTitle")')
    expect(src).toContain('t("panel.channels.focusDescription")')
    expect(src).toContain('t("panel.channels.unavailable")')
  })

  it('moves evidence drift empty states and diff summary labels into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-panel.tsx'), 'utf8')

    expect(src).toContain('t("panel.evidenceDrift.addedEmpty")')
    expect(src).toContain('t("panel.evidenceDrift.removedEmpty")')
    expect(src).toContain('t("panel.evidenceDrift.missingLocalSummary")')
    expect(src).toContain('t("panel.compare.summaryA")')
    expect(src).toContain('t("panel.compare.summaryB")')
    expect(src).toContain('t("panel.compare.changesMeta"')
    expect(src).toContain('t("panel.compare.truncatedYes")')
    expect(src).toContain('t("panel.compare.truncatedNo")')
    expect(src).toContain('t("panel.topCitations.open")')
  })
})
