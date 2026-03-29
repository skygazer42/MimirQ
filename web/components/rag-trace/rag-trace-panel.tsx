'use client'

import * as React from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Loader2, Route, Quote, Timer, Database, ExternalLink, Download, GitCompare } from 'lucide-react'
import { toast } from 'sonner'

import { chatApi, healthApi, metaApi, observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { RagTrace, RagTraceBundleDiffResponse, RagTraceCitation, RagTraceListResponse } from '@/types'

function formatTs(tsMs: number) {
  try {
    return new Date(tsMs).toLocaleString()
  } catch {
    return String(tsMs)
  }
}

function formatSec(sec?: number | null) {
  if (sec == null || !Number.isFinite(sec)) return '—'
  if (sec < 1) return `${Math.round(sec * 1000)}ms`
  return `${sec.toFixed(2)}s`
}

function shortHash(value: string, opts?: { head?: number; tail?: number }) {
  const v = String(value || '').trim()
  if (!v) return ''
  const head = Math.max(1, Number(opts?.head ?? 8) || 8)
  const tail = Math.max(0, Number(opts?.tail ?? 4) || 4)
  if (v.length <= head + tail + 1) return v
  return `${v.slice(0, head)}...${v.slice(-tail)}`
}

function safeIsoForFilename(ts: string) {
  return (ts || new Date().toISOString()).replaceAll(/[:.]/g, '-')
}

function safeIdForFilename(value: string) {
  return String(value || '')
    .trim()
    .replaceAll(/[^a-zA-Z0-9_-]+/g, '_')
    .slice(0, 80) || 'request'
}

function formatScore(v?: number | null, digits = 3) {
  if (v == null) return null
  const n = Number(v)
  if (!Number.isFinite(n)) return null
  return n.toFixed(digits)
}

function isNonZero(v?: number | null, eps = 1e-12) {
  if (v == null) return false
  const n = Number(v)
  if (!Number.isFinite(n)) return false
  return Math.abs(n) > eps
}

function formatDiffValue(value: any, maxLen = 160): string {
  if (value == null) return '—'
  if (typeof value === 'string') return value.trim() ? value : '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    const s = JSON.stringify(value)
    if (!s) return '—'
    return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s
  } catch {
    const s = String(value)
    return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s
  }
}

