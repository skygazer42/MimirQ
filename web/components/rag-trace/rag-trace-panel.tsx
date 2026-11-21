'use client'

import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { reportClientError } from '@/lib/client-logging'
import * as React from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Loader2, Route, Quote, Timer, Database, ExternalLink, Download, GitCompare } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { useTenantAccess } from '@/hooks/use-tenant-access'
import { chatApi, documentApi, healthApi, metaApi, observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getAuthCacheScope, getAuthSessionRevision, getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'
import { writeClientStorage } from '@/lib/client-storage'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { queryKeys } from '@/lib/query-keys'
import { TENANT_PERMISSIONS, tenantAccessAllows } from '@/lib/tenant-permissions'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { RagTrace, RagTraceCitation } from '@/types/chat'
import type { RagTraceBundleDiffResponse } from '@/types/observability'

const TRACE_EVIDENCE_PREVIEW_LIMIT = 3

function formatTs(tsMs: number) {
  return new Date(tsMs).toLocaleString()
}

function formatSec(sec?: number | null) {
  if (sec == null || !Number.isFinite(sec)) return '—'
  if (sec < 1) return `${Math.round(sec * 1000)}ms`
  return `${sec.toFixed(2)}s`
}

function formatTraceModeLabel(mode?: string | null) {
  if (mode == null) return '—'
  const labels = new Map([
    ['dify_external_knowledge', 'Dify 外部知识'],
    ['dify_result', 'Dify 结果'],
    ['hybrid', '混合检索'],
    ['vector', '向量检索'],
    ['bm25', '关键词检索'],
  ])
  return labels.get(mode) ?? mode.replaceAll('_', ' ')
}

function formatCitationCount(count: number) {
  return `${count} 条证据`
}

function abbreviateIdentifier(value: string, opts?: { head?: number; tail?: number }) {
  const v = value.trim()
  const head = opts?.head ?? 8
  const tail = opts?.tail ?? 4
  if (v.length <= head + tail + 1) return v
  return `${v.slice(0, head)}...${tail === 0 ? '' : v.slice(-tail)}`
}

function formatFilenameTimestamp(ts: string) {
  return ts.replaceAll(/[:.]/g, '-')
}

function formatRequestFilenamePart(value: string) {
  return value
    .trim()
    .replaceAll(/[^a-zA-Z0-9_-]+/g, '_')
    .slice(0, 80)
}

function formatScore(value?: number | null, digits = 3) {
  return value == null ? null : value.toFixed(digits)
}

function compareScoresDescending(left: number | null, right: number | null): number {
  if (left === right) return 0
  if (left === null) return 1
  if (right === null) return -1
  return right - left
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getRecordField(source: unknown, key: string): Record<string, unknown> | null {
  const value = isRecord(source) ? source[key] : undefined
  return isRecord(value) ? value : null
}

function formatDiffValue(value: unknown, maxLen = 160): string {
  if (value === undefined) return '—'
  const text = JSON.stringify(value)
  return text.length > maxLen ? `${text.slice(0, maxLen)}…` : text
}

function formatDiagnosticText(value: unknown): string {
  if (value === undefined) return '未提供'
  if (typeof value === 'string') return value.length === 0 ? '""' : value
  return formatDiffValue(value)
}

function getPrimaryScore(citation: RagTraceCitation) {
  return citation.rerank_score ?? citation.retrieval_score ?? citation.relevance_score ?? null
}

type TraceDiffCandidateOption = {
  requestId: string
  tsMs: number
  mode: RagTrace['retrieval']['mode']
  citationsCount: number
  retrievalConfigHash: RagTrace['retrieval']['retrieval_config_hash']
  sameRetrievalConfig: boolean | null
}

function buildTraceDiffCandidateOptions(
  traces: ReadonlyArray<RagTrace>,
  currentTrace: RagTrace,
): TraceDiffCandidateOption[] {
  const currentRequestId = currentTrace.request_id?.trim()
  if (!currentRequestId) return []
  const currentConfigHash = currentTrace.retrieval.retrieval_config_hash
  const candidates = new Map<string, TraceDiffCandidateOption>()
  for (const trace of traces) {
    const requestId = trace.request_id?.trim()
    if (!requestId || requestId === currentRequestId) continue
    const previous = candidates.get(requestId)
    if (previous !== undefined && previous.tsMs >= trace.ts_ms) continue
    const retrievalConfigHash = trace.retrieval.retrieval_config_hash
    candidates.set(requestId, {
      requestId,
      tsMs: trace.ts_ms,
      mode: trace.retrieval.mode,
      citationsCount: trace.citations_count,
      retrievalConfigHash,
      sameRetrievalConfig:
        currentConfigHash != null &&
        currentConfigHash.length > 0 &&
        retrievalConfigHash != null &&
        retrievalConfigHash.length > 0
          ? retrievalConfigHash === currentConfigHash
          : null,
    })
  }
  return Array.from(candidates.values()).sort((a, b) => {
    const aConfigChanged = a.sameRetrievalConfig === false ? 1 : 0
    const bConfigChanged = b.sameRetrievalConfig === false ? 1 : 0
    if (aConfigChanged !== bConfigChanged) return bConfigChanged - aConfigChanged

    const aDistance = Math.abs(a.tsMs - currentTrace.ts_ms)
    const bDistance = Math.abs(b.tsMs - currentTrace.ts_ms)
    if (aDistance !== bDistance) return aDistance - bDistance

    return b.tsMs - a.tsMs
  })
}

const CITATION_SIMULATION_CHANNELS = [
  { key: 'rerank_score', label: 'Rerank' },
  { key: 'vector_score', label: 'Vector' },
  { key: 'bm25_score', label: 'BM25' },
  { key: 'lexical_score', label: 'Lexical' },
] as const

type CitationSimulationChannelKey = (typeof CITATION_SIMULATION_CHANNELS)[number]['key']
type CitationSimulationWeights = Record<CitationSimulationChannelKey, number>
type CitationSimulationPreset = 'balanced' | 'vector' | 'lexical'

type CitationSimulationContribution = {
  label: string
  normalizedScore: number
  weightedScore: number
}

type CitationSimulationRow = {
  citation: RagTraceCitation
  rank: number
  baseRank: number
  rankDelta: number
  compositeScore: number | null
  dominantChannelLabel: string | null
}

function getCitationSimulationScore(citation: RagTraceCitation, key: CitationSimulationChannelKey): number | null {
  return citation[key] ?? null
}

function getVaryingCitationSimulationChannels(citations: RagTraceCitation[]) {
  return CITATION_SIMULATION_CHANNELS.filter((channel) => {
    const scores = new Set(
      citations
        .map((citation) => getCitationSimulationScore(citation, channel.key))
        .filter((score): score is number => score !== null),
    )
    return scores.size > 1
  })
}

function buildCitationSimulationWeightsForPreset(
  preset: CitationSimulationPreset,
  channels: ReadonlyArray<{ key: CitationSimulationChannelKey }>,
): CitationSimulationWeights {
  const weights: CitationSimulationWeights = {
    rerank_score: 0,
    vector_score: 0,
    bm25_score: 0,
    lexical_score: 0,
  }
  if (preset === 'vector') {
    weights.vector_score = 0.8
    weights.rerank_score = 0.2
    return weights
  }
  if (preset === 'lexical') {
    weights.bm25_score = 0.7
    weights.lexical_score = 0.2
    weights.rerank_score = 0.1
    return weights
  }

  for (const channel of channels) {
    weights[channel.key] = 1 / channels.length
  }
  return weights
}

function moveTraceSelectionIndex(currentIndex: number, total: number, direction: -1 | 1): number {
  return (currentIndex + direction + total) % total
}

function buildCitationSimulationRows(
  citations: RagTraceCitation[],
  weights: CitationSimulationWeights,
): CitationSimulationRow[] {
  const channels = getVaryingCitationSimulationChannels(citations).map((channel) => {
    const scores = citations
      .map((citation) => getCitationSimulationScore(citation, channel.key))
      .filter((score): score is number => score !== null)
    return { ...channel, weight: weights[channel.key], min: Math.min(...scores), max: Math.max(...scores) }
  })
  const totalWeight = channels.reduce((sum, channel) => sum + channel.weight, 0)
  if (totalWeight === 0) return []

  return citations
    .map((citation, index) => {
      const contributions = channels.flatMap<CitationSimulationContribution>((channel) => {
        const rawScore = getCitationSimulationScore(citation, channel.key)
        if (rawScore === null || channel.weight === 0) return []
        const normalizedScore = (rawScore - channel.min) / (channel.max - channel.min)
        return [
          {
            label: channel.label,
            normalizedScore,
            weightedScore: normalizedScore * channel.weight,
          },
        ]
      })
      const compositeScore =
        contributions.length > 0
          ? contributions.reduce((sum, contribution) => sum + contribution.weightedScore, 0) / totalWeight
          : null
      const dominantContribution = contributions
        .slice()
        .sort((a, b) => b.weightedScore - a.weightedScore || b.normalizedScore - a.normalizedScore)
        .find((contribution) => contribution.weightedScore > 0)

      return {
        citation,
        baseRank: index + 1,
        compositeScore,
        dominantChannelLabel: dominantContribution?.label ?? null,
      }
    })
    .sort((a, b) => compareScoresDescending(a.compositeScore, b.compositeScore) || a.baseRank - b.baseRank)
    .map((row, index) => ({
      ...row,
      rank: index + 1,
      rankDelta: row.baseRank - (index + 1),
    }))
}

type RagTraceCitationChannelFilter = 'all' | 'vector' | 'bm25' | 'lexical_db'

type RagTraceCitationChannelSummary = {
  key: RagTraceCitationChannelFilter
  label: string
  summary: string
  matchCount: number
  candidateCount: number | null
  maxScore: number | null
  active: boolean
}

type StoredTraceCitationTarget = {
  conversationId: string
  requestId: string
  documentId: string
  chunkId?: string
  range?: { start: number; end: number }
  pageNumber?: number
  label: string
  openedAt: number
}
type TraceTargetState =
  | { status: 'pending' }
  | { status: 'ready'; target: StoredTraceCitationTarget | null; warning?: string }
  | { status: 'error'; message: string }
const TRACE_TARGET_STORAGE_PREFIX = 'mimirq_rag_trace_last_target_v2'
const storedTraceTargetSchema: z.ZodType<StoredTraceCitationTarget> = z.strictObject({
  conversationId: z.string().min(1),
  requestId: z.string().min(1),
  documentId: z.string().min(1),
  chunkId: z.string().min(1).optional(),
  range: z
    .object({ start: z.number().int().nonnegative(), end: z.number().int().nonnegative() })
    .refine((range) => range.end > range.start)
    .optional(),
  pageNumber: z.number().int().optional(),
  label: z.string(),
  openedAt: z.number().int(),
})

type RagTraceTranslation = (key: string, values?: Record<string, string | number | Date>) => string

function getRagTraceCitationChannelOptions(t: RagTraceTranslation): ReadonlyArray<{
  key: RagTraceCitationChannelFilter
  label: string
  summary: string
}> {
  return [
    { key: 'all', label: t('panel.channels.options.all.label'), summary: t('panel.channels.options.all.summary') },
    {
      key: 'vector',
      label: t('panel.channels.options.vector.label'),
      summary: t('panel.channels.options.vector.summary'),
    },
    { key: 'bm25', label: t('panel.channels.options.bm25.label'), summary: t('panel.channels.options.bm25.summary') },
    {
      key: 'lexical_db',
      label: t('panel.channels.options.lexicalDb.label'),
      summary: t('panel.channels.options.lexicalDb.summary'),
    },
  ]
}

function getRagTraceCitationChannelLabel(channel: RagTraceCitationChannelFilter, t: RagTraceTranslation) {
  return getRagTraceCitationChannelOptions(t).find((option) => option.key === channel)?.label
}

function getRagTraceCitationChannelScore(
  citation: RagTraceCitation,
  channel: Exclude<RagTraceCitationChannelFilter, 'all'>,
): number | null {
  if (channel === 'vector') return citation.vector_score ?? null
  if (channel === 'bm25') return citation.bm25_score ?? null
  return citation.lexical_score ?? null
}

function getTraceConfigMatchLabel(value: boolean | null): string {
  if (value === false) return 'cfg changed'
  if (value === true) return 'same cfg'
  return 'cfg ?'
}

function getTraceRankDeltaLabel(rankDelta: number): string {
  if (rankDelta > 0) return `↑${rankDelta}`
  if (rankDelta < 0) return `↓${Math.abs(rankDelta)}`
  return '—'
}

function filterTraceCitationsByChannel(
  citations: ReadonlyArray<RagTraceCitation>,
  channel: RagTraceCitationChannelFilter,
): RagTraceCitation[] {
  const list = Array.from(citations)
  if (channel === 'all') {
    return list.sort((a, b) => compareScoresDescending(getPrimaryScore(a), getPrimaryScore(b)))
  }

  return list
    .filter((citation) => getRagTraceCitationChannelScore(citation, channel) !== null)
    .sort((a, b) => {
      const channelDelta = compareScoresDescending(
        getRagTraceCitationChannelScore(a, channel),
        getRagTraceCitationChannelScore(b, channel),
      )
      if (channelDelta !== 0) return channelDelta
      return compareScoresDescending(getPrimaryScore(a), getPrimaryScore(b))
    })
}

function buildTraceCitationChannelSummaries(
  trace: RagTrace,
  activeChannel: RagTraceCitationChannelFilter,
  t: RagTraceTranslation,
): RagTraceCitationChannelSummary[] {
  const citations = trace.citations
  const mainQuery = trace.retrieval.per_query?.find((query) => query.kind === 'main')
  const channels = getRecordField(mainQuery?.retriever_debug, 'channels')

  return getRagTraceCitationChannelOptions(t).map((option) => {
    const { label, summary } = option
    if (option.key === 'all') {
      const sorted = filterTraceCitationsByChannel(citations, option.key)
      return {
        key: option.key,
        label,
        summary,
        matchCount: sorted.length,
        candidateCount: trace.citations_count,
        maxScore: sorted[0] ? getPrimaryScore(sorted[0]) : null,
        active: activeChannel === option.key,
      }
    }

    const filtered = filterTraceCitationsByChannel(citations, option.key)
    const box = getRecordField(channels, option.key)
    return {
      key: option.key,
      label,
      summary,
      matchCount: filtered.length,
      candidateCount: typeof box?.candidates === 'number' && Number.isFinite(box.candidates) ? box.candidates : null,
      maxScore: filtered[0] ? getRagTraceCitationChannelScore(filtered[0], option.key) : null,
      active: activeChannel === option.key,
    }
  })
}

function getTraceCitationLabel(citation: RagTraceCitation, fallback: string) {
  const documentId = citation.document_id?.trim()
  return documentId !== undefined && documentId.length > 0 ? documentId : fallback
}

function getTraceCitationIds(citation: RagTraceCitation) {
  return {
    documentId: citation.document_id?.trim(),
    chunkId: citation.chunk_id?.trim(),
  }
}

function compactEvidenceText(value: string, maxChars = 150) {
  const text = value.replaceAll(/\s+/g, ' ').trim()
  return text.length > maxChars ? `${text.slice(0, maxChars)}…` : text
}

type TraceCitationDiffItem = {
  key: string
  label: string
  citation: RagTraceCitation
  score: number | null
}

type TraceCitationScoreShiftItem = {
  key: string
  label: string
  a: RagTraceCitation
  b: RagTraceCitation
  scoreA: number | null
  scoreB: number | null
  scoreFieldA: string | undefined
  scoreFieldB: string | undefined
  scoreDelta: number | null
}

type TraceCitationDiffSummary = {
  sharedCount: number
  addedCount: number
  removedCount: number
  scoreShiftCount: number
  unidentifiedCountA: number
  unidentifiedCountB: number
  added: TraceCitationDiffItem[]
  removed: TraceCitationDiffItem[]
  scoreShifts: TraceCitationScoreShiftItem[]
}

function buildTraceCitationKey(citation: RagTraceCitation) {
  if (!citation.document_id?.trim() && !citation.chunk_id?.trim()) return null
  return JSON.stringify([
    citation.document_id?.trim(),
    citation.chunk_id?.trim(),
    citation.chunk_index,
    citation.page_number,
    citation.start_char,
    citation.end_char,
    citation.retrieval_role,
    citation.neighbor_of,
  ])
}

function indexTraceCitations(citations: readonly RagTraceCitation[]) {
  const occurrences = new Map<string, number>()
  const byIdentity = new Map<string, RagTraceCitation>()
  let unidentifiedCount = 0
  for (const citation of citations) {
    const identity = buildTraceCitationKey(citation)
    if (identity === null) {
      unidentifiedCount += 1
      continue
    }
    const occurrence = occurrences.get(identity) ?? 0
    occurrences.set(identity, occurrence + 1)
    byIdentity.set(JSON.stringify([identity, occurrence]), citation)
  }
  return { byIdentity, unidentifiedCount }
}

function buildTraceCitationDiff(traceA: RagTrace, traceB: RagTrace | null): TraceCitationDiffSummary | null {
  if (traceB === null) return null
  const { byIdentity: mapA, unidentifiedCount: unidentifiedCountA } = indexTraceCitations(traceA.citations)
  const { byIdentity: mapB, unidentifiedCount: unidentifiedCountB } = indexTraceCitations(traceB.citations)
  const scoreFields = ['rerank_score', 'retrieval_score', 'relevance_score'] as const

  const added: TraceCitationDiffItem[] = []
  const removed: TraceCitationDiffItem[] = []
  const scoreShifts: TraceCitationScoreShiftItem[] = []
  let sharedCount = 0

  const keys = new Set<string>([...mapA.keys(), ...mapB.keys()])
  for (const key of keys) {
    const citationA = mapA.get(key)
    const citationB = mapB.get(key)

    if (citationA && citationB) {
      sharedCount += 1
      const scoreA = getPrimaryScore(citationA)
      const scoreB = getPrimaryScore(citationB)
      const scoreFieldA = scoreFields.find((field) => citationA[field] != null)
      const scoreFieldB = scoreFields.find((field) => citationB[field] != null)
      const scoreDelta = scoreA !== null && scoreB !== null && scoreFieldA === scoreFieldB ? scoreB - scoreA : null
      if (scoreFieldA !== scoreFieldB || (scoreDelta !== null && Math.abs(scoreDelta) > 1e-6)) {
        scoreShifts.push({
          key,
          label: getTraceCitationLabel(citationB, '文档标识未提供'),
          a: citationA,
          b: citationB,
          scoreA,
          scoreB,
          scoreFieldA,
          scoreFieldB,
          scoreDelta,
        })
      }
      continue
    }

    if (citationB) {
      added.push({
        key,
        label: getTraceCitationLabel(citationB, '文档标识未提供'),
        citation: citationB,
        score: getPrimaryScore(citationB),
      })
      continue
    }

    if (citationA) {
      removed.push({
        key,
        label: getTraceCitationLabel(citationA, '文档标识未提供'),
        citation: citationA,
        score: getPrimaryScore(citationA),
      })
    }
  }

  added.sort((a, b) => compareScoresDescending(a.score, b.score) || a.label.localeCompare(b.label))
  removed.sort((a, b) => compareScoresDescending(a.score, b.score) || a.label.localeCompare(b.label))
  scoreShifts.sort(
    (a, b) =>
      compareScoresDescending(
        a.scoreDelta === null ? null : Math.abs(a.scoreDelta),
        b.scoreDelta === null ? null : Math.abs(b.scoreDelta),
      ) || a.label.localeCompare(b.label),
  )

  return {
    sharedCount,
    addedCount: added.length,
    removedCount: removed.length,
    scoreShiftCount: scoreShifts.length,
    unidentifiedCountA,
    unidentifiedCountB,
    added,
    removed,
    scoreShifts,
  }
}

function traceTargetStorageKey(scope: string, conversationId: string, requestId: string): string {
  return `${TRACE_TARGET_STORAGE_PREFIX}:${JSON.stringify([scope, conversationId, requestId])}`
}
function readStoredTraceCitationTarget(
  scope: string,
  conversationId: string,
  requestId: string,
): StoredTraceCitationTarget | null {
  const raw = window.localStorage.getItem(traceTargetStorageKey(scope, conversationId, requestId))
  if (raw === null) return null
  const parsed: unknown = JSON.parse(raw)
  const target = storedTraceTargetSchema.parse(parsed)
  if (target.conversationId !== conversationId || target.requestId !== requestId)
    throw new TypeError('Stored trace target identity does not match')
  return target
}
function writeStoredTraceCitationTarget(scope: string, target: StoredTraceCitationTarget): boolean {
  return writeClientStorage(
    traceTargetStorageKey(scope, target.conversationId, target.requestId),
    JSON.stringify(target),
  )
}

type PipelineTimelineStep = {
  key: string
  label: string
  elapsedSec: number | null
  share: number | null
  width: number | null
  mode: string | null
  queryCount: number | null
  itemCount: number | null
  topK: number | null
  rerankTopN: number | null
}

type PipelineInspectorMetric = {
  label: string
  value: string
}

type PipelineInspectorSection = {
  id: string
  label: string
  summary: string
  callout?: string | null
  metrics: PipelineInspectorMetric[]
  citations: RagTraceCitation[]
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function stringifyInspectorValue(value: unknown, fallback = '—') {
  if (value == null) return fallback
  if (typeof value === 'string') return value.length === 0 ? '""' : value
  if (typeof value === 'number') return String(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return formatDiagnosticText(value)
}

function buildInspectorMetric(
  label: string,
  value: unknown,
  opts?: { formatter?: (value: unknown) => string | null },
): PipelineInspectorMetric | null {
  if (value == null) return null
  const formatted = opts?.formatter ? opts.formatter(value) : stringifyInspectorValue(value)
  if (formatted === null) return null
  return { label, value: formatted }
}

function getTraceCitationRange(citation: RagTraceCitation): { start: number; end: number } | undefined {
  const start = citation.start_char
  const end = citation.end_char
  return start != null && end != null && start >= 0 && end > start ? { start, end } : undefined
}

function buildCitationsSummary(citations: RagTraceCitation[]) {
  const sorted = filterTraceCitationsByChannel(citations, 'all')
  return {
    top: sorted.slice(0, 4),
    distinctDocuments: new Set(
      sorted
        .map((citation) => citation.document_id?.trim())
        .filter((documentId): documentId is string => documentId !== undefined && documentId.length > 0),
    ).size,
    imageHits: sorted.filter((citation) => citation.has_image === true).length,
  }
}

function buildPipelineInspectorSections(trace: RagTrace, t: RagTraceTranslation): PipelineInspectorSection[] {
  const mainQuery = trace.retrieval.per_query?.find((query) => query.kind === 'main')
  const channels = getRecordField(mainQuery?.retriever_debug, 'channels')
  const hierarchyRecall = getRecordField(mainQuery?.retriever_debug, 'hierarchy_recall')
  const rerankMeta = getRecordField(channels, 'rerank')
  const citationSummary = buildCitationsSummary(trace.citations)

  const sections = buildPipelineTimelineSteps(trace).map<PipelineInspectorSection>((step, index) => {
    const id = step.key
    const stepMeta = trace.steps[index].meta
    if (id === 'retrieve') {
      const metrics = [
        buildInspectorMetric('Latency', step.elapsedSec, { formatter: (value) => formatSec(asFiniteNumber(value)) }),
        buildInspectorMetric('Mode', step.mode ?? trace.retrieval.mode),
        buildInspectorMetric('Queries', step.queryCount),
        buildInspectorMetric('Top K', step.topK),
        buildInspectorMetric('Candidates', step.itemCount),
        buildInspectorMetric('Fusion', channels?.fusion_strategy),
        buildInspectorMetric('Vector backend', channels?.vector_backend),
      ].filter((value): value is PipelineInspectorMetric => value !== null)

      return {
        id,
        label: step.label,
        summary: t('panel.inspector.retrieveSummary'),
        callout:
          typeof hierarchyRecall?.enabled !== 'boolean'
            ? null
            : t('panel.inspector.retrieveCallout', {
                status: hierarchyRecall.enabled
                  ? t('panel.inspector.retrieveEnabled')
                  : t('panel.inspector.retrieveDisabled'),
                overfetch:
                  hierarchyRecall.overfetch_factor == null
                    ? ''
                    : ` · overfetch=${formatDiagnosticText(hierarchyRecall.overfetch_factor)}`,
              }),
        metrics,
        citations: citationSummary.top,
      }
    }

    if (id === 'rerank') {
      const metrics = [
        buildInspectorMetric('Latency', step.elapsedSec, { formatter: (value) => formatSec(asFiniteNumber(value)) }),
        buildInspectorMetric('Enabled', trace.rerank.enabled),
        buildInspectorMetric('Provider', trace.rerank.provider),
        buildInspectorMetric('Top N', step.rerankTopN),
        buildInspectorMetric('Candidates kept', step.itemCount),
        buildInspectorMetric('Skip reason', rerankMeta?.skip_reason),
        buildInspectorMetric('Error', rerankMeta?.error),
      ].filter((value): value is PipelineInspectorMetric => value !== null)

      return {
        id,
        label: step.label,
        summary: t('panel.inspector.rerankSummary'),
        callout:
          rerankMeta?.skip_reason != null
            ? t('panel.inspector.rerankSkipped', { reason: formatDiagnosticText(rerankMeta.skip_reason) })
            : null,
        metrics,
        citations: citationSummary.top,
      }
    }

    if (id === 'citations') {
      const metrics = [
        buildInspectorMetric('Latency', step.elapsedSec, { formatter: (value) => formatSec(asFiniteNumber(value)) }),
        buildInspectorMetric('Citations', trace.citations_count),
        buildInspectorMetric('Distinct docs', citationSummary.distinctDocuments),
        buildInspectorMetric('Image hits', citationSummary.imageHits),
      ].filter((value): value is PipelineInspectorMetric => value !== null)

      return {
        id,
        label: step.label,
        summary: t('panel.inspector.citationsSummary'),
        metrics,
        citations: citationSummary.top,
      }
    }

    if (id === 'dify_result') {
      const metrics = [
        buildInspectorMetric('Answer chars', stepMeta?.answer_chars),
        buildInspectorMetric('Answer hash', stepMeta?.answer_hash),
        buildInspectorMetric('Dify message', stepMeta?.source_message_id),
        buildInspectorMetric('Workflow run', stepMeta?.source_run_id),
        buildInspectorMetric('Citations', stepMeta?.citations_count),
      ].filter((value): value is PipelineInspectorMetric => value !== null)

      return {
        id,
        label: step.label,
        summary: 'Dify workflow result metadata attached to this RAG trace.',
        metrics,
        citations: citationSummary.top,
      }
    }

    const metrics = [
      buildInspectorMetric('Latency', step.elapsedSec, { formatter: (value) => formatSec(asFiniteNumber(value)) }),
      buildInspectorMetric('Mode', step.mode),
      buildInspectorMetric('Queries', step.queryCount),
      buildInspectorMetric('Items', step.itemCount),
    ].filter((value): value is PipelineInspectorMetric => value !== null)

    return {
      id,
      label: step.label,
      summary: t('panel.inspector.defaultSummary'),
      metrics,
      citations: [],
    }
  })

  if (!sections.some((section) => section.id === 'citations') && trace.citations_count > 0) {
    sections.push({
      id: 'citations',
      label: 'Citations',
      summary: t('panel.inspector.citationsSummary'),
      metrics: [
        buildInspectorMetric('Citations', trace.citations_count),
        buildInspectorMetric('Distinct docs', citationSummary.distinctDocuments),
        buildInspectorMetric('Image hits', citationSummary.imageHits),
      ].filter((value): value is PipelineInspectorMetric => value !== null),
      citations: citationSummary.top,
    })
  }

  return sections
}

function buildPipelineTimelineSteps(trace: RagTrace): PipelineTimelineStep[] {
  const stepRows = trace.steps.map((step) => {
    const elapsed = step.elapsed_sec ?? null
    const meta = step.meta ?? null
    const mode = typeof meta?.mode === 'string' ? meta.mode : null
    const queryCount =
      asFiniteNumber(meta?.query_count) ?? (step.key === 'retrieve' ? (trace.retrieval.query_count ?? null) : null)
    const itemCount = asFiniteNumber(meta?.count)
    const topK = step.key === 'retrieve' ? (trace.retrieval.top_k ?? null) : null
    const rerankTopN = step.key === 'rerank' ? (trace.rerank.top_n ?? null) : null

    return {
      key: step.key,
      label: step.label,
      elapsedSec: elapsed,
      mode,
      queryCount,
      itemCount,
      topK,
      rerankTopN,
    }
  })

  const measuredDurations = stepRows
    .map((step) => step.elapsedSec)
    .filter((duration): duration is number => duration !== null && duration >= 0)
  const maxElapsed = measuredDurations.reduce((max, duration) => Math.max(max, duration), 0)
  const totalElapsed = measuredDurations.reduce((sum, duration) => sum + duration, 0)

  return stepRows.map((step) => ({
    ...step,
    share:
      step.elapsedSec !== null && step.elapsedSec >= 0 && totalElapsed > 0
        ? (step.elapsedSec / totalElapsed) * 100
        : null,
    width:
      step.elapsedSec !== null && step.elapsedSec >= 0 && maxElapsed > 0 ? (step.elapsedSec / maxElapsed) * 100 : null,
  }))
}

function RagTracePipelineTimeline({
  steps,
  selectedKey = null,
  onSelectStep,
  emptyLabel = 'pipeline steps unavailable',
}: Readonly<{
  steps: PipelineTimelineStep[]
  selectedKey?: string | null
  onSelectStep?: (key: string) => void
  emptyLabel?: string
}>) {
  const t = useTranslations('RagTrace')
  return (
    <div className="p-4 space-y-2">
      {steps.length ? (
        steps.map((step) => {
          const barWidth = step.width !== null && step.width > 0 ? Math.max(step.width, 6) : 0
          const shareLabel = step.share === null ? '—' : `${step.share.toFixed(1)}%`
          const selected = selectedKey === step.key
          const content = (
            <>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-foreground">{step.label}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {t('panel.timeline.recordedShare', { share: shareLabel })}
                    {step.mode ? ` · mode=${step.mode}` : null}
                    {step.queryCount == null ? null : ` · queries=${step.queryCount}`}
                    {step.itemCount == null ? null : ` · count=${step.itemCount}`}
                    {step.topK == null ? null : ` · top_k=${step.topK}`}
                    {step.rerankTopN == null ? null : ` · top_n=${step.rerankTopN}`}
                  </div>
                </div>
                <div className="shrink-0 text-xs font-medium text-muted-foreground">{formatSec(step.elapsedSec)}</div>
              </div>
              <div className="h-1.5 w-full rounded-full bg-border/60">
                <div
                  className="h-full rounded-full bg-info"
                  style={{ width: `${barWidth}%` }}
                  data-pipeline-share={shareLabel}
                />
              </div>
            </>
          )

          if (!onSelectStep) {
            return (
              <div key={step.key} className="space-y-1 rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
                {content}
              </div>
            )
          }

          return (
            <button
              key={step.key}
              type="button"
              aria-pressed={selected}
              onClick={() => onSelectStep(step.key)}
              className={cn(
                'block w-full space-y-1 rounded-xl border px-3 py-2 text-left transition-colors',
                'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background',
                selected
                  ? 'border-info bg-info shadow-sm'
                  : 'border-border/60 bg-muted/20 hover:border-info hover:bg-muted/40',
              )}
            >
              {content}
            </button>
          )
        })
      ) : (
        <div className="text-xs text-muted-foreground">{emptyLabel}</div>
      )}
    </div>
  )
}

function TraceCitationDiffList({
  title,
  emptyLabel,
  items,
  tone,
  onPrefetchCitation,
  onOpenCitation,
}: Readonly<{
  title: string
  emptyLabel: string
  items: TraceCitationDiffItem[]
  tone: 'added' | 'removed'
  onPrefetchCitation: (documentId?: string | null, chunkId?: string | null) => void
  onOpenCitation: (citation: RagTraceCitation, opts?: { label?: string; notify?: boolean }) => void
}>) {
  const t = useTranslations('RagTrace')
  return (
    <div className="rounded-2xl border border-border/60 bg-card/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-foreground">{title}</div>
        <Badge
          variant="soft"
          className={cn(
            'text-[11px]',
            tone === 'added' ? 'border-success/20 bg-success/10 text-success' : undefined,
            tone === 'removed' ? 'border-warning/20 bg-warning/10 text-warning' : undefined,
          )}
        >
          {items.length}
        </Badge>
      </div>

      {items.length ? (
        <div className="mt-3 space-y-2">
          {items.slice(0, 5).map((item) => {
            const { documentId, chunkId } = getTraceCitationIds(item.citation)
            const scoreLabel = item.score == null ? '—' : item.score.toFixed(3)
            const pageLabel = item.citation.page_number == null ? null : `P.${item.citation.page_number}`
            return (
              <div
                key={`${tone}:${item.key}`}
                className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-background/80 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-foreground">{item.label}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{chunkId ? `chunk=${chunkId}` : 'document-level evidence'}</span>
                    {pageLabel ? <span>{pageLabel}</span> : null}
                    <span className="font-mono">score={scoreLabel}</span>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  disabled={!documentId}
                  aria-label={`${t('panel.evidencePreview.open')} · ${item.label}`}
                  onMouseEnter={() => onPrefetchCitation(documentId, chunkId)}
                  onFocus={() => onPrefetchCitation(documentId, chunkId)}
                  onClick={() => onOpenCitation(item.citation, { label: item.label })}
                >
                  <ExternalLink className="h-4 w-4" />
                </Button>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-border/60 bg-muted/20 px-3 py-4 text-xs text-muted-foreground">
          {emptyLabel}
        </div>
      )}
    </div>
  )
}

function TraceCitationScoreShiftList({
  items,
  onPrefetchCitation,
  onOpenCitation,
}: Readonly<{
  items: TraceCitationScoreShiftItem[]
  onPrefetchCitation: (documentId?: string | null, chunkId?: string | null) => void
  onOpenCitation: (citation: RagTraceCitation, opts?: { label?: string; notify?: boolean }) => void
}>) {
  const t = useTranslations('RagTrace')

  return (
    <div className="rounded-2xl border border-border/60 bg-card/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-foreground">{t('panel.evidenceDrift.scoreShiftTitle')}</div>
        <Badge variant="soft" className="text-[11px]">
          {items.length}
        </Badge>
      </div>

      {items.length ? (
        <div className="mt-3 space-y-2">
          {items.slice(0, 5).map((item) => {
            const { documentId, chunkId } = getTraceCitationIds(item.b)
            return (
              <div
                key={`shift:${item.key}`}
                className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-background/80 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-foreground">{item.label}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{chunkId ? `chunk=${chunkId}` : 'document-level evidence'}</span>
                    <span className="font-mono">
                      A{item.scoreFieldA === undefined ? '' : ` (${item.scoreFieldA})`}=
                      {item.scoreA === null ? '—' : item.scoreA.toFixed(3)} → B
                      {item.scoreFieldB === undefined ? '' : ` (${item.scoreFieldB})`}=
                      {item.scoreB === null ? '—' : item.scoreB.toFixed(3)}
                    </span>
                    <span
                      className={cn(
                        'font-mono',
                        item.scoreDelta === null
                          ? 'text-muted-foreground'
                          : item.scoreDelta >= 0
                            ? 'text-success'
                            : 'text-warning',
                      )}
                    >
                      {item.scoreDelta === null
                        ? t('panel.evidenceDrift.incomparableScore')
                        : `Δ ${item.scoreDelta.toFixed(3)}`}
                    </span>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl"
                  disabled={!documentId}
                  onMouseEnter={() => onPrefetchCitation(documentId, chunkId)}
                  onFocus={() => onPrefetchCitation(documentId, chunkId)}
                  onClick={() => onOpenCitation(item.b, { label: item.label })}
                >
                  <ExternalLink className="h-4 w-4" />
                </Button>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-dashed border-border/60 bg-muted/20 px-3 py-4 text-xs text-muted-foreground">
          共享 evidence 的排序分数没有明显变化。
        </div>
      )}
    </div>
  )
}

type RagTracePanelProps = {
  conversationId: string
  onCitationOpen: () => void
  className?: string
}

type TraceOperation = {
  owner: { active: boolean }
  controller: AbortController
  authRevision: number
  authScope: string
}

function createTraceOperation(owner: TraceOperation['owner']): TraceOperation {
  return {
    owner,
    controller: new AbortController(),
    authRevision: getAuthSessionRevision(),
    authScope: getAuthCacheScope(),
  }
}

function isCurrentTraceOperation(operation: TraceOperation, current: TraceOperation | null): boolean {
  return (
    operation === current &&
    operation.owner.active &&
    operation.authRevision === getAuthSessionRevision() &&
    operation.authScope === getAuthCacheScope()
  )
}

type TraceRow = { key: string; trace: RagTrace }
const TRACE_QUERY_PARAMS = { limit: 40, window_minutes: 24 * 60 }

function getTraceRows(items: readonly RagTrace[]): TraceRow[] {
  const occurrences = new Map<string, number>()
  return items.map((trace) => {
    const identity = JSON.stringify(trace)
    const occurrence = occurrences.get(identity) ?? 0
    occurrences.set(identity, occurrence + 1)
    return { key: `${identity}:${occurrence}`, trace }
  })
}

export function RagTracePanel({ conversationId, onCitationOpen, className }: Readonly<RagTracePanelProps>) {
  const t = useTranslations('RagTrace')
  const sessionKey = React.useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const selectionScope = JSON.stringify([sessionKey, conversationId])
  const tracesQuery = useQuery({
    queryKey: [...queryKeys.chat.ragTraces(conversationId, TRACE_QUERY_PARAMS), sessionKey],
    queryFn: ({ signal }) => chatApi.getRagTraces(conversationId, TRACE_QUERY_PARAMS, { signal }),
    staleTime: 0,
  })
  const data = tracesQuery.data
  const items = data?.items
  const reading = tracesQuery.fetchStatus !== 'idle'
  const rows = React.useMemo(() => (items === undefined ? [] : getTraceRows(items)), [items])
  const [selection, setSelection] = React.useState<{ scope: string; key: string } | undefined>()
  const selectedTraceKey = selection?.scope === selectionScope ? selection.key : undefined
  const selectTrace = (key: string) => setSelection({ scope: selectionScope, key })
  const selectedIndex = selectedTraceKey === undefined ? 0 : rows.findIndex((row) => row.key === selectedTraceKey)
  const selectedRow = selectedIndex < 0 ? undefined : rows[selectedIndex]
  React.useEffect(() => {
    const first = rows[0]
    if (first === undefined) return
    setSelection((current) => (current?.scope === selectionScope ? current : { scope: selectionScope, key: first.key }))
  }, [rows, selectionScope])

  function refreshTraces() {
    void tracesQuery.refetch({ cancelRefetch: false })
  }
  const handleTraceKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
    let direction: -1 | 1
    if (event.key === 'j' || event.key === 'ArrowDown') direction = 1
    else if (event.key === 'k' || event.key === 'ArrowUp') direction = -1
    else return
    event.preventDefault()
    event.stopPropagation()
    const nextIndex = selectedIndex < 0 ? 0 : moveTraceSelectionIndex(selectedIndex, rows.length, direction)
    selectTrace(rows[nextIndex].key)
    event.currentTarget.querySelectorAll<HTMLButtonElement>('button')[nextIndex].focus()
  }

  return (
    <div className={cn('min-w-0 space-y-3', className)} aria-busy={tracesQuery.isFetching}>
      {tracesQuery.isError && !reading && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 text-sm text-destructive">
          <p>{formatApiError(tracesQuery.error, t('panel.errors.traceLoadFailed'))}</p>
          <Button type="button" variant="outline" onClick={refreshTraces}>
            重新读取
          </Button>
        </div>
      )}
      {(tracesQuery.isPaused || tracesQuery.isRefetching) && (
        <p role="status" className="text-sm text-muted-foreground">
          {tracesQuery.isPaused ? '追踪读取已暂停' : '正在刷新追踪记录…'}
        </p>
      )}
      {tracesQuery.isLoading ? (
        <Panel variant="glass" className="flex min-h-[420px] items-center justify-center">
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-5 animate-spin motion-reduce:animate-none" />
            正在读取追踪记录…
          </p>
        </Panel>
      ) : data === undefined ? null : !data.enabled ? (
        <EmptyState
          title={t('panel.states.notEnabledTitle')}
          description={t('panel.states.notEnabledDescription')}
          icon={Route}
          iconClassName="text-info"
        >
          <Button type="button" variant="outline" disabled={reading} onClick={refreshTraces}>
            {t('panel.actions.refresh')}
          </Button>
        </EmptyState>
      ) : rows.length === 0 ? (
        <EmptyState
          title={t('panel.states.emptyTitle')}
          icon={Quote}
          iconClassName="text-info"
          description={
            <span>
              <span className="block">{t('panel.states.emptyHint')}</span>
              <span className="block text-xs">{t('panel.states.emptyFollowup')}</span>
            </span>
          }
        >
          <Button type="button" variant="outline" disabled={reading} onClick={refreshTraces}>
            {t('panel.actions.refresh')}
          </Button>
        </EmptyState>
      ) : (
        <section className="grid grid-cols-1 gap-3 lg:grid-cols-[300px,minmax(0,1fr)]" aria-label="RAG 追踪记录">
          <Panel
            variant="glass"
            padding="none"
            className="overflow-hidden border-info/14 bg-[linear-gradient(180deg,hsl(var(--info)/0.05),hsl(var(--background)/0.7))]"
          >
            <div className="flex items-center justify-between gap-3 border-b border-border/60 px-3 py-2.5">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Route className="size-4 text-info" />
                  <div className="text-sm font-semibold">{t('panel.header.title')}</div>
                  <Badge variant="soft" className="text-[11px]">
                    {rows.length} 条
                  </Badge>
                </div>
                <p className="mt-1 truncate text-[11px] text-muted-foreground">{t('panel.header.keyboardHint')}</p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={refreshTraces}
                disabled={reading}
                className="h-8 rounded-xl px-3"
              >
                {t('panel.actions.refresh')}
              </Button>
            </div>
            <div
              role="group"
              aria-label="追踪记录选择"
              tabIndex={0}
              onKeyDown={handleTraceKeyDown}
              className="max-h-[250px] overflow-y-auto p-2"
            >
              {rows.map((row) => {
                const trace = row.trace
                const active = row.key === selectedRow?.key
                return (
                  <button
                    key={row.key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => selectTrace(row.key)}
                    className={cn(
                      'w-full rounded-xl border px-3 py-2 text-left transition-colors',
                      'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background',
                      active ? 'border-info bg-info shadow-sm' : 'border-border/60 bg-background/65 hover:bg-muted/40',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs font-medium text-foreground">{formatTs(trace.ts_ms)}</div>
                      <Badge variant="soft" className="text-[11px]">
                        {formatTraceModeLabel(trace.retrieval.mode)}
                      </Badge>
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                      <span>{formatCitationCount(trace.citations_count)}</span>
                      <span className="inline-flex items-center gap-1">
                        <Timer className="size-3" />
                        {formatSec(trace.retrieval.elapsed_sec)}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          </Panel>
          {selectedRow === undefined ? (
            <Panel>
              <p role="status" className="text-sm text-muted-foreground">
                所选记录已不在当前追踪窗口中。
              </p>
              <Button type="button" variant="outline" className="mt-3" onClick={() => selectTrace(rows[0].key)}>
                查看最新记录
              </Button>
            </Panel>
          ) : (
            <RagTraceDetails
              key={`${selectionScope}:${selectedRow.key}`}
              selected={selectedRow.trace}
              items={data.items}
              conversationId={conversationId}
              onCitationOpen={onCitationOpen}
              sessionKey={sessionKey}
            />
          )}
        </section>
      )}
    </div>
  )
}

function RagTraceDetails({
  selected,
  items,
  conversationId,
  onCitationOpen,
  sessionKey,
}: Readonly<{
  selected: RagTrace
  items: readonly RagTrace[]
  conversationId: string
  onCitationOpen: () => void
  sessionKey: string
}>) {
  const t = useTranslations('RagTrace')
  const openDocument = useDocumentView((state) => state.openDocument)
  const access = useTenantAccess()
  const canReadObservability = tenantAccessAllows(access.data, TENANT_PERMISSIONS.OBSERVABILITY_READ)

  const [bundleDownloading, setBundleDownloading] = React.useState(false)
  const [bundleError, setBundleError] = React.useState<string | null>(null)
  const operationOwnerRef = React.useRef({ active: true })
  const bundleOperationRef = React.useRef<TraceOperation | null>(null)
  const diffOperationRef = React.useRef<TraceOperation | null>(null)
  React.useLayoutEffect(() => {
    operationOwnerRef.current = { active: true }
    return () => {
      operationOwnerRef.current.active = false
      const bundle = bundleOperationRef.current
      bundleOperationRef.current = null
      bundle?.controller.abort()
      const diff = diffOperationRef.current
      diffOperationRef.current = null
      diff?.controller.abort()
    }
  }, [])
  const [diffOpen, setDiffOpen] = React.useState(false)
  const [diffOtherRequestId, setDiffOtherRequestId] = React.useState('')
  const [diffLoading, setDiffLoading] = React.useState(false)
  const [diffError, setDiffError] = React.useState<string | null>(null)
  const [diffResult, setDiffResult] = React.useState<RagTraceBundleDiffResponse | null>(null)
  const [selectedPipelineSectionId, setSelectedPipelineSectionId] = React.useState<string | null>(null)
  const [selectedCitationChannel, setSelectedCitationChannel] = React.useState<RagTraceCitationChannelFilter>('all')
  const [citationSimulationWeights, setCitationSimulationWeights] = React.useState<CitationSimulationWeights>(() =>
    buildCitationSimulationWeightsForPreset('balanced', getVaryingCitationSimulationChannels(selected.citations)),
  )
  const [traceTargetState, setTraceTargetState] = React.useState<TraceTargetState>({ status: 'pending' })
  const [traceTargetScope] = React.useState(getAuthCacheScope)
  const prefetchedTraceCitationTargetsRef = React.useRef<Set<string>>(new Set())

  const retrievalConfigHash = selected.retrieval.retrieval_config_hash
  const { enabled: rerankEnabled, provider: rerankProvider } = selected.rerank
  const mainQuery = selected.retrieval.per_query?.find((query) => query.kind === 'main')
  const channels = getRecordField(mainQuery?.retriever_debug, 'channels')
  const hierarchyRecall = getRecordField(mainQuery?.retriever_debug, 'hierarchy_recall')
  const rerankMeta = getRecordField(channels, 'rerank')
  const channelTiming = getRecordField(channels, 'timing')
  const rerankSkipReason = rerankMeta?.skip_reason == null ? null : formatDiagnosticText(rerankMeta.skip_reason)
  const rerankError = rerankMeta?.error == null ? null : formatDiagnosticText(rerankMeta.error)
  const requestId = selected.request_id?.trim()
  const diffCandidateOptions = React.useMemo(() => buildTraceDiffCandidateOptions(items, selected), [items, selected])
  const displayedDiffRequestId = diffOtherRequestId.trim()
  const selectedDiffComparisonTrace = React.useMemo(() => {
    const targetRequestId = displayedDiffRequestId
    if (!targetRequestId) return null
    return items.find((item) => item.request_id?.trim() === targetRequestId) ?? null
  }, [displayedDiffRequestId, items])
  const localCitationDiff = React.useMemo(
    () => buildTraceCitationDiff(selected, selectedDiffComparisonTrace),
    [selected, selectedDiffComparisonTrace],
  )
  const pipelineSteps = React.useMemo(() => buildPipelineTimelineSteps(selected), [selected])
  const pipelineInspectorSections = React.useMemo(() => buildPipelineInspectorSections(selected, t), [selected, t])
  const availableCitationSimulationChannels = React.useMemo(
    () => getVaryingCitationSimulationChannels(selected.citations),
    [selected],
  )
  const simulatedCitationRows = React.useMemo(
    () => buildCitationSimulationRows(selected.citations, citationSimulationWeights),
    [citationSimulationWeights, selected],
  )
  const channelSummaries = React.useMemo(
    () => buildTraceCitationChannelSummaries(selected, selectedCitationChannel, t),
    [selected, selectedCitationChannel, t],
  )
  const filteredCitations = React.useMemo(
    () => filterTraceCitationsByChannel(selected.citations, selectedCitationChannel),
    [selected, selectedCitationChannel],
  )
  const evidencePreviewCitations = React.useMemo(
    () => buildCitationsSummary(selected.citations).top.slice(0, TRACE_EVIDENCE_PREVIEW_LIMIT),
    [selected],
  )
  const evidencePreviewKey = React.useMemo(
    () =>
      JSON.stringify(
        evidencePreviewCitations.map((citation) => {
          const { documentId, chunkId } = getTraceCitationIds(citation)
          return [documentId, chunkId]
        }),
      ),
    [evidencePreviewCitations],
  )
  const evidencePreviewQuery = useQuery({
    queryKey: ['rag-trace', 'evidence-preview', sessionKey, requestId, evidencePreviewKey],
    enabled: evidencePreviewCitations.length > 0,
    staleTime: 0,
    queryFn: ({ signal }) => {
      return Promise.allSettled(
        evidencePreviewCitations.map(async (citation) => {
          const { documentId, chunkId } = getTraceCitationIds(citation)
          if (!documentId || !chunkId) return null
          return documentApi.getChunk(documentId, chunkId, { signal })
        }),
      )
    },
  })
  const activeChannelSummary = React.useMemo(
    () => channelSummaries.find((summary) => summary.active),
    [channelSummaries],
  )
  const lastOpenedTraceCitationTarget = traceTargetState.status === 'ready' ? traceTargetState.target : null
  const traceTargetError =
    traceTargetState.status === 'error'
      ? traceTargetState.message
      : traceTargetState.status === 'ready'
        ? traceTargetState.warning
        : undefined
  const selectedPipelineSection = React.useMemo(
    () =>
      pipelineInspectorSections.find((section) => section.id === selectedPipelineSectionId) ??
      pipelineInspectorSections[0] ??
      null,
    [pipelineInspectorSections, selectedPipelineSectionId],
  )
  const selectedPipelineSectionIndex = React.useMemo(() => {
    if (!selectedPipelineSection) return -1
    return pipelineInspectorSections.findIndex((section) => section.id === selectedPipelineSection.id)
  }, [pipelineInspectorSections, selectedPipelineSection])

  React.useEffect(() => {
    if (!requestId) {
      setTraceTargetState({ status: 'ready', target: null })
      return
    }
    try {
      const target = readStoredTraceCitationTarget(traceTargetScope, conversationId, requestId)
      setTraceTargetState({ status: 'ready', target })
    } catch (error) {
      reportClientError('Failed to read the last trace citation target', error)
      setTraceTargetState({ status: 'error', message: '最近打开的位置无法读取，重新打开一条证据即可更新。' })
    }
  }, [traceTargetScope, conversationId, requestId])

  const applyCitationSimulationPreset = React.useCallback(
    (preset: CitationSimulationPreset) => {
      setCitationSimulationWeights(buildCitationSimulationWeightsForPreset(preset, availableCitationSimulationChannels))
    },
    [availableCitationSimulationChannels],
  )

  const prefetchTraceCitationTarget = React.useCallback((documentId?: string | null, chunkId?: string | null) => {
    const docId = documentId?.trim()
    if (!docId) return
    const cid = chunkId?.trim()
    const targetKey = JSON.stringify([docId, cid])
    if (prefetchedTraceCitationTargetsRef.current.has(targetKey)) return
    prefetchedTraceCitationTargetsRef.current.add(targetKey)
    prefetchDocumentView({ documentId: docId, chunkId: cid })
  }, [])

  const rememberOpenedTraceCitationTarget = React.useCallback(
    (target: StoredTraceCitationTarget) => {
      const saved = writeStoredTraceCitationTarget(traceTargetScope, target)
      setTraceTargetState({
        status: 'ready',
        target,
        warning: saved ? undefined : '最近位置未能保存，刷新后不会保留。',
      })
    },
    [traceTargetScope],
  )

  const openTraceCitation = React.useCallback(
    (citation: RagTraceCitation, opts?: { label?: string; notify?: boolean }) => {
      const documentId = citation.document_id?.trim()
      if (!documentId) return

      let chunkId = citation.chunk_id?.trim()
      if (chunkId === '') chunkId = undefined
      const range = getTraceCitationRange(citation)
      const label = opts?.label ?? getTraceCitationLabel(citation, documentId)

      if (requestId) {
        rememberOpenedTraceCitationTarget({
          conversationId,
          requestId,
          documentId,
          chunkId,
          range,
          pageNumber: citation.page_number ?? undefined,
          label,
          openedAt: Date.now(),
        })
      }

      onCitationOpen()
      openDocument(documentId, chunkId, range, {
        previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
      })
      if (opts?.notify) {
        const chunkSuffix = chunkId ? ` · ${chunkId}` : ''
        toast.message(t('panel.toasts.openedCitationDocument'), {
          description: `${label}${chunkSuffix}`,
        })
      }
    },
    [conversationId, onCitationOpen, openDocument, rememberOpenedTraceCitationTarget, requestId, t],
  )

  const reopenLastTraceCitation = React.useCallback(() => {
    if (lastOpenedTraceCitationTarget === null) return
    const target = lastOpenedTraceCitationTarget
    onCitationOpen()
    openDocument(target.documentId, target.chunkId, target.range, {
      previewAnchor: target.pageNumber === undefined ? undefined : { pageNumber: target.pageNumber },
    })
    const pageLabel = target.pageNumber === undefined ? '' : ` · P.${target.pageNumber}`
    toast.message(t('panel.toasts.reopenedRecentEvidence'), { description: `${target.label}${pageLabel}` })
  }, [lastOpenedTraceCitationTarget, onCitationOpen, openDocument, t])

  const downloadBundle = React.useCallback(async () => {
    const rid = requestId
    if (!canReadObservability || !rid || bundleOperationRef.current !== null) return
    const operation = createTraceOperation(operationOwnerRef.current)
    bundleOperationRef.current = operation
    setBundleDownloading(true)
    setBundleError(null)
    try {
      const signal = operation.controller.signal
      const [meta, ready, configSnapshot, traceBundle] = await Promise.all([
        metaApi.details({ signal }),
        healthApi.details({ signal }),
        observabilityApi.getOpsConfigSnapshot({ signal }),
        observabilityApi.getRagTraceBundle(
          { request_id: rid, window_minutes: TRACE_QUERY_PARAMS.window_minutes },
          { signal },
        ),
      ])
      if (!isCurrentTraceOperation(operation, bundleOperationRef.current)) return
      const { default: JSZip } = await import('jszip')
      if (!isCurrentTraceOperation(operation, bundleOperationRef.current)) return
      const exportedAt = new Date().toISOString()
      const zip = new JSZip()
      zip.file('meta.json', JSON.stringify(meta, null, 2))
      zip.file('health_ready.json', JSON.stringify(ready, null, 2))
      zip.file('config_snapshot.json', JSON.stringify(configSnapshot, null, 2))
      zip.file('trace_bundle.json', JSON.stringify(traceBundle, null, 2))
      zip.file(
        'README.txt',
        [
          'Ragvia Incident Bundle',
          `exported_at: ${exportedAt}`,
          `request_id: ${rid}`,
          `window_minutes: ${TRACE_QUERY_PARAMS.window_minutes}`,
          '',
          'Files:',
          '- meta.json',
          '- health_ready.json',
          '- config_snapshot.json',
          '- trace_bundle.json',
          '',
          'trace_bundle.json contains the diagnostic records returned by /api/v1/observability/rag-metrics/trace-bundle.',
        ].join('\n'),
      )
      const blob = await zip.generateAsync({ type: 'blob' })
      if (!isCurrentTraceOperation(operation, bundleOperationRef.current)) return
      downloadBlob(`incident_bundle_${formatRequestFilenamePart(rid)}_${formatFilenameTimestamp(exportedAt)}.zip`, blob)
      toast.success(t('panel.toasts.bundleDownloadStarted'))
    } catch (error) {
      if (!isCurrentTraceOperation(operation, bundleOperationRef.current)) return
      const message = formatApiError(error, t('panel.errors.bundleDownloadFailed'))
      setBundleError(message)
      toast.error(message)
    } finally {
      operation.controller.abort()
      if (bundleOperationRef.current === operation) {
        bundleOperationRef.current = null
        if (operation.owner.active) setBundleDownloading(false)
      }
    }
  }, [canReadObservability, requestId, t])

  const changeComparisonRequest = React.useCallback((value: string) => {
    const previous = diffOperationRef.current
    diffOperationRef.current = null
    previous?.controller.abort()
    setDiffOtherRequestId(value)
    setDiffLoading(false)
    setDiffResult(null)
    setDiffError(null)
  }, [])

  const runDiffForRequestId = React.useCallback(
    async (otherRequestId: string) => {
      const a = requestId
      const b = otherRequestId.trim()
      if (!canReadObservability || !a || !b) return
      if (a === b) {
        setDiffError(t('panel.errors.diffSameRequest'))
        return
      }
      const previous = diffOperationRef.current
      diffOperationRef.current = null
      previous?.controller.abort()
      const operation = createTraceOperation(operationOwnerRef.current)
      diffOperationRef.current = operation
      setDiffLoading(true)
      setDiffError(null)
      try {
        const response = await observabilityApi.getRagTraceBundleDiff(
          { request_id_a: a, request_id_b: b, window_minutes: TRACE_QUERY_PARAMS.window_minutes },
          { signal: operation.controller.signal },
        )
        if (!isCurrentTraceOperation(operation, diffOperationRef.current)) return
        setDiffResult(response)
      } catch (error) {
        if (!isCurrentTraceOperation(operation, diffOperationRef.current)) return
        const message = formatApiError(error, t('panel.errors.diffLoadFailed'))
        setDiffError(message)
      } finally {
        operation.controller.abort()
        if (diffOperationRef.current === operation) {
          diffOperationRef.current = null
          if (operation.owner.active) setDiffLoading(false)
        }
      }
    },
    [canReadObservability, requestId, t],
  )
  const selectDiffCandidate = React.useCallback(
    (candidate: TraceDiffCandidateOption) => {
      changeComparisonRequest(candidate.requestId)
      if (canReadObservability) detachPromise(runDiffForRequestId(candidate.requestId))
    },
    [canReadObservability, changeComparisonRequest, runDiffForRequestId],
  )

  return (
    <div className="min-w-0 space-y-3">
      <Panel
        variant="glass"
        className="flex flex-col gap-2 border-info/14 bg-[linear-gradient(135deg,hsl(var(--background)),hsl(var(--background)),hsl(var(--info)/0.04))]"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="soft"
              className="max-w-[14rem] truncate text-[11px] font-mono"
              title={selected.request_id ?? undefined}
            >
              请求 {selected.request_id ? abbreviateIdentifier(selected.request_id, { head: 12, tail: 8 }) : '—'}
            </Badge>
            <Badge variant="soft" className="text-[11px]">
              {formatTraceModeLabel(selected.retrieval.mode)}
            </Badge>
            {retrievalConfigHash ? (
              <Badge variant="soft" className="text-[11px] font-mono" title={retrievalConfigHash}>
                cfg: {abbreviateIdentifier(retrievalConfigHash)}
              </Badge>
            ) : null}
            <Badge variant="soft" className="text-[11px]">
              {formatCitationCount(selected.citations_count)}
            </Badge>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Timer className="h-4 w-4" />
              检索 {formatSec(selected.retrieval.elapsed_sec)} · 重排 {formatSec(selected.rerank.elapsed_sec)}
            </div>
            {canReadObservability && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 rounded-xl px-3 text-xs"
                disabled={!requestId || bundleDownloading}
                onClick={() => detachPromise(downloadBundle())}
                title={t('panel.actions.downloadBundleTitle')}
              >
                {bundleDownloading ? (
                  <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                {t('panel.actions.downloadBundle')}
              </Button>
            )}
            {(canReadObservability || diffCandidateOptions.length > 0) && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 rounded-xl px-3 text-xs"
                disabled={!requestId}
                onClick={() => setDiffOpen((v) => !v)}
                title={t('panel.actions.compareTitle')}
              >
                <GitCompare className="h-4 w-4" />
                {t('panel.actions.compare')}
              </Button>
            )}
          </div>
        </div>

        {canReadObservability && bundleError ? (
          <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {bundleError}
          </div>
        ) : null}

        <AnimatePresence initial={false}>
          {diffOpen ? (
            <motion.div
              key="trace-diff"
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
            >
              <Panel variant="muted" className="space-y-3">
                {diffCandidateOptions.length ? (
                  <div className="space-y-2">
                    <div>
                      <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                        {t('panel.compareCandidates.title')}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {t('panel.compareCandidates.description')}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {diffCandidateOptions.slice(0, 6).map((candidate) => {
                        const active = diffOtherRequestId.trim() === candidate.requestId
                        return (
                          <button
                            key={`diff-candidate:${candidate.requestId}`}
                            type="button"
                            onClick={() => selectDiffCandidate(candidate)}
                            className={cn(
                              'rounded-xl border px-3 py-2 text-left transition-colors',
                              'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background',
                              active
                                ? 'border-info bg-info'
                                : 'border-border/60 bg-background/80 hover:border-info hover:bg-muted/30',
                            )}
                          >
                            <div className="flex items-center gap-2 text-xs font-medium text-foreground">
                              <span className="font-mono">
                                {abbreviateIdentifier(candidate.requestId, { head: 10, tail: 6 })}
                              </span>
                              <Badge variant="soft" className="text-[11px]">
                                {getTraceConfigMatchLabel(candidate.sameRetrievalConfig)}
                              </Badge>
                            </div>
                            <div className="mt-1 text-[11px] text-muted-foreground">
                              {candidate.mode || '—'} · citations={candidate.citationsCount} ·{' '}
                              {formatTs(candidate.tsMs)}
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ) : null}

                {canReadObservability && (
                  <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                    <div className="grid w-full grid-cols-1 gap-3 md:grid-cols-2">
                      <div className="space-y-1">
                        <div className="text-[11px] text-muted-foreground">{t('panel.compare.requestIdA')}</div>
                        <Input
                          value={requestId}
                          readOnly
                          className="font-mono text-xs"
                          aria-label={t('panel.compare.requestIdA')}
                        />
                      </div>
                      <div className="space-y-1">
                        <div className="text-[11px] text-muted-foreground">{t('panel.compare.requestIdB')}</div>
                        <Input
                          value={diffOtherRequestId}
                          onChange={(event) => changeComparisonRequest(event.target.value)}
                          aria-label={t('panel.compare.requestIdB')}
                          placeholder={t('panel.compare.requestIdBPlaceholder')}
                          className="font-mono text-xs"
                        />
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="gap-2 rounded-xl"
                      disabled={!requestId || !diffOtherRequestId.trim() || diffLoading}
                      onClick={() => detachPromise(runDiffForRequestId(diffOtherRequestId))}
                    >
                      {diffLoading ? (
                        <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                      ) : (
                        <GitCompare className="h-4 w-4" />
                      )}
                      {t('panel.compare.action')}
                    </Button>
                  </div>
                )}

                {canReadObservability && diffError ? (
                  <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                    {diffError}
                  </div>
                ) : null}

                {localCitationDiff !== null && selectedDiffComparisonTrace !== null ? (
                  <Panel variant="glass" className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                          {t('panel.evidenceDrift.title')}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">{t('panel.evidenceDrift.description')}</div>
                      </div>
                      <Badge variant="soft" className="text-[11px]">
                        A {requestId || '—'} vs B {selectedDiffComparisonTrace.request_id || '—'}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                      <div className="rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft">
                        <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                          {t('panel.evidenceDrift.sharedTitle')}
                        </div>
                        <div className="mt-1 text-lg font-semibold text-foreground">
                          {localCitationDiff.sharedCount}
                        </div>
                      </div>
                      <div className="rounded-xl border border-success/20 bg-success/5 px-3 py-3">
                        <div className="text-[11px] font-semibold uppercase text-success">
                          {t('panel.evidenceDrift.addedSummaryTitle')}
                        </div>
                        <div className="mt-1 text-lg font-semibold text-foreground">{localCitationDiff.addedCount}</div>
                      </div>
                      <div className="rounded-xl border border-warning/20 bg-warning/5 px-3 py-3">
                        <div className="text-[11px] font-semibold uppercase text-warning">
                          {t('panel.evidenceDrift.removedSummaryTitle')}
                        </div>
                        <div className="mt-1 text-lg font-semibold text-foreground">
                          {localCitationDiff.removedCount}
                        </div>
                      </div>
                      <div className="rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft">
                        <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                          {t('panel.evidenceDrift.scoreShiftSummaryTitle')}
                        </div>
                        <div className="mt-1 text-lg font-semibold text-foreground">
                          {localCitationDiff.scoreShiftCount}
                        </div>
                      </div>
                    </div>

                    {(localCitationDiff.unidentifiedCountA > 0 || localCitationDiff.unidentifiedCountB > 0) && (
                      <p className="text-xs text-muted-foreground">
                        {t('panel.evidenceDrift.unidentifiedSummary', {
                          a: localCitationDiff.unidentifiedCountA,
                          b: localCitationDiff.unidentifiedCountB,
                        })}
                      </p>
                    )}
                    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                      <TraceCitationDiffList
                        title={t('panel.evidenceDrift.addedTitle')}
                        emptyLabel={t('panel.evidenceDrift.addedEmpty')}
                        items={localCitationDiff.added}
                        tone="added"
                        onPrefetchCitation={prefetchTraceCitationTarget}
                        onOpenCitation={openTraceCitation}
                      />
                      <TraceCitationDiffList
                        title={t('panel.evidenceDrift.removedTitle')}
                        emptyLabel={t('panel.evidenceDrift.removedEmpty')}
                        items={localCitationDiff.removed}
                        tone="removed"
                        onPrefetchCitation={prefetchTraceCitationTarget}
                        onOpenCitation={openTraceCitation}
                      />
                    </div>

                    <TraceCitationScoreShiftList
                      items={localCitationDiff.scoreShifts}
                      onPrefetchCitation={prefetchTraceCitationTarget}
                      onOpenCitation={openTraceCitation}
                    />
                  </Panel>
                ) : null}
                {localCitationDiff === null && displayedDiffRequestId ? (
                  <div className="rounded-xl border border-dashed border-sidebar-border/60 bg-sidebar/45 px-3 py-3 text-xs text-muted-foreground">
                    {t('panel.evidenceDrift.missingLocalSummary')}
                  </div>
                ) : null}

                {canReadObservability && diffResult ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      <div className="rounded-xl border border-sidebar-border/60 bg-sidebar/45 px-3 py-2 text-xs text-muted-foreground">
                        <div className="break-all text-[11px] text-muted-foreground">
                          {t('panel.compare.summaryA')} · {diffResult.request_id_a}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          mode={formatTraceModeLabel(diffResult.summary_a.retrieval_mode)} · cfg=
                          {diffResult.summary_a.retrieval_config_hash
                            ? abbreviateIdentifier(diffResult.summary_a.retrieval_config_hash)
                            : '—'}{' '}
                          · citations=
                          {diffResult.summary_a.citations_count ?? '—'}
                        </div>
                      </div>
                      <div className="rounded-xl border border-sidebar-border/60 bg-sidebar/45 px-3 py-2 text-xs text-muted-foreground">
                        <div className="break-all text-[11px] text-muted-foreground">
                          {t('panel.compare.summaryB')} · {diffResult.request_id_b}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          mode={formatTraceModeLabel(diffResult.summary_b.retrieval_mode)} · cfg=
                          {diffResult.summary_b.retrieval_config_hash
                            ? abbreviateIdentifier(diffResult.summary_b.retrieval_config_hash)
                            : '—'}{' '}
                          · citations=
                          {diffResult.summary_b.citations_count ?? '—'}
                        </div>
                      </div>
                    </div>

                    <div className="text-[11px] text-muted-foreground">
                      {t('panel.compare.changesMeta', {
                        changes: diffResult.diff.length,
                        truncated: diffResult.truncated
                          ? t('panel.compare.truncatedYes')
                          : t('panel.compare.truncatedNo'),
                      })}
                    </div>
                    <div className="space-y-2">
                      {diffResult.diff.map((it) => (
                        <div
                          key={it.key}
                          className="grid grid-cols-1 gap-2 rounded-xl border border-sidebar-border/60 bg-sidebar/45 px-3 py-2 md:grid-cols-3"
                        >
                          <div className="text-xs font-mono text-foreground">{it.key}</div>
                          <div className="text-xs text-muted-foreground break-words">{formatDiffValue(it.a)}</div>
                          <div className="text-xs text-muted-foreground break-words">
                            {formatDiffValue(it.b)}
                            {it.delta != null ? (
                              <span className="ml-2 font-mono text-[11px] text-foreground/80">
                                Δ {String(it.delta)}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </Panel>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <div className="grid grid-cols-3 gap-2">
          <Panel variant="muted" className="flex items-center gap-2 px-3 py-2">
            <Timer className="h-4 w-4 text-info" />
            <div className="min-w-0">
              <div className="text-xs font-semibold text-foreground">{t('panel.pipelineSummary.retrieve')}</div>
              <div className="text-xs text-muted-foreground">{formatSec(selected.retrieval.elapsed_sec)}</div>
            </div>
          </Panel>
          <Panel variant="muted" className="flex items-center gap-2 px-3 py-2">
            <Database className="h-4 w-4 text-info" />
            <div className="min-w-0">
              <div className="text-xs font-semibold text-foreground">{t('panel.pipelineSummary.reranker')}</div>
              <div className="truncate text-xs text-muted-foreground">
                {!rerankEnabled ? '未启用' : rerankProvider ? rerankProvider : '已启用'}
              </div>
            </div>
          </Panel>
          <Panel variant="muted" className="flex items-center gap-2 px-3 py-2">
            <Quote className="h-4 w-4 text-info" />
            <div className="min-w-0">
              <div className="text-xs font-semibold text-foreground">{t('panel.pipelineSummary.citations')}</div>
              <div className="text-xs text-muted-foreground">{selected.citations_count}</div>
            </div>
          </Panel>
        </div>

        {evidencePreviewCitations.length ? (
          <div className="space-y-2 rounded-2xl border border-info bg-info/[0.035] p-3 shadow-soft">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-xs font-semibold text-foreground">{t('panel.evidencePreview.title')}</div>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  {t('panel.evidencePreview.description', {
                    count: Math.min(TRACE_EVIDENCE_PREVIEW_LIMIT, evidencePreviewCitations.length),
                  })}
                </div>
              </div>
              {evidencePreviewQuery.isFetching ? (
                <Badge variant="soft" className="gap-1 text-[11px]">
                  <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
                  {t('panel.evidencePreview.loading')}
                </Badge>
              ) : null}
            </div>

            <div className="grid grid-cols-1 gap-2 lg:grid-cols-2 2xl:grid-cols-3">
              {evidencePreviewCitations.map((citation, index) => {
                const { documentId, chunkId } = getTraceCitationIds(citation)
                const label = getTraceCitationLabel(citation, t('panel.evidencePreview.kinds.default'))
                const score = getPrimaryScore(citation)
                const previewResult = evidencePreviewQuery.data?.[index]
                const previewChunk = previewResult?.status === 'fulfilled' ? previewResult.value : undefined
                const previewError =
                  previewResult?.status === 'rejected'
                    ? formatApiError(previewResult.reason, '读取切片失败')
                    : undefined
                const previewText =
                  previewChunk == null
                    ? (previewError ??
                      (evidencePreviewQuery.isFetching
                        ? t('panel.evidencePreview.loading')
                        : t('panel.evidencePreview.missingContent')))
                    : previewChunk.content.length === 0
                      ? '该切片正文为空。'
                      : compactEvidenceText(previewChunk.content)
                return (
                  <div
                    key={`evidence-preview:${index}`}
                    className="flex flex-col rounded-xl border border-border/60 bg-background/80 p-2.5 shadow-sm"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge variant="soft" className="text-[11px]">
                          {t('panel.evidencePreview.kinds.default')}
                        </Badge>
                        {score == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            {t('panel.evidencePreview.score')}={score.toFixed(3)}
                          </Badge>
                        )}
                        {previewChunk ? (
                          <Badge variant="soft" className="text-[11px]">
                            {t('panel.evidencePreview.loaded')}
                          </Badge>
                        ) : null}
                      </div>
                      <div className="mt-1.5 truncate text-sm font-semibold text-foreground" title={label}>
                        {label}
                      </div>
                      <div className="mt-1 break-all text-[11px] leading-4 text-muted-foreground">
                        {t('panel.evidencePreview.document')}{' '}
                        {documentId ? abbreviateIdentifier(documentId, { head: 10, tail: 6 }) : '—'}
                        {chunkId
                          ? ` · ${t('panel.evidencePreview.chunk')} ${abbreviateIdentifier(chunkId, { head: 10, tail: 6 })}`
                          : ''}
                      </div>
                      <div className="mt-2 rounded-lg bg-muted/35 px-2 py-1.5 text-xs leading-5 text-foreground/85">
                        <span className="font-semibold">{t('panel.evidencePreview.takeaway')}：</span>
                        {t('panel.evidencePreview.reasons.default')}
                      </div>
                      <p
                        role={previewError === undefined ? undefined : 'alert'}
                        className={cn(
                          'mt-1.5 text-[11px] leading-4',
                          previewError === undefined ? 'text-muted-foreground' : 'text-destructive',
                        )}
                      >
                        {previewText}
                      </p>
                      {previewError !== undefined && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={evidencePreviewQuery.isFetching}
                          onClick={() => void evidencePreviewQuery.refetch({ cancelRefetch: false })}
                        >
                          重试读取
                        </Button>
                      )}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-2 h-8 w-full rounded-xl"
                      disabled={!documentId}
                      onMouseEnter={() => prefetchTraceCitationTarget(documentId, chunkId)}
                      onFocus={() => prefetchTraceCitationTarget(documentId, chunkId)}
                      onClick={() => openTraceCitation(citation, { label, notify: true })}
                    >
                      <ExternalLink className="h-4 w-4" />
                      <span className="ml-1">{t('panel.evidencePreview.open')}</span>
                    </Button>
                  </div>
                )
              })}
            </div>
          </div>
        ) : null}
      </Panel>

      <Panel variant="glass" className="overflow-hidden" padding="none">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
          <div>
            <div className="text-sm font-semibold">{t('panel.timeline.title')}</div>
            <div className="mt-1 text-xs text-muted-foreground">{t('panel.timeline.description')}</div>
          </div>
          {selectedPipelineSection && selectedPipelineSectionIndex >= 0 ? (
            <Badge variant="soft" className="text-[11px]">
              stage {selectedPipelineSectionIndex + 1}/{pipelineInspectorSections.length}
            </Badge>
          ) : null}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.2fr)_minmax(18rem,0.8fr)]">
          <section
            aria-label="Pipeline timeline"
            className="outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <RagTracePipelineTimeline
              steps={pipelineSteps}
              selectedKey={selectedPipelineSection?.id ?? selectedPipelineSectionId}
              onSelectStep={setSelectedPipelineSectionId}
              emptyLabel={t('panel.timeline.unavailable')}
            />
          </section>
          <div className="border-t border-border/60 bg-muted/10 lg:border-l lg:border-t-0">
            <AnimatePresence mode="wait" initial={false}>
              {selectedPipelineSection ? (
                <motion.div
                  key={selectedPipelineSection.id}
                  initial={{ opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -12 }}
                  transition={{ duration: 0.18, ease: 'easeOut' }}
                  className="space-y-3 p-4"
                >
                  <div>
                    <div className="text-sm font-semibold text-foreground">{selectedPipelineSection.label}</div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{selectedPipelineSection.summary}</p>
                  </div>

                  {selectedPipelineSection.callout ? (
                    <div className="rounded-xl border border-info/25 bg-info/10 px-3 py-2 text-xs text-info">
                      {selectedPipelineSection.callout}
                    </div>
                  ) : null}

                  {selectedPipelineSection.metrics.length ? (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {selectedPipelineSection.metrics.map((metric) => (
                        <div
                          key={`${selectedPipelineSection.id}:${metric.label}`}
                          className="rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-2 shadow-soft"
                        >
                          <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                            {metric.label}
                          </div>
                          <div className="mt-1 text-sm font-semibold text-foreground">{metric.value}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-xl border border-dashed border-sidebar-border/60 bg-sidebar/45 px-3 py-2 text-xs text-muted-foreground">
                      {t('panel.timeline.metricsUnavailable')}
                    </div>
                  )}

                  {selectedPipelineSection.citations.length ? (
                    <div className="space-y-2">
                      <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                        {t('panel.timeline.quickEvidence')}
                      </div>
                      {selectedPipelineSection.citations.slice(0, 3).map((citation, index) => {
                        const documentId = citation.document_id?.trim()
                        let chunkId = citation.chunk_id?.trim()
                        if (chunkId === '') chunkId = undefined
                        const pageLabel = citation.page_number == null ? null : `P.${citation.page_number}`
                        const label = getTraceCitationLabel(citation, `citation-${index + 1}`)
                        return (
                          <button
                            key={`${documentId}:${chunkId || index}`}
                            type="button"
                            disabled={!documentId}
                            onMouseEnter={() => prefetchTraceCitationTarget(documentId, chunkId)}
                            onFocus={() => prefetchTraceCitationTarget(documentId, chunkId)}
                            onClick={() => {
                              if (!documentId) return
                              openTraceCitation(citation, { label })
                            }}
                            className="flex w-full items-center justify-between gap-3 rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-2 text-left transition-colors shadow-soft hover:bg-sidebar/70 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <div className="min-w-0">
                              <div className="truncate text-sm font-medium text-foreground">{label}</div>
                              <div className="mt-1 text-[11px] text-muted-foreground">
                                {pageLabel ? `${pageLabel} · ` : ''}
                                {chunkId ? `chunk=${chunkId}` : t('panel.timeline.documentLevelEvidence')}
                              </div>
                            </div>
                            <ExternalLink className="h-4 w-4 shrink-0 text-muted-foreground" />
                          </button>
                        )
                      })}
                    </div>
                  ) : null}
                </motion.div>
              ) : (
                <div className="p-4 text-xs text-muted-foreground">{t('panel.timeline.unavailable')}</div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </Panel>

      <Panel variant="glass" className="overflow-hidden" padding="none">
        <div className="px-4 py-3 border-b border-border/60">
          <div className="text-sm font-semibold">{t('panel.channels.title')}</div>
        </div>
        <div className="p-4 space-y-3">
          <div className="rounded-2xl border border-sidebar-border/70 bg-sidebar/60 p-3 shadow-soft">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                  {t('panel.channels.focusTitle')}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{t('panel.channels.focusDescription')}</div>
              </div>
              {activeChannelSummary ? (
                <Badge variant="soft" className="text-[11px]">
                  {activeChannelSummary.matchCount}/{selected.citations.length} 条引用 · focus=
                  {getRagTraceCitationChannelLabel(selectedCitationChannel, t)}
                </Badge>
              ) : null}
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              {channelSummaries.map((summary) => (
                <button
                  key={summary.key}
                  type="button"
                  aria-pressed={summary.active}
                  onClick={() => setSelectedCitationChannel(summary.key)}
                  className={cn(
                    'rounded-full border px-3 py-1.5 text-left text-xs transition-colors',
                    'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background',
                    summary.active
                      ? 'border-info/25 bg-info/10 text-info'
                      : 'border-border/60 bg-background/80 text-muted-foreground hover:border-info hover:text-foreground',
                  )}
                >
                  <span className="font-semibold">{summary.label}</span>
                  <span className="ml-2 font-mono">{summary.matchCount}</span>
                  {summary.candidateCount == null ? null : (
                    <span className="ml-2 text-[11px]">cand {summary.candidateCount}</span>
                  )}
                </button>
              ))}
            </div>

            {activeChannelSummary ? (
              <div className="mt-3 text-xs text-muted-foreground">
                {activeChannelSummary.summary}
                {activeChannelSummary.maxScore == null ? null : ` · top=${activeChannelSummary.maxScore.toFixed(3)}`}
              </div>
            ) : null}
          </div>

          {channels !== null && (
            <div className="flex flex-wrap items-center gap-2">
              {channels.retrieval_mode != null ? (
                <Badge variant="soft" className="text-[11px]">
                  mode={formatDiagnosticText(channels.retrieval_mode)}
                </Badge>
              ) : null}
              {channels.fusion_strategy != null ? (
                <Badge variant="soft" className="text-[11px]">
                  fusion={formatDiagnosticText(channels.fusion_strategy)}
                </Badge>
              ) : null}
              {channels.vector_backend != null ? (
                <Badge variant="soft" className="text-[11px]">
                  vec={formatDiagnosticText(channels.vector_backend)}
                </Badge>
              ) : null}
              {typeof channels.rrf_k === 'number' ? (
                <Badge variant="soft" className="text-[11px]">
                  rrf_k={channels.rrf_k}
                </Badge>
              ) : null}
              {channelTiming?.vector_ms == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  vector_ms={formatDiagnosticText(channelTiming.vector_ms)}
                </Badge>
              )}
              {channelTiming?.bm25_ms == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  bm25_ms={formatDiagnosticText(channelTiming.bm25_ms)}
                </Badge>
              )}
              {channelTiming?.fusion_ms == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  fusion_ms={formatDiagnosticText(channelTiming.fusion_ms)}
                </Badge>
              )}
            </div>
          )}
          {hierarchyRecall ? (
            <div className="flex flex-wrap items-center gap-2">
              {hierarchyRecall.enabled == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  hierarchy={formatDiagnosticText(hierarchyRecall.enabled)}
                </Badge>
              )}
              {hierarchyRecall.family_collapse == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  family_collapse={formatDiagnosticText(hierarchyRecall.family_collapse)}
                </Badge>
              )}
              {hierarchyRecall.family_aggregation != null ? (
                <Badge variant="soft" className="text-[11px]">
                  family_aggregation={formatDiagnosticText(hierarchyRecall.family_aggregation)}
                </Badge>
              ) : null}
              {hierarchyRecall.tree_dedup == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  tree_dedup={formatDiagnosticText(hierarchyRecall.tree_dedup)}
                </Badge>
              )}
              {hierarchyRecall.overfetch_factor == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  overfetch_factor={formatDiagnosticText(hierarchyRecall.overfetch_factor)}
                </Badge>
              )}
              {hierarchyRecall.parent_depth == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  parent_depth={formatDiagnosticText(hierarchyRecall.parent_depth)}
                </Badge>
              )}
              {hierarchyRecall.sibling_window == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  sibling_window={formatDiagnosticText(hierarchyRecall.sibling_window)}
                </Badge>
              )}
              {hierarchyRecall.context_expansion_used == null ? null : (
                <Badge variant="soft" className="text-[11px]">
                  context_expansion_used={formatDiagnosticText(hierarchyRecall.context_expansion_used)}
                </Badge>
              )}
              {hierarchyRecall.context_expansion_error != null ? (
                <Badge variant="soft" className="text-[11px]">
                  context_expansion_error={formatDiagnosticText(hierarchyRecall.context_expansion_error)}
                </Badge>
              ) : null}
            </div>
          ) : null}

          {rerankSkipReason || rerankError ? (
            <div className="flex flex-wrap items-center gap-2">
              {rerankSkipReason ? (
                <Badge variant="soft" className="text-[11px]">
                  skip_reason={rerankSkipReason}
                </Badge>
              ) : null}
              {rerankError ? (
                <Badge variant="soft" className="text-[11px]">
                  rerank_error={rerankError}
                </Badge>
              ) : null}
            </div>
          ) : null}

          {availableCitationSimulationChannels.length > 1 && selected.citations.length > 1 ? (
            <Panel variant="muted" className="space-y-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="space-y-1">
                  <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                    {t('panel.fusionSimulator.title')}
                  </div>
                  <div className="text-xs text-muted-foreground">{t('panel.fusionSimulator.description')}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-xl"
                    onClick={() => applyCitationSimulationPreset('balanced')}
                  >
                    {t('panel.fusionSimulator.presetBalanced')}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-xl"
                    onClick={() => applyCitationSimulationPreset('vector')}
                  >
                    {t('panel.fusionSimulator.presetVector')}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-xl"
                    onClick={() => applyCitationSimulationPreset('lexical')}
                  >
                    {t('panel.fusionSimulator.presetLexical')}
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {availableCitationSimulationChannels.map((channel) => {
                  const value = citationSimulationWeights[channel.key]
                  return (
                    <div
                      key={channel.key}
                      className="space-y-2 rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs font-semibold text-foreground">{channel.label}</span>
                        <span className="text-[11px] font-mono text-muted-foreground">{Math.round(value * 100)}%</span>
                      </div>
                      <input
                        aria-label={channel.label}
                        type="range"
                        min={0}
                        max={100}
                        step={5}
                        value={Math.round(value * 100)}
                        onChange={(event) => {
                          const nextValue = event.currentTarget.valueAsNumber / 100
                          setCitationSimulationWeights((current) => ({
                            ...current,
                            [channel.key]: nextValue,
                          }))
                        }}
                        className="w-full accent-sky-600"
                      />
                    </div>
                  )
                })}
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                    {t('panel.fusionSimulator.simulatedTitle')}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {t('panel.fusionSimulator.simulatedDescription')}
                  </div>
                </div>
                <div className="space-y-2">
                  {simulatedCitationRows.length === 0 && (
                    <p role="status" className="text-xs text-muted-foreground">
                      {t('panel.fusionSimulator.noWeightedScores')}
                    </p>
                  )}
                  {simulatedCitationRows.slice(0, 4).map((row) => {
                    const { documentId: docId, chunkId } = getTraceCitationIds(row.citation)
                    const deltaLabel = getTraceRankDeltaLabel(row.rankDelta)
                    const label = getTraceCitationLabel(row.citation, t('panel.evidencePreview.kinds.default'))
                    return (
                      <div
                        key={`sim-${row.baseRank}`}
                        className="flex items-start justify-between gap-3 rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft"
                      >
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="soft" className="text-[11px]">
                              #{row.rank}
                            </Badge>
                            <Badge variant="soft" className="text-[11px]">
                              Δ {deltaLabel}
                            </Badge>
                            <Badge variant="soft" className="text-[11px]">
                              score={row.compositeScore === null ? '—' : row.compositeScore.toFixed(3)}
                            </Badge>
                            {row.dominantChannelLabel ? (
                              <Badge variant="soft" className="text-[11px]">
                                dominant={row.dominantChannelLabel}
                              </Badge>
                            ) : null}
                          </div>
                          <div className="text-sm font-medium text-foreground break-all">{label}</div>
                          <div className="text-[11px] text-muted-foreground break-all">
                            {chunkId ? `chunk=${chunkId}` : 'document-level evidence'} · base rank #{row.baseRank}
                          </div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          disabled={!docId}
                          aria-label={`${t('panel.evidencePreview.open')} · ${label}`}
                          onMouseEnter={() => prefetchTraceCitationTarget(docId, chunkId)}
                          onFocus={() => prefetchTraceCitationTarget(docId, chunkId)}
                          onClick={() => openTraceCitation(row.citation, { label })}
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Button>
                      </div>
                    )
                  })}
                </div>
              </div>
            </Panel>
          ) : null}

          {channels !== null ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {['vector', 'bm25', 'lexical_db'].map((k) => {
                const box = getRecordField(channels, k)
                if (!box) return null
                const summary = channelSummaries.find((item) => item.key === k)
                return (
                  <Panel
                    key={k}
                    variant="muted"
                    className={cn(
                      'flex items-center justify-between gap-3',
                      summary?.active ? 'border-info bg-info' : undefined,
                    )}
                  >
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-foreground">{k}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {box.enabled == null ? null : `enabled=${formatDiagnosticText(box.enabled)}`}
                        {box.used == null ? null : ` · used=${formatDiagnosticText(box.used)}`}
                        {box.filter_applied == null ? null : ` · filter=${formatDiagnosticText(box.filter_applied)}`}
                        {box.index_enabled == null ? null : ` · index=${formatDiagnosticText(box.index_enabled)}`}
                        {box.provider == null ? null : ` · provider=${formatDiagnosticText(box.provider)}`}
                        {box.skipped_reason == null ? null : ` · skipped=${formatDiagnosticText(box.skipped_reason)}`}
                      </div>
                    </div>
                    <div className="shrink-0 text-xs font-medium text-muted-foreground">
                      {box.candidates == null ? '—' : formatDiagnosticText(box.candidates)}
                      {summary ? (
                        <span className="ml-2 text-[11px] text-foreground/70">有分数 {summary.matchCount}</span>
                      ) : null}
                    </div>
                  </Panel>
                )
              })}
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">{t('panel.channels.unavailable')}</div>
          )}
        </div>
      </Panel>

      <Panel variant="glass" className="overflow-hidden" padding="none">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
          <div>
            <div className="text-sm font-semibold">{t('panel.topCitations.title')}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {activeChannelSummary
                ? `${activeChannelSummary.label} · ${activeChannelSummary.matchCount}/${selected.citations.length} 条证据`
                : `All · ${selected.citations.length}`}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="soft" className="text-[11px]">
              focus={getRagTraceCitationChannelLabel(selectedCitationChannel, t)}
            </Badge>
            {lastOpenedTraceCitationTarget ? (
              <Button
                variant="outline"
                size="sm"
                className="rounded-xl"
                onClick={reopenLastTraceCitation}
                title={t('panel.topCitations.reopenRecentTitle')}
              >
                {t('panel.topCitations.reopenRecent')}
              </Button>
            ) : null}
          </div>
        </div>
        {traceTargetError !== undefined && (
          <p role="alert" className="px-4 py-2 text-sm text-destructive">
            {traceTargetError}
          </p>
        )}
        <ScrollArea className="h-[360px]">
          <div className="p-2">
            {filteredCitations.length ? (
              filteredCitations.map((c) => {
                const score = getPrimaryScore(c)
                const { documentId: docId, chunkId } = getTraceCitationIds(c)
                const page = c.page_number == null ? null : `p.${c.page_number}`
                const rerankScore = formatScore(c.rerank_score, 3)
                const retrievalScore = formatScore(c.retrieval_score, 3)
                const relScore = formatScore(c.relevance_score, 3)
                const vectorScore = formatScore(c.vector_score, 3)
                const bm25Score = formatScore(c.bm25_score, 3)
                const lexicalScore = formatScore(c.lexical_score, 3)
                const role = c.retrieval_role
                const neighborOf = c.neighbor_of
                const label = getTraceCitationLabel(c, t('panel.evidencePreview.kinds.default'))
                const focusedChannelScore =
                  selectedCitationChannel === 'all' ? null : getRagTraceCitationChannelScore(c, selectedCitationChannel)
                return (
                  <div
                    key={JSON.stringify([c, selected.citations.indexOf(c)])}
                    className="flex items-start justify-between gap-3 rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-2 text-left transition-colors shadow-soft hover:bg-sidebar/70"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="soft" className="text-[11px]">
                          {c.hit_type || 'hit'}
                        </Badge>
                        {role ? (
                          <Badge variant="soft" className="text-[11px]">
                            role={role}
                          </Badge>
                        ) : null}
                        {neighborOf ? (
                          <Badge variant="soft" className="text-[11px]" title={neighborOf}>
                            neighbor_of={abbreviateIdentifier(neighborOf, { head: 10, tail: 6 })}
                          </Badge>
                        ) : null}
                        {score == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            score={score.toFixed(3)}
                          </Badge>
                        )}
                        {focusedChannelScore != null && selectedCitationChannel !== 'all' ? (
                          <Badge variant="soft" className="text-[11px] border-info bg-info">
                            {getRagTraceCitationChannelLabel(selectedCitationChannel, t)}=
                            {focusedChannelScore.toFixed(3)}
                          </Badge>
                        ) : null}
                        {rerankScore ? (
                          <Badge variant="soft" className="text-[11px]">
                            rerank={rerankScore}
                          </Badge>
                        ) : null}
                        {retrievalScore ? (
                          <Badge variant="soft" className="text-[11px]">
                            retrieval={retrievalScore}
                          </Badge>
                        ) : null}
                        {relScore ? (
                          <Badge variant="soft" className="text-[11px]">
                            rel={relScore}
                          </Badge>
                        ) : null}
                        {vectorScore ? (
                          <Badge variant="soft" className="text-[11px]">
                            v={vectorScore}
                          </Badge>
                        ) : null}
                        {bm25Score ? (
                          <Badge variant="soft" className="text-[11px]">
                            bm25={bm25Score}
                          </Badge>
                        ) : null}
                        {lexicalScore ? (
                          <Badge variant="soft" className="text-[11px]">
                            lex={lexicalScore}
                          </Badge>
                        ) : null}
                        {page ? (
                          <Badge variant="soft" className="text-[11px]">
                            {page}
                          </Badge>
                        ) : null}
                        {c.has_image ? (
                          <Badge variant="soft" className="text-[11px]">
                            image
                          </Badge>
                        ) : null}
                      </div>
                      <div className="mt-1 text-[11px] text-muted-foreground break-all">doc {docId || '—'}</div>
                      <div className="text-[11px] text-muted-foreground break-all">chunk {chunkId || '—'}</div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-xl"
                      disabled={!docId}
                      aria-label={`${t('panel.topCitations.open')} · ${label}`}
                      onMouseEnter={() => prefetchTraceCitationTarget(docId, chunkId)}
                      onFocus={() => prefetchTraceCitationTarget(docId, chunkId)}
                      onClick={() => {
                        openTraceCitation(c, { label, notify: true })
                      }}
                    >
                      <ExternalLink className="h-4 w-4" />
                      <span className="ml-1 hidden sm:inline">{t('panel.topCitations.open')}</span>
                    </Button>
                  </div>
                )
              })
            ) : (
              <div className="rounded-xl border border-dashed border-sidebar-border/60 bg-sidebar/45 px-4 py-6 text-sm text-muted-foreground">
                {t('panel.topCitations.empty')}
              </div>
            )}
          </div>
        </ScrollArea>
      </Panel>
    </div>
  )
}
