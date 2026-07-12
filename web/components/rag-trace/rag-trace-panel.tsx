'use client'

import { useQuery } from '@tanstack/react-query'
import * as React from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Loader2, Route, Quote, Timer, Database, ExternalLink, Download, GitCompare } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { chatApi, documentApi, healthApi, metaApi, observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { JsonObject, RagTrace, RagTraceBundleDiffResponse, RagTraceCitation, RagTraceListResponse } from '@/types'

const TRACE_EVIDENCE_PREVIEW_LIMIT = 3

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

function formatTraceModeLabel(mode?: string | null) {
  const value = String(mode || '').trim()
  if (!value) return '—'
  const labels: Record<string, string> = {
    dify_external_knowledge: 'Dify 外部知识',
    dify_result: 'Dify 结果',
    hybrid: '混合检索',
    vector: '向量检索',
    bm25: '关键词检索',
  }
  return labels[value] || value.replaceAll('_', ' ')
}

function formatCitationCount(count?: number | null) {
  const value = Number.isFinite(Number(count)) ? Number(count) : 0
  return `${value} 条证据`
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

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function jsonObjectField(source: unknown, key: string): JsonObject | null {
  const value = isJsonObject(source) ? source[key] : undefined
  return isJsonObject(value) ? value : null
}

function formatDiffValue(value: unknown, maxLen = 160): string {
  if (value == null) return '—'
  if (typeof value === 'string') return value.trim() ? value : '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    const s = JSON.stringify(value)
    if (!s) return '—'
    return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s
  } catch {
    return '—'
  }
}

function safeDisplayString(value: unknown, fallback = ''): string {
  const formatted = formatDiffValue(value)
  return formatted === '—' ? fallback : formatted
}

function getPrimaryScore(c: RagTraceCitation) {
  // Prefer rerank score when available.
  const v = c.rerank_score ?? c.retrieval_score ?? c.relevance_score ?? null
  if (v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export type TraceDiffCandidateOption = {
  requestId: string
  tsMs: number
  mode: string | null
  citationsCount: number
  retrievalConfigHash: string | null
  sameRetrievalConfig: boolean | null
}

function normalizeTraceRequestId(trace: RagTrace | null | undefined) {
  return String(trace?.request_id || '').trim()
}

export function buildTraceDiffCandidateOptions(
  traces: ReadonlyArray<RagTrace>,
  currentRequestId: string,
  currentRetrievalConfigHash?: string | null
): TraceDiffCandidateOption[] {
  const normalizedCurrentRequestId = String(currentRequestId || '').trim()
  const normalizedCurrentConfigHash = String(currentRetrievalConfigHash || '').trim() || null
  const currentTrace = traces.find((trace) => normalizeTraceRequestId(trace) === normalizedCurrentRequestId) ?? null
  const currentTsMs = typeof currentTrace?.ts_ms === 'number' && Number.isFinite(currentTrace.ts_ms) ? currentTrace.ts_ms : null

  return traces
    .map((trace) => {
      const requestId = normalizeTraceRequestId(trace)
      if (!requestId || requestId === normalizedCurrentRequestId) return null

      const retrievalConfigHash = String(trace.retrieval?.retrieval_config_hash || '').trim() || null
      return {
        requestId,
        tsMs: typeof trace.ts_ms === 'number' && Number.isFinite(trace.ts_ms) ? trace.ts_ms : 0,
        mode: typeof trace.retrieval?.mode === 'string' ? trace.retrieval.mode : null,
        citationsCount:
          typeof trace.citations_count === 'number' && Number.isFinite(trace.citations_count)
            ? trace.citations_count
            : (trace.citations || []).length,
        retrievalConfigHash,
        sameRetrievalConfig:
          normalizedCurrentConfigHash && retrievalConfigHash ? retrievalConfigHash === normalizedCurrentConfigHash : null,
      } satisfies TraceDiffCandidateOption
    })
    .filter((candidate): candidate is TraceDiffCandidateOption => Boolean(candidate))
    .sort((a, b) => {
      const aConfigChanged = a.sameRetrievalConfig === false ? 1 : 0
      const bConfigChanged = b.sameRetrievalConfig === false ? 1 : 0
      if (aConfigChanged !== bConfigChanged) return bConfigChanged - aConfigChanged

      if (currentTsMs != null) {
        const aDistance = Math.abs(a.tsMs - currentTsMs)
        const bDistance = Math.abs(b.tsMs - currentTsMs)
        if (aDistance !== bDistance) return aDistance - bDistance
      }

      return b.tsMs - a.tsMs
    })
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

type RagTraceTranslation = (key: string, values?: Record<string, string | number | Date>) => string

const RAG_TRACE_FALLBACK_MESSAGES: Record<string, string> = {
  'panel.channels.options.all.label': 'All',
  'panel.channels.options.all.summary': '查看整条链路的最终证据面。',
  'panel.channels.options.vector.label': 'Vector',
  'panel.channels.options.vector.summary': '聚焦 dense/vector 通道真正贡献到最终引用的证据。',
  'panel.channels.options.bm25.label': 'BM25',
  'panel.channels.options.bm25.summary': '排查 lexical keyword 命中是否主导了召回结果。',
  'panel.channels.options.lexicalDb.label': 'Lexical DB',
  'panel.channels.options.lexicalDb.summary': '查看数据库级词法通道在最终证据里的存在感。',
  'panel.channels.options.sparse.label': 'Sparse',
  'panel.channels.options.sparse.summary': '检查 learned sparse / SPLADE 风格通道是否带来额外证据。',
  'panel.channels.options.colbert.label': 'ColBERT',
  'panel.channels.options.colbert.summary': '聚焦 late-interaction / ColBERT 通道影响到的证据。',
  'panel.inspector.retrieveSummary': '检索层决定候选面宽度，可以直接看 query 扩散、top_k 和融合策略是否异常。',
  'panel.inspector.retrieveCallout': 'hierarchy recall {status}{overfetch}',
  'panel.inspector.retrieveEnabled': '已启用',
  'panel.inspector.retrieveDisabled': '未启用',
  'panel.inspector.rerankSummary': '重排层用于判断“为什么这个 chunk 最终浮到前面”，适合排查 provider、top_n 和跳过原因。',
  'panel.inspector.rerankSkipped': '当前 trace 跳过 rerank：{reason}',
  'panel.inspector.citationsSummary': '证据层把最终引用聚合成可验证的来源，你可以直接跳到高分 chunk 做人工复核。',
  'panel.inspector.defaultSummary': '该阶段没有专门的诊断面板，保留关键计数与耗时，方便对照整条流水线。',
  'panel.evidencePreview.title': '证据解读',
  'panel.evidencePreview.description': '这块用于判断回答到底引用了什么。当前展示排名前 {count} 条证据；如果证据偏题，就说明召回或 Dify 回传证据需要调整。',
  'panel.evidencePreview.loading': '正在加载切片',
  'panel.evidencePreview.loaded': '已加载切片',
  'panel.evidencePreview.score': '相关度',
  'panel.evidencePreview.document': '文档',
  'panel.evidencePreview.chunk': '切片',
  'panel.evidencePreview.missingContent': '暂未拉到切片正文；仍可点击打开定位查看后端返回。',
  'panel.evidencePreview.takeaway': '用途',
  'panel.evidencePreview.kinds.examRequired': '携带材料线索',
  'panel.evidencePreview.kinds.putonghuaRelated': '普通话相关线索',
  'panel.evidencePreview.kinds.default': '引用证据',
  'panel.evidencePreview.reasons.examRequired': '能支撑“身份证、准考证”等携带要求，但不是普通话考试专属证据。',
  'panel.evidencePreview.reasons.putonghuaRelated': '能说明普通话/教育事项相关材料，但更偏教师资格认定，不能直接证明考试当天要求。',
  'panel.evidencePreview.reasons.default': '用于核对回答引用的来源；需要结合正文判断是否真正命中问题。',
  'panel.evidencePreview.open': '打开证据切片',
}

function fallbackRagTraceTranslation(key: string, values?: Record<string, string | number | Date>) {
  const template = RAG_TRACE_FALLBACK_MESSAGES[key] ?? key
  if (!values) return template

  return template.replace(/\{(\w+)\}/g, (_match, token: string) => {
    const value = values[token]
    return value == null ? '' : String(value)
  })
}

function getRagTraceCitationChannelOptions(t: RagTraceTranslation = fallbackRagTraceTranslation): ReadonlyArray<{
  key: RagTraceCitationChannelFilter
  label: string
  summary: string
}> {
  return [
    { key: 'all', label: t("panel.channels.options.all.label"), summary: t("panel.channels.options.all.summary") },
    { key: 'vector', label: t("panel.channels.options.vector.label"), summary: t("panel.channels.options.vector.summary") },
    { key: 'bm25', label: t("panel.channels.options.bm25.label"), summary: t("panel.channels.options.bm25.summary") },
    {
      key: 'lexical_db',
      label: t("panel.channels.options.lexicalDb.label"),
      summary: t("panel.channels.options.lexicalDb.summary"),
    },
    { key: 'sparse', label: t("panel.channels.options.sparse.label"), summary: t("panel.channels.options.sparse.summary") },
    {
      key: 'colbert_ann',
      label: t("panel.channels.options.colbert.label"),
      summary: t("panel.channels.options.colbert.summary"),
    },
  ]
}

function getRagTraceCitationChannelLabel(channel: RagTraceCitationChannelFilter, t: RagTraceTranslation = fallbackRagTraceTranslation) {
  return getRagTraceCitationChannelOptions(t).find((option) => option.key === channel)?.label || t("panel.channels.options.all.label")
}

function getRagTraceCitationChannelSummary(channel: RagTraceCitationChannelFilter, t: RagTraceTranslation = fallbackRagTraceTranslation) {
  return (
    getRagTraceCitationChannelOptions(t).find((option) => option.key === channel)?.summary || t("panel.channels.options.all.summary")
  )
}

function getRagTraceCitationChannelScore(
  citation: RagTraceCitation,
  channel: Exclude<RagTraceCitationChannelFilter, 'all'>
): number | null {
  const raw = getRagTraceCitationChannelRawScore(citation, channel)

  if (raw == null) return null
  const score = Number(raw)
  return Number.isFinite(score) ? score : null
}

function getRagTraceCitationChannelRawScore(
  citation: RagTraceCitation,
  channel: Exclude<RagTraceCitationChannelFilter, 'all'>
) {
  if (channel === 'vector') return citation.vector_score
  if (channel === 'bm25') return citation.bm25_score
  if (channel === 'lexical_db') return citation.lexical_score
  if (channel === 'sparse') return citation.sparse_score
  return citation.colbert_score
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

function getRagTraceChannelBox(
  channels: JsonObject | null | undefined,
  channel: Exclude<RagTraceCitationChannelFilter, 'all'>
): JsonObject | null {
  return jsonObjectField(channels, channel)
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
  activeChannel: RagTraceCitationChannelFilter,
  t: RagTraceTranslation = fallbackRagTraceTranslation
): RagTraceCitationChannelSummary[] {
  const citations = trace?.citations || []
  const mainQuery =
    (trace?.retrieval?.per_query || []).find((query) => query?.kind === 'main') ??
    (trace?.retrieval?.per_query || [])[0] ??
    null
  const channels = jsonObjectField(mainQuery?.retriever_debug, 'channels')

  return getRagTraceCitationChannelOptions(t).map((option) => {
    const label = getRagTraceCitationChannelLabel(option.key, t)
    const summary = getRagTraceCitationChannelSummary(option.key, t)
    if (option.key === 'all') {
      const sorted = filterTraceCitationsByChannel(citations, option.key)
      return {
        key: option.key,
        label,
        summary,
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
      label,
      summary,
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

function getTraceCitationIds(citation: RagTraceCitation) {
  return {
    documentId: String(citation.document_id || '').trim(),
    chunkId: String(citation.chunk_id || '').trim(),
  }
}

function compactEvidenceText(value: string, maxChars = 150) {
  const text = String(value || '').replaceAll(/\s+/g, ' ').trim()
  if (!text) return ''
  return text.length > maxChars ? `${text.slice(0, maxChars)}…` : text
}

function getTraceEvidenceInterpretation(citation: RagTraceCitation, t: RagTraceTranslation) {
  const hitType = String(citation.hit_type || '').trim().toLowerCase()
  if (hitType.includes('exam_required')) {
    return {
      label: t("panel.evidencePreview.kinds.examRequired"),
      reason: t("panel.evidencePreview.reasons.examRequired"),
    }
  }
  if (hitType.includes('putonghua')) {
    return {
      label: t("panel.evidencePreview.kinds.putonghuaRelated"),
      reason: t("panel.evidencePreview.reasons.putonghuaRelated"),
    }
  }
  return {
    label: t("panel.evidencePreview.kinds.default"),
    reason: t("panel.evidencePreview.reasons.default"),
  }
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
  scoreDelta: number
}

export type TraceCitationDiffSummary = {
  sharedCount: number
  addedCount: number
  removedCount: number
  scoreShiftCount: number
  added: TraceCitationDiffItem[]
  removed: TraceCitationDiffItem[]
  scoreShifts: TraceCitationScoreShiftItem[]
}

function buildTraceCitationKey(citation: RagTraceCitation) {
  return [
    String(citation.document_id || '').trim(),
    String(citation.chunk_id || '').trim(),
    citation.chunk_index == null ? '' : String(citation.chunk_index),
    citation.page_number == null ? '' : String(citation.page_number),
    citation.start_char == null ? '' : String(citation.start_char),
    citation.end_char == null ? '' : String(citation.end_char),
    String(citation.retrieval_role || '').trim(),
    String(citation.neighbor_of || '').trim(),
  ].join('::')
}

export function buildTraceCitationDiff(traceA: RagTrace | null, traceB: RagTrace | null): TraceCitationDiffSummary {
  const citationsA = traceA?.citations || []
  const citationsB = traceB?.citations || []
  const mapA = new Map(citationsA.map((citation) => [buildTraceCitationKey(citation), citation] as const))
  const mapB = new Map(citationsB.map((citation) => [buildTraceCitationKey(citation), citation] as const))

  const added: TraceCitationDiffItem[] = []
  const removed: TraceCitationDiffItem[] = []
  const scoreShifts: TraceCitationScoreShiftItem[] = []
  let sharedCount = 0

  const keys = new Set<string>([...mapA.keys(), ...mapB.keys()])
  for (const key of keys) {
    const citationA = mapA.get(key) ?? null
    const citationB = mapB.get(key) ?? null

    if (citationA && citationB) {
      sharedCount += 1
      const scoreA = getPrimaryScore(citationA)
      const scoreB = getPrimaryScore(citationB)
      const scoreDelta = (scoreB ?? 0) - (scoreA ?? 0)
      if (Math.abs(scoreDelta) > 1e-6) {
        scoreShifts.push({
          key,
          label: getTraceCitationLabel(citationB, String(citationB.document_id || key).trim() || key),
          a: citationA,
          b: citationB,
          scoreA,
          scoreB,
          scoreDelta,
        })
      }
      continue
    }

    if (citationB) {
      added.push({
        key,
        label: getTraceCitationLabel(citationB, String(citationB.document_id || key).trim() || key),
        citation: citationB,
        score: getPrimaryScore(citationB),
      })
      continue
    }

    if (citationA) {
      removed.push({
        key,
        label: getTraceCitationLabel(citationA, String(citationA.document_id || key).trim() || key),
        citation: citationA,
        score: getPrimaryScore(citationA),
      })
    }
  }

  added.sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || a.label.localeCompare(b.label))
  removed.sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || a.label.localeCompare(b.label))
  scoreShifts.sort((a, b) => Math.abs(b.scoreDelta) - Math.abs(a.scoreDelta) || a.label.localeCompare(b.label))

  return {
    sharedCount,
    addedCount: added.length,
    removedCount: removed.length,
    scoreShiftCount: scoreShifts.length,
    added,
    removed,
    scoreShifts,
  }
}

function readStoredTraceCitationTargets(): Record<string, StoredTraceCitationTarget> {
  if (globalThis.window === undefined) return {}

  try {
    const raw = readClientStorage(RAG_TRACE_LAST_TARGETS_STORAGE_KEY)
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
  writeClientStorage(RAG_TRACE_LAST_TARGETS_STORAGE_KEY, JSON.stringify(targets))
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
  return safeDisplayString(value, fallback)
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
  return moveTraceSelectionIndex(currentIndex, total, direction)
}

export function buildPipelineInspectorSections(trace: RagTrace | null, t: RagTraceTranslation = fallbackRagTraceTranslation): PipelineInspectorSection[] {
  if (!trace) return []

  const mainQuery = (trace.retrieval?.per_query || []).find((query) => query?.kind === 'main') ?? (trace.retrieval?.per_query || [])[0] ?? null
  const channels = jsonObjectField(mainQuery?.retriever_debug, 'channels')
  const hierarchyRecall = jsonObjectField(mainQuery?.retriever_debug, 'hierarchy_recall')
  const rerankMeta = jsonObjectField(channels, 'rerank')
  const citationSummary = buildCitationsSummary(trace.citations || [])

  const sections = buildPipelineTimelineSteps(trace).map<PipelineInspectorSection>((step) => {
    const id = normalizePipelineSectionId(step.key)
    const rawStep = (trace.steps || []).find((candidate) => {
      const rawKey = String(candidate?.key || candidate?.label || '')
      return normalizePipelineSectionId(rawKey) === id
    })
    const stepMeta =
      rawStep?.meta && typeof rawStep.meta === 'object' && !Array.isArray(rawStep.meta)
        ? (rawStep.meta as Record<string, unknown>)
        : {}
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
        summary: t("panel.inspector.retrieveSummary"),
        callout:
          hierarchyRecall?.enabled == null
            ? null
            : t("panel.inspector.retrieveCallout", {
                status: hierarchyRecall.enabled ? t("panel.inspector.retrieveEnabled") : t("panel.inspector.retrieveDisabled"),
                overfetch:
                  hierarchyRecall.overfetch_factor == null ? '' : ` · overfetch=${safeDisplayString(hierarchyRecall.overfetch_factor)}`,
              }),
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
        summary: t("panel.inspector.rerankSummary"),
        callout: rerankMeta?.skip_reason ? t("panel.inspector.rerankSkipped", { reason: safeDisplayString(rerankMeta.skip_reason) }) : null,
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
        summary: t("panel.inspector.citationsSummary"),
        metrics,
        citations: citationSummary.top,
      }
    }

    if (id === 'dify_result') {
      const metrics = [
        buildInspectorMetric('Answer chars', stepMeta.answer_chars),
        buildInspectorMetric('Answer hash', stepMeta.answer_hash),
        buildInspectorMetric('Dify message', stepMeta.source_message_id),
        buildInspectorMetric('Workflow run', stepMeta.source_run_id),
        buildInspectorMetric('Citations', stepMeta.citations_count ?? trace.citations_count),
      ].filter((value): value is PipelineInspectorMetric => Boolean(value))

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
    ].filter((value): value is PipelineInspectorMetric => Boolean(value))

    return {
      id,
      label: step.label,
      summary: t("panel.inspector.defaultSummary"),
      metrics,
      citations: [],
    }
  })

  if (!sections.some((section) => section.id === 'citations') && trace.citations_count > 0) {
    sections.push({
      id: 'citations',
      label: 'Citations',
      summary: t("panel.inspector.citationsSummary"),
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
    const meta = step.meta ?? null
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
  emptyLabel = 'pipeline steps unavailable',
}: Readonly<{
  steps: PipelineTimelineStep[]
  selectedKey?: string | null
  onSelectStep?: (key: string) => void
  emptyLabel?: string
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
                  : 'border-border/60 bg-muted/20 hover:border-info hover:bg-muted/40'
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
  return (
    <div className="rounded-2xl border border-border/60 bg-card/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-foreground">{title}</div>
        <Badge
          variant="soft"
          className={cn(
            'text-[11px]',
            tone === 'added' ? 'border-success/20 bg-success/10 text-success' : undefined,
            tone === 'removed' ? 'border-warning/20 bg-warning/10 text-warning' : undefined
          )}
        >
          {items.length}
        </Badge>
      </div>

      {items.length ? (
        <div className="mt-3 space-y-2">
          {items.slice(0, 5).map((item) => {
            const documentId = String(item.citation.document_id || '').trim()
            const chunkId = String(item.citation.chunk_id || '').trim() || undefined
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
        <div className="text-sm font-semibold text-foreground">{t("panel.evidenceDrift.scoreShiftTitle")}</div>
        <Badge variant="soft" className="text-[11px]">
          {items.length}
        </Badge>
      </div>

      {items.length ? (
        <div className="mt-3 space-y-2">
          {items.slice(0, 5).map((item) => {
            const documentId = String(item.b.document_id || item.a.document_id || '').trim()
            const chunkId = String(item.b.chunk_id || item.a.chunk_id || '').trim() || undefined
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
                      A={item.scoreA == null ? '—' : item.scoreA.toFixed(3)} → B={item.scoreB == null ? '—' : item.scoreB.toFixed(3)}
                    </span>
                    <span className={cn('font-mono', item.scoreDelta >= 0 ? 'text-success' : 'text-warning')}>
                      Δ {item.scoreDelta.toFixed(3)}
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
  className?: string
}

export function RagTracePanel({ conversationId, className }: Readonly<RagTracePanelProps>) {
  const t = useTranslations('RagTrace')
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

  const items = React.useMemo(() => data?.items ?? [], [data])
  const selected = items[selectedIndex] ?? items[0] ?? null
  const retrievalConfigHash = selected?.retrieval?.retrieval_config_hash || null
  const mainQuery = (selected?.retrieval?.per_query || []).find((q) => q?.kind === 'main') ?? (selected?.retrieval?.per_query || [])[0] ?? null
  const channels = jsonObjectField(mainQuery?.retriever_debug, 'channels')
  const hierarchyRecall = jsonObjectField(mainQuery?.retriever_debug, 'hierarchy_recall')
  const rerankMeta = jsonObjectField(channels, 'rerank')
  const channelTiming = jsonObjectField(channels, 'timing')
  const rerankSkipReason = rerankMeta?.skip_reason ? safeDisplayString(rerankMeta.skip_reason) : null
  const rerankError = rerankMeta?.error ? safeDisplayString(rerankMeta.error) : null
  const requestId = String(selected?.request_id || '').trim()
  const diffCandidateOptions = React.useMemo(
    () => buildTraceDiffCandidateOptions(items, requestId, retrievalConfigHash),
    [items, requestId, retrievalConfigHash]
  )
  const selectedDiffComparisonTrace = React.useMemo(() => {
    const targetRequestId = diffOtherRequestId.trim()
    if (!targetRequestId) return null
    return items.find((item) => String(item.request_id || '').trim() === targetRequestId) ?? null
  }, [diffOtherRequestId, items])
  const localCitationDiff = React.useMemo(
    () => buildTraceCitationDiff(selected, selectedDiffComparisonTrace),
    [selected, selectedDiffComparisonTrace]
  )
  const pipelineSteps = React.useMemo(() => buildPipelineTimelineSteps(selected), [selected])
  const pipelineInspectorSections = React.useMemo(() => buildPipelineInspectorSections(selected, t), [selected, t])
  const availableCitationSimulationChannels = React.useMemo(
    () => getAvailableCitationSimulationChannels(selected?.citations || []),
    [selected]
  )
  const simulatedCitationRows = React.useMemo(
    () => buildCitationSimulationRows(selected?.citations || [], citationSimulationWeights),
    [citationSimulationWeights, selected]
  )
  const channelSummaries = React.useMemo(
    () => buildTraceCitationChannelSummaries(selected, selectedCitationChannel, t),
    [selected, selectedCitationChannel, t]
  )
  const filteredCitations = React.useMemo(
    () => filterTraceCitationsByChannel(selected?.citations || [], selectedCitationChannel),
    [selected, selectedCitationChannel]
  )
  const evidencePreviewCitations = React.useMemo(
    () => buildCitationsSummary(selected?.citations || []).top.slice(0, TRACE_EVIDENCE_PREVIEW_LIMIT),
    [selected]
  )
  const evidencePreviewKey = React.useMemo(
    () =>
      evidencePreviewCitations
        .map((citation) => {
          const { documentId, chunkId } = getTraceCitationIds(citation)
          return `${documentId}:${chunkId}`
        })
        .join('|'),
    [evidencePreviewCitations]
  )
  const evidencePreviewQuery = useQuery({
    queryKey: ['rag-trace', 'evidence-preview', requestId, evidencePreviewKey],
    enabled: evidencePreviewCitations.length > 0,
    staleTime: 30_000,
    queryFn: async () => {
      return Promise.all(
        evidencePreviewCitations.map(async (citation) => {
          const { documentId, chunkId } = getTraceCitationIds(citation)
          if (!documentId || !chunkId) return null
          try {
            return await documentApi.getChunk(documentId, chunkId)
          } catch {
            return null
          }
        })
      )
    },
  })
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

      openDocument(documentId, chunkId, range, {
        previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
      })
      if (opts?.notify) {
        const chunkSuffix = chunkId ? ` · ${chunkId}` : ''
        toast.message(t("panel.toasts.openedCitationDocument"), {
          description: `${label}${chunkSuffix}`,
        })
      }
    },
    [openDocument, rememberOpenedTraceCitationTarget, requestId, t]
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
      range,
      {
        previewAnchor:
          lastOpenedTraceCitationTarget.pageNumber == null
            ? undefined
            : { pageNumber: lastOpenedTraceCitationTarget.pageNumber },
      }
    )

    const pageLabel =
      lastOpenedTraceCitationTarget.pageNumber == null ? '' : ` · P.${lastOpenedTraceCitationTarget.pageNumber}`
    toast.message(t("panel.toasts.reopenedRecentEvidence"), {
      description: `${lastOpenedTraceCitationTarget.label || lastOpenedTraceCitationTarget.documentId}${pageLabel}`,
    })
  }, [lastOpenedTraceCitationTarget, openDocument, t])

  const downloadBundle = React.useCallback(async () => {
    const rid = requestId
    if (!rid) return
    if (bundleDownloadingRef.current) return

    bundleDownloadingRef.current = true
    setBundleDownloading(true)
    setBundleError(null)
    try {
      const [meta, ready, configSnapshot, traceBundle] = await Promise.all([
        metaApi.details(),
        healthApi.details(),
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
      toast.success(t("panel.toasts.bundleDownloaded"))
    } catch (err) {
      const msg = formatApiError(err, t("panel.errors.bundleDownloadFailed"))
      setBundleError(msg)
      toast.error(msg)
    } finally {
      bundleDownloadingRef.current = false
      setBundleDownloading(false)
    }
	  }, [requestId, t])

	  const runDiffForRequestId = React.useCallback(async (otherRequestId: string) => {
	    const a = requestId
	    const b = String(otherRequestId || '').trim()
	    if (!a || !b) return
	    if (a === b) {
	      toast.error(t("panel.errors.diffSameRequest"))
	      return
	    }

	    setDiffLoading(true)
	    setDiffError(null)
	    try {
	      const res = await observabilityApi.getRagTraceBundleDiff({ request_id_a: a, request_id_b: b })
	      setDiffResult(res)
	    } catch (err) {
	      const msg = formatApiError(err, t("panel.errors.diffLoadFailed"))
	      setDiffResult(null)
	      setDiffError(msg)
	      toast.error(msg)
	    } finally {
	      setDiffLoading(false)
	    }
	  }, [requestId, t])

	  const runDiff = React.useCallback(async () => {
      const b = diffOtherRequestId.trim()
      if (!b) return
      await runDiffForRequestId(b)
    }, [diffOtherRequestId, runDiffForRequestId])

	  const selectDiffCandidate = React.useCallback((candidate: TraceDiffCandidateOption) => {
      setDiffOtherRequestId(candidate.requestId)
      detachPromise(runDiffForRequestId(candidate.requestId))
    }, [runDiffForRequestId])

	  React.useEffect(() => {
	    // Clear diff results when switching the selected trace.
	    setDiffResult(null)
	    setDiffError(null)
	  }, [requestId])
  const tracesQuery = useQuery({
    queryKey: queryKeys.chat.ragTraces(conversationId, {
      limit: 40,
      window_minutes: 24 * 60,
    }),
    enabled: Boolean(conversationId),
    queryFn: () =>
      chatApi.getRagTraces(conversationId, {
        limit: 40,
        window_minutes: 24 * 60,
      }),
  })

  React.useEffect(() => {
    if (!tracesQuery.error) return
    toast.error(formatApiError(tracesQuery.error, t("panel.errors.traceLoadFailed")))
  }, [tracesQuery.error, t])

  React.useEffect(() => {
    if (!tracesQuery.data) return
    setData(tracesQuery.data)
    setSelectedIndex(0)
  }, [tracesQuery.data])

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      await tracesQuery.refetch()
    } finally {
      setLoading(false)
    }
  }, [tracesQuery])

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
        title={t("panel.states.notEnabledTitle")}
        description={
          <span>
            {t("panel.states.notEnabledDescription")}
          </span>
        }
        icon={Route}
        iconClassName="text-info"
      />
    )
  }

  if (!items.length) {
    return (
      <EmptyState
        className={className}
        title={t("panel.states.emptyTitle")}
        description={
          <span className="space-y-1">
            <span className="block">{t("panel.states.emptyHint")}</span>
            <span className="block text-xs">{t("panel.states.emptyFollowup")}</span>
          </span>
        }
        icon={Quote}
        iconClassName="text-info"
      >
        <Button variant="outline" onClick={load} className="rounded-xl">
          {t("panel.actions.refresh")}
        </Button>
      </EmptyState>
    )
  }

  return (
    <section
      className={cn('grid grid-cols-1 gap-3 lg:grid-cols-[300px,minmax(0,1fr)]', className)}
      aria-label="RAG trace keyboard navigation"
    >
      <Panel variant="glass" padding="none" className="overflow-hidden border-info/14 bg-[linear-gradient(180deg,hsl(var(--info)/0.05),hsl(var(--background)/0.7))]">
        <div className="flex items-center justify-between gap-3 border-b border-border/60 px-3 py-2.5">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Route className="h-4 w-4 text-info" />
              <div className="text-sm font-semibold">{t("panel.header.title")}</div>
              <Badge variant="soft" className="text-[11px]">
                {items.length} 条
              </Badge>
            </div>
            <div className="mt-1 truncate text-[11px] text-muted-foreground">{t("panel.header.keyboardHint")}</div>
          </div>
          <Button variant="outline" size="sm" onClick={load} className="h-8 rounded-xl px-3">
            {t("panel.actions.refresh")}
          </Button>
        </div>
        <div className="max-h-[250px] overflow-y-auto p-2">
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
                    ? 'border-info bg-info shadow-sm'
                    : 'border-border/60 bg-background/65 hover:bg-muted/40'
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-medium text-foreground">{formatTs(t.ts_ms)}</div>
                  <Badge variant="soft" className="text-[11px]">
                    {formatTraceModeLabel(mode)}
                  </Badge>
                </div>
                <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                  <span>{formatCitationCount(t.citations_count)}</span>
                  <span className="inline-flex items-center gap-1">
                    <Timer className="h-3 w-3" />
                    {formatSec(t?.retrieval?.elapsed_sec)}
                  </span>
                </div>
              </button>
            )
          })}
        </div>
      </Panel>

      <div className="min-w-0 space-y-3">
        {selected ? (
          <>
            <Panel
              variant="glass"
              className="flex flex-col gap-2 border-info/14 bg-[linear-gradient(135deg,hsl(var(--background)),hsl(var(--background)),hsl(var(--info)/0.04))]"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="soft" className="max-w-[14rem] truncate text-[11px] font-mono" title={selected.request_id || ''}>
                    请求 {selected.request_id ? shortHash(selected.request_id, { head: 12, tail: 8 }) : '—'}
                  </Badge>
                  <Badge variant="soft" className="text-[11px]">
                    {formatTraceModeLabel(selected?.retrieval?.mode)}
                  </Badge>
                  {retrievalConfigHash ? (
                    <Badge
                      variant="soft"
                      className="text-[11px] font-mono"
                      title={retrievalConfigHash}
                    >
                      cfg: {shortHash(retrievalConfigHash)}
                    </Badge>
                  ) : null}
                  <Badge variant="soft" className="text-[11px]">
                    {formatCitationCount(selected.citations_count)}
                  </Badge>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Timer className="h-4 w-4" />
                    检索 {formatSec(selected?.retrieval?.elapsed_sec)} · 重排 {formatSec(selected?.rerank?.elapsed_sec)}
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5 rounded-xl px-3 text-xs"
                    disabled={!requestId || bundleDownloading}
                    onClick={() => detachPromise(downloadBundle())}
                    title={t("panel.actions.downloadBundleTitle")}
                  >
                    {bundleDownloading ? (
                      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <Download className="h-4 w-4" />
                    )}
                    {t("panel.actions.downloadBundle")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5 rounded-xl px-3 text-xs"
                    disabled={!requestId}
                    onClick={() => setDiffOpen((v) => !v)}
                    title={t("panel.actions.compareTitle")}
                  >
                    <GitCompare className="h-4 w-4" />
                    {t("panel.actions.compare")}
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
                      {diffCandidateOptions.length ? (
                        <div className="space-y-2">
                          <div>
                            <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                              {t("panel.compareCandidates.title")}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {t("panel.compareCandidates.description")}
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
                                      : 'border-border/60 bg-background/80 hover:border-info hover:bg-muted/30'
                                  )}
                                >
                                  <div className="flex items-center gap-2 text-xs font-medium text-foreground">
                                    <span className="font-mono">{shortHash(candidate.requestId, { head: 10, tail: 6 })}</span>
                                    <Badge variant="soft" className="text-[11px]">
                                      {getTraceConfigMatchLabel(candidate.sameRetrievalConfig)}
                                    </Badge>
                                  </div>
                                  <div className="mt-1 text-[11px] text-muted-foreground">
                                    {candidate.mode || '—'} · citations={candidate.citationsCount} · {formatTs(candidate.tsMs)}
                                  </div>
                                </button>
                              )
                            })}
                          </div>
                        </div>
                      ) : null}

                      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                        <div className="grid w-full grid-cols-1 gap-3 md:grid-cols-2">
                          <div className="space-y-1">
                            <div className="text-[11px] text-muted-foreground">{t("panel.compare.requestIdA")}</div>
                            <Input value={requestId} readOnly className="font-mono text-xs" />
                          </div>
                          <div className="space-y-1">
                            <div className="text-[11px] text-muted-foreground">{t("panel.compare.requestIdB")}</div>
                            <Input
                              value={diffOtherRequestId}
                              onChange={(e) => {
                                setDiffOtherRequestId(e.target.value)
                                setDiffResult(null)
                                setDiffError(null)
                              }}
                              placeholder={t("panel.compare.requestIdBPlaceholder")}
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
                          {t("panel.compare.action")}
                        </Button>
                      </div>

                      {diffError ? (
                        <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                          {diffError}
                        </div>
                      ) : null}

                      {selectedDiffComparisonTrace ? (
                        <Panel variant="glass" className="space-y-3">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                                {t("panel.evidenceDrift.title")}
                              </div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                {t("panel.evidenceDrift.description")}
                              </div>
                            </div>
                            <Badge variant="soft" className="text-[11px]">
                              A {requestId || '—'} vs B {selectedDiffComparisonTrace.request_id || '—'}
                            </Badge>
                          </div>

                          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                            <div className="rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft">
                              <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                                {t("panel.evidenceDrift.sharedTitle")}
                              </div>
                              <div className="mt-1 text-lg font-semibold text-foreground">{localCitationDiff.sharedCount}</div>
                            </div>
                            <div className="rounded-xl border border-success/20 bg-success/5 px-3 py-3">
                              <div className="text-[11px] font-semibold uppercase text-success">
                                {t("panel.evidenceDrift.addedSummaryTitle")}
                              </div>
                              <div className="mt-1 text-lg font-semibold text-foreground">{localCitationDiff.addedCount}</div>
                            </div>
                            <div className="rounded-xl border border-warning/20 bg-warning/5 px-3 py-3">
                              <div className="text-[11px] font-semibold uppercase text-warning">
                                {t("panel.evidenceDrift.removedSummaryTitle")}
                              </div>
                              <div className="mt-1 text-lg font-semibold text-foreground">{localCitationDiff.removedCount}</div>
                            </div>
                            <div className="rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft">
                              <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                                {t("panel.evidenceDrift.scoreShiftSummaryTitle")}
                              </div>
                              <div className="mt-1 text-lg font-semibold text-foreground">{localCitationDiff.scoreShiftCount}</div>
                            </div>
                          </div>

                          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                            <TraceCitationDiffList
                              title={t("panel.evidenceDrift.addedTitle")}
                              emptyLabel={t("panel.evidenceDrift.addedEmpty")}
                              items={localCitationDiff.added}
                              tone="added"
                              onPrefetchCitation={prefetchTraceCitationTarget}
                              onOpenCitation={openTraceCitation}
                            />
                            <TraceCitationDiffList
                              title={t("panel.evidenceDrift.removedTitle")}
                              emptyLabel={t("panel.evidenceDrift.removedEmpty")}
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
                      {!localCitationDiff && diffOtherRequestId.trim() ? (
                        <div className="rounded-xl border border-dashed border-sidebar-border/60 bg-sidebar/45 px-3 py-3 text-xs text-muted-foreground">
                          {t("panel.evidenceDrift.missingLocalSummary")}
                        </div>
                      ) : null}

                      {diffResult ? (
                        <div className="space-y-3">
                          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                            <div className="rounded-xl border border-sidebar-border/60 bg-sidebar/45 px-3 py-2 text-xs text-muted-foreground">
                              <div className="text-[11px] text-muted-foreground">{t("panel.compare.summaryA")}</div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                mode={diffResult.summary_a?.retrieval_mode || '—'} · cfg=
                                {diffResult.summary_a?.retrieval_config_hash ? shortHash(diffResult.summary_a.retrieval_config_hash) : '—'} · citations=
                                {diffResult.summary_a?.citations_count ?? '—'}
                              </div>
                            </div>
                            <div className="rounded-xl border border-sidebar-border/60 bg-sidebar/45 px-3 py-2 text-xs text-muted-foreground">
                              <div className="text-[11px] text-muted-foreground">{t("panel.compare.summaryB")}</div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                mode={diffResult.summary_b?.retrieval_mode || '—'} · cfg=
                                {diffResult.summary_b?.retrieval_config_hash ? shortHash(diffResult.summary_b.retrieval_config_hash) : '—'} · citations=
                                {diffResult.summary_b?.citations_count ?? '—'}
                              </div>
                            </div>
                          </div>

                          <div className="text-[11px] text-muted-foreground">
                            {t("panel.compare.changesMeta", {
                              changes: diffResult.diff?.length ?? 0,
                              truncated: diffResult.truncated ? t("panel.compare.truncatedYes") : t("panel.compare.truncatedNo"),
                            })}
                          </div>
                          <div className="space-y-2">
                            {(diffResult.diff || []).map((it) => (
                              <div
                                key={String(it.key)}
                                className="grid grid-cols-1 gap-2 rounded-xl border border-sidebar-border/60 bg-sidebar/45 px-3 py-2 md:grid-cols-3"
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

              <div className="grid grid-cols-3 gap-2">
                <Panel variant="muted" className="flex items-center gap-2 px-3 py-2">
                  <Timer className="h-4 w-4 text-info" />
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-foreground">{t("panel.pipelineSummary.retrieve")}</div>
                    <div className="text-xs text-muted-foreground">{formatSec(selected?.retrieval?.elapsed_sec)}</div>
                  </div>
                </Panel>
                <Panel variant="muted" className="flex items-center gap-2 px-3 py-2">
                  <Database className="h-4 w-4 text-info" />
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-foreground">{t("panel.pipelineSummary.reranker")}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {selected?.rerank?.enabled ? selected?.rerank?.provider || '已启用' : '未启用'}
                    </div>
                  </div>
                </Panel>
                <Panel variant="muted" className="flex items-center gap-2 px-3 py-2">
                  <Quote className="h-4 w-4 text-info" />
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-foreground">{t("panel.pipelineSummary.citations")}</div>
                    <div className="text-xs text-muted-foreground">{selected.citations_count}</div>
                  </div>
                </Panel>
              </div>

              {evidencePreviewCitations.length ? (
                <div className="space-y-2 rounded-2xl border border-info bg-info/[0.035] p-3 shadow-soft">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-xs font-semibold text-foreground">{t("panel.evidencePreview.title")}</div>
                      <div className="mt-1 text-[11px] text-muted-foreground">
                        {t("panel.evidencePreview.description", {
                          count: Math.min(TRACE_EVIDENCE_PREVIEW_LIMIT, evidencePreviewCitations.length),
                        })}
                      </div>
                    </div>
                    {evidencePreviewQuery.isFetching ? (
                      <Badge variant="soft" className="gap-1 text-[11px]">
                        <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
                        {t("panel.evidencePreview.loading")}
                      </Badge>
                    ) : null}
                  </div>

                  <div className="grid grid-cols-1 gap-2 lg:grid-cols-2 2xl:grid-cols-3">
                    {evidencePreviewCitations.map((citation, index) => {
                      const { documentId, chunkId } = getTraceCitationIds(citation)
                      const label = getTraceCitationLabel(citation, documentId || `citation-${index + 1}`)
                      const score = getPrimaryScore(citation)
                      const previewChunk = evidencePreviewQuery.data?.[index] ?? null
                      const content = String(previewChunk?.content || '').trim()
                      const interpretation = getTraceEvidenceInterpretation(citation, t)
                      const previewText = compactEvidenceText(content || t("panel.evidencePreview.missingContent"))
                      return (
                        <div
                          key={`evidence-preview:${documentId}:${chunkId || index}`}
                          className="flex flex-col rounded-xl border border-border/60 bg-background/80 p-2.5 shadow-sm"
                        >
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <Badge variant="soft" className="text-[11px]">{interpretation.label}</Badge>
                              {score == null ? null : <Badge variant="soft" className="text-[11px]">{t("panel.evidencePreview.score")}={score.toFixed(3)}</Badge>}
                              {previewChunk ? <Badge variant="soft" className="text-[11px]">{t("panel.evidencePreview.loaded")}</Badge> : null}
                            </div>
                            <div className="mt-1.5 truncate text-sm font-semibold text-foreground" title={label}>
                              {label}
                            </div>
                            <div className="mt-1 break-all text-[11px] leading-4 text-muted-foreground">
                              {t("panel.evidencePreview.document")} {shortHash(documentId, { head: 10, tail: 6 }) || '—'}
                              {chunkId ? ` · ${t("panel.evidencePreview.chunk")} ${shortHash(chunkId, { head: 10, tail: 6 })}` : ''}
                            </div>
                            <div className="mt-2 rounded-lg bg-muted/35 px-2 py-1.5 text-xs leading-5 text-foreground/85">
                              <span className="font-semibold">{t("panel.evidencePreview.takeaway")}：</span>
                              {interpretation.reason}
                            </div>
                            <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
                              {previewText}
                            </p>
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            className="mt-2 h-8 w-full rounded-xl"
                            disabled={!documentId}
                            onMouseEnter={() => prefetchTraceCitationTarget(documentId, chunkId || undefined)}
                            onFocus={() => prefetchTraceCitationTarget(documentId, chunkId || undefined)}
                            onClick={() => openTraceCitation(citation, { label, notify: true })}
                          >
                            <ExternalLink className="h-4 w-4" />
                            <span className="ml-1">{t("panel.evidencePreview.open")}</span>
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
                  <div className="text-sm font-semibold">{t("panel.timeline.title")}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{t("panel.timeline.description")}</div>
                </div>
                {selectedPipelineSection && selectedPipelineSectionIndex >= 0 ? (
                  <Badge variant="soft" className="text-[11px]">
                    stage {selectedPipelineSectionIndex + 1}/{pipelineInspectorSections.length}
                  </Badge>
                ) : null}
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.2fr)_minmax(18rem,0.8fr)]">
                <section
                  aria-label="Pipeline timeline keyboard navigation"
                  className="outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  <RagTracePipelineTimeline
                    steps={pipelineSteps}
                    selectedKey={selectedPipelineSection?.id ?? selectedPipelineSectionId}
                    onSelectStep={(key) => setSelectedPipelineSectionId(normalizePipelineSectionId(key))}
                    emptyLabel={t("panel.timeline.unavailable")}
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
                                <div className="text-[11px] font-semibold uppercase text-muted-foreground">{metric.label}</div>
                                <div className="mt-1 text-sm font-semibold text-foreground">{metric.value}</div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="rounded-xl border border-dashed border-sidebar-border/60 bg-sidebar/45 px-3 py-2 text-xs text-muted-foreground">
                            {t("panel.timeline.metricsUnavailable")}
                          </div>
                        )}

                        {selectedPipelineSection.citations.length ? (
                          <div className="space-y-2">
                            <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                              {t("panel.timeline.quickEvidence")}
                            </div>
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
                                  className="flex w-full items-center justify-between gap-3 rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-2 text-left transition-colors shadow-soft hover:bg-sidebar/70 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  <div className="min-w-0">
                                    <div className="truncate text-sm font-medium text-foreground">{label}</div>
                                    <div className="mt-1 text-[11px] text-muted-foreground">
                                      {pageLabel ? `${pageLabel} · ` : ''}
                                      {chunkId ? `chunk=${chunkId}` : t("panel.timeline.documentLevelEvidence")}
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
                      <div className="p-4 text-xs text-muted-foreground">{t("panel.timeline.unavailable")}</div>
                    )}
                  </AnimatePresence>
                </div>
              </div>
            </Panel>

            <Panel variant="glass" className="overflow-hidden" padding="none">
              <div className="px-4 py-3 border-b border-border/60">
                <div className="text-sm font-semibold">{t("panel.channels.title")}</div>
              </div>
              <div className="p-4 space-y-3">
                {channels ? (
                  <>
                    <div className="rounded-2xl border border-sidebar-border/70 bg-sidebar/60 p-3 shadow-soft">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="text-[11px] font-semibold uppercase text-muted-foreground">{t("panel.channels.focusTitle")}</div>
                          <div className="mt-1 text-xs text-muted-foreground">{t("panel.channels.focusDescription")}</div>
                        </div>
                        {activeChannelSummary ? (
                          <Badge variant="soft" className="text-[11px]">
                            {activeChannelSummary.matchCount}/{selected.citations.length} hits · focus=
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
                                : 'border-border/60 bg-background/80 text-muted-foreground hover:border-info hover:text-foreground'
                            )}
                          >
                            <span className="font-semibold">{summary.label}</span>
                            <span className="ml-2 font-mono">{summary.matchCount}</span>
                            {summary.candidateCount == null ? null : <span className="ml-2 text-[11px]">cand {summary.candidateCount}</span>}
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
                        <Badge variant="soft" className="text-[11px]">
                          mode={safeDisplayString(channels.retrieval_mode)}
                        </Badge>
                      ) : null}
                      {channels.fusion_strategy ? (
                        <Badge variant="soft" className="text-[11px]">
                          fusion={safeDisplayString(channels.fusion_strategy)}
                        </Badge>
                      ) : null}
                      {channels.vector_backend ? (
                        <Badge variant="soft" className="text-[11px]">
                          vec={safeDisplayString(channels.vector_backend)}
                        </Badge>
                      ) : null}
                      {typeof channels.rrf_k === 'number' ? (
                        <Badge variant="soft" className="text-[11px]">
                          rrf_k={channels.rrf_k}
                        </Badge>
                      ) : null}
                      {channelTiming?.vector_ms == null ? null : (
                        <Badge variant="soft" className="text-[11px]">
                          vector_ms={safeDisplayString(channelTiming.vector_ms)}
                        </Badge>
                      )}
                      {channelTiming?.bm25_ms == null ? null : (
                        <Badge variant="soft" className="text-[11px]">
                          bm25_ms={safeDisplayString(channelTiming.bm25_ms)}
                        </Badge>
                      )}
                      {channelTiming?.fusion_ms == null ? null : (
                        <Badge variant="soft" className="text-[11px]">
                          fusion_ms={safeDisplayString(channelTiming.fusion_ms)}
                        </Badge>
                      )}
                    </div>

                    {hierarchyRecall ? (
                      <div className="flex flex-wrap items-center gap-2">
                        {hierarchyRecall.enabled == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            hierarchy={hierarchyRecall.enabled ? 'on' : 'off'}
                          </Badge>
                        )}
                        {hierarchyRecall.family_collapse == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            family_collapse={String(Boolean(hierarchyRecall.family_collapse))}
                          </Badge>
                        )}
                        {hierarchyRecall.family_aggregation ? (
                          <Badge variant="soft" className="text-[11px]">
                            family_aggregation={safeDisplayString(hierarchyRecall.family_aggregation)}
                          </Badge>
                        ) : null}
                        {hierarchyRecall.tree_dedup == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            tree_dedup={String(Boolean(hierarchyRecall.tree_dedup))}
                          </Badge>
                        )}
                        {hierarchyRecall.overfetch_factor == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            overfetch_factor={safeDisplayString(hierarchyRecall.overfetch_factor)}
                          </Badge>
                        )}
                        {hierarchyRecall.parent_depth == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            parent_depth={safeDisplayString(hierarchyRecall.parent_depth)}
                          </Badge>
                        )}
                        {hierarchyRecall.sibling_window == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            sibling_window={safeDisplayString(hierarchyRecall.sibling_window)}
                          </Badge>
                        )}
                        {hierarchyRecall.context_expansion_used == null ? null : (
                          <Badge variant="soft" className="text-[11px]">
                            context_expansion_used={String(Boolean(hierarchyRecall.context_expansion_used))}
                          </Badge>
                        )}
                        {hierarchyRecall.context_expansion_error ? (
                          <Badge variant="soft" className="text-[11px]">
                            context_expansion_error={safeDisplayString(hierarchyRecall.context_expansion_error)}
                          </Badge>
                        ) : null}
                      </div>
                    ) : null}

                    {(rerankSkipReason || rerankError) ? (
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

                    {availableCitationSimulationChannels.length > 1 && simulatedCitationRows.length > 1 ? (
                      <Panel variant="muted" className="space-y-4">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div className="space-y-1">
                            <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                              {t("panel.fusionSimulator.title")}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {t("panel.fusionSimulator.description")}
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Button variant="outline" size="sm" className="rounded-xl" onClick={() => applyCitationSimulationPreset('balanced')}>
                              {t("panel.fusionSimulator.presetBalanced")}
                            </Button>
                            <Button variant="outline" size="sm" className="rounded-xl" onClick={() => applyCitationSimulationPreset('vector')}>
                              {t("panel.fusionSimulator.presetVector")}
                            </Button>
                            <Button variant="outline" size="sm" className="rounded-xl" onClick={() => applyCitationSimulationPreset('lexical')}>
                              {t("panel.fusionSimulator.presetLexical")}
                            </Button>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                          {availableCitationSimulationChannels.map((channel) => {
                            const value = citationSimulationWeights[channel.key] ?? 0
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
                                    const nextValue = clampCitationSimulationWeight(Number(event.target.value) / 100)
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
                              {t("panel.fusionSimulator.simulatedTitle")}
                            </div>
                            <div className="text-[11px] text-muted-foreground">
                              {t("panel.fusionSimulator.simulatedDescription")}
                            </div>
                          </div>
                          <div className="space-y-2">
                            {simulatedCitationRows.slice(0, 4).map((row) => {
                              const docId = String(row.citation.document_id || '').trim()
                              const chunkId = String(row.citation.chunk_id || '').trim() || undefined
                              const deltaLabel = getTraceRankDeltaLabel(row.rankDelta)
                              const label = getTraceCitationLabel(row.citation, docId || `citation-${row.rank}`)
                              return (
                                <div
                                  key={`sim-${docId}:${chunkId || row.rank}`}
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
                                        score={row.compositeScore.toFixed(3)}
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
                        const box = jsonObjectField(channels, k)
                        if (!box) return null
                        const summary = channelSummaries.find((item) => item.key === k)
                        return (
                          <Panel
                            key={k}
                            variant="muted"
                            className={cn(
                              'flex items-center justify-between gap-3',
                              summary?.active ? 'border-info bg-info' : undefined
                            )}
                          >
                            <div className="min-w-0">
                              <div className="text-xs font-semibold text-foreground">{k}</div>
                              <div className="mt-0.5 text-[11px] text-muted-foreground">
                                {box.enabled == null ? null : `enabled=${safeDisplayString(box.enabled)}`}
                                {box.used == null ? null : ` · used=${safeDisplayString(box.used)}`}
                                {box.filter_applied == null ? null : ` · filter=${safeDisplayString(box.filter_applied)}`}
                                {box.index_enabled == null ? null : ` · index=${safeDisplayString(box.index_enabled)}`}
                                {box.provider ? ` · provider=${safeDisplayString(box.provider)}` : null}
                                {box.skipped_reason ? ` · skipped=${safeDisplayString(box.skipped_reason)}` : null}
                              </div>
                            </div>
                            <div className="shrink-0 text-xs font-medium text-muted-foreground">
                              {box.candidates == null ? '—' : safeDisplayString(box.candidates, '—')}
                              {summary ? <span className="ml-2 text-[11px] text-foreground/70">hits {summary.matchCount}</span> : null}
                            </div>
                          </Panel>
                        )
                      })}
                    </div>
                  </>
                ) : (
                  <div className="text-xs text-muted-foreground">{t("panel.channels.unavailable")}</div>
                )}
              </div>
            </Panel>

            <Panel variant="glass" className="overflow-hidden" padding="none">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
                <div>
                  <div className="text-sm font-semibold">{t("panel.topCitations.title")}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {activeChannelSummary
                      ? `${activeChannelSummary.label} · ${activeChannelSummary.matchCount}/${selected.citations.length} hits`
                      : `All · ${selected.citations.length} hits`}
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
                        title={t("panel.topCitations.reopenRecentTitle")}
                      >
                        {t("panel.topCitations.reopenRecent")}
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
                                neighbor_of={shortHash(neighborOf, { head: 10, tail: 6 })}
                              </Badge>
                            ) : null}
                            {score == null ? null : (
                              <Badge variant="soft" className="text-[11px]">
                                score={score.toFixed(3)}
                              </Badge>
                            )}
                            {focusedChannelScore != null && selectedCitationChannel !== 'all' ? (
                              <Badge variant="soft" className="text-[11px] border-info bg-info">
                                {getRagTraceCitationChannelLabel(selectedCitationChannel, t)}={focusedChannelScore.toFixed(3)}
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
                            {sparseScore ? (
                              <Badge variant="soft" className="text-[11px]">
                                sparse={sparseScore}
                              </Badge>
                            ) : null}
                            {colbertScore ? (
                              <Badge variant="soft" className="text-[11px]">
                                colbert={colbertScore}
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
                          <span className="ml-1 hidden sm:inline">{t("panel.topCitations.open")}</span>
                        </Button>
                      </div>
                    )
                  }) : (
                     <div className="rounded-xl border border-dashed border-sidebar-border/60 bg-sidebar/45 px-4 py-6 text-sm text-muted-foreground">
                       {t("panel.topCitations.empty")} <span className="font-mono">{getRagTraceCitationChannelLabel('all', t)}</span> {t("panel.topCitations.emptySuffix")}
                     </div>
                   )}
                </div>
              </ScrollArea>
            </Panel>
          </>
        ) : null}
      </div>
    </section>
  )
}