function getPrimaryScore(c: RagTraceCitation) {
  // Prefer rerank score when available.
  const v = c.rerank_score ?? c.retrieval_score ?? c.relevance_score ?? null
  if (v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

const CITATION_SIMULATION_CHANNELS = [
  { key: 'rerank_score', label: 'Rerank' },
  { key: 'vector_score', label: 'Vector' },
  { key: 'bm25_score', label: 'BM25' },
  { key: 'lexical_score', label: 'Lexical' },
  { key: 'sparse_score', label: 'Sparse' },
  { key: 'colbert_score', label: 'ColBERT' },
] as const

type CitationSimulationChannelKey = (typeof CITATION_SIMULATION_CHANNELS)[number]['key']
type CitationSimulationWeights = Partial<Record<CitationSimulationChannelKey, number>>
type CitationSimulationPreset = 'balanced' | 'vector' | 'lexical'

type CitationSimulationContribution = {
  key: CitationSimulationChannelKey
  label: string
  rawScore: number | null
  normalizedScore: number
  weightedScore: number
}

export type CitationSimulationRow = {
  citation: RagTraceCitation
  rank: number
  baseRank: number
  rankDelta: number
  compositeScore: number
  dominantChannelKey: CitationSimulationChannelKey | null
  dominantChannelLabel: string | null
  contributions: CitationSimulationContribution[]
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tagName = target.tagName
  return target.isContentEditable || tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT'
}

function getCitationSimulationScore(citation: RagTraceCitation, key: CitationSimulationChannelKey): number | null {
  const raw = citation[key]
  if (raw == null) return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

function getAvailableCitationSimulationChannels(citations: RagTraceCitation[]) {
  return CITATION_SIMULATION_CHANNELS.filter((channel) =>
    citations.some((citation) => getCitationSimulationScore(citation, channel.key) != null)
  )
}

function clampCitationSimulationWeight(value: unknown) {
  const next = Number(value)
  if (!Number.isFinite(next)) return 0
  return Math.min(1, Math.max(0, next))
}

function buildCitationSimulationWeightsForPreset(
  preset: CitationSimulationPreset,
  channels: ReadonlyArray<{ key: CitationSimulationChannelKey }>
): CitationSimulationWeights {
  const keys = channels.map((channel) => channel.key)
  const weights = Object.fromEntries(keys.map((key) => [key, 0])) as CitationSimulationWeights

  if (!keys.length) return weights
  if (preset === 'vector') {
    if (keys.includes('vector_score')) weights.vector_score = 0.7
    if (keys.includes('rerank_score')) weights.rerank_score = 0.2
    if (keys.includes('colbert_score')) weights.colbert_score = 0.1
    return weights
  }
  if (preset === 'lexical') {
    if (keys.includes('bm25_score')) weights.bm25_score = 0.55
    if (keys.includes('lexical_score')) weights.lexical_score = 0.2
    if (keys.includes('sparse_score')) weights.sparse_score = 0.15
    if (keys.includes('rerank_score')) weights.rerank_score = 0.1
    return weights
  }

  const weight = 1 / keys.length
  for (const key of keys) {
    weights[key] = weight
  }
  return weights
}

function normalizeCitationSimulationSeries(values: Array<number | null>) {
  const finiteValues = values.filter((value): value is number => value != null)
  if (!finiteValues.length) return values.map(() => 0)

  const min = Math.min(...finiteValues)
  const max = Math.max(...finiteValues)
  if (Math.abs(max - min) < 1e-12) {
    return values.map((value) => (value == null ? 0 : 1))
  }

  return values.map((value) => {
    if (value == null) return 0
    return (value - min) / (max - min)
  })
}

export function moveTraceSelectionIndex(currentIndex: number, total: number, direction: -1 | 1): number {
  if (!Number.isFinite(total) || total <= 0) return -1
  const base = Number.isFinite(currentIndex) && currentIndex >= 0 ? Math.trunc(currentIndex) % total : 0
  return (base + direction + total) % total
}

export function buildCitationSimulationRows(
  citations: RagTraceCitation[],
  weights: CitationSimulationWeights = {}
): CitationSimulationRow[] {
  const channels = getAvailableCitationSimulationChannels(citations)
  if (!citations.length || !channels.length) return []

  const normalizedScoreByKey = new Map<CitationSimulationChannelKey, number[]>()
  for (const channel of channels) {
    normalizedScoreByKey.set(
      channel.key,
      normalizeCitationSimulationSeries(citations.map((citation) => getCitationSimulationScore(citation, channel.key)))
    )
  }

  const normalizedWeights = Object.fromEntries(
    channels.map((channel) => [channel.key, clampCitationSimulationWeight(weights[channel.key])])
  ) as CitationSimulationWeights
  const totalWeight = channels.reduce((sum, channel) => sum + (normalizedWeights[channel.key] ?? 0), 0)

  return citations
    .map((citation, index) => {
      const contributions = channels.map<CitationSimulationContribution>((channel) => {
        const normalizedScore = normalizedScoreByKey.get(channel.key)?.[index] ?? 0
        const weightedScore = normalizedScore * (normalizedWeights[channel.key] ?? 0)
        return {
          key: channel.key,
          label: channel.label,
          rawScore: getCitationSimulationScore(citation, channel.key),
          normalizedScore,
          weightedScore,
        }
      })
      const compositeScore =
        totalWeight > 0
          ? contributions.reduce((sum, contribution) => sum + contribution.weightedScore, 0) / totalWeight
          : 0
      const dominantContribution =
        contributions
          .slice()
          .sort((a, b) => b.weightedScore - a.weightedScore || b.normalizedScore - a.normalizedScore)[0] ?? null

      return {
        citation,
        rank: 0,
        baseRank: index + 1,
        rankDelta: 0,
        compositeScore,
        dominantChannelKey: dominantContribution?.weightedScore ? dominantContribution.key : null,
        dominantChannelLabel: dominantContribution?.weightedScore ? dominantContribution.label : null,
        contributions,
      }
    })
    .sort((a, b) => b.compositeScore - a.compositeScore || a.baseRank - b.baseRank)
    .map((row, index) => ({
      ...row,
      rank: index + 1,
      rankDelta: row.baseRank - (index + 1),
    }))
}

export type RagTraceCitationChannelFilter = 'all' | 'vector' | 'bm25' | 'lexical_db' | 'sparse' | 'colbert_ann'

export type RagTraceCitationChannelSummary = {
  key: RagTraceCitationChannelFilter
  label: string
  summary: string
  matchCount: number
  candidateCount: number | null
  maxScore: number | null
  active: boolean
}

type StoredTraceCitationTarget = {
  requestId: string
  documentId: string
  chunkId: string | null
  start: number | null
  end: number | null
  pageNumber: number | null
  label: string | null
  openedAt: number
}

const RAG_TRACE_LAST_TARGETS_STORAGE_KEY = 'mimirq_rag_trace_last_targets_v1'

const RAG_TRACE_CITATION_CHANNEL_OPTIONS: ReadonlyArray<{
  key: RagTraceCitationChannelFilter
  label: string
  summary: string
}> = [
  { key: 'all', label: 'All', summary: '查看整条链路的最终证据面。' },
  { key: 'vector', label: 'Vector', summary: '聚焦 dense/vector 通道真正贡献到最终引用的证据。' },
  { key: 'bm25', label: 'BM25', summary: '排查 lexical keyword 命中是否主导了召回结果。' },
  { key: 'lexical_db', label: 'Lexical DB', summary: '查看数据库级词法通道在最终证据里的存在感。' },
  { key: 'sparse', label: 'Sparse', summary: '检查 learned sparse / SPLADE 风格通道是否带来额外证据。' },
  { key: 'colbert_ann', label: 'ColBERT', summary: '聚焦 late-interaction / ColBERT 通道影响到的证据。' },
]

function getRagTraceCitationChannelLabel(channel: RagTraceCitationChannelFilter) {
  return RAG_TRACE_CITATION_CHANNEL_OPTIONS.find((option) => option.key === channel)?.label || 'All'
}

function getRagTraceCitationChannelSummary(channel: RagTraceCitationChannelFilter) {
  return (
    RAG_TRACE_CITATION_CHANNEL_OPTIONS.find((option) => option.key === channel)?.summary ||
    '查看整条链路的最终证据面。'
  )
}

function getRagTraceCitationChannelScore(
  citation: RagTraceCitation,
  channel: Exclude<RagTraceCitationChannelFilter, 'all'>
): number | null {
  const raw =
    channel === 'vector'
      ? citation.vector_score
      : channel === 'bm25'
        ? citation.bm25_score
        : channel === 'lexical_db'
          ? citation.lexical_score
          : channel === 'sparse'
            ? citation.sparse_score
            : citation.colbert_score

  if (raw == null) return null
  const score = Number(raw)
  return Number.isFinite(score) ? score : null
}

function getRagTraceChannelBox(
  channels: Record<string, any> | null | undefined,
  channel: Exclude<RagTraceCitationChannelFilter, 'all'>
): Record<string, any> | null {
  return (channels as Record<string, any> | null | undefined)?.[channel] ?? null
}

export function filterTraceCitationsByChannel(
  citations: ReadonlyArray<RagTraceCitation>,
  channel: RagTraceCitationChannelFilter
): RagTraceCitation[] {
  const list = Array.from(citations || [])
  if (channel === 'all') {
    return list.sort((a, b) => (getPrimaryScore(b) ?? 0) - (getPrimaryScore(a) ?? 0))
  }

  return list
    .filter((citation) => isNonZero(getRagTraceCitationChannelScore(citation, channel)))
    .sort((a, b) => {
      const channelDelta = (getRagTraceCitationChannelScore(b, channel) ?? 0) - (getRagTraceCitationChannelScore(a, channel) ?? 0)
      if (channelDelta !== 0) return channelDelta
      return (getPrimaryScore(b) ?? 0) - (getPrimaryScore(a) ?? 0)
    })
}

export function buildTraceCitationChannelSummaries(
  trace: RagTrace | null,
  activeChannel: RagTraceCitationChannelFilter
): RagTraceCitationChannelSummary[] {
  const citations = trace?.citations || []
  const mainQuery =
    (trace?.retrieval?.per_query || []).find((query) => query?.kind === 'main') ??
    (trace?.retrieval?.per_query || [])[0] ??
    null
  const channels = (mainQuery?.retriever_debug as Record<string, unknown> | null | undefined)?.channels as
    | Record<string, any>
    | null
    | undefined

  return RAG_TRACE_CITATION_CHANNEL_OPTIONS.map((option) => {
    if (option.key === 'all') {
      const sorted = filterTraceCitationsByChannel(citations, option.key)
      return {
        key: option.key,
        label: option.label,
        summary: option.summary,
        matchCount: sorted.length,
        candidateCount: trace?.citations_count ?? sorted.length,
        maxScore: sorted[0] ? getPrimaryScore(sorted[0]) : null,
        active: activeChannel === option.key,
      }
    }

    const filtered = filterTraceCitationsByChannel(citations, option.key)
    const box = getRagTraceChannelBox(channels, option.key)
    return {
      key: option.key,
      label: option.label,
      summary: option.summary,
      matchCount: filtered.length,
      candidateCount:
        typeof box?.candidates === 'number' && Number.isFinite(box.candidates) ? Number(box.candidates) : null,
      maxScore: filtered[0] ? getRagTraceCitationChannelScore(filtered[0], option.key) : null,
      active: activeChannel === option.key,
    }
  })
}

function getTraceCitationLabel(citation: RagTraceCitation, fallback: string) {
  const citationRecord = citation as Record<string, unknown>
  const rawDocumentName = typeof citationRecord.document_name === 'string' ? citationRecord.document_name : ''
  return String(rawDocumentName || citation.document_id || fallback).trim() || fallback
}

function readStoredTraceCitationTargets(): Record<string, StoredTraceCitationTarget> {
  if (globalThis.window === undefined) return {}

  try {
    const raw = globalThis.window.localStorage.getItem(RAG_TRACE_LAST_TARGETS_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, Partial<StoredTraceCitationTarget>> | null
    if (!parsed || typeof parsed !== 'object') return {}

    const entries = Object.entries(parsed)
      .map(([requestId, value]) => {
        const normalizedRequestId = String(requestId || '').trim()
        const documentId = String(value?.documentId || '').trim()
        if (!normalizedRequestId || !documentId) return null

        return [
          normalizedRequestId,
          {
            requestId: normalizedRequestId,
            documentId,
            chunkId: String(value?.chunkId || '').trim() || null,
            start: typeof value?.start === 'number' && Number.isFinite(value.start) ? Math.trunc(value.start) : null,
            end: typeof value?.end === 'number' && Number.isFinite(value.end) ? Math.trunc(value.end) : null,
            pageNumber:
              typeof value?.pageNumber === 'number' && Number.isFinite(value.pageNumber) ? Math.trunc(value.pageNumber) : null,
            label: String(value?.label || '').trim() || null,
            openedAt:
              typeof value?.openedAt === 'number' && Number.isFinite(value.openedAt) ? Math.trunc(value.openedAt) : Date.now(),
          } satisfies StoredTraceCitationTarget,
        ] as const
      })
      .filter((entry): entry is readonly [string, StoredTraceCitationTarget] => Boolean(entry))

    return Object.fromEntries(entries)
  } catch {
    return {}
  }
}

function writeStoredTraceCitationTargets(targets: Record<string, StoredTraceCitationTarget>) {
  if (globalThis.window === undefined) return

  try {
    globalThis.window.localStorage.setItem(RAG_TRACE_LAST_TARGETS_STORAGE_KEY, JSON.stringify(targets))
  } catch {
    // best-effort persistence only
  }
}

export type PipelineTimelineStep = {
  key: string
  label: string
  elapsedSec: number
  share: number
  width: number
  mode: string | null
  queryCount: number | null
  itemCount: number | null
  topK: number | null
  rerankTopN: number | null
}

export type PipelineInspectorMetric = {
  label: string
  value: string
}

export type PipelineInspectorSection = {
  id: string
  label: string
  summary: string
  callout?: string | null
  metrics: PipelineInspectorMetric[]
  citations: RagTraceCitation[]
}

function asFiniteNumber(value: unknown): number | null {
  if (value == null) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function getMetaNumber(meta: Record<string, unknown> | null, key: string): number | null {
  if (!meta) return null
  return asFiniteNumber(meta[key])
}

function stringifyInspectorValue(value: unknown, fallback = '—') {
  if (value == null) return fallback
  if (typeof value === 'string') return value.trim() || fallback
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : fallback
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return fallback
}

function buildInspectorMetric(label: string, value: unknown, opts?: { formatter?: (value: unknown) => string | null }): PipelineInspectorMetric | null {
  const formatted = opts?.formatter ? opts.formatter(value) : stringifyInspectorValue(value)
  if (!formatted || formatted === '—') return null
  return { label, value: formatted }
}

function getTraceCitationRange(citation: RagTraceCitation): { start: number; end: number } | undefined {
  const start = typeof citation.start_char === 'number' ? citation.start_char : null
  const end = typeof citation.end_char === 'number' ? citation.end_char : null
  return start != null && end != null && end > start ? { start, end } : undefined
}

function normalizePipelineSectionId(value: string) {
  const key = String(value || '').trim().toLowerCase()
  if (!key) return 'stage'
  if (key.includes('retriev')) return 'retrieve'
  if (key.includes('rerank')) return 'rerank'
  if (key.includes('citation')) return 'citations'
  if (key.includes('answer')) return 'answer'
  return key
}

function buildCitationsSummary(citations: RagTraceCitation[]) {
  const sorted = citations
    .slice()
    .sort((a, b) => (getPrimaryScore(b) ?? 0) - (getPrimaryScore(a) ?? 0))
  return {
    top: sorted.slice(0, 4),
    distinctDocuments: new Set(sorted.map((citation) => String(citation.document_id || '').trim()).filter(Boolean)).size,
    imageHits: sorted.filter((citation) => Boolean(citation.has_image)).length,
  }
}

export function movePipelineSelectionIndex(currentIndex: number, total: number, direction: -1 | 1): number {
  if (!Number.isFinite(total) || total <= 0) return -1
  const base = Number.isFinite(currentIndex) && currentIndex >= 0 ? Math.trunc(currentIndex) % total : 0
  return (base + direction + total) % total
}

export function buildPipelineInspectorSections(trace: RagTrace | null): PipelineInspectorSection[] {
  if (!trace) return []

  const mainQuery = (trace.retrieval?.per_query || []).find((query) => query?.kind === 'main') ?? (trace.retrieval?.per_query || [])[0] ?? null
  const channels = (mainQuery?.retriever_debug as Record<string, unknown> | null | undefined)?.channels as Record<string, any> | null | undefined
  const hierarchyRecall = (mainQuery?.retriever_debug as Record<string, unknown> | null | undefined)?.hierarchy_recall as Record<string, any> | null | undefined
  const rerankMeta = (channels as Record<string, any> | null | undefined)?.rerank as Record<string, any> | null | undefined
  const citationSummary = buildCitationsSummary(trace.citations || [])

  const sections = buildPipelineTimelineSteps(trace).map<PipelineInspectorSection>((step) => {
    const id = normalizePipelineSectionId(step.key)
    if (id === 'retrieve') {
      const metrics = [
        buildInspectorMetric('Latency', step.elapsedSec, { formatter: (value) => formatSec(asFiniteNumber(value)) }),
        buildInspectorMetric('Mode', step.mode ?? trace.retrieval?.mode),
        buildInspectorMetric('Queries', step.queryCount),
        buildInspectorMetric('Top K', step.topK),
        buildInspectorMetric('Candidates', step.itemCount),
        buildInspectorMetric('Fusion', channels?.fusion_strategy),
        buildInspectorMetric('Vector backend', channels?.vector_backend),
      ].filter((value): value is PipelineInspectorMetric => Boolean(value))

      return {
        id,
        label: step.label,
        summary: '检索层决定候选面宽度，可以直接看 query 扩散、top_k 和融合策略是否异常。',
        callout:
          hierarchyRecall?.enabled == null
            ? null
            : `hierarchy recall ${hierarchyRecall.enabled ? '已启用' : '未启用'}${hierarchyRecall.overfetch_factor == null ? '' : ` · overfetch=${hierarchyRecall.overfetch_factor}`}`,
        metrics,
        citations: citationSummary.top,
      }
    }

    if (id === 'rerank') {
      const metrics = [
        buildInspectorMetric('Latency', step.elapsedSec, { formatter: (value) => formatSec(asFiniteNumber(value)) }),
        buildInspectorMetric('Provider', trace.rerank?.enabled ? trace.rerank?.provider || 'enabled' : 'disabled'),
        buildInspectorMetric('Top N', step.rerankTopN ?? trace.rerank?.top_n),
        buildInspectorMetric('Candidates kept', step.itemCount),
        buildInspectorMetric('Skip reason', rerankMeta?.skip_reason),
        buildInspectorMetric('Error', rerankMeta?.error),
      ].filter((value): value is PipelineInspectorMetric => Boolean(value))

      return {
        id,
        label: step.label,
        summary: '重排层用于判断“为什么这个 chunk 最终浮到前面”，适合排查 provider、top_n 和跳过原因。',
        callout: rerankMeta?.skip_reason ? `当前 trace 跳过 rerank：${String(rerankMeta.skip_reason)}` : null,
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
      ].filter((value): value is PipelineInspectorMetric => Boolean(value))

      return {
        id,
        label: step.label,
        summary: '证据层把最终引用聚合成可验证的来源，你可以直接跳到高分 chunk 做人工复核。',
        metrics,
        citations: citationSummary.top,
      }
    }

    const metrics = [
      buildInspectorMetric('Latency', step.elapsedSec, { formatter: (value) => formatSec(asFiniteNumber(value)) }),
      buildInspectorMetric('Mode', step.mode),
      buildInspectorMetric('Queries', step.queryCount),
      buildInspectorMetric('Items', step.itemCount),
    ].filter((value): value is PipelineInspectorMetric => Boolean(value))

    return {
      id,
      label: step.label,
      summary: '该阶段没有专门的诊断面板，保留关键计数与耗时，方便对照整条流水线。',
      metrics,
      citations: [],
    }
  })

  if (!sections.some((section) => section.id === 'citations') && trace.citations_count > 0) {
    sections.push({
      id: 'citations',
      label: 'Citations',
      summary: '证据层把最终引用聚合成可验证的来源，你可以直接跳到高分 chunk 做人工复核。',
      metrics: [
        buildInspectorMetric('Citations', trace.citations_count),
        buildInspectorMetric('Distinct docs', citationSummary.distinctDocuments),
        buildInspectorMetric('Image hits', citationSummary.imageHits),
      ].filter((value): value is PipelineInspectorMetric => Boolean(value)),
      citations: citationSummary.top,
    })
  }

  return sections
}

export function buildPipelineTimelineSteps(trace: RagTrace | null): PipelineTimelineStep[] {
  const rawSteps = trace?.steps || []
  if (!rawSteps.length) return []

  const stepRows = rawSteps.map((step) => {
    const elapsed = Math.max(0, asFiniteNumber(step.elapsed_sec) ?? 0)
    const lowerKey = String(step.key || '').toLowerCase()
    const meta = (step.meta ?? null) as Record<string, unknown> | null
    const mode = typeof meta?.mode === 'string' ? meta.mode : null
    const queryCount = getMetaNumber(meta, 'query_count') ?? (lowerKey.includes('retriev') ? asFiniteNumber(trace?.retrieval?.query_count) : null)
    const itemCount = getMetaNumber(meta, 'count')
    const topK = lowerKey.includes('retriev') ? asFiniteNumber(trace?.retrieval?.top_k) : null
    const rerankTopN = lowerKey.includes('rerank') ? asFiniteNumber(trace?.rerank?.top_n) : null

    return {
      key: String(step.key || step.label || 'step'),
      label: String(step.label || step.key || 'step'),
      elapsedSec: elapsed,
      mode,
      queryCount,
      itemCount,
      topK,
      rerankTopN,
    }
  })

  const maxElapsed = stepRows.reduce((acc, s) => Math.max(acc, s.elapsedSec), 0)
  const totalElapsed = stepRows.reduce((acc, s) => acc + s.elapsedSec, 0)

  return stepRows.map((s) => ({
    ...s,
    share: totalElapsed > 0 ? (s.elapsedSec / totalElapsed) * 100 : 0,
    width: maxElapsed > 0 ? (s.elapsedSec / maxElapsed) * 100 : 0,
  }))
}

export function RagTracePipelineTimeline({
  steps,
  selectedKey = null,
  onSelectStep,
}: Readonly<{
  steps: PipelineTimelineStep[]
  selectedKey?: string | null
  onSelectStep?: ((key: string) => void) | undefined
}>) {
  return (
    <div className="p-4 space-y-2">
      {steps.length ? (
        steps.map((step) => {
          const barWidth = step.width > 0 ? Math.max(step.width, 6) : 0
          const shareLabel = Number.isFinite(step.share) ? `${step.share.toFixed(1)}%` : '—'
          const selected = selectedKey === step.key || selectedKey === normalizePipelineSectionId(step.key)
          const content = (
            <>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-foreground">{step.label}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    share={shareLabel}
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
                  className="h-full rounded-full bg-sky-500/70"
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
                  ? 'border-sky-500/60 bg-sky-500/10 shadow-sm'
                  : 'border-border/60 bg-muted/20 hover:border-sky-500/30 hover:bg-muted/40'
              )}
            >
              {content}
            </button>
          )
        })
      ) : (
        <div className="text-xs text-muted-foreground">pipeline steps unavailable</div>
      )}
    </div>
  )
}

type RagTracePanelProps = {
  conversationId: string
  className?: string
}

export function RagTracePanel({ conversationId, className }: Readonly<RagTracePanelProps>) {
  const { openDocument } = useDocumentView()

  const [data, setData] = React.useState<RagTraceListResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [selectedIndex, setSelectedIndex] = React.useState(0)
  const [bundleDownloading, setBundleDownloading] = React.useState(false)
  const [bundleError, setBundleError] = React.useState<string | null>(null)
  const bundleDownloadingRef = React.useRef(false)
  const [diffOpen, setDiffOpen] = React.useState(false)
  const [diffOtherRequestId, setDiffOtherRequestId] = React.useState('')
  const [diffLoading, setDiffLoading] = React.useState(false)
  const [diffError, setDiffError] = React.useState<string | null>(null)
  const [diffResult, setDiffResult] = React.useState<RagTraceBundleDiffResponse | null>(null)
  const [selectedPipelineSectionId, setSelectedPipelineSectionId] = React.useState<string | null>(null)
  const [selectedCitationChannel, setSelectedCitationChannel] = React.useState<RagTraceCitationChannelFilter>('all')
  const [citationSimulationWeights, setCitationSimulationWeights] = React.useState<CitationSimulationWeights>({})
  const [storedTraceCitationTargets, setStoredTraceCitationTargets] = React.useState<Record<string, StoredTraceCitationTarget>>({})
  const prefetchedTraceCitationTargetsRef = React.useRef<Set<string>>(new Set())

  const items = data?.items ?? []
  const selected = items[selectedIndex] ?? items[0] ?? null
  const retrievalConfigHash = selected?.retrieval?.retrieval_config_hash || null
  const mainQuery = (selected?.retrieval?.per_query || []).find((q) => q?.kind === 'main') ?? (selected?.retrieval?.per_query || [])[0] ?? null
  const channels = (mainQuery?.retriever_debug as any)?.channels as Record<string, any> | null | undefined
  const hierarchyRecall = (mainQuery?.retriever_debug as any)?.hierarchy_recall as Record<string, any> | null | undefined
  const rerankMeta = (channels as any)?.rerank as Record<string, any> | null | undefined
  const rerankSkipReason = rerankMeta?.skip_reason ? String(rerankMeta.skip_reason) : null
  const rerankError = rerankMeta?.error ? String(rerankMeta.error) : null
  const requestId = String(selected?.request_id || '').trim()
  const pipelineSteps = React.useMemo(() => buildPipelineTimelineSteps(selected), [selected])
  const pipelineInspectorSections = React.useMemo(() => buildPipelineInspectorSections(selected), [selected])
  const availableCitationSimulationChannels = React.useMemo(
    () => getAvailableCitationSimulationChannels(selected?.citations || []),
    [selected]
  )
  const simulatedCitationRows = React.useMemo(
    () => buildCitationSimulationRows(selected?.citations || [], citationSimulationWeights),
    [citationSimulationWeights, selected]
  )
  const channelSummaries = React.useMemo(
    () => buildTraceCitationChannelSummaries(selected, selectedCitationChannel),
    [selected, selectedCitationChannel]
  )
  const filteredCitations = React.useMemo(
    () => filterTraceCitationsByChannel(selected?.citations || [], selectedCitationChannel),
    [selected, selectedCitationChannel]
  )
  const activeChannelSummary = React.useMemo(
    () => channelSummaries.find((summary) => summary.active) ?? channelSummaries[0] ?? null,
    [channelSummaries]
  )
  const lastOpenedTraceCitationTarget = React.useMemo(
    () => (requestId ? storedTraceCitationTargets[requestId] ?? null : null),
    [requestId, storedTraceCitationTargets]
  )
  const selectedPipelineSection = React.useMemo(
    () => pipelineInspectorSections.find((section) => section.id === selectedPipelineSectionId) ?? pipelineInspectorSections[0] ?? null,
    [pipelineInspectorSections, selectedPipelineSectionId]
  )
  const selectedPipelineSectionIndex = React.useMemo(() => {
    if (!selectedPipelineSection) return -1
    return pipelineInspectorSections.findIndex((section) => section.id === selectedPipelineSection.id)
  }, [pipelineInspectorSections, selectedPipelineSection])

  React.useEffect(() => {
    setSelectedPipelineSectionId((current) => {
      if (current && pipelineInspectorSections.some((section) => section.id === current)) {
        return current
      }
      return pipelineInspectorSections[0]?.id ?? null
    })
  }, [pipelineInspectorSections])

  React.useEffect(() => {
    setStoredTraceCitationTargets(readStoredTraceCitationTargets())
  }, [])

  React.useEffect(() => {
    setCitationSimulationWeights(buildCitationSimulationWeightsForPreset('balanced', availableCitationSimulationChannels))
  }, [availableCitationSimulationChannels, requestId])

  const handlePipelineTimelineKeyDown = React.useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!pipelineInspectorSections.length) return

    const key = event.key.toLowerCase()
    let direction: -1 | 1 | null = null
    if (key === 'arrowright' || key === 'l') direction = 1
    if (key === 'arrowleft' || key === 'h') direction = -1
    if (direction == null) return

    event.preventDefault()
    const nextIndex = movePipelineSelectionIndex(selectedPipelineSectionIndex, pipelineInspectorSections.length, direction)
    const nextId = pipelineInspectorSections[nextIndex]?.id ?? null
    if (nextId) setSelectedPipelineSectionId(nextId)
  }, [pipelineInspectorSections, selectedPipelineSectionIndex])

  const handleTracePanelKeyDown = React.useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!items.length) return
    if (isEditableTarget(event.target)) return

    const key = event.key.toLowerCase()
    let direction: -1 | 1 | null = null
    if (key === 'arrowdown' || key === 'j') direction = 1
    if (key === 'arrowup' || key === 'k') direction = -1
    if (direction == null) return

    event.preventDefault()
    setSelectedIndex((current) => moveTraceSelectionIndex(current, items.length, direction))
  }, [items.length])

  const applyCitationSimulationPreset = React.useCallback((preset: CitationSimulationPreset) => {
    setCitationSimulationWeights(buildCitationSimulationWeightsForPreset(preset, availableCitationSimulationChannels))
  }, [availableCitationSimulationChannels])

  const prefetchTraceCitationTarget = React.useCallback((documentId?: string | null, chunkId?: string | null) => {
    const docId = String(documentId || '').trim()
    if (!docId) return
    const cid = String(chunkId || '').trim()
    const targetKey = `${docId}:${cid}`
    if (prefetchedTraceCitationTargetsRef.current.has(targetKey)) return
    prefetchedTraceCitationTargetsRef.current.add(targetKey)
    prefetchDocumentView({ documentId: docId, chunkId: cid || undefined })
  }, [])

  const rememberOpenedTraceCitationTarget = React.useCallback((target: StoredTraceCitationTarget) => {
    setStoredTraceCitationTargets((current) => {
      const next = {
        ...current,
        [target.requestId]: target,
      }
      writeStoredTraceCitationTargets(next)
      return next
    })
  }, [])

  const openTraceCitation = React.useCallback(
    (citation: RagTraceCitation, opts?: { label?: string; notify?: boolean }) => {
      const documentId = String(citation.document_id || '').trim()
      if (!documentId) return

      const chunkId = String(citation.chunk_id || '').trim() || undefined
      const range = getTraceCitationRange(citation)
      const label = opts?.label?.trim() || getTraceCitationLabel(citation, documentId)

      if (requestId) {
        rememberOpenedTraceCitationTarget({
          requestId,
          documentId,
          chunkId: chunkId || null,
          start: range?.start ?? null,
          end: range?.end ?? null,
          pageNumber: typeof citation.page_number === 'number' && Number.isFinite(citation.page_number) ? citation.page_number : null,
          label,
          openedAt: Date.now(),
        })
      }

      openDocument(documentId, chunkId, range)
      if (opts?.notify) {
        toast.message('已打开引用文档', {
          description: `${label}${chunkId ? ` · ${chunkId}` : ''}`,
        })
      }
    },
    [openDocument, rememberOpenedTraceCitationTarget, requestId]
  )

  const reopenLastTraceCitation = React.useCallback(() => {
    if (!lastOpenedTraceCitationTarget) return

    const range =
      lastOpenedTraceCitationTarget.start != null &&
      lastOpenedTraceCitationTarget.end != null &&
      lastOpenedTraceCitationTarget.end > lastOpenedTraceCitationTarget.start
        ? { start: lastOpenedTraceCitationTarget.start, end: lastOpenedTraceCitationTarget.end }
        : undefined

    openDocument(
      lastOpenedTraceCitationTarget.documentId,
      lastOpenedTraceCitationTarget.chunkId || undefined,
      range
    )

    const pageLabel =
      lastOpenedTraceCitationTarget.pageNumber != null ? ` · P.${lastOpenedTraceCitationTarget.pageNumber}` : ''
    toast.message('已重新打开最近证据', {
      description: `${lastOpenedTraceCitationTarget.label || lastOpenedTraceCitationTarget.documentId}${pageLabel}`,
    })
  }, [lastOpenedTraceCitationTarget, openDocument])

  const downloadBundle = React.useCallback(async () => {
    const rid = requestId
    if (!rid) return
    if (bundleDownloadingRef.current) return

    bundleDownloadingRef.current = true
    setBundleDownloading(true)
    setBundleError(null)
    try {
      const [meta, ready, configSnapshot, traceBundle] = await Promise.all([
        metaApi.get(),
        healthApi.ready(),
        observabilityApi.getOpsConfigSnapshot(),
        observabilityApi.getRagTraceBundle({ request_id: rid }),
      ])

      const { default: JSZip } = await import('jszip')
      const zip = new JSZip()
      zip.file('meta.json', JSON.stringify(meta, null, 2))
      zip.file('health_ready.json', JSON.stringify(ready, null, 2))
      zip.file('config_snapshot.json', JSON.stringify(configSnapshot, null, 2))
      zip.file('trace_bundle.json', JSON.stringify(traceBundle, null, 2))
      zip.file(
        'README.txt',
        [
          'MimirQ Incident Bundle (PII-safe)',
          `exported_at: ${new Date().toISOString()}`,
          `request_id: ${rid}`,
          '',
          'Files:',
          '- meta.json',
          '- health_ready.json',
          '- config_snapshot.json',
          '- trace_bundle.json',
          '',
          'Notes:',
          '- query text is NOT included; only hashes/aggregates are exported.',
          '- trace_bundle.json is produced by /api/v1/observability/rag-metrics/trace-bundle',
        ].join('\n')
      )

      const blob = await zip.generateAsync({ type: 'blob' })
      const filename = `incident_bundle_${safeIdForFilename(rid)}_${safeIsoForFilename(new Date().toISOString())}.zip`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      toast.success('已下载 incident bundle')
    } catch (err) {
      const msg = formatApiError(err, '下载 bundle 失败')
      setBundleError(msg)
      toast.error(msg)
    } finally {
      bundleDownloadingRef.current = false
      setBundleDownloading(false)
    }
	  }, [requestId])

	  const runDiff = React.useCallback(async () => {
	    const a = requestId
	    const b = diffOtherRequestId.trim()
	    if (!a || !b) return
	    if (a === b) {
	      toast.error('请提供两个不同的 request_id')
	      return
	    }

	    setDiffLoading(true)
	    setDiffError(null)
	    try {
	      const res = await observabilityApi.getRagTraceBundleDiff({ request_id_a: a, request_id_b: b })
	      setDiffResult(res)
	    } catch (err) {
	      const msg = formatApiError(err, '加载 diff 失败')
	      setDiffResult(null)
	      setDiffError(msg)
	      toast.error(msg)
	    } finally {
	      setDiffLoading(false)
	    }
	  }, [diffOtherRequestId, requestId])

	  React.useEffect(() => {
	    // Clear diff results when switching the selected trace.
	    setDiffResult(null)
	    setDiffError(null)
	  }, [requestId])

	  const load = React.useCallback(async () => {
	    setLoading(true)
	    try {
	      const res = await chatApi.getRagTraces(conversationId, { limit: 40, window_minutes: 24 * 60 })
      setData(res)
      setSelectedIndex(0)
    } catch (err) {
      setData(null)
      toast.error(formatApiError(err, '加载 RAG Trace 失败'))
    } finally {
      setLoading(false)
    }
  }, [conversationId])

  React.useEffect(() => {
    detachPromise(load())
  }, [load])

  if (loading && !data) {
    return (
      <Panel className={cn('flex min-h-[420px] items-center justify-center', className)} variant="glass">
        <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground" />
      </Panel>
    )
  }

  if (!data?.enabled) {
    return (
      <EmptyState
        className={className}
        title="RAG Trace 未启用"
        description={
          <span>
            后端未开启 metrics JSONL（ENABLE_METRICS_LOG=false），或当前环境未配置 METRICS_LOG_PATH。
          </span>
        }
        icon={Route}
        iconClassName="text-sky-600 dark:text-sky-400"
      />
    )
  }

  if (!items.length) {
    return (
      <EmptyState
        className={className}
        title="暂无 RAG Trace"
        description={
          <span className="space-y-1">
            <span className="block">提示：只有走到检索链路时才会记录 trace。</span>
            <span className="block text-xs">可尝试在该会话继续提问后再刷新。</span>
          </span>
        }
        icon={Quote}
        iconClassName="text-sky-600 dark:text-sky-400"
      >
        <Button variant="outline" onClick={load} className="rounded-xl">
          刷新
        </Button>
      </EmptyState>
    )
  }

  return (
    <div
      className={cn('grid grid-cols-1 gap-4 md:grid-cols-[260px,1fr]', className)}
      tabIndex={0}
      onKeyDownCapture={handleTracePanelKeyDown}
    >
      <Panel variant="glass" padding="none" className="overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/60">
          <div className="flex items-center gap-2">
            <Route className="h-4 w-4 text-sky-600 dark:text-sky-400" />
            <div className="text-sm font-semibold">RAG Trace</div>
          </div>
          <Button variant="outline" size="sm" onClick={load} className="rounded-xl">
            刷新
          </Button>
        </div>
        <div className="border-b border-border/60 bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
          聚焦面板后可用 <span className="font-mono">j/k</span> 或 <span className="font-mono">↑/↓</span> 切换 trace。
        </div>
        <ScrollArea className="h-[420px]">
          <div className="p-2">
            {items.map((t, idx) => {
              const active = idx === selectedIndex
              const mode = t?.retrieval?.mode || '—'
              return (
                <button
                  key={`${t.ts_ms}-${t.request_id || idx}`}
                  type="button"
                  onClick={() => setSelectedIndex(idx)}
                  className={cn(
                    'w-full rounded-xl border px-3 py-2 text-left transition-colors',
                    'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background',
                    active
                      ? 'border-sky-500/60 bg-sky-500/10'
                      : 'border-border/60 hover:bg-muted/40'
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs font-medium text-foreground">{formatTs(t.ts_ms)}</div>
                    <Badge variant="soft" className="text-[10px]">
                      {mode}
                    </Badge>
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                    <span>{t.citations_count} citations</span>
                    <span className="inline-flex items-center gap-1">
                      <Timer className="h-3 w-3" />
                      {formatSec(t?.retrieval?.elapsed_sec)}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </ScrollArea>
      </Panel>

      <div className="min-w-0 space-y-4">
        {selected ? (
          <>
            <Panel variant="glass" className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="soft" className="text-[10px]">
                    request: {selected.request_id || '—'}
                  </Badge>
                  <Badge variant="soft" className="text-[10px]">
                    mode: {selected?.retrieval?.mode || '—'}
                  </Badge>
                  {retrievalConfigHash ? (
                    <Badge
                      variant="soft"
                      className="text-[10px] font-mono"
                      title={retrievalConfigHash}
                    >
                      cfg: {shortHash(retrievalConfigHash)}
                    </Badge>
                  ) : null}
                  <Badge variant="soft" className="text-[10px]">
                    citations: {selected.citations_count}
                  </Badge>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Timer className="h-4 w-4" />
                    Retrieve {formatSec(selected?.retrieval?.elapsed_sec)} · Rerank {formatSec(selected?.rerank?.elapsed_sec)}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2 rounded-xl"
                    disabled={!requestId || bundleDownloading}
                    onClick={() => detachPromise(downloadBundle())}
                    title="下载 request_id bundle（admin-only）"
                  >
                    {bundleDownloading ? (
                      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <Download className="h-4 w-4" />
                    )}
                    下载 bundle
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2 rounded-xl"
                    disabled={!requestId}
                    onClick={() => setDiffOpen((v) => !v)}
                    title="对比两个 request_id 的 trace bundle（admin-only）"
                  >
                    <GitCompare className="h-4 w-4" />
                    对比
                  </Button>
                </div>
              </div>

              {bundleError ? (
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
                      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                        <div className="grid w-full grid-cols-1 gap-3 md:grid-cols-2">
                          <div className="space-y-1">
                            <div className="text-[11px] text-muted-foreground">request_id A</div>
                            <Input value={requestId} readOnly className="font-mono text-xs" />
                          </div>
                          <div className="space-y-1">
                            <div className="text-[11px] text-muted-foreground">request_id B</div>
                            <Input
                              value={diffOtherRequestId}
                              onChange={(e) => setDiffOtherRequestId(e.target.value)}
                              placeholder="输入另一个 request_id"
                              className="font-mono text-xs"
                            />
                          </div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="gap-2 rounded-xl"
                          disabled={!requestId || !diffOtherRequestId.trim() || diffLoading}
                          onClick={() => detachPromise(runDiff())}
                        >
                          {diffLoading ? (
                            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                          ) : (
                            <GitCompare className="h-4 w-4" />
                          )}
                          比较
                        </Button>
                      </div>

                      {diffError ? (
                        <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                          {diffError}
                        </div>
                      ) : null}

                      {diffResult ? (
                        <div className="space-y-3">
                          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                            <div className="rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
                              <div className="text-[11px] text-muted-foreground">A</div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                mode={diffResult.summary_a?.retrieval_mode || '—'} · cfg=
                                {diffResult.summary_a?.retrieval_config_hash ? shortHash(diffResult.summary_a.retrieval_config_hash) : '—'} · citations=
                                {diffResult.summary_a?.citations_count ?? '—'}
                              </div>
                            </div>
                            <div className="rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
                              <div className="text-[11px] text-muted-foreground">B</div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                mode={diffResult.summary_b?.retrieval_mode || '—'} · cfg=
                                {diffResult.summary_b?.retrieval_config_hash ? shortHash(diffResult.summary_b.retrieval_config_hash) : '—'} · citations=
                                {diffResult.summary_b?.citations_count ?? '—'}
                              </div>
                            </div>
                          </div>

                          <div className="text-[11px] text-muted-foreground">
                            changes: {diffResult.diff?.length ?? 0} · truncated: {diffResult.truncated ? 'yes' : 'no'}
                          </div>
                          <div className="space-y-2">
                            {(diffResult.diff || []).map((it) => (
                              <div
                                key={String(it.key)}
                                className="grid grid-cols-1 gap-2 rounded-xl border border-border/60 bg-muted/20 px-3 py-2 md:grid-cols-3"
                              >
                                <div className="text-xs font-mono text-foreground">{it.key}</div>
                                <div className="text-xs text-muted-foreground break-words">{formatDiffValue(it.a)}</div>
                                <div className="text-xs text-muted-foreground break-words">
                                  {formatDiffValue(it.b)}
                                  {it.delta != null && Number.isFinite(Number(it.delta)) ? (
                                    <span className="ml-2 font-mono text-[11px] text-foreground/80">Δ {String(it.delta)}</span>
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

	              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <Panel variant="muted" className="flex items-center gap-3">
                  <Timer className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                  <div>
                    <div className="text-xs font-semibold text-foreground">Retrieve</div>
                    <div className="text-xs text-muted-foreground">{formatSec(selected?.retrieval?.elapsed_sec)}</div>
                  </div>
                </Panel>
                <Panel variant="muted" className="flex items-center gap-3">
                  <Database className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                  <div>
                    <div className="text-xs font-semibold text-foreground">Reranker</div>
                    <div className="text-xs text-muted-foreground">
                      {selected?.rerank?.enabled ? selected?.rerank?.provider || 'enabled' : 'disabled'}
                    </div>
                  </div>
                </Panel>
                <Panel variant="muted" className="flex items-center gap-3">
                  <Quote className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                  <div>
                    <div className="text-xs font-semibold text-foreground">Citations</div>
                    <div className="text-xs text-muted-foreground">{selected.citations_count}</div>
                  </div>
                </Panel>
              </div>
            </Panel>

            <Panel variant="glass" className="overflow-hidden" padding="none">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
                <div>
                  <div className="text-sm font-semibold">Pipeline Timeline</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    点击 stage 进入检查器；聚焦时间线后可用 <span className="font-mono">←/→</span> 或{' '}
                    <span className="font-mono">h/l</span> 切换阶段。
                  </div>
                </div>
                {selectedPipelineSection && selectedPipelineSectionIndex >= 0 ? (
                  <Badge variant="soft" className="text-[10px]">
                    stage {selectedPipelineSectionIndex + 1}/{pipelineInspectorSections.length}
                  </Badge>
                ) : null}
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.2fr)_minmax(18rem,0.8fr)]">
                <div
                  tabIndex={0}
                  onKeyDown={handlePipelineTimelineKeyDown}
                  className="outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  <RagTracePipelineTimeline
                    steps={pipelineSteps}
                    selectedKey={selectedPipelineSection?.id ?? selectedPipelineSectionId}
                    onSelectStep={(key) => setSelectedPipelineSectionId(normalizePipelineSectionId(key))}
                  />
                </div>
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
                          <div className="rounded-xl border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-xs text-sky-900 dark:text-sky-100">
                            {selectedPipelineSection.callout}
                          </div>
                        ) : null}

                        {selectedPipelineSection.metrics.length ? (
                          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                            {selectedPipelineSection.metrics.map((metric) => (
                              <div key={`${selectedPipelineSection.id}:${metric.label}`} className="rounded-xl border border-border/60 bg-card/60 px-3 py-2">
                                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{metric.label}</div>
                                <div className="mt-1 text-sm font-semibold text-foreground">{metric.value}</div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="rounded-xl border border-dashed border-border/60 bg-card/40 px-3 py-2 text-xs text-muted-foreground">
                            当前阶段没有额外指标，更多细节可继续看下方 channel / citation 面板。
                          </div>
                        )}

                        {selectedPipelineSection.citations.length ? (
                          <div className="space-y-2">
                            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Quick Evidence</div>
                            {selectedPipelineSection.citations.slice(0, 3).map((citation, index) => {
                              const documentId = String(citation.document_id || '').trim()
                              const chunkId = String(citation.chunk_id || '').trim() || undefined
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
                                  className="flex w-full items-center justify-between gap-3 rounded-xl border border-border/60 bg-card/60 px-3 py-2 text-left transition-colors hover:bg-muted/30 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  <div className="min-w-0">
                                    <div className="truncate text-sm font-medium text-foreground">{label}</div>
                                    <div className="mt-1 text-[11px] text-muted-foreground">
                                      {pageLabel ? `${pageLabel} · ` : ''}
                                      {chunkId ? `chunk=${chunkId}` : 'document-level evidence'}
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
                      <div className="p-4 text-xs text-muted-foreground">pipeline steps unavailable</div>
                    )}
                  </AnimatePresence>
                </div>
              </div>
            </Panel>

            <Panel variant="glass" className="overflow-hidden" padding="none">
              <div className="px-4 py-3 border-b border-border/60">
                <div className="text-sm font-semibold">Channels</div>
              </div>
              <div className="p-4 space-y-3">
                {channels ? (
                  <>
                    <div className="rounded-2xl border border-border/60 bg-card/50 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Focus citations</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            点击 channel，直接筛出真正带来最终证据的命中。
                          </div>
                        </div>
                        {activeChannelSummary ? (
                          <Badge variant="soft" className="text-[10px]">
                            {activeChannelSummary.matchCount}/{selected.citations.length} hits · focus=
                            {getRagTraceCitationChannelLabel(selectedCitationChannel)}
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
                                ? 'border-sky-500/50 bg-sky-500/10 text-sky-900 dark:text-sky-100'
                                : 'border-border/60 bg-background/80 text-muted-foreground hover:border-sky-500/30 hover:text-foreground'
                            )}
                          >
                            <span className="font-semibold">{summary.label}</span>
                            <span className="ml-2 font-mono">{summary.matchCount}</span>
                            {summary.candidateCount != null ? <span className="ml-2 text-[11px]">cand {summary.candidateCount}</span> : null}
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

                    <div className="flex flex-wrap items-center gap-2">
                      {channels.retrieval_mode ? (
                        <Badge variant="soft" className="text-[10px]">
                          mode={String(channels.retrieval_mode)}
                        </Badge>
                      ) : null}
                      {channels.fusion_strategy ? (
                        <Badge variant="soft" className="text-[10px]">
                          fusion={String(channels.fusion_strategy)}
                        </Badge>
                      ) : null}
                      {channels.vector_backend ? (
                        <Badge variant="soft" className="text-[10px]">
                          vec={String(channels.vector_backend)}
                        </Badge>
                      ) : null}
                      {typeof channels.rrf_k === 'number' ? (
                        <Badge variant="soft" className="text-[10px]">
                          rrf_k={channels.rrf_k}
                        </Badge>
                      ) : null}
                      {channels?.timing?.vector_ms == null ? null : (
                        <Badge variant="soft" className="text-[10px]">
                          vector_ms={channels.timing.vector_ms}
                        </Badge>
                      )}
                      {channels?.timing?.bm25_ms == null ? null : (
                        <Badge variant="soft" className="text-[10px]">
                          bm25_ms={channels.timing.bm25_ms}
                        </Badge>
                      )}
                      {channels?.timing?.fusion_ms == null ? null : (
                        <Badge variant="soft" className="text-[10px]">
                          fusion_ms={channels.timing.fusion_ms}
                        </Badge>
                      )}
                    </div>

                    {hierarchyRecall ? (
                      <div className="flex flex-wrap items-center gap-2">
                        {hierarchyRecall.enabled == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            hierarchy={hierarchyRecall.enabled ? 'on' : 'off'}
                          </Badge>
                        )}
                        {hierarchyRecall.family_collapse == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            family_collapse={String(Boolean(hierarchyRecall.family_collapse))}
                          </Badge>
                        )}
                        {hierarchyRecall.family_aggregation ? (
                          <Badge variant="soft" className="text-[10px]">
                            family_aggregation={String(hierarchyRecall.family_aggregation)}
                          </Badge>
                        ) : null}
                        {hierarchyRecall.tree_dedup == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            tree_dedup={String(Boolean(hierarchyRecall.tree_dedup))}
                          </Badge>
                        )}
                        {hierarchyRecall.overfetch_factor == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            overfetch_factor={String(hierarchyRecall.overfetch_factor)}
                          </Badge>
                        )}
                        {hierarchyRecall.parent_depth == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            parent_depth={String(hierarchyRecall.parent_depth)}
                          </Badge>
                        )}
                        {hierarchyRecall.sibling_window == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            sibling_window={String(hierarchyRecall.sibling_window)}
                          </Badge>
                        )}
                        {hierarchyRecall.context_expansion_used == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            context_expansion_used={String(Boolean(hierarchyRecall.context_expansion_used))}
                          </Badge>
                        )}
                        {hierarchyRecall.context_expansion_error ? (
                          <Badge variant="soft" className="text-[10px]">
                            context_expansion_error={String(hierarchyRecall.context_expansion_error)}
                          </Badge>
                        ) : null}
                      </div>
                    ) : null}

                    {(rerankSkipReason || rerankError) ? (
                      <div className="flex flex-wrap items-center gap-2">
                        {rerankSkipReason ? (
                          <Badge variant="soft" className="text-[10px]">
                            skip_reason={rerankSkipReason}
                          </Badge>
                        ) : null}
                        {rerankError ? (
                          <Badge variant="soft" className="text-[10px]">
                            rerank_error={rerankError}
                          </Badge>
                        ) : null}
                      </div>
                    ) : null}

                    {availableCitationSimulationChannels.length > 1 && simulatedCitationRows.length > 1 ? (
                      <Panel variant="muted" className="space-y-4">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div className="space-y-1">
                            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Fusion Simulator</div>
                            <div className="text-xs text-muted-foreground">
                              拖动权重，实时模拟当前 trace 在不同 channel 配比下的 TopK 重排。
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Button variant="outline" size="sm" className="rounded-xl" onClick={() => applyCitationSimulationPreset('balanced')}>
                              平衡
                            </Button>
                            <Button variant="outline" size="sm" className="rounded-xl" onClick={() => applyCitationSimulationPreset('vector')}>
                              Vector 优先
                            </Button>
                            <Button variant="outline" size="sm" className="rounded-xl" onClick={() => applyCitationSimulationPreset('lexical')}>
                              Lexical 优先
                            </Button>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                          {availableCitationSimulationChannels.map((channel) => {
                            const value = citationSimulationWeights[channel.key] ?? 0
                            return (
                              <label key={channel.key} className="space-y-2 rounded-xl border border-border/60 bg-card/60 px-3 py-3">
                                <div className="flex items-center justify-between gap-3">
                                  <span className="text-xs font-semibold text-foreground">{channel.label}</span>
                                  <span className="text-[11px] font-mono text-muted-foreground">{Math.round(value * 100)}%</span>
                                </div>
                                <input
                                  type="range"
                                  min={0}
                                  max={100}
                                  step={5}
                                  value={Math.round(value * 100)}
                                  onChange={(event) => {
                                    const nextValue = clampCitationSimulationWeight(Number(event.target.value) / 100)
                                    setCitationSimulationWeights((current) => ({
                                      ...current,
                                      [channel.key]: nextValue,
                                    }))
                                  }}
                                  className="w-full accent-sky-600"
                                />
                              </label>
                            )
                          })}
                        </div>

                        <div className="space-y-2">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Simulated TopK</div>
                            <div className="text-[11px] text-muted-foreground">Δ 表示相对当前排序的升降。</div>
                          </div>
                          <div className="space-y-2">
                            {simulatedCitationRows.slice(0, 4).map((row) => {
                              const docId = String(row.citation.document_id || '').trim()
                              const chunkId = String(row.citation.chunk_id || '').trim() || undefined
                              const deltaLabel =
                                row.rankDelta > 0 ? `↑${row.rankDelta}` : row.rankDelta < 0 ? `↓${Math.abs(row.rankDelta)}` : '—'
                              const label = getTraceCitationLabel(row.citation, docId || `citation-${row.rank}`)
                              return (
                                <div
                                  key={`sim-${docId}:${chunkId || row.rank}`}
                                  className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card/60 px-3 py-3"
                                >
                                  <div className="min-w-0 space-y-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <Badge variant="soft" className="text-[10px]">
                                        #{row.rank}
                                      </Badge>
                                      <Badge variant="soft" className="text-[10px]">
                                        Δ {deltaLabel}
                                      </Badge>
                                      <Badge variant="soft" className="text-[10px]">
                                        score={row.compositeScore.toFixed(3)}
                                      </Badge>
                                      {row.dominantChannelLabel ? (
                                        <Badge variant="soft" className="text-[10px]">
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

                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      {(['vector', 'colbert_ann', 'bm25', 'lexical_db', 'sparse']).map((k) => {
                        const box = (channels as any)?.[k] as Record<string, any> | null | undefined
                        if (!box) return null
                        const summary = channelSummaries.find((item) => item.key === k)
                        return (
                          <Panel
                            key={k}
                            variant="muted"
                            className={cn(
                              'flex items-center justify-between gap-3',
                              summary?.active ? 'border-sky-500/40 bg-sky-500/10' : undefined
                            )}
                          >
                            <div className="min-w-0">
                              <div className="text-xs font-semibold text-foreground">{k}</div>
                              <div className="mt-0.5 text-[11px] text-muted-foreground">
                                {box.enabled == null ? null : `enabled=${String(box.enabled)}`}
                                {box.used == null ? null : ` · used=${String(box.used)}`}
                                {box.filter_applied == null ? null : ` · filter=${String(box.filter_applied)}`}
                                {box.index_enabled == null ? null : ` · index=${String(box.index_enabled)}`}
                                {box.provider ? ` · provider=${String(box.provider)}` : null}
                                {box.skipped_reason ? ` · skipped=${String(box.skipped_reason)}` : null}
                              </div>
                            </div>
                            <div className="shrink-0 text-xs font-medium text-muted-foreground">
                              {box.candidates == null ? '—' : `${box.candidates}`}
                              {summary ? <span className="ml-2 text-[11px] text-foreground/70">hits {summary.matchCount}</span> : null}
                            </div>
                          </Panel>
                        )
                      })}
                    </div>
                  </>
                ) : (
                  <div className="text-xs text-muted-foreground">暂无 per-channel 指标（旧 trace 或 retriever_debug 被裁剪）。</div>
                )}
              </div>
            </Panel>

            <Panel variant="glass" className="overflow-hidden" padding="none">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
                <div>
                  <div className="text-sm font-semibold">TopK Citations</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {activeChannelSummary
                      ? `${activeChannelSummary.label} · ${activeChannelSummary.matchCount}/${selected.citations.length} hits`
                      : `All · ${selected.citations.length} hits`}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="soft" className="text-[10px]">
                    focus={getRagTraceCitationChannelLabel(selectedCitationChannel)}
                  </Badge>
                  {lastOpenedTraceCitationTarget ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-xl"
                      onClick={reopenLastTraceCitation}
                      title="重新打开当前 request 最近查看过的证据"
                    >
                      重新打开最近证据
                    </Button>
                  ) : null}
                </div>
              </div>
              <ScrollArea className="h-[360px]">
                <div className="p-2">
                  {filteredCitations.length ? filteredCitations.map((c, idx) => {
                    const score = getPrimaryScore(c)
                    const docId = c.document_id || ''
                    const chunkId = c.chunk_id || ''
                    const page = c.page_number == null ? null : `p.${c.page_number}`
                    const rerankScore = formatScore(c.rerank_score, 3)
                    const retrievalScore = formatScore(c.retrieval_score, 3)
                    const relScore = formatScore(c.relevance_score, 3)
                    const vectorScore = isNonZero(c.vector_score) ? formatScore(c.vector_score, 3) : null
                    const bm25Score = isNonZero(c.bm25_score) ? formatScore(c.bm25_score, 3) : null
                    const lexicalScore = isNonZero(c.lexical_score) ? formatScore(c.lexical_score, 3) : null
                    const sparseScore = isNonZero(c.sparse_score) ? formatScore(c.sparse_score, 3) : null
                    const colbertScore = isNonZero(c.colbert_score) ? formatScore(c.colbert_score, 3) : null
                    const role = c.retrieval_role ? String(c.retrieval_role) : null
                    const neighborOf = c.neighbor_of ? String(c.neighbor_of) : null
                    const label = getTraceCitationLabel(c, docId || `citation-${idx + 1}`)
                    const focusedChannelScore =
                      selectedCitationChannel === 'all'
                        ? null
                        : getRagTraceCitationChannelScore(c, selectedCitationChannel)
                    return (
                      <div
                        key={`${docId}:${chunkId}:${role || ''}:${neighborOf || ''}`}
                        className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card/40 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="soft" className="text-[10px]">
                              {c.hit_type || 'hit'}
                            </Badge>
                            {role ? (
                              <Badge variant="soft" className="text-[10px]">
                                role={role}
                              </Badge>
                            ) : null}
                            {neighborOf ? (
                              <Badge variant="soft" className="text-[10px]" title={neighborOf}>
                                neighbor_of={shortHash(neighborOf, { head: 10, tail: 6 })}
                              </Badge>
                            ) : null}
                            {score == null ? null : (
                              <Badge variant="soft" className="text-[10px]">
                                score={score.toFixed(3)}
                              </Badge>
                            )}
                            {focusedChannelScore != null && selectedCitationChannel !== 'all' ? (
                              <Badge variant="soft" className="text-[10px] border-sky-500/20 bg-sky-500/10">
                                {getRagTraceCitationChannelLabel(selectedCitationChannel)}={focusedChannelScore.toFixed(3)}
                              </Badge>
                            ) : null}
                            {rerankScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                rerank={rerankScore}
                              </Badge>
                            ) : null}
                            {retrievalScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                retrieval={retrievalScore}
                              </Badge>
                            ) : null}
                            {relScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                rel={relScore}
                              </Badge>
                            ) : null}
                            {vectorScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                v={vectorScore}
                              </Badge>
                            ) : null}
                            {bm25Score ? (
                              <Badge variant="soft" className="text-[10px]">
                                bm25={bm25Score}
                              </Badge>
                            ) : null}
                            {lexicalScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                lex={lexicalScore}
                              </Badge>
                            ) : null}
                            {sparseScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                sparse={sparseScore}
                              </Badge>
                            ) : null}
                            {colbertScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                colbert={colbertScore}
                              </Badge>
                            ) : null}
                            {page ? (
                              <Badge variant="soft" className="text-[10px]">
                                {page}
                              </Badge>
                            ) : null}
                            {c.has_image ? (
                              <Badge variant="soft" className="text-[10px]">
                                image
                              </Badge>
                            ) : null}
                          </div>
                          <div className="mt-1 text-[11px] text-muted-foreground break-all">
                            doc {docId || '—'}
                          </div>
                          <div className="text-[11px] text-muted-foreground break-all">
                            chunk {chunkId || '—'}
                          </div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          disabled={!docId}
                          onMouseEnter={() => prefetchTraceCitationTarget(docId, chunkId || undefined)}
                          onFocus={() => prefetchTraceCitationTarget(docId, chunkId || undefined)}
                          onClick={() => {
                            openTraceCitation(c, { label, notify: true })
                          }}
                        >
                          <ExternalLink className="h-4 w-4" />
                          <span className="ml-1 hidden sm:inline">打开</span>
                        </Button>
                      </div>
                    )
                  }) : (
                    <div className="rounded-xl border border-dashed border-border/60 bg-card/30 px-4 py-6 text-sm text-muted-foreground">
                      当前 channel 没有可展示的 citations。切回 <span className="font-mono">All</span> 或其他 channel 继续排查。
                    </div>
                  )}
                </div>
              </ScrollArea>
            </Panel>
          </>
        ) : null}
      </div>
    </div>
  )
}
