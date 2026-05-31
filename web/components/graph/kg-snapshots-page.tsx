'use client'

import { diffLines } from 'diff'
import {
  AlertCircle,
  ArrowRightLeft,
  BarChart3,
  Box,
  Brain,
  ChevronRight,
  CheckCircle2,
  CircleDashed,
  Copy,
  Database,
  Download,
  FileJson,
  FolderOpen,
  GitCompare,
  Hash,
  Layers,
  Link2,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Star,
  Table2,
  Trash2,
  User,
  X,
} from 'lucide-react'
import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { useSearchParams } from 'next/navigation'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi } from '@/lib/api/datasets'
import { documentApi } from '@/lib/api/documents'
import { kgApi } from '@/lib/api/graph'
import { metaApi } from '@/lib/api/meta'
import { reportApi } from '@/lib/api/reports'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, detachPromise } from '@/lib/utils'
import type {
  Dataset,
  Document,
  KGGraphNode,
  KGGraphResponse,
} from '@/types'

type SnapshotPayload = Record<string, unknown>

type SnapshotDiffEntityRow = {
  type?: string
  delta?: number | null
  [key: string]: unknown
}

type SnapshotDiffPayload = {
  delta?: SnapshotPayload | null
  entity_types_delta?: SnapshotDiffEntityRow[] | null
  node_diff?: SnapshotExactDiffSummary | null
  edge_diff?: SnapshotExactDiffSummary | null
  [key: string]: unknown
}

type SnapshotExactDiffSummary = {
  added_count?: number | null
  removed_count?: number | null
  changed_count?: number | null
  sample_limit?: number | null
}

type SnapshotView = 'diff' | 'a' | 'b'
type WorkspaceTab = 'studio' | 'audit'
type StudioCanvasView = 'graph' | 'table' | 'stats'
type DiffCellStatus = 'same' | 'added' | 'removed' | 'empty'
type JsonTokenKind =
  | 'plain'
  | 'key'
  | 'string'
  | 'number'
  | 'boolean'
  | 'null'
  | 'punctuation'
type AuditSeverity = 'healthy' | 'notice' | 'warning'
type SnapshotInlineStatTone = 'muted' | 'neutral' | 'positive' | 'negative' | 'warning'
type DeltaDirection = 'positive' | 'negative' | 'flat'

type PipelineCandidate = {
  hash: string
  documents: number
  source: 'report' | 'documents'
  active: boolean
}

type DiffCell = {
  lineNumber: number | null
  text: string
  status: DiffCellStatus
}

type SideBySideDiffRow = {
  left: DiffCell
  right: DiffCell
}

type SnapshotDeltaRow = {
  key: string
  a: number
  b: number
  delta: number
}

type SnapshotChartTooltipProps = {
  active?: boolean
  payload?: Array<{ payload?: SnapshotDeltaRow }>
}

type SnapshotStudioNode = {
  id: string
  label: string
  type: string
  kind: string
  description: string
  x: number
  y: number
  tone: 'blue' | 'green' | 'orange' | 'purple' | 'rose' | 'amber' | 'teal'
  icon: ReactNode
  occurrences: number
  status: '一致' | '新增' | '移除' | '变化'
  relations: Array<{ label: string; target: string }>
}

type SnapshotStudioLink = {
  source: string
  target: string
  label: string
  strength: 'weak' | 'medium' | 'strong'
}

const DIFF_KEYS = ['docs', 'events', 'entities', 'links', 'relations'] as const

const INLINE_STAT_TONE_CLASSES: Record<SnapshotInlineStatTone, string> = {
  muted: 'border-border/70 bg-card text-muted-foreground',
  neutral: 'border-border/70 bg-card text-foreground',
  positive: 'border-emerald-200/70 bg-emerald-50/70 text-emerald-700',
  negative: 'border-rose-200/70 bg-rose-50/70 text-rose-700',
  warning: 'border-amber-200/70 bg-amber-50/70 text-amber-700',
}

const INLINE_STAT_VALUE_TONE_CLASSES: Record<SnapshotInlineStatTone, string> = {
  muted: 'text-muted-foreground',
  neutral: 'text-foreground',
  positive: 'text-emerald-700',
  negative: 'text-rose-700',
  warning: 'text-amber-700',
}

const SNAPSHOT_NODE_TONE_CLASSES: Record<SnapshotStudioNode['tone'], string> = {
  amber: 'from-amber-400 to-orange-500 ring-amber-200',
  blue: 'from-blue-500 to-sky-500 ring-blue-200',
  green: 'from-emerald-400 to-teal-500 ring-emerald-200',
  orange: 'from-orange-400 to-rose-500 ring-orange-200',
  purple: 'from-violet-400 to-indigo-500 ring-violet-200',
  rose: 'from-rose-400 to-pink-500 ring-rose-200',
  teal: 'from-teal-400 to-cyan-500 ring-teal-200',
}

const DELTA_TEXT_CLASSES: Record<DeltaDirection, string> = {
  flat: 'text-muted-foreground',
  negative: 'text-rose-700',
  positive: 'text-emerald-700',
}

const DELTA_TINT_CLASSES: Record<DeltaDirection, string> = {
  flat: 'bg-muted/40 ring-border',
  negative: 'bg-rose-50 ring-rose-200/60',
  positive: 'bg-emerald-50 ring-emerald-200/60',
}

const DELTA_BADGE_VARIANTS: Record<DeltaDirection, 'soft' | 'outline' | 'destructive'> = {
  flat: 'outline',
  negative: 'destructive',
  positive: 'soft',
}

const DELTA_LABELS: Record<DeltaDirection, string> = {
  flat: 'flat',
  negative: 'decrease',
  positive: 'increase',
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function primitiveDisplayString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value).trim()
  }
  return ''
}

function firstDisplayString(...values: unknown[]): string {
  for (const value of values) {
    const direct = primitiveDisplayString(value)
    if (direct) return direct

    if (value && typeof value === 'object') {
      const record = value as Record<string, unknown>
      const nested = firstDisplayString(record.id, record.name, record.label, record.title)
      if (nested) return nested
    }
  }
  return ''
}

function deltaDirection(value: number): DeltaDirection {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return 'flat'
}

function deltaSign(value: number): string {
  return value > 0 ? '+' : ''
}

function deltaFill(value: number): string {
  const direction = deltaDirection(value)
  if (direction === 'positive') return '#10b981'
  if (direction === 'negative') return '#f43f5e'
  return '#94a3b8'
}

function driftScoreToneForSeverity(severity: AuditSeverity): SnapshotInlineStatTone {
  if (severity === 'healthy') return 'positive'
  if (severity === 'notice') return 'warning'
  return 'negative'
}

function inlineStatToneForDelta(value: number): SnapshotInlineStatTone {
  const direction = deltaDirection(value)
  if (direction === 'positive') return 'positive'
  if (direction === 'negative') return 'negative'
  return 'muted'
}

function auditSeverityForDriftScore(score: number): AuditSeverity {
  if (score >= 0.35) return 'warning'
  if (score >= 0.12) return 'notice'
  return 'healthy'
}

function getHashPairStatus(hasA: boolean, hasB: boolean): string {
  if (hasA && hasB) return '已就绪'
  if (hasA || hasB) return '待补全'
  return '未设置'
}

function getHashPairTone(hasA: boolean, hasB: boolean): SnapshotInlineStatTone {
  if (hasA && hasB) return 'positive'
  if (hasA || hasB) return 'warning'
  return 'muted'
}

function getHashPairIcon(hasA: boolean, hasB: boolean): ReactNode {
  if (hasA && hasB) return <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
  if (hasA || hasB) return <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
  return <CircleDashed className="h-3.5 w-3.5" aria-hidden="true" />
}

function getSnapshotScopeSubtitle(
  documentCount: number,
  datasetId: string | undefined,
  datasetLabel: string
): string {
  if (documentCount > 0) return `${documentCount} 个文档范围`
  if (datasetId) return `${datasetLabel} · 数据集范围`
  return '后端全局范围'
}

function getSelectedDatasetLabel(
  selectedDataset: Dataset | null,
  selectedDatasetId: string
): string {
  if (selectedDataset) return getDatasetLabel(selectedDataset)
  if (selectedDatasetId) return selectedDatasetId
  return '全部数据集'
}

function getScopeDocumentCountLabel(documentCount: number, selectedDatasetId: string): string {
  if (documentCount > 0) return `${documentCount} 个文档`
  if (selectedDatasetId) return '后端解析'
  return '全局范围'
}

function getPipelineCandidatesStatusText(
  loading: boolean,
  error: string | null,
  count: number
): string {
  if (loading) return '正在读取候选版本'
  if (error) return error
  if (count > 0) return `已发现 ${count} 个版本`
  return '暂无可选版本'
}

function downloadJson(value: unknown, filename: string): void {
  const content = JSON.stringify(value ?? {}, null, 2)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function copyToClipboard(text: string, label: string): Promise<void> {
  const v = String(text || '')
  if (!v.trim()) {
    toast.error('无可复制内容')
    return
  }
  try {
    await navigator.clipboard.writeText(v)
    toast.success(`已复制 ${label}`)
  } catch (err) {
    console.error('clipboard.writeText failed:', err)
    toast.error('复制失败（浏览器权限限制）')
  }
}

function parseDocumentIds(raw: string): string[] {
  const input = String(raw || '').trim()
  if (!input) return []
  return input
    .split(/[,\n]/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

function getDatasetLabel(dataset: Dataset | null | undefined): string {
  return String(dataset?.name || dataset?.id || '').trim()
}

function getLinkEndpointId(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number')
    return String(value)
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    return firstDisplayString(record.id, record.name, record.label)
  }
  return ''
}

function getNodeMetaValue(node: KGGraphNode, ...keys: string[]): unknown {
  const meta = node.meta && typeof node.meta === 'object' ? node.meta : {}
  for (const key of keys) {
    const direct = (node as any)[key]
    if (direct != null && direct !== '') return direct
    const metaValue = (meta as Record<string, unknown>)[key]
    if (metaValue != null && metaValue !== '') return metaValue
  }
  return undefined
}

function getDocumentMetaValue(document: Document, ...keys: string[]): unknown {
  const meta = document.metadata && typeof document.metadata === 'object' ? document.metadata : {}
  for (const key of keys) {
    const direct = (document as Record<string, unknown>)[key]
    if (direct != null && direct !== '') return direct
    const metaValue = (meta as Record<string, unknown>)[key]
    if (metaValue != null && metaValue !== '') return metaValue
  }
  return undefined
}

function compactHashLabel(hash: string): string {
  const value = String(hash || '').trim()
  if (value.length <= 18) return value
  return `${value.slice(0, 10)}…${value.slice(-6)}`
}

function mergePipelineCandidate(
  map: Map<string, PipelineCandidate>,
  candidate: PipelineCandidate
) {
  const hash = candidate.hash.trim()
  if (!hash) return
  const current = map.get(hash)
  if (!current) {
    map.set(hash, { ...candidate, hash })
    return
  }
  map.set(hash, {
    hash,
    source: current.source === 'report' ? current.source : candidate.source,
    documents: Math.max(current.documents, candidate.documents),
    active: current.active || candidate.active,
  })
}

function sortPipelineCandidates(candidates: PipelineCandidate[]): PipelineCandidate[] {
  return [...candidates].sort((a, b) => {
    if (a.active !== b.active) return a.active ? -1 : 1
    if (a.documents !== b.documents) return b.documents - a.documents
    return a.hash.localeCompare(b.hash)
  })
}

function getNodeType(node: KGGraphNode): string {
  return (
    firstDisplayString(getNodeMetaValue(node, 'type', 'entity_type', 'kind', 'node_type')) ||
    '节点'
  )
}

function toneForNodeType(type: string): SnapshotStudioNode['tone'] {
  const normalized = type.toLowerCase()
  if (normalized.includes('event') || normalized.includes('事件'))
    return 'orange'
  if (normalized.includes('document') || normalized.includes('文档'))
    return 'amber'
  if (normalized.includes('model') || normalized.includes('模型'))
    return 'purple'
  if (
    normalized.includes('person') ||
    normalized.includes('用户') ||
    normalized.includes('人员')
  )
    return 'green'
  if (normalized.includes('feedback') || normalized.includes('评价'))
    return 'rose'
  if (normalized.includes('technology') || normalized.includes('技术'))
    return 'teal'
  return 'blue'
}

function iconForNodeType(type: string): ReactNode {
  const normalized = type.toLowerCase()
  if (normalized.includes('event') || normalized.includes('事件'))
    return <Sparkles className="h-5 w-5" aria-hidden="true" />
  if (normalized.includes('document') || normalized.includes('文档'))
    return <FolderOpen className="h-5 w-5" aria-hidden="true" />
  if (normalized.includes('model') || normalized.includes('模型'))
    return <Brain className="h-5 w-5" aria-hidden="true" />
  if (
    normalized.includes('person') ||
    normalized.includes('用户') ||
    normalized.includes('人员')
  )
    return <User className="h-5 w-5" aria-hidden="true" />
  if (normalized.includes('feedback') || normalized.includes('评价'))
    return <Star className="h-5 w-5" aria-hidden="true" />
  if (normalized.includes('technology') || normalized.includes('技术'))
    return <Box className="h-5 w-5" aria-hidden="true" />
  return <Network className="h-5 w-5" aria-hidden="true" />
}

function strengthForWeight(weight: unknown): SnapshotStudioLink['strength'] {
  const value = Number(weight ?? 1)
  if (!Number.isFinite(value)) return 'medium'
  if (value >= 0.75 || value >= 3) return 'strong'
  if (value <= 0.25) return 'weak'
  return 'medium'
}

function getProminentNodeLimit(isDense: boolean, isMedium: boolean): number {
  if (isDense) return 8
  if (isMedium) return 14
  return 28
}

function getLinkBaseOpacity(
  hasFilter: boolean,
  sourceVisible: boolean,
  targetVisible: boolean,
  strength: SnapshotStudioLink['strength']
): number {
  if (hasFilter && (!sourceVisible || !targetVisible)) return 0.08
  if (strength === 'strong') return 0.56
  if (strength === 'medium') return 0.38
  return 0.24
}

function getLinkDensityOpacity(baseOpacity: number, isDense: boolean, isMedium: boolean): number {
  if (isDense) return baseOpacity * 0.52
  if (isMedium) return baseOpacity * 0.72
  return baseOpacity
}

function getLinkStrokeWidth(isDense: boolean, strength: SnapshotStudioLink['strength']): number {
  if (isDense) return 0.16
  if (strength === 'strong') return 0.36
  return 0.24
}

function getGraphNodeSizeClass(isDense: boolean, isMedium: boolean): string {
  if (isDense) return 'h-7 w-7'
  if (isMedium) return 'h-10 w-10'
  return 'h-14 w-14'
}

function graphLoadingTitle(isLoading: boolean): string {
  return isLoading ? '正在读取真实 KG 图谱' : '暂无图谱节点'
}

function graphLoadingDescription(isLoading: boolean, emptyMessage?: string): string {
  if (isLoading) return '系统会按当前数据集、文档范围和 pipeline hash 请求后端接口。'
  return emptyMessage || '当前作用域没有返回 KG 节点，请先完成文档入库或 KG 抽取。'
}

function buildSnapshotStudioGraphFromKgGraph(graph: KGGraphResponse | null): {
  nodes: SnapshotStudioNode[]
  links: SnapshotStudioLink[]
} {
  const rawNodes = Array.isArray(graph?.nodes) ? graph.nodes : []
  const rawLinks = Array.isArray(graph?.links) ? graph.links : []
  const total = Math.max(rawNodes.length, 1)
  const radiusX = 31
  const radiusY = 25

  const nodes: SnapshotStudioNode[] = rawNodes.map(
    (node, index): SnapshotStudioNode => {
      const type = getNodeType(node)
      const angle = (index / total) * Math.PI * 2 - Math.PI / 2
      const id = String(node.id || node.label || `node-${index}`)
      const occurrences = Number(
        getNodeMetaValue(
          node,
          'occurrences',
          'count',
          'event_count',
          'degree',
          'val'
        ) ??
          node.val ??
          0
      )
      return {
        id,
        label: String(node.label || id),
        type,
        kind: firstDisplayString(getNodeMetaValue(node, 'kind', 'node_type', 'source')) || type,
        description:
          firstDisplayString(getNodeMetaValue(node, 'description', 'summary', 'content')) ||
          '来自 KG 图谱接口的真实节点。',
        x: Math.round((50 + Math.cos(angle) * radiusX) * 10) / 10,
        y: Math.round((50 + Math.sin(angle) * radiusY) * 10) / 10,
        tone: toneForNodeType(type),
        icon: iconForNodeType(type),
        occurrences: Number.isFinite(occurrences)
          ? Math.max(0, occurrences)
          : 0,
        status: '一致' as const,
        relations: [],
      }
    }
  )

  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const links = rawLinks
    .map((link) => {
      const source = getLinkEndpointId(link.source)
      const target = getLinkEndpointId(link.target)
      if (!source || !target || !nodeById.has(source) || !nodeById.has(target))
        return null
      const label = String(
        (link as any).label ||
          (link as any).predicate ||
          (link as any).relation ||
          (link as any).type ||
          '关联'
      )
      return {
        source,
        target,
        label,
        strength: strengthForWeight(
          (link as any).weight ??
            (link as any).confidence ??
            (link as any).score
        ),
      } satisfies SnapshotStudioLink
    })
    .filter((link): link is SnapshotStudioLink => Boolean(link))

  for (const link of links) {
    const source = nodeById.get(link.source)
    const target = nodeById.get(link.target)
    if (source && target)
      source.relations.push({ label: link.label, target: target.label })
    if (target && source)
      target.relations.push({ label: link.label, target: source.label })
  }

  for (const node of nodes) {
    node.relations = node.relations.slice(0, 8)
  }

  return { nodes, links }
}

function clampPercent(value: number, min = 7, max = 93): number {
  return Math.min(max, Math.max(min, Math.round(value * 10) / 10))
}

function layoutSnapshotStudioNodes(
  nodes: SnapshotStudioNode[],
  layout: string
): SnapshotStudioNode[] {
  const total = nodes.length
  if (total === 0 || layout === 'radial') return nodes

  if (layout === 'layered') {
    const groups = new Map<string, SnapshotStudioNode[]>()
    for (const node of nodes) {
      const group = groups.get(node.type) ?? []
      group.push(node)
      groups.set(node.type, group)
    }

    const orderedGroups = Array.from(groups.values()).sort(
      (a, b) => b.length - a.length
    )
    const columnCount = Math.max(1, orderedGroups.length)
    const xStep = columnCount > 1 ? 76 / (columnCount - 1) : 0

    return orderedGroups.flatMap((group, columnIndex) => {
      const x = columnCount > 1 ? 12 + columnIndex * xStep : 50
      const yStep = 70 / Math.max(group.length, 1)
      return group.map((node, rowIndex) => ({
        ...node,
        x: clampPercent(x),
        y: clampPercent(15 + rowIndex * yStep + yStep / 2),
      }))
    })
  }

  const goldenAngle = Math.PI * (3 - Math.sqrt(5))
  const radiusX = total > 120 ? 40 : 36
  const radiusY = total > 120 ? 32 : 29

  return nodes.map((node, index) => {
    const radius = Math.sqrt((index + 0.5) / total)
    const angle = index * goldenAngle
    return {
      ...node,
      x: clampPercent(50 + Math.cos(angle) * radius * radiusX),
      y: clampPercent(50 + Math.sin(angle) * radius * radiusY),
    }
  })
}

function splitCodeLines(value: string): string[] {
  const normalized = String(value ?? '').replaceAll('\r', '')
  const lines = normalized.split('\n')
  if (lines.length > 1 && lines.at(-1) === '') lines.pop()
  return lines.length ? lines : ['']
}

function buildPairedRows(
  leftLines: string[],
  rightLines: string[],
  leftStatus: DiffCellStatus,
  rightStatus: DiffCellStatus,
  leftCounter: { value: number },
  rightCounter: { value: number }
): SideBySideDiffRow[] {
  const maxLength = Math.max(leftLines.length, rightLines.length)
  return Array.from({ length: maxLength }, (_, index) => {
    const leftText = leftLines[index]
    const rightText = rightLines[index]

    const leftCell: DiffCell = {
      lineNumber: typeof leftText === 'string' ? leftCounter.value++ : null,
      text: leftText ?? '',
      status: typeof leftText === 'string' ? leftStatus : 'empty',
    }
    const rightCell: DiffCell = {
      lineNumber: typeof rightText === 'string' ? rightCounter.value++ : null,
      text: rightText ?? '',
      status: typeof rightText === 'string' ? rightStatus : 'empty',
    }
    return { left: leftCell, right: rightCell }
  })
}

function buildSideBySideDiffRows(
  aText: string,
  bText: string
): SideBySideDiffRow[] {
  const changes = diffLines(aText, bText)
  const leftCounter = { value: 1 }
  const rightCounter = { value: 1 }
  const rows: SideBySideDiffRow[] = []

  for (let index = 0; index < changes.length; index += 1) {
    const change = changes[index]
    if (!change) continue

    if (!change.added && !change.removed) {
      const lines = splitCodeLines(change.value)
      rows.push(
        ...buildPairedRows(
          lines,
          lines,
          'same',
          'same',
          leftCounter,
          rightCounter
        )
      )
      continue
    }

    const next = changes[index + 1]
    if (change.removed && next?.added) {
      rows.push(
        ...buildPairedRows(
          splitCodeLines(change.value),
          splitCodeLines(next.value),
          'removed',
          'added',
          leftCounter,
          rightCounter
        )
      )
      index += 1
      continue
    }

    if (change.added && next?.removed) {
      rows.push(
        ...buildPairedRows(
          splitCodeLines(next.value),
          splitCodeLines(change.value),
          'removed',
          'added',
          leftCounter,
          rightCounter
        )
      )
      index += 1
      continue
    }

    if (change.removed) {
      rows.push(
        ...buildPairedRows(
          splitCodeLines(change.value),
          [],
          'removed',
          'empty',
          leftCounter,
          rightCounter
        )
      )
      continue
    }

    if (change.added) {
      rows.push(
        ...buildPairedRows(
          [],
          splitCodeLines(change.value),
          'empty',
          'added',
          leftCounter,
          rightCounter
        )
      )
    }
  }

  return rows
}

function tokenizeJsonLine(
  line: string
): Array<{ text: string; kind: JsonTokenKind }> {
  const tokens: Array<{ text: string; kind: JsonTokenKind }> = []
  const pattern =
    /("(?:\\.|[^"\\])*")(\s*:)?|\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b|\btrue\b|\bfalse\b|\bnull\b|[{}\[\],:]/g

  let lastIndex = 0
  let match: RegExpExecArray | null = pattern.exec(line)
  while (match) {
    if (match.index > lastIndex) {
      tokens.push({ text: line.slice(lastIndex, match.index), kind: 'plain' })
    }

    const raw = match[0] ?? ''
    if (match[1]) {
      const suffix = match[2] ?? ''
      tokens.push({ text: match[1], kind: suffix ? 'key' : 'string' })
      if (suffix) tokens.push({ text: suffix, kind: 'punctuation' })
    } else if (raw === 'true' || raw === 'false') {
      tokens.push({ text: raw, kind: 'boolean' })
    } else if (raw === 'null') {
      tokens.push({ text: raw, kind: 'null' })
    } else if (/^-?\d/.test(raw)) {
      tokens.push({ text: raw, kind: 'number' })
    } else {
      tokens.push({ text: raw, kind: 'punctuation' })
    }

    lastIndex = pattern.lastIndex
    match = pattern.exec(line)
  }

  if (lastIndex < line.length) {
    tokens.push({ text: line.slice(lastIndex), kind: 'plain' })
  }

  if (tokens.length === 0) return [{ text: line, kind: 'plain' }]
  return tokens
}

function toneClassForDelta(value: number) {
  return DELTA_TEXT_CLASSES[deltaDirection(value)]
}

function lineNumberClassForStatus(status: DiffCellStatus | 'single'): string {
  if (status === 'added') return 'text-emerald-700'
  if (status === 'removed') return 'text-rose-700'
  return 'text-muted-foreground'
}

function jsonLineSurfaceClass(status: DiffCellStatus | 'single', side: 'left' | 'right' | 'single') {
  if (status === 'single') return 'bg-transparent'
  return cellSurfaceClass(status, side === 'single' ? 'left' : side)
}

function tabLabelForView(view: SnapshotView) {
  if (view === 'diff') return 'Diff 对比'
  if (view === 'a') return '视图 A'
  return '视图 B'
}

function cellSurfaceClass(status: DiffCellStatus, side: 'left' | 'right') {
  if (status === 'removed') return 'bg-rose-50/90'
  if (status === 'added') return 'bg-emerald-50/90'
  if (status === 'empty')
    return side === 'left' ? 'bg-rose-50/35' : 'bg-emerald-50/35'
  return 'bg-card'
}

function tokenClassName(kind: JsonTokenKind) {
  if (kind === 'key') return 'text-sky-700'
  if (kind === 'string') return 'text-emerald-700'
  if (kind === 'number') return 'text-amber-700'
  if (kind === 'boolean') return 'text-violet-700'
  if (kind === 'null') return 'text-rose-600'
  if (kind === 'punctuation') return 'text-slate-500'
  return 'text-foreground/90'
}

function SnapshotInlineStat({
  icon,
  label,
  value,
  tone = 'muted',
  valueTitle,
  valueClassName,
}: Readonly<{
  icon?: ReactNode
  label: string
  value: ReactNode
  tone?: 'muted' | 'neutral' | 'positive' | 'negative' | 'warning'
  valueTitle?: string
  valueClassName?: string
}>) {
  const toneClasses = INLINE_STAT_TONE_CLASSES[tone]
  const valueTone = INLINE_STAT_VALUE_TONE_CLASSES[tone]

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1',
        toneClasses
      )}
    >
      {icon ? (
        <span className="flex h-3.5 w-3.5 items-center justify-center opacity-80">
          {icon}
        </span>
      ) : null}
      <span className="text-[10.5px] font-medium uppercase tracking-[0.1em] opacity-80">
        {label}
      </span>
      <span
        title={valueTitle}
        className={cn(
          'font-mono text-[11px] font-semibold tabular-nums',
          valueTone,
          valueClassName
        )}
      >
        {value}
      </span>
    </div>
  )
}

function snapshotToneClassName(
  tone: SnapshotStudioNode['tone'],
  selected: boolean
) {
  const base = SNAPSHOT_NODE_TONE_CLASSES[tone]
  return cn(
    base,
    selected ? 'ring-4 ring-offset-4 ring-offset-background' : 'ring-1'
  )
}

function SnapshotStudioToolbar({
  searchValue,
  nodeType,
  relationType,
  nodeTypes,
  relationTypes,
  layout,
  studioView,
  activeSnapshotView,
  onSearchChange,
  onNodeTypeChange,
  onRelationTypeChange,
  onLayoutChange,
  onStudioViewChange,
  onSnapshotViewChange,
  onDiffClick,
  isRunning,
}: Readonly<{
  searchValue: string
  nodeType: string
  relationType: string
  nodeTypes: string[]
  relationTypes: string[]
  layout: string
  studioView: StudioCanvasView
  activeSnapshotView: SnapshotView
  onSearchChange: (value: string) => void
  onNodeTypeChange: (value: string) => void
  onRelationTypeChange: (value: string) => void
  onLayoutChange: (value: string) => void
  onStudioViewChange: (value: StudioCanvasView) => void
  onSnapshotViewChange: (value: SnapshotView) => void
  onDiffClick: () => void
  isRunning: boolean
}>) {
  const selectClassName =
    'h-8 rounded-xl border border-border/70 bg-card px-2 text-[11.5px] font-medium text-foreground shadow-sm outline-none transition-colors hover:bg-muted/30 focus:ring-2 focus:ring-primary/20'

  return (
    <div className="shrink-0 border-b border-border/70 bg-background/92 px-4 py-2.5 backdrop-blur">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto no-scrollbar">
          <div className="relative w-[220px] shrink-0">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/70"
              aria-hidden="true"
            />
            <Input
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="搜索节点 / 关系"
              className="h-8 rounded-xl border-border/70 bg-card pl-9 text-[11.5px] shadow-sm"
            />
          </div>

          <div className="inline-flex shrink-0 items-center gap-2">
            <select
              aria-label="节点类型"
              value={nodeType}
              onChange={(event) => onNodeTypeChange(event.target.value)}
              className={cn(selectClassName, 'w-[92px] shrink-0')}
            >
              <option value="all">节点类型</option>
              {nodeTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>

            <select
              aria-label="关系类型"
              value={relationType}
              onChange={(event) => onRelationTypeChange(event.target.value)}
              className={cn(selectClassName, 'w-[92px] shrink-0')}
            >
              <option value="all">关系类型</option>
              {relationTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>

          <select
            aria-label="布局"
            value={layout}
            onChange={(event) => onLayoutChange(event.target.value)}
            className={cn(selectClassName, 'w-[76px] shrink-0')}
          >
            <option value="force">布局</option>
            <option value="radial">径向</option>
            <option value="layered">分层</option>
          </select>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <div className="grid h-8 shrink-0 grid-cols-3 gap-1 rounded-xl border border-border/70 bg-card p-1 shadow-sm">
            {[
              {
                value: 'graph',
                label: '图谱视图',
                icon: <Network className="h-3.5 w-3.5" aria-hidden="true" />,
              },
              {
                value: 'table',
                label: '表格视图',
                icon: <Table2 className="h-3.5 w-3.5" aria-hidden="true" />,
              },
              {
                value: 'stats',
                label: '统计视图',
                icon: <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />,
              },
            ].map((item) => (
              <button
                key={item.value}
                type="button"
                className={cn(
                  'inline-flex items-center justify-center gap-1 rounded-lg px-2 text-[11.5px] font-semibold transition-colors',
                  studioView === item.value
                    ? 'bg-info text-primary-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                )}
                onClick={() =>
                  onStudioViewChange(item.value as StudioCanvasView)
                }
              >
                <span className="hidden 2xl:inline-flex">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </div>

          <Button
            className="h-8 shrink-0 gap-1.5 rounded-xl bg-slate-900 px-3 text-[11.5px] font-semibold text-primary-foreground shadow-sm hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-card"
            onClick={onDiffClick}
            disabled={isRunning}
          >
            <ArrowRightLeft
              className={cn('h-3.5 w-3.5', isRunning && 'animate-spin')}
              aria-hidden="true"
            />
            Diff 对比
          </Button>

          <div className="grid h-8 shrink-0 grid-cols-2 gap-1 rounded-xl border border-border/70 bg-card p-1 shadow-sm">
            <button
              type="button"
              className={cn(
                'inline-flex items-center justify-center gap-1 rounded-lg px-2 text-[11.5px] font-medium transition-colors',
                activeSnapshotView === 'a'
                  ? 'bg-emerald-50 text-emerald-700'
                  : 'text-muted-foreground hover:bg-muted/50'
              )}
              onClick={() => onSnapshotViewChange('a')}
            >
              <span className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700">
                A
              </span>
              <span>视图 A</span>
            </button>
            <button
              type="button"
              className={cn(
                'inline-flex items-center justify-center gap-1 rounded-lg px-2 text-[11.5px] font-medium transition-colors',
                activeSnapshotView === 'b'
                  ? 'bg-sky-50 text-sky-700'
                  : 'text-muted-foreground hover:bg-muted/50'
              )}
              onClick={() => onSnapshotViewChange('b')}
            >
              <span className="inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-sky-100 text-[10px] font-bold text-sky-700">
                B
              </span>
              <span>视图 B</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function SnapshotGraphCanvas({
  nodes,
  links,
  layout,
  selectedNodeId,
  searchValue,
  nodeType,
  relationType,
  nodeCount,
  relationCount,
  isLoading,
  emptyMessage,
  onSelectNode,
}: Readonly<{
  nodes: SnapshotStudioNode[]
  links: SnapshotStudioLink[]
  layout: string
  selectedNodeId: string
  searchValue: string
  nodeType: string
  relationType: string
  nodeCount: number
  relationCount: number
  isLoading: boolean
  emptyMessage?: string
  onSelectNode: (nodeId: string) => void
}>) {
  const normalizedSearch = searchValue.trim().toLowerCase()
  const displayNodes = useMemo(
    () => layoutSnapshotStudioNodes(nodes, layout),
    [layout, nodes]
  )
  const nodeById = useMemo(
    () => new Map(displayNodes.map((node) => [node.id, node])),
    [displayNodes]
  )
  const filteredNodeIds = useMemo(() => {
    const ids = new Set<string>()
    for (const node of displayNodes) {
      const matchesType = nodeType === 'all' || node.type === nodeType
      const matchesSearch =
        !normalizedSearch ||
        node.label.toLowerCase().includes(normalizedSearch) ||
        node.type.toLowerCase().includes(normalizedSearch) ||
        node.description.toLowerCase().includes(normalizedSearch)
      if (matchesType && matchesSearch) ids.add(node.id)
    }
    return ids
  }, [displayNodes, nodeType, normalizedSearch])
  const filteredLinks = useMemo(() => {
    return links.filter((link) => {
      const matchesRelation =
        relationType === 'all' || link.label === relationType
      const matchesSearch =
        !normalizedSearch || link.label.toLowerCase().includes(normalizedSearch)
      return matchesRelation && matchesSearch
    })
  }, [links, normalizedSearch, relationType])
  const hasFilter =
    Boolean(normalizedSearch) || nodeType !== 'all' || relationType !== 'all'
  const isEmpty = nodes.length === 0
  const isDenseGraph = nodes.length > 64 || filteredLinks.length > 96
  const mediumGraph = nodes.length > 36 || filteredLinks.length > 56
  const prominentNodeIds = useMemo(() => {
    const sorted = [...displayNodes].sort((a, b) => {
      const bScore = b.relations.length * 2 + b.occurrences
      const aScore = a.relations.length * 2 + a.occurrences
      return bScore - aScore
    })
    return new Set(
      sorted
        .slice(0, getProminentNodeLimit(isDenseGraph, mediumGraph))
        .map((node) => node.id)
    )
  }, [displayNodes, isDenseGraph, mediumGraph])
  const legendRows = useMemo(() => {
    const colorByTone: Record<SnapshotStudioNode['tone'], string> = {
      blue: 'bg-blue-500',
      green: 'bg-emerald-500',
      orange: 'bg-orange-500',
      purple: 'bg-violet-500',
      rose: 'bg-rose-500',
      amber: 'bg-amber-500',
      teal: 'bg-teal-500',
    }
    const seen = new Map<string, string>()
    for (const node of displayNodes) {
      if (!seen.has(node.type)) seen.set(node.type, colorByTone[node.tone])
    }
    return Array.from(seen.entries()).slice(0, 8)
  }, [displayNodes])

  return (
    <div
      data-testid="kg-snapshot-graph-canvas"
      className="relative min-h-0 flex-1 overflow-hidden bg-[radial-gradient(circle_at_center,rgba(37,99,235,0.05),transparent_44%),radial-gradient(circle_at_70%_20%,rgba(14,165,233,0.04),transparent_28%)]"
    >
      <div
        className="absolute inset-0 opacity-[0.42] [background-image:radial-gradient(circle,hsl(var(--muted-foreground)/0.26)_1px,transparent_1px)] [background-size:14px_14px]"
        aria-hidden
      />

      <div className="absolute left-7 top-7 z-20 rounded-2xl border border-border/70 bg-card/90 p-3 shadow-lg backdrop-blur">
        <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-1 text-[12px]">
          <span className="text-muted-foreground">节点</span>
          <span className="font-mono font-semibold tabular-nums text-foreground">
            {nodeCount}
          </span>
          <span className="text-muted-foreground">关系</span>
          <span className="font-mono font-semibold tabular-nums text-foreground">
            {relationCount}
          </span>
        </div>
      </div>

      {isLoading || isEmpty ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center px-8">
          <div className="flex max-w-[460px] flex-col items-center text-center">
            <div className="relative">
              <div
                className="absolute inset-0 rounded-full bg-primary/10 blur-2xl"
                aria-hidden
              />
              <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-border/70 bg-card text-primary shadow-sm">
                {isLoading ? (
                  <RefreshCcw
                    className="h-7 w-7 animate-spin"
                    aria-hidden="true"
                  />
                ) : (
                  <Network className="h-7 w-7" aria-hidden="true" />
                )}
              </div>
            </div>
            <div className="mt-4 text-[15px] font-semibold text-foreground">
              {graphLoadingTitle(isLoading)}
            </div>
            <div className="mt-1.5 text-[12px] leading-5 text-muted-foreground">
              {graphLoadingDescription(isLoading, emptyMessage)}
            </div>
          </div>
        </div>
      ) : null}

      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <marker
            id="snapshot-arrow"
            viewBox="0 0 10 10"
            refX="7.5"
            refY="5"
            markerWidth="4"
            markerHeight="4"
            orient="auto-start-reverse"
          >
            <path
              d="M 0 0 L 10 5 L 0 10 z"
              fill="rgb(148 163 184)"
              opacity="0.72"
            />
          </marker>
        </defs>
        {filteredLinks.map((link) => {
          const source = nodeById.get(link.source)
          const target = nodeById.get(link.target)
          if (!source || !target) return null
          const sourceVisible = filteredNodeIds.has(source.id)
          const targetVisible = filteredNodeIds.has(target.id)
          const baseOpacity = getLinkBaseOpacity(
            hasFilter,
            sourceVisible,
            targetVisible,
            link.strength
          )
          const opacity = getLinkDensityOpacity(baseOpacity, isDenseGraph, mediumGraph)
          const midX = (source.x + target.x) / 2
          const midY = (source.y + target.y) / 2
          const curve = source.x < target.x ? -6 : 6
          const showLinkLabel =
            !isDenseGraph || hasFilter || link.strength === 'strong'
          return (
            <g key={`${link.source}:${link.target}:${link.label}`}>
              <path
                d={`M ${source.x} ${source.y} C ${midX} ${midY + curve}, ${midX} ${midY - curve}, ${target.x} ${target.y}`}
                fill="none"
                stroke="rgb(148 163 184)"
                strokeWidth={getLinkStrokeWidth(isDenseGraph, link.strength)}
                strokeDasharray={
                  link.strength === 'weak' ? '1.1 1.1' : undefined
                }
                opacity={opacity}
                markerEnd="url(#snapshot-arrow)"
              />
              {showLinkLabel ? (
                <text
                  x={midX}
                  y={midY - 1.2}
                  textAnchor="middle"
                  className="fill-slate-400 text-[1.55px] font-normal tracking-[0.03em]"
                  opacity={Math.max(opacity * 0.9, 0.16)}
                >
                  {link.label}
                </text>
              ) : null}
            </g>
          )
        })}
      </svg>

      {displayNodes.map((node) => {
        const selected = selectedNodeId === node.id
        const matches = filteredNodeIds.has(node.id)
        const muted = hasFilter && !matches
        const showNodeLabel =
          selected ||
          (!mediumGraph && matches) ||
          (isDenseGraph
            ? prominentNodeIds.has(node.id)
            : prominentNodeIds.has(node.id) && !muted) ||
          (hasFilter && matches && normalizedSearch)
        return (
          <button
            key={node.id}
            type="button"
            className={cn(
              'absolute z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center transition-all duration-200',
              isDenseGraph ? 'gap-1' : 'gap-1.5',
              muted ? 'scale-95 opacity-25' : 'opacity-100 hover:scale-105'
            )}
            style={{ left: `${node.x}%`, top: `${node.y}%` }}
            onClick={() => onSelectNode(node.id)}
            aria-label={`选择节点 ${node.label}`}
          >
            <span
              className={cn(
                'flex items-center justify-center rounded-full text-info-foreground shadow-strong shadow-slate-900/10',
                getGraphNodeSizeClass(isDenseGraph, mediumGraph),
                snapshotToneClassName(node.tone, selected)
              )}
            >
              {node.icon}
            </span>
            {showNodeLabel ? (
              <span
                className={cn(
                  'max-w-[132px] rounded-full bg-background/82 px-2 py-0.5 font-semibold text-foreground shadow-sm backdrop-blur',
                  isDenseGraph ? 'text-[10px]' : 'text-[12px]'
                )}
              >
                <span className="block truncate">{node.label}</span>
              </span>
            ) : null}
          </button>
        )
      })}

      <div className="absolute bottom-5 left-7 z-20 flex max-w-[calc(100%-3.5rem)] flex-wrap items-center gap-3 rounded-2xl border border-border/70 bg-card/92 px-4 py-2.5 text-[12px] text-muted-foreground shadow-lg backdrop-blur">
        <span className="font-medium text-foreground">图例:</span>
        {legendRows.length ? (
          legendRows.map(([label, color]) => (
            <span key={label} className="inline-flex items-center gap-1.5">
              <span className={cn('h-2 w-2 rounded-full', color)} aria-hidden />
              {label}
            </span>
          ))
        ) : (
          <span>暂无类型</span>
        )}
        <span className="inline-flex items-center gap-2">
          <span>关系强度:</span>
          <span className="h-px w-10 bg-slate-300" aria-hidden />
          <span>弱</span>
          <span className="h-0.5 w-14 bg-slate-500" aria-hidden />
          <span>强</span>
        </span>
      </div>
    </div>
  )
}

function SnapshotNodeDetailsRail({
  selectedNode,
  diffOverview,
}: Readonly<{
  selectedNode: SnapshotStudioNode | null
  diffOverview: Array<{ label: string; value: number; tone: string }>
}>) {
  return (
    <aside className="hidden min-h-0 w-[300px] shrink-0 flex-col border-l border-border/70 bg-background xl:flex">
      <div className="flex shrink-0 items-center justify-between border-b border-border/70 px-4 py-4">
        <div className="text-[14px] font-semibold text-foreground">
          节点详情
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-lg text-muted-foreground"
          title="收起详情"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {selectedNode ? (
          <>
            <div className="flex items-start gap-3">
              <div
                className={cn(
                  'flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-info-foreground shadow-lg',
                  snapshotToneClassName(selectedNode.tone, false)
                )}
              >
                {selectedNode.icon}
              </div>
              <div className="min-w-0">
                <div className="truncate text-[16px] font-semibold text-foreground">
                  {selectedNode.label}
                </div>
                <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span>ID: {selectedNode.id}</span>
                  <Badge variant="soft" className="text-[10px]">
                    {selectedNode.type}
                  </Badge>
                </div>
              </div>
            </div>

            <section className="mt-5 rounded-2xl border border-border/70 bg-card p-4 shadow-sm">
              <div className="text-[12px] font-semibold text-foreground">
                属性
              </div>
              <div className="mt-3 space-y-3 text-[12px]">
                {[
                  ['名称', selectedNode.label],
                  ['类型', selectedNode.type],
                  ['描述', selectedNode.description],
                  ['出现次数', String(selectedNode.occurrences)],
                  ['A/B 状态', selectedNode.status],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="grid grid-cols-[64px_minmax(0,1fr)] gap-3"
                  >
                    <span className="text-muted-foreground">{label}</span>
                    <span className="min-w-0 text-foreground">{value}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="mt-4 rounded-2xl border border-border/70 bg-card p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="text-[12px] font-semibold text-foreground">
                  关联关系 ({selectedNode.relations.length})
                </div>
              </div>
              <div className="mt-3 divide-y divide-border/60">
                {selectedNode.relations.map((relation) => (
                  <button
                    key={`${relation.label}:${relation.target}`}
                    type="button"
                    className="flex w-full items-center justify-between gap-3 py-2 text-left text-[12px] transition-colors hover:text-primary"
                  >
                    <span className="inline-flex items-center gap-2 text-muted-foreground">
                      <ChevronRight
                        className="h-3.5 w-3.5"
                        aria-hidden="true"
                      />
                      {relation.label}
                    </span>
                    <span className="truncate font-medium text-foreground">
                      {relation.target}
                    </span>
                  </button>
                ))}
              </div>
              <Button
                variant="link"
                className="mt-2 h-auto p-0 text-[12px] font-semibold"
              >
                查看全部 →
              </Button>
            </section>
          </>
        ) : (
          <div className="flex min-h-[220px] flex-col items-center justify-center rounded-2xl border border-dashed border-border/70 bg-card/60 px-4 text-center">
            <Network
              className="h-8 w-8 text-muted-foreground/50"
              aria-hidden="true"
            />
            <div className="mt-3 text-[13px] font-semibold text-foreground">
              未选中节点
            </div>
            <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
              图谱返回节点后，点击任一节点即可查看真实属性和关联关系。
            </div>
          </div>
        )}

        <section className="mt-4 rounded-2xl border border-border/70 bg-card p-4 shadow-sm">
          <div className="text-[12px] font-semibold text-foreground">
            Diff 概览
          </div>
          <div className="mt-3 space-y-2">
            {diffOverview.map((item) => (
              <div
                key={item.label}
                className="flex items-center justify-between gap-3 text-[12px]"
              >
                <span className="inline-flex items-center gap-2 text-muted-foreground">
                  <span
                    className={cn('h-2.5 w-2.5 rounded-full', item.tone)}
                    aria-hidden
                  />
                  {item.label}
                </span>
                <span className="font-mono font-semibold tabular-nums text-foreground">
                  {item.value}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </aside>
  )
}

function WorkspaceSection({
  icon,
  label,
  hint,
  children,
}: Readonly<{
  icon?: ReactNode
  label: string
  hint?: string
  children: ReactNode
}>) {
  return (
    <section className="space-y-2.5 rounded-xl border border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.18))] p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {icon ? (
            <span className="flex h-3.5 w-3.5 items-center justify-center text-primary/70">
              {icon}
            </span>
          ) : null}
          {label}
        </div>
        {hint ? (
          <span className="text-[10px] text-muted-foreground/70">{hint}</span>
        ) : null}
      </div>
      {children}
    </section>
  )
}

function SectionHeading({
  eyebrow,
  title,
  description,
  icon,
  extra,
}: Readonly<{
  eyebrow: string
  title: string
  description?: string
  icon?: ReactNode
  extra?: ReactNode
}>) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--muted)/0.30))] text-primary shadow-sm">
            {icon}
          </div>
        ) : null}
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {eyebrow}
          </div>
          <div className="mt-0.5 text-[15px] font-semibold tracking-[-0.01em] text-foreground md:text-base">
            {title}
          </div>
          {description ? (
            <div className="mt-1 max-w-[640px] text-[12px] leading-5 text-muted-foreground">
              {description}
            </div>
          ) : null}
        </div>
      </div>
      {extra ? <div className="shrink-0">{extra}</div> : null}
    </div>
  )
}

function DiffEmptyState({
  title,
  description,
  hint,
}: Readonly<{
  title: string
  description: string
  hint?: string
}>) {
  return (
    <div className="flex h-full min-h-[280px] items-center justify-center px-6 py-10">
      <div className="flex max-w-[440px] flex-col items-center text-center">
        <div className="relative">
          <div
            className="absolute inset-0 -z-0 rounded-full bg-[radial-gradient(circle,hsl(var(--primary)/0.18),transparent_60%)] blur-xl"
            aria-hidden
          />
          <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-border/60 bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--muted)/0.30))] text-primary shadow-sm">
            <ArrowRightLeft
              className="h-7 w-7"
              strokeWidth={1.5}
              aria-hidden="true"
            />
          </div>
        </div>
        <h3 className="mt-4 text-[15px] font-semibold text-foreground">
          {title}
        </h3>
        <p className="mt-1.5 text-[12px] leading-5 text-muted-foreground">
          {description}
        </p>
        {hint ? (
          <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] text-muted-foreground">
            <CircleDashed
              className="h-3.5 w-3.5 text-primary/60"
              aria-hidden="true"
            />
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function auditSeverityMeta(severity: AuditSeverity): {
  label: string
  variant: 'soft' | 'outline' | 'destructive'
  icon: ReactNode
} {
  if (severity === 'warning') {
    return {
      label: '高波动',
      variant: 'destructive',
      icon: <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />,
    }
  }
  if (severity === 'notice') {
    return {
      label: '关注',
      variant: 'outline',
      icon: <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />,
    }
  }
  return {
    label: '稳定',
    variant: 'soft',
    icon: <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />,
  }
}

function SnapshotChartTooltip({
  active,
  payload,
}: Readonly<SnapshotChartTooltipProps>) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  const sign = row.delta > 0 ? '+' : ''
  return (
    <div className="rounded-lg border border-border/70 bg-card px-3 py-2 shadow-sm">
      <div className="font-mono text-[11px] text-muted-foreground">
        {row.key}
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11px]">
        <span className="font-mono text-muted-foreground">A {row.a}</span>
        <span className="font-mono text-muted-foreground">B {row.b}</span>
        <span
          className={cn(
            'font-mono font-semibold',
            deltaDirection(row.delta) === 'flat' ? 'text-foreground' : toneClassForDelta(row.delta)
          )}
        >
          Δ {sign}
          {row.delta}
        </span>
      </div>
    </div>
  )
}

function exactDiffCount(
  summary: SnapshotExactDiffSummary | null | undefined,
  key: keyof SnapshotExactDiffSummary
): number {
  const value = Number(summary?.[key] ?? 0)
  return Number.isFinite(value) ? value : 0
}

function exactDiffSample(
  diff: SnapshotDiffPayload | null,
  key: string
): Array<Record<string, unknown>> {
  const value = diff?.[key]
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> =>
        Boolean(item && typeof item === 'object')
      )
    : []
}

function DriftCounterCluster({
  groupIcon,
  groupLabel,
  added,
  removed,
  changed,
}: Readonly<{
  groupIcon: ReactNode
  groupLabel: string
  added: number
  removed: number
  changed: number
}>) {
  const total = added + removed + changed
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border/70 bg-card px-3 py-2 shadow-sm">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        {groupIcon}
      </div>
      <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {groupLabel}
          </div>
          <div className="mt-0.5 text-[10px] text-muted-foreground/80">
            {total > 0 ? `共 ${total} 条变更` : '暂无变更'}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-emerald-50 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-emerald-700 ring-1 ring-emerald-200/60">
            <span aria-hidden className="opacity-70">
              +
            </span>
            {added}
          </span>
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-rose-50 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-rose-700 ring-1 ring-rose-200/60">
            <span aria-hidden className="opacity-70">
              −
            </span>
            {removed}
          </span>
          <span className="inline-flex min-w-[40px] items-center justify-center gap-0.5 rounded-md bg-amber-50 px-1.5 py-1 font-mono text-[11px] font-semibold tabular-nums text-amber-700 ring-1 ring-amber-200/60">
            <span aria-hidden className="opacity-70">
              Δ
            </span>
            {changed}
          </span>
        </div>
      </div>
    </div>
  )
}

function SnapshotExactDriftPanel({
  diff,
}: Readonly<{ diff: SnapshotDiffPayload | null }>) {
  const nodeSummary = diff?.node_diff
  const edgeSummary = diff?.edge_diff
  const hasExactDiff = Boolean(nodeSummary || edgeSummary)
  const sampleRows = [
    {
      label: '新增节点',
      key: 'nodes_added',
      icon: <Database className="h-3.5 w-3.5" />,
      tone: 'text-emerald-700',
      tint: 'bg-emerald-50',
    },
    {
      label: '移除节点',
      key: 'nodes_removed',
      icon: <Database className="h-3.5 w-3.5" />,
      tone: 'text-rose-700',
      tint: 'bg-rose-50',
    },
    {
      label: '变更节点',
      key: 'nodes_changed',
      icon: <Database className="h-3.5 w-3.5" />,
      tone: 'text-amber-700',
      tint: 'bg-amber-50',
    },
    {
      label: '新增边',
      key: 'edges_added',
      icon: <Link2 className="h-3.5 w-3.5" />,
      tone: 'text-emerald-700',
      tint: 'bg-emerald-50',
    },
    {
      label: '移除边',
      key: 'edges_removed',
      icon: <Link2 className="h-3.5 w-3.5" />,
      tone: 'text-rose-700',
      tint: 'bg-rose-50',
    },
    {
      label: '变更边',
      key: 'edges_changed',
      icon: <Link2 className="h-3.5 w-3.5" />,
      tone: 'text-amber-700',
      tint: 'bg-amber-50',
    },
  ]

  return (
    <div className="border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.10))] px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            <Sparkles
              className="h-3.5 w-3.5 text-primary/70"
              aria-hidden="true"
            />
            精确节点/边 Diff
          </div>
          <div className="mt-1 max-w-[560px] text-[11px] leading-5 text-muted-foreground">
            {hasExactDiff
              ? '后端已返回 bounded nodes / edges 明细，可直接定位新增、移除和属性变化。'
              : '当前 diff 只有聚合计数；重新执行对比会请求 include_details=true。'}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DriftCounterCluster
            groupIcon={<Database className="h-4 w-4" />}
            groupLabel="Node"
            added={exactDiffCount(nodeSummary, 'added_count')}
            removed={exactDiffCount(nodeSummary, 'removed_count')}
            changed={exactDiffCount(nodeSummary, 'changed_count')}
          />
          <DriftCounterCluster
            groupIcon={<Link2 className="h-4 w-4" />}
            groupLabel="Edge"
            added={exactDiffCount(edgeSummary, 'added_count')}
            removed={exactDiffCount(edgeSummary, 'removed_count')}
            changed={exactDiffCount(edgeSummary, 'changed_count')}
          />
        </div>
      </div>

      {hasExactDiff ? (
        <div className="mt-3 grid gap-2 lg:grid-cols-3">
          {sampleRows.map((row) => {
            const items = exactDiffSample(diff, row.key)
            const preview = items
              .slice(0, 3)
              .map((item) => firstDisplayString(item.name, item.id) || 'unknown')
              .join(' / ')
            return (
              <div
                key={row.key}
                className="rounded-lg border border-border/70 bg-card px-3 py-2 transition-shadow hover:shadow-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                    <span
                      className={cn(
                        'flex h-5 w-5 items-center justify-center rounded-md',
                        row.tint,
                        row.tone
                      )}
                    >
                      {row.icon}
                    </span>
                    {row.label}
                  </span>
                  <span
                    className={cn(
                      'font-mono text-[11px] font-semibold tabular-nums',
                      row.tone
                    )}
                  >
                    {items.length}
                  </span>
                </div>
                <div
                  className="mt-1 truncate font-mono text-[11px] text-muted-foreground"
                  title={preview || '暂无样本'}
                >
                  {preview || '暂无样本'}
                </div>
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

function JsonLine({
  lineNumber,
  text,
  status,
  side = 'single',
}: Readonly<{
  lineNumber: number | null
  text: string
  status: DiffCellStatus | 'single'
  side?: 'left' | 'right' | 'single'
}>) {
  const tokens = useMemo(() => tokenizeJsonLine(text), [text])
  const lineNumberClass = lineNumberClassForStatus(status)

  return (
    <div
      className={cn(
        'grid min-w-0 grid-cols-[52px_minmax(0,1fr)] border-b border-border/60 text-[12px] leading-6',
        jsonLineSurfaceClass(status, side)
      )}
    >
      <div
        className={cn(
          'select-none border-r border-border/70 px-3 text-right font-mono tabular-nums',
          lineNumberClass
        )}
      >
        {lineNumber ?? ''}
      </div>
      <div className="px-3 font-mono">
        <span className="inline-block min-w-full whitespace-pre">
          {tokens.map((token, index) => (
            <span
              key={`${lineNumber ?? 'x'}:${index}:${token.kind}`}
              className={tokenClassName(token.kind)}
            >
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </div>
  )
}

function JsonDiffCell({
  cell,
  side,
}: Readonly<{
  cell: DiffCell
  side: 'left' | 'right'
}>) {
  const tokens = useMemo(() => tokenizeJsonLine(cell.text), [cell.text])
  const lineNumberClass = lineNumberClassForStatus(cell.status)

  return (
    <>
      <div
        className={cn(
          'select-none border-r border-border/70 px-3 py-0.5 text-right font-mono text-[12px] leading-6 tabular-nums',
          cellSurfaceClass(cell.status, side),
          lineNumberClass
        )}
      >
        {cell.lineNumber ?? ''}
      </div>
      <div
        className={cn(
          'px-3 py-0.5 font-mono text-[12px] leading-6',
          cellSurfaceClass(cell.status, side)
        )}
      >
        <span className="inline-block min-w-full whitespace-pre">
          {tokens.map((token, index) => (
            <span
              key={`${cell.lineNumber ?? side}:${index}:${token.kind}`}
              className={tokenClassName(token.kind)}
            >
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </>
  )
}

function JsonCodePane({
  label,
  title,
  subtitle,
  code,
  isEmpty,
  emptyState,
  onCopy,
  onDownload,
}: Readonly<{
  label: string
  title: string
  subtitle?: string
  code: string
  isEmpty?: boolean
  emptyState?: ReactNode
  onCopy: () => void
  onDownload: () => void
}>) {
  const lines = useMemo(() => splitCodeLines(code), [code])

  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      <div className="flex shrink-0 items-center justify-between border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.15))] px-4 py-2.5">
        <div className="min-w-0">
          <div className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-card px-2 py-0.5 text-[10.5px] font-semibold tracking-[0.08em] text-muted-foreground">
            <FileJson className="h-3 w-3 text-primary/70" aria-hidden="true" />
            {label}
          </div>
          <div className="mt-1 truncate text-[13px] font-semibold text-foreground">
            {title}
          </div>
          {subtitle ? (
            <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {subtitle}
            </div>
          ) : null}
        </div>
        <div className="ml-4 flex shrink-0 items-center gap-1 rounded-md border border-border/70 bg-card p-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg"
            title="复制 JSON"
            onClick={onCopy}
            disabled={isEmpty}
          >
            <Copy className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg"
            title="导出 JSON"
            onClick={onDownload}
            disabled={isEmpty}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-card">
        {isEmpty && emptyState ? (
          emptyState
        ) : (
          <div className="min-w-max">
            {lines.map((line, index) => (
              <JsonLine
                key={`${title}:${index + 1}`}
                lineNumber={index + 1}
                text={line}
                status="single"
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SnapshotDiffView({
  titleA,
  titleB,
  subtitleA,
  subtitleB,
  leftCode,
  rightCode,
  diff,
  typeDrift,
  isEmpty,
  emptyState,
  onCopy,
  onDownload,
}: Readonly<{
  titleA: string
  titleB: string
  subtitleA?: string
  subtitleB?: string
  leftCode: string
  rightCode: string
  diff: SnapshotDiffPayload | null
  typeDrift: SnapshotDiffEntityRow[]
  isEmpty?: boolean
  emptyState?: ReactNode
  onCopy: () => void
  onDownload: () => void
}>) {
  const rows = useMemo(
    () => buildSideBySideDiffRows(leftCode, rightCode),
    [leftCode, rightCode]
  )

  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/70 bg-background px-4 py-2">
        <div className="min-w-0 flex-1">
          {typeDrift.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                <Layers
                  className="h-3.5 w-3.5 text-primary/70"
                  aria-hidden="true"
                />
                Type Drift
              </span>
              {typeDrift.slice(0, 8).map((row) => {
                const type = String(row.type || 'unknown')
                const delta = Number(row.delta ?? 0)
                const sign = delta > 0 ? '+' : ''
                return (
                  <Badge
                    key={`${type}:${delta}`}
                    variant="outline"
                    className="inline-flex items-center gap-1 font-mono text-[11px]"
                  >
                    <span className="text-muted-foreground">{type}</span>
                    <span className={toneClassForDelta(delta)}>
                      {sign + delta}
                    </span>
                  </Badge>
                )
              })}
            </div>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <Layers
                className="h-3.5 w-3.5 text-muted-foreground/60"
                aria-hidden="true"
              />
              Type Drift · 暂无
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg"
            title="复制 Diff JSON"
            onClick={onCopy}
            disabled={isEmpty}
          >
            <Copy className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 rounded-lg"
            title="导出 Diff JSON"
            onClick={onDownload}
            disabled={isEmpty}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <SnapshotExactDriftPanel diff={diff} />

      <div className="min-h-0 flex-1 overflow-auto bg-card">
        {isEmpty && emptyState ? (
          emptyState
        ) : (
          <div className="min-w-[980px]">
            <div className="sticky top-0 z-10 grid grid-cols-[52px_minmax(0,1fr)_52px_minmax(0,1fr)] border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.10))] text-[12px] backdrop-blur">
              <div className="border-r border-border/70 px-3 py-2 text-right font-mono text-muted-foreground">
                #
              </div>
              <div className="border-r border-border/70 px-3 py-2">
                <div className="text-[12px] font-semibold tracking-[-0.01em] text-foreground">
                  {titleA}
                </div>
                {subtitleA ? (
                  <div className="truncate text-[11px] text-muted-foreground">
                    {subtitleA}
                  </div>
                ) : null}
              </div>
              <div className="border-r border-border/70 px-3 py-2 text-right font-mono text-muted-foreground">
                #
              </div>
              <div className="px-3 py-2">
                <div className="text-[12px] font-semibold tracking-[-0.01em] text-foreground">
                  {titleB}
                </div>
                {subtitleB ? (
                  <div className="truncate text-[11px] text-muted-foreground">
                    {subtitleB}
                  </div>
                ) : null}
              </div>
            </div>

            {rows.map((row, index) => (
              <div
                key={`diff-row:${index}`}
                className="grid grid-cols-[52px_minmax(0,1fr)_52px_minmax(0,1fr)]"
              >
                <JsonDiffCell cell={row.left} side="left" />
                <JsonDiffCell cell={row.right} side="right" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SnapshotAuditPanel({
  deltaRows,
  typeDriftRows,
  severity,
  driftScore,
  includeZeroDeltas,
  compactRows,
  onIncludeZeroDeltasChange,
  onCompactRowsChange,
}: Readonly<{
  deltaRows: SnapshotDeltaRow[]
  typeDriftRows: SnapshotDiffEntityRow[]
  severity: AuditSeverity
  driftScore: number
  includeZeroDeltas: boolean
  compactRows: boolean
  onIncludeZeroDeltasChange: (value: boolean) => void
  onCompactRowsChange: (value: boolean) => void
}>) {
  const severityMeta = auditSeverityMeta(severity)
  const chartRows = includeZeroDeltas
    ? deltaRows
    : deltaRows.filter((row) => row.delta !== 0)
  const chartRowsWithFill = chartRows.map((row) => ({
    ...row,
    fill: deltaFill(row.delta),
  }))
  const shownDriftRows = compactRows
    ? typeDriftRows.slice(0, 14)
    : typeDriftRows
  const driftScoreTone = driftScoreToneForSeverity(severity)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.20))] px-4 py-3">
        <SectionHeading
          eyebrow="评估"
          title="效果面板"
          description="快速查看快照差异强度、类型漂移与整体风险等级。"
          icon={<BarChart3 className="h-5 w-5" aria-hidden="true" />}
          extra={
            <Badge
              variant={severityMeta.variant}
              className="inline-flex items-center gap-1.5 font-mono text-[11px]"
            >
              {severityMeta.icon}
              {severityMeta.label}
            </Badge>
          }
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <SnapshotInlineStat
            icon={<Sparkles className="h-3.5 w-3.5" />}
            label="Drift Score"
            value={driftScore.toFixed(2)}
            tone={driftScoreTone}
          />
          <SnapshotInlineStat
            icon={<Layers className="h-3.5 w-3.5" />}
            label="Type Drift"
            value={typeDriftRows.length}
            tone={typeDriftRows.length > 0 ? 'positive' : 'muted'}
          />
          <SnapshotInlineStat
            icon={<ArrowRightLeft className="h-3.5 w-3.5" />}
            label="Delta Keys"
            value={deltaRows.filter((row) => row.delta !== 0).length}
            tone="neutral"
          />
        </div>
      </div>

      <div className="grid min-h-0 flex-1 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="min-h-0 border-b border-border/70 xl:border-b-0 xl:border-r">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-4 py-2.5">
            <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <BarChart3
                className="h-3.5 w-3.5 text-primary/70"
                aria-hidden="true"
              />
              Delta Distribution
            </div>
            <div className="flex items-center gap-4">
              <label className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
                <Switch
                  checked={includeZeroDeltas}
                  onCheckedChange={onIncludeZeroDeltasChange}
                />
                显示 0 值
              </label>
            </div>
          </div>

          <div className="px-3 py-2">
            <SafeResponsiveChart className="h-[280px]" minHeight={280}>
              <BarChart
                data={chartRowsWithFill}
                margin={{ top: 8, right: 10, left: -16, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  vertical={false}
                  stroke="#e2e8f0"
                />
                <XAxis
                  dataKey="key"
                  tick={{ fontSize: 11, fill: '#64748b' }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#64748b' }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                  content={<SnapshotChartTooltip />}
                />
                <Bar dataKey="delta" radius={[6, 6, 0, 0]} />
              </BarChart>
            </SafeResponsiveChart>
          </div>
        </div>

        <div className="min-h-0 flex flex-col">
          <div className="flex items-center justify-between gap-2 border-b border-border/70 px-4 py-2.5">
            <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              <Layers
                className="h-3.5 w-3.5 text-primary/70"
                aria-hidden="true"
              />
              Type Drift Rows
            </div>
            <label className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
              <Switch
                checked={compactRows}
                onCheckedChange={onCompactRowsChange}
              />
              紧凑模式
            </label>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {shownDriftRows.length ? (
              shownDriftRows.map((row, index) => {
                const type = String(row.type || 'unknown')
                const delta = Number(row.delta ?? 0)
                const direction = deltaDirection(delta)
                const sign = deltaSign(delta)
                const tone = DELTA_TEXT_CLASSES[direction]
                const tint = DELTA_TINT_CLASSES[direction]
                return (
                  <button
                    key={`drift:${type}:${index}`}
                    type="button"
                    className="grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-b border-border/60 px-4 py-2 text-left transition-colors hover:bg-muted/30"
                    title={`${type} Δ ${sign}${delta}`}
                  >
                    <span className="truncate font-mono text-[12px] text-foreground">
                      {type}
                    </span>
                    <span
                      className={cn(
                        'inline-flex min-w-[52px] items-center justify-center rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums ring-1',
                        tint,
                        tone
                      )}
                    >
                      Δ {sign}
                      {delta}
                    </span>
                    <Badge
                      variant={DELTA_BADGE_VARIANTS[direction]}
                      className="font-mono text-[10.5px]"
                    >
                      {DELTA_LABELS[direction]}
                    </Badge>
                  </button>
                )
              })
            ) : (
              <div className="flex h-full items-center justify-center px-4 py-12">
                <div className="flex max-w-[320px] flex-col items-center text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border/60 bg-card text-muted-foreground/70 shadow-sm">
                    <Layers className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="mt-3 text-[13px] font-semibold text-foreground">
                    暂无类型漂移
                  </div>
                  <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                    entity_types_delta 为空：A / B 之间的实体类型构成保持一致。
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export function KGSnapshotsPage() {
  const searchParams = useSearchParams()
  const scopeParamKey = searchParams.toString()
  const datasetIdFromUrl = useMemo(() => {
    return (new URLSearchParams(scopeParamKey).get('dataset_id') || '').trim()
  }, [scopeParamKey])

  const [pipelineHashA, setPipelineHashA] = useState('')
  const [pipelineHashB, setPipelineHashB] = useState('')
  const [documentIdsRaw, setDocumentIdsRaw] = useState('')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [selectedDatasetId, setSelectedDatasetId] = useState(datasetIdFromUrl)
  const [pipelineCandidates, setPipelineCandidates] = useState<PipelineCandidate[]>([])
  const [pipelineCandidatesLoading, setPipelineCandidatesLoading] = useState(false)
  const [pipelineCandidatesError, setPipelineCandidatesError] = useState<string | null>(null)
  const [advancedHashOpen, setAdvancedHashOpen] = useState(false)
  const [liveGraph, setLiveGraph] = useState<KGGraphResponse | null>(null)
  const [liveGraphLoading, setLiveGraphLoading] = useState(false)
  const [liveGraphError, setLiveGraphError] = useState<string | null>(null)
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('studio')
  const [activeView, setActiveView] = useState<SnapshotView>('diff')
  const [studioCanvasView, setStudioCanvasView] =
    useState<StudioCanvasView>('graph')
  const [studioSearch, setStudioSearch] = useState('')
  const [studioNodeType, setStudioNodeType] = useState('all')
  const [studioRelationType, setStudioRelationType] = useState('all')
  const [studioLayout, setStudioLayout] = useState('force')
  const [selectedStudioNodeId, setSelectedStudioNodeId] = useState('')
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false)
  const [includeZeroDeltas, setIncludeZeroDeltas] = useState(true)
  const [compactAuditRows, setCompactAuditRows] = useState(true)

  const [snapA, setSnapA] = useState<SnapshotPayload | null>(null)
  const [snapB, setSnapB] = useState<SnapshotPayload | null>(null)
  const [diff, setDiff] = useState<SnapshotDiffPayload | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const documentIds = useMemo(
    () => parseDocumentIds(documentIdsRaw),
    [documentIdsRaw]
  )
  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId) ?? null,
    [datasets, selectedDatasetId]
  )
  const scopeDatasetId = selectedDatasetId || undefined
  const scopeDocumentIds = documentIds.length > 0 ? documentIds : undefined
  const scopeDocumentIdsKey = scopeDocumentIds?.join(',') ?? ''
  const selectedDatasetLabel = getSelectedDatasetLabel(selectedDataset, selectedDatasetId)
  const scopeDocumentCountLabel = getScopeDocumentCountLabel(documentIds.length, selectedDatasetId)

  useEffect(() => {
    setSelectedDatasetId(datasetIdFromUrl)
    setPipelineHashA('')
    setPipelineHashB('')
    setSnapA(null)
    setSnapB(null)
    setDiff(null)
  }, [datasetIdFromUrl])

  useEffect(() => {
    let cancelled = false
    setDatasetsLoading(true)
    ;(async () => {
      try {
        const result = await datasetApi.list({ skip: 0, limit: 200 })
        if (!cancelled) {
          setDatasets(Array.isArray(result.items) ? result.items : [])
        }
      } catch {
        if (!cancelled) setDatasets([])
      } finally {
        if (!cancelled) setDatasetsLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const selectedDataset = selectedDatasetId.trim()
    setPipelineCandidatesLoading(true)
    setPipelineCandidatesError(null)
    ;(async () => {
      const candidateMap = new Map<string, PipelineCandidate>()
      try {
        if (selectedDataset) {
          const report = await reportApi.getDatasetReport(selectedDataset).catch(() => null)
          for (const version of report?.pipeline_versions ?? []) {
            mergePipelineCandidate(candidateMap, {
              hash: String(version.pipeline_hash || '').trim(),
              documents: Number(version.documents ?? 0) || 0,
              source: 'report',
              active: String(version.pipeline_hash || '').trim() === String(report?.pipeline_hash || '').trim(),
            })
          }
          const reportHash = String(report?.pipeline_hash || '').trim()
          if (reportHash) {
            mergePipelineCandidate(candidateMap, {
              hash: reportHash,
              documents: Number((report as any)?.profile?.document_count ?? 0) || 0,
              source: 'report',
              active: true,
            })
          }
        }

        const documents = await documentApi
          .list({
            skip: 0,
            limit: 200,
            dataset_id: selectedDataset || null,
            order_by: 'created_at',
            order_dir: 'desc',
          })
          .catch(() => null)

        for (const document of documents?.items ?? []) {
          const activeHash = firstDisplayString(
            getDocumentMetaValue(document, 'active_pipeline_hash')
          )
          const currentHash = firstDisplayString(getDocumentMetaValue(document, 'pipeline_hash'))
          if (activeHash) {
            mergePipelineCandidate(candidateMap, {
              hash: activeHash,
              documents: 1,
              source: 'documents',
              active: true,
            })
          }
          if (currentHash) {
            mergePipelineCandidate(candidateMap, {
              hash: currentHash,
              documents: 1,
              source: 'documents',
              active: currentHash === activeHash,
            })
          }
        }

        if (!cancelled) {
          const next = sortPipelineCandidates(Array.from(candidateMap.values()))
          setPipelineCandidates(next)
          setPipelineHashB((current) =>
            current.trim() ? current : next[0]?.hash ?? ''
          )
          setPipelineHashA((current) =>
            current.trim() ? current : next[1]?.hash ?? ''
          )
        }
      } catch (err) {
        if (!cancelled) {
          setPipelineCandidates([])
          setPipelineCandidatesError(formatApiError(err, '快照候选加载失败'))
        }
      } finally {
        if (!cancelled) setPipelineCandidatesLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [selectedDatasetId])

  const snapAJson = useMemo(
    () => prettyJson(snapA ?? { hint: '点击左侧“导出 A”生成快照。' }),
    [snapA]
  )
  const snapBJson = useMemo(
    () => prettyJson(snapB ?? { hint: '点击左侧“导出 B”生成快照。' }),
    [snapB]
  )
  const diffJson = useMemo(
    () => prettyJson(diff ?? { hint: '点击左侧“开始对比”生成 diff。' }),
    [diff]
  )

  const diffDelta = useMemo(() => {
    const delta =
      diff?.delta && typeof diff.delta === 'object' ? diff.delta : null
    const entityTypesDelta = Array.isArray(diff?.entity_types_delta)
      ? diff.entity_types_delta
      : []
    return { delta, entityTypesDelta }
  }, [diff])
  const deferredEntityTypesDelta = useDeferredValue(diffDelta.entityTypesDelta)

  async function runExport(which: 'a' | 'b'): Promise<void> {
    const pipelineHash = (which === 'a' ? pipelineHashA : pipelineHashB).trim()
    if (!pipelineHash) {
      toast.error(which === 'a' ? '请选择快照 A' : '请选择快照 B')
      return
    }

    setIsRunning(true)
    try {
      const snapshot = await kgApi.exportSnapshot({
        pipeline_hash: pipelineHash,
        dataset_id: scopeDatasetId,
        document_ids: scopeDocumentIds,
        include_details: true,
      })
      if (which === 'a') {
        setSnapA(snapshot)
        setActiveView('a')
      } else {
        setSnapB(snapshot)
        setActiveView('b')
      }
      toast.success(`已导出 ${which.toUpperCase()} 快照`)
    } catch (err) {
      toast.error(formatApiError(err, '导出 KG snapshot 失败'))
    } finally {
      setIsRunning(false)
    }
  }

  async function runCompare(): Promise<void> {
    const a = pipelineHashA.trim()
    const b = pipelineHashB.trim()
    if (!a || !b) {
      toast.error('请选择快照 A / B')
      return
    }
    if (a === b) {
      toast.error('A / B pipeline_hash 不能相同')
      return
    }

    setIsRunning(true)
    setLatencyMs(null)
    try {
      const start = Date.now()
      const [snapshotA, snapshotB] = await Promise.all([
        kgApi.exportSnapshot({
          pipeline_hash: a,
          dataset_id: scopeDatasetId,
          document_ids: scopeDocumentIds,
          include_details: true,
        }),
        kgApi.exportSnapshot({
          pipeline_hash: b,
          dataset_id: scopeDatasetId,
          document_ids: scopeDocumentIds,
          include_details: true,
        }),
      ])
      const result = await kgApi.diffSnapshots({
        snapshot_a: snapshotA,
        snapshot_b: snapshotB,
      })
      setLatencyMs(Math.max(0, Date.now() - start))
      setSnapA(snapshotA)
      setSnapB(snapshotB)
      setDiff(result)
      setActiveView('diff')
      toast.success('已生成 diff')
    } catch (err) {
      toast.error(formatApiError(err, 'KG snapshot compare 失败'))
    } finally {
      setIsRunning(false)
    }
  }

  async function runBackendCompare(): Promise<void> {
    const a = pipelineHashA.trim()
    const b = pipelineHashB.trim()
    if (!a || !b) {
      toast.error('请选择快照 A / B')
      return
    }
    if (a === b) {
      toast.error('A / B pipeline_hash 不能相同')
      return
    }

    setIsRunning(true)
    setLatencyMs(null)
    try {
      const start = Date.now()
      const result = await kgApi.compareSnapshots({
        pipeline_hash_a: a,
        pipeline_hash_b: b,
        dataset_id: scopeDatasetId,
        document_ids: scopeDocumentIds,
      })
      setLatencyMs(Math.max(0, Date.now() - start))
      setDiff(result)
      setActiveView('diff')
      toast.success('后端对比完成')
    } catch (err) {
      toast.error(formatApiError(err, 'KG snapshot 后端对比失败'))
    } finally {
      setIsRunning(false)
    }
  }

  const hashAValue = pipelineHashA.trim()
  const hashBValue = pipelineHashB.trim()
  const liveGraphPipelineHash = hashBValue || hashAValue || undefined
  const hasHashA = Boolean(hashAValue)
  const hasHashB = Boolean(hashBValue)
  const hashATitle = hashAValue || '未设置'
  const hashBTitle = hashBValue || '未设置'
  const hashPairStatus = getHashPairStatus(hasHashA, hasHashB)
  const hashPairTitle = `A: ${hashAValue || '未填写'}\nB: ${hashBValue || '未填写'}`
  const hashPairTone = getHashPairTone(hasHashA, hasHashB)
  const hashPairIcon = getHashPairIcon(hasHashA, hasHashB)
  const diffBaseName =
    sanitizeFilename(
      `kg_snapshot_${hashAValue || 'A'}_vs_${hashBValue || 'B'}`
    ) || 'kg_snapshot'
  const snapshotScopeSubtitle = getSnapshotScopeSubtitle(
    scopeDocumentIds?.length ?? 0,
    scopeDatasetId,
    selectedDatasetLabel
  )
  const snapshotAFileName =
    sanitizeFilename(`kg_snapshot_${hashAValue || 'A'}`) || 'kg_snapshot_A'
  const snapshotBFileName =
    sanitizeFilename(`kg_snapshot_${hashBValue || 'B'}`) || 'kg_snapshot_B'
  useEffect(() => {
    let cancelled = false
    setLiveGraphLoading(true)
    setLiveGraphError(null)
    ;(async () => {
      try {
        const meta = await metaApi.get().catch(() => null)
        if (meta?.features?.kg_enabled === false) {
          if (!cancelled) {
            setLiveGraph({ nodes: [], links: [] })
            setLiveGraphError(
              'KG 功能未启用，已按后端能力状态跳过实时图谱读取。请在设置中开启 KG 抽取后刷新。'
            )
          }
          return
        }

        const graph = await kgApi.getGraph({
          dataset_id: scopeDatasetId,
          document_ids: scopeDocumentIds,
          pipeline_hash: liveGraphPipelineHash,
          max_events: 80,
          max_entities: 80,
          max_links: 160,
          include_entity_links: true,
          include_relation_links: true,
          min_shared_events: 1,
          max_entity_links: 160,
        })
        if (!cancelled) setLiveGraph(graph)
      } catch (err) {
        if (!cancelled) {
          setLiveGraph({ nodes: [], links: [] })
          setLiveGraphError(formatApiError(err, 'KG 图谱读取失败'))
        }
      } finally {
        if (!cancelled) setLiveGraphLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [
    liveGraphPipelineHash,
    selectedDatasetId,
    scopeDatasetId,
    scopeDocumentIds,
    scopeDocumentIdsKey,
  ])

  const studioGraph = useMemo(
    () => buildSnapshotStudioGraphFromKgGraph(liveGraph),
    [liveGraph]
  )
  const nodeTypes = useMemo(
    () => Array.from(new Set(studioGraph.nodes.map((node) => node.type))),
    [studioGraph.nodes]
  )
  const relationTypes = useMemo(
    () => Array.from(new Set(studioGraph.links.map((link) => link.label))),
    [studioGraph.links]
  )
  const selectedStudioNode = useMemo(() => {
    return (
      studioGraph.nodes.find((node) => node.id === selectedStudioNodeId) ??
      studioGraph.nodes[0] ??
      null
    )
  }, [selectedStudioNodeId, studioGraph.nodes])
  useEffect(() => {
    if (studioGraph.nodes.length === 0) {
      if (selectedStudioNodeId) setSelectedStudioNodeId('')
      return
    }
    if (!studioGraph.nodes.some((node) => node.id === selectedStudioNodeId)) {
      setSelectedStudioNodeId(studioGraph.nodes[0]?.id ?? '')
    }
  }, [selectedStudioNodeId, studioGraph.nodes])

  const deltaRows = useMemo<SnapshotDeltaRow[]>(() => {
    return DIFF_KEYS.map((key) => {
      const a = Number(snapA?.[key] ?? 0)
      const b = Number(snapB?.[key] ?? 0)
      const d = Number(diffDelta.delta?.[key] ?? b - a)
      return {
        key,
        a: Number.isFinite(a) ? a : 0,
        b: Number.isFinite(b) ? b : 0,
        delta: Number.isFinite(d) ? d : 0,
      }
    })
  }, [diffDelta.delta, snapA, snapB])
  const driftScore = useMemo(() => {
    const denominator = deltaRows.reduce(
      (acc, row) => acc + Math.max(Math.max(row.a, row.b), 1),
      0
    )
    if (denominator <= 0) return 0
    const totalDelta = deltaRows.reduce(
      (acc, row) => acc + Math.abs(row.delta),
      0
    )
    return totalDelta / denominator
  }, [deltaRows])
  const auditSeverity = auditSeverityForDriftScore(driftScore)
  const auditDriftRows = useMemo(() => {
    return [...deferredEntityTypesDelta].sort(
      (a, b) => Math.abs(Number(b.delta ?? 0)) - Math.abs(Number(a.delta ?? 0))
    )
  }, [deferredEntityTypesDelta])
  const diffOverview = useMemo(() => {
    const nodeAdded = exactDiffCount(diff?.node_diff, 'added_count')
    const nodeRemoved = exactDiffCount(diff?.node_diff, 'removed_count')
    const nodeChanged = exactDiffCount(diff?.node_diff, 'changed_count')
    const edgeAdded = exactDiffCount(diff?.edge_diff, 'added_count')
    const edgeRemoved = exactDiffCount(diff?.edge_diff, 'removed_count')
    return [
      {
        label: '节点变化',
        value: nodeAdded + nodeRemoved + nodeChanged,
        tone: 'bg-slate-400',
      },
      { label: '属性变化', value: nodeChanged, tone: 'bg-emerald-400' },
      { label: '新增关系', value: edgeAdded, tone: 'bg-rose-400' },
      { label: '删除关系', value: edgeRemoved, tone: 'bg-red-400' },
      {
        label: '重要变化',
        value: driftScore >= 0.35 ? 1 : 0,
        tone: 'bg-amber-400',
      },
    ]
  }, [diff, driftScore])
  const formInputClassName =
    'h-10 rounded-lg border-border/70 bg-card font-mono text-xs shadow-none'
  const formTextareaClassName =
    'min-h-[108px] resize-none rounded-lg border-border/70 bg-card font-mono text-xs shadow-none'

  return (
    <AppFrame showBackground={false}>
      <div className="flex h-full min-h-0 flex-col bg-[radial-gradient(1200px_460px_at_12%_-18%,rgba(37,99,235,0.08),transparent_58%),radial-gradient(960px_420px_at_88%_-24%,rgba(14,165,233,0.06),transparent_56%)] bg-background">
        <header className="shrink-0 border-b border-border/70 bg-background/80 backdrop-blur">
          <div className="px-4 py-3 md:px-6">
            <PageHeader
              title="图谱快照"
              description="对比同一数据集不同入库/治理版本生成的图谱快照，并快速判断结构波动。"
              iconImage="kg-snapshot"
              icon={GitCompare}
              iconColor="text-info"
              badge="Graph"
              compact
              className="p-0"
            >
              <div className="flex shrink-0 items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 gap-2 rounded-lg border-border/70 bg-card text-xs font-medium"
                  title={
                    hashAValue && hashBValue
                      ? '重新导出并刷新 A/B 对比结果'
                      : '先填写快照 A / 快照 B'
                  }
                  disabled={isRunning || !hashAValue || !hashBValue}
                  onClick={() => detachPromise(runCompare())}
                >
                  <RefreshCcw
                    className={cn('h-3.5 w-3.5', isRunning && 'animate-spin')}
                    aria-hidden="true"
                  />
                  刷新对比
                </Button>

                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 rounded-lg text-muted-foreground hover:text-foreground"
                  title="清空"
                  onClick={() => {
                    setSnapA(null)
                    setSnapB(null)
                    setDiff(null)
                    setLatencyMs(null)
                    startTransition(() => {
                      setWorkspaceTab('studio')
                      setActiveView('diff')
                      setStudioCanvasView('graph')
                    })
                    toast.message('已清空')
                  }}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>

                <div className="mx-1 h-5 w-px bg-border/70" aria-hidden />

                <Button
                  variant="outline"
                  size="icon"
                  className="h-9 w-9 rounded-lg border-border/70 bg-card"
                  onClick={() => setLeftSidebarCollapsed((prev) => !prev)}
                  aria-label={
                    leftSidebarCollapsed ? '展开参数栏' : '折叠参数栏'
                  }
                  title={leftSidebarCollapsed ? '展开参数栏' : '折叠参数栏'}
                >
                  {leftSidebarCollapsed ? (
                    <PanelLeftOpen className="h-4 w-4" />
                  ) : (
                    <PanelLeftClose className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </PageHeader>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <aside
            className={cn(
              'shrink-0 border-r border-border/70 bg-background transition-[width,opacity] duration-200',
              leftSidebarCollapsed
                ? 'w-0 overflow-hidden border-r-0 opacity-0'
                : 'w-[288px] opacity-100',
              'flex min-h-0 flex-col'
            )}
          >
            <div className="flex h-full min-h-0 flex-col">
              <div className="shrink-0 border-b border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.20))] px-4 py-3">
                <div className="grid grid-cols-2 gap-1 rounded-xl border border-border/70 bg-card p-1 shadow-sm">
                  <button
                    type="button"
                    className={cn(
                      'inline-flex h-8 items-center justify-center gap-1.5 rounded-lg text-[12px] font-medium transition-colors',
                      workspaceTab === 'studio'
                        ? 'bg-primary text-primary-foreground shadow-sm'
                        : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                    )}
                    onClick={() => {
                      startTransition(() => setWorkspaceTab('studio'))
                    }}
                  >
                    <FileJson className="h-3.5 w-3.5" aria-hidden="true" />
                    工作台
                  </button>
                  <button
                    type="button"
                    className={cn(
                      'inline-flex h-8 items-center justify-center gap-1.5 rounded-lg text-[12px] font-medium transition-colors',
                      workspaceTab === 'audit'
                        ? 'bg-primary text-primary-foreground shadow-sm'
                        : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                    )}
                    onClick={() => {
                      startTransition(() => setWorkspaceTab('audit'))
                    }}
                  >
                    <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />
                    评估
                  </button>
                </div>
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  <SnapshotInlineStat
                    icon={hashPairIcon}
                    label="A/B"
                    value={hashPairStatus}
                    valueTitle={hashPairTitle}
                    tone={hashPairTone}
                  />
                  {typeof latencyMs === 'number' ? (
                    <SnapshotInlineStat
                      icon={<Sparkles className="h-3.5 w-3.5" />}
                      label="耗时"
                      value={`${latencyMs} ms`}
                      tone="neutral"
                    />
                  ) : null}
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                <div className="space-y-3">
                  <WorkspaceSection
                    icon={<Hash className="h-3.5 w-3.5" />}
                    label="快照版本"
                    hint={selectedDatasetId ? '已绑定数据集' : '全局候选'}
                  >
                    <div className="space-y-2.5">
                      <div className="rounded-lg border border-info/14 bg-info/5 px-3 py-2 text-[11px] leading-5 text-muted-foreground">
                        选择数据集后会从后端报告和文档元数据读取可对比版本；一般选最新版本作为 B，旧版本作为 A。
                      </div>

                      <div className="flex items-center justify-between gap-2 text-[11px]">
                        <span className="text-muted-foreground">
                          {getPipelineCandidatesStatusText(
                            pipelineCandidatesLoading,
                            pipelineCandidatesError,
                            pipelineCandidates.length
                          )}
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[11px] text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                          onClick={() => setAdvancedHashOpen((value) => !value)}
                        >
                          {advancedHashOpen ? '收起手填' : '手动填写'}
                        </Button>
                      </div>

                      <div className="space-y-1.5">
                        <Label
                          htmlFor="pipeline-hash-a"
                          className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"
                        >
                          <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-emerald-50 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-200/60">
                            A
                          </span>
                          <span>快照 A</span>
                        </Label>
                        <select
                          id="pipeline-hash-a"
                          value={pipelineHashA}
                          onChange={(e) => setPipelineHashA(e.target.value)}
                          className="h-10 w-full rounded-lg border border-border/70 bg-card px-3 text-xs font-medium text-foreground shadow-none outline-none transition-colors hover:bg-muted/20 focus:ring-2 focus:ring-primary/20"
                        >
                          <option value="">
                            {pipelineCandidatesLoading ? '正在加载版本…' : '选择旧版本'}
                          </option>
                          {pipelineHashA &&
                          !pipelineCandidates.some((item) => item.hash === pipelineHashA) ? (
                            <option value={pipelineHashA}>
                              手动版本 · {compactHashLabel(pipelineHashA)}
                            </option>
                          ) : null}
                          {pipelineCandidates.map((item) => (
                            <option key={`a:${item.hash}`} value={item.hash}>
                              {item.active ? '当前' : '历史'} · {compactHashLabel(item.hash)} · {item.documents} 文档
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="space-y-1.5">
                        <Label
                          htmlFor="pipeline-hash-b"
                          className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"
                        >
                          <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-sky-50 text-[10px] font-bold text-sky-700 ring-1 ring-sky-200/60">
                            B
                          </span>
                          <span>快照 B</span>
                        </Label>
                        <select
                          id="pipeline-hash-b"
                          value={pipelineHashB}
                          onChange={(e) => setPipelineHashB(e.target.value)}
                          className="h-10 w-full rounded-lg border border-border/70 bg-card px-3 text-xs font-medium text-foreground shadow-none outline-none transition-colors hover:bg-muted/20 focus:ring-2 focus:ring-primary/20"
                        >
                          <option value="">
                            {pipelineCandidatesLoading ? '正在加载版本…' : '选择当前版本'}
                          </option>
                          {pipelineHashB &&
                          !pipelineCandidates.some((item) => item.hash === pipelineHashB) ? (
                            <option value={pipelineHashB}>
                              手动版本 · {compactHashLabel(pipelineHashB)}
                            </option>
                          ) : null}
                          {pipelineCandidates.map((item) => (
                            <option key={`b:${item.hash}`} value={item.hash}>
                              {item.active ? '当前' : '历史'} · {compactHashLabel(item.hash)} · {item.documents} 文档
                            </option>
                          ))}
                        </select>
                      </div>

                      {advancedHashOpen ? (
                        <div className="space-y-2 rounded-lg border border-dashed border-border/70 bg-muted/20 p-2.5">
                          <Input
                            aria-label="手动填写快照 A 哈希"
                            placeholder="手动填写快照 A 哈希"
                            value={pipelineHashA}
                            onChange={(e) => setPipelineHashA(e.target.value)}
                            className={formInputClassName}
                          />
                          <Input
                            aria-label="手动填写快照 B 哈希"
                            placeholder="手动填写快照 B 哈希"
                            value={pipelineHashB}
                            onChange={(e) => setPipelineHashB(e.target.value)}
                            className={formInputClassName}
                          />
                        </div>
                      ) : null}
                    </div>
                  </WorkspaceSection>

                  <WorkspaceSection
                    icon={<Layers className="h-3.5 w-3.5" />}
                    label="作用范围"
                    hint="数据集绑定"
                  >
                    <div className="space-y-1.5">
                      <Label
                        htmlFor="snapshot-dataset"
                        className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"
                      >
                        数据集
                      </Label>
                      <select
                        id="snapshot-dataset"
                        value={selectedDatasetId}
                        onChange={(event) => {
                          setSelectedDatasetId(event.target.value)
                          setPipelineHashA('')
                          setPipelineHashB('')
                          setSnapA(null)
                          setSnapB(null)
                          setDiff(null)
                        }}
                        className="h-10 w-full rounded-lg border border-border/70 bg-card px-3 text-xs font-medium text-foreground shadow-none outline-none transition-colors hover:bg-muted/20 focus:ring-2 focus:ring-primary/20"
                      >
                        <option value="">
                          {datasetsLoading ? '正在加载数据集…' : '全部数据集'}
                        </option>
                        {datasets.map((dataset) => (
                          <option key={dataset.id} value={dataset.id}>
                            {getDatasetLabel(dataset)}
                          </option>
                        ))}
                      </select>
                      <div className="text-[11px] leading-5 text-muted-foreground">
                        {selectedDatasetId
                          ? '后端会按数据集解析可访问文档范围；文档覆盖仅用于排查单文件或子集。'
                          : '全部数据集表示直接请求后端 KG 全局范围，不使用演示数据。'}
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <Label
                        htmlFor="document-ids"
                        className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"
                      >
                        文档覆盖
                      </Label>
                      <Textarea
                        id="document-ids"
                        placeholder="按逗号或换行填写文档编号；留空使用后端按数据集解析的文档范围。"
                        value={documentIdsRaw}
                        onChange={(e) => setDocumentIdsRaw(e.target.value)}
                        rows={4}
                        className={cn(formTextareaClassName, 'min-h-[88px]')}
                      />
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <SnapshotInlineStat
                        icon={<Database className="h-3.5 w-3.5" />}
                        label="数据集"
                        value={selectedDatasetLabel}
                        valueClassName="max-w-[118px] truncate"
                        tone={selectedDatasetId ? 'neutral' : 'muted'}
                      />
                      <SnapshotInlineStat
                        icon={<FolderOpen className="h-3.5 w-3.5" />}
                        label="文档范围"
                        value={
                          documentIds.length
                            ? `${documentIds.length} 覆盖`
                            : scopeDocumentCountLabel
                        }
                        tone={scopeDocumentIds?.length ? 'neutral' : 'muted'}
                      />
                      <SnapshotInlineStat
                        icon={<ShieldCheck className="h-3.5 w-3.5" />}
                        label="模式"
                        value="脱敏"
                        tone="muted"
                      />
                    </div>
                  </WorkspaceSection>
                </div>
              </div>

              <div className="shrink-0 border-t border-border/70 bg-background/95 px-4 py-4 backdrop-blur">
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="outline"
                    className="h-10 gap-1.5 rounded-lg border-border/70 bg-card text-xs font-medium"
                    onClick={() => detachPromise(runExport('a'))}
                    disabled={isRunning}
                  >
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                    导出 A
                  </Button>
                  <Button
                    variant="outline"
                    className="h-10 gap-1.5 rounded-lg border-border/70 bg-card text-xs font-medium"
                    onClick={() => detachPromise(runExport('b'))}
                    disabled={isRunning}
                  >
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                    导出 B
                  </Button>
                </div>

                <Button
                  className="mt-2.5 h-11 w-full gap-2 rounded-xl bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--info)))] text-sm font-semibold text-primary-foreground shadow-md transition-shadow hover:shadow-lg"
                  onClick={() => detachPromise(runCompare())}
                  disabled={isRunning}
                >
                  {isRunning ? (
                    <RefreshCcw
                      className="h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <GitCompare className="h-4 w-4" aria-hidden="true" />
                  )}
                  {isRunning ? '对比中…' : '开始对比'}
                </Button>

                <Button
                  variant="outline"
                  className="mt-2 h-10 w-full gap-1.5 rounded-xl border-border/70 bg-card text-xs font-medium"
                  onClick={() => detachPromise(runBackendCompare())}
                  disabled={isRunning}
                >
                  <ArrowRightLeft className="h-3.5 w-3.5" aria-hidden="true" />
                  后端对比
                </Button>

                <p className="mt-3 text-[11px] leading-5 text-muted-foreground/85">
                  默认请求 bounded 明细：节点、边、属性 hash 都会参与
                  diff；完整溯源仍可结合 KG diagnostics 或 traces 排查。
                </p>
              </div>
            </div>
          </aside>

          <div className="flex min-w-0 flex-1 bg-card">
            <section className="min-w-0 flex-1 bg-card">
              {workspaceTab === 'studio' ? (
                <div className="flex h-full min-h-0 flex-col">
                  <SnapshotStudioToolbar
                    searchValue={studioSearch}
                    nodeType={studioNodeType}
                    relationType={studioRelationType}
                    nodeTypes={nodeTypes}
                    relationTypes={relationTypes}
                    layout={studioLayout}
                    studioView={studioCanvasView}
                    activeSnapshotView={activeView}
                    onSearchChange={setStudioSearch}
                    onNodeTypeChange={setStudioNodeType}
                    onRelationTypeChange={setStudioRelationType}
                    onLayoutChange={setStudioLayout}
                    onStudioViewChange={(value) => {
                      startTransition(() => setStudioCanvasView(value))
                    }}
                    onSnapshotViewChange={(value) => {
                      startTransition(() => {
                        setActiveView(value)
                        setStudioCanvasView('table')
                      })
                    }}
                    onDiffClick={() => {
                      startTransition(() => {
                        setActiveView('diff')
                        setStudioCanvasView('table')
                      })
                      detachPromise(runCompare())
                    }}
                    isRunning={isRunning}
                  />
                  {studioCanvasView === 'graph' ? (
                    <SnapshotGraphCanvas
                      nodes={studioGraph.nodes}
                      links={studioGraph.links}
                      layout={studioLayout}
                      selectedNodeId={selectedStudioNode?.id ?? ''}
                      searchValue={studioSearch}
                      nodeType={studioNodeType}
                      relationType={studioRelationType}
                      nodeCount={studioGraph.nodes.length}
                      relationCount={studioGraph.links.length}
                      isLoading={liveGraphLoading}
                      emptyMessage={
                        liveGraphError ||
                        (selectedDatasetId
                          ? '当前数据集没有返回 KG 节点，请确认文档已完成入库且已开启 KG 抽取。'
                          : '当前后端 KG 图谱接口没有返回节点。')
                      }
                      onSelectNode={setSelectedStudioNodeId}
                    />
                  ) : studioCanvasView === 'stats' ? (
                    <SnapshotAuditPanel
                      deltaRows={deltaRows}
                      typeDriftRows={auditDriftRows}
                      severity={auditSeverity}
                      driftScore={driftScore}
                      includeZeroDeltas={includeZeroDeltas}
                      compactRows={compactAuditRows}
                      onIncludeZeroDeltasChange={setIncludeZeroDeltas}
                      onCompactRowsChange={setCompactAuditRows}
                    />
                  ) : (
                    <Tabs
                      value={activeView}
                      onValueChange={(value) => {
                        startTransition(() =>
                          setActiveView(value as SnapshotView)
                        )
                      }}
                      className="flex h-full min-h-0 flex-col"
                    >
                      <div className="hidden">
                        <div className="px-4 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="min-w-0">
                              <div className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                                <FileJson
                                  className="h-3.5 w-3.5 text-primary/70"
                                  aria-hidden="true"
                                />
                                快照工作台
                              </div>
                              <div className="mt-0.5 truncate text-[15px] font-semibold text-foreground">
                                {tabLabelForView(activeView)}
                              </div>
                            </div>

                            <TabsList className="h-9 gap-1 rounded-xl border border-border/70 bg-card p-1 shadow-sm">
                              <TabsTrigger
                                value="diff"
                                className="inline-flex h-7 items-center gap-1.5 rounded-lg px-3 text-[12px] font-medium text-muted-foreground transition-colors data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-sm hover:text-foreground"
                              >
                                <ArrowRightLeft
                                  className="h-3.5 w-3.5"
                                  aria-hidden="true"
                                />
                                Diff 对比
                              </TabsTrigger>
                              <TabsTrigger
                                value="a"
                                className="inline-flex h-7 items-center gap-1.5 rounded-lg px-3 text-[12px] font-medium text-muted-foreground transition-colors data-[state=active]:bg-emerald-500 data-[state=active]:text-info-foreground data-[state=active]:shadow-sm hover:text-foreground"
                              >
                                <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-emerald-50 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-200/60 data-[state=active]:bg-emerald-700 data-[state=active]:text-info-foreground data-[state=active]:ring-0">
                                  A
                                </span>
                                <span>视图 A</span>
                              </TabsTrigger>
                              <TabsTrigger
                                value="b"
                                className="inline-flex h-7 items-center gap-1.5 rounded-lg px-3 text-[12px] font-medium text-muted-foreground transition-colors data-[state=active]:bg-sky-500 data-[state=active]:text-info-foreground data-[state=active]:shadow-sm hover:text-foreground"
                              >
                                <span className="inline-flex h-4 w-4 items-center justify-center rounded-md bg-sky-50 text-[10px] font-bold text-sky-700 ring-1 ring-sky-200/60 data-[state=active]:bg-sky-700 data-[state=active]:text-info-foreground data-[state=active]:ring-0">
                                  B
                                </span>
                                <span>视图 B</span>
                              </TabsTrigger>
                            </TabsList>
                          </div>

                          <div className="mt-2.5 flex flex-wrap items-center gap-2">
                            {diffDelta.delta ? (
                              deltaRows.map((row) => {
                                const sign = row.delta > 0 ? '+' : ''
                                return (
                                  <SnapshotInlineStat
                                    key={row.key}
                                    label={row.key}
                                    value={`${row.a} → ${row.b} (${sign}${row.delta})`}
                                    tone={inlineStatToneForDelta(row.delta)}
                                  />
                                )
                              })
                            ) : (
                              <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border/70 bg-card/60 px-2.5 py-1 text-[11px] text-muted-foreground">
                                <CircleDashed
                                  className="h-3.5 w-3.5 text-primary/60"
                                  aria-hidden="true"
                                />
                                填写 A / B Hash 后点击「开始对比」即可查看 docs
                                / events / entities / links / relations 增量
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <TabsContent value="diff" className="mt-0 min-h-0 flex-1">
                        <SnapshotDiffView
                          titleA={`Snapshot A · ${hashATitle}`}
                          titleB={`Snapshot B · ${hashBTitle}`}
                          subtitleA={snapshotScopeSubtitle}
                          subtitleB={snapshotScopeSubtitle}
                          leftCode={snapAJson}
                          rightCode={snapBJson}
                          diff={diff}
                          typeDrift={auditDriftRows}
                          isEmpty={!diff}
                          emptyState={
                            <DiffEmptyState
                              title="还没有对比结果"
                              description="填写左侧的快照 A / 快照 B，可以选择文档范围，然后点击「开始对比」生成左右差异与节点/边精确变更。"
                              hint={
                                hasHashA && hasHashB
                                  ? '已就绪：直接点击「开始对比」'
                                  : '提示：A / B Hash 二者皆需填写'
                              }
                            />
                          }
                          onCopy={() =>
                            detachPromise(
                              copyToClipboard(diffJson, 'diff JSON')
                            )
                          }
                          onDownload={() => {
                            downloadJson(
                              diff ?? {},
                              `${diffBaseName}.diff.json`
                            )
                            toast.success('已导出 diff.json')
                          }}
                        />
                      </TabsContent>

                      <TabsContent value="a" className="mt-0 min-h-0 flex-1">
                        <JsonCodePane
                          label="A 视图"
                          title="快照内容"
                          subtitle={
                            hashAValue ? `Hash · ${hashAValue}` : '尚未导出'
                          }
                          code={snapAJson}
                          isEmpty={!snapA}
                          emptyState={
                            <DiffEmptyState
                              title="A 视图为空"
                              description="先在左侧填写快照 A，然后点击「导出 A」即可在此查看明细快照 JSON。"
                              hint={
                                hasHashA
                                  ? '已填写快照 A，可点击「导出 A」'
                                  : '请先填写快照 A'
                              }
                            />
                          }
                          onCopy={() =>
                            detachPromise(
                              copyToClipboard(snapAJson, 'snapshot A JSON')
                            )
                          }
                          onDownload={() => {
                            downloadJson(
                              snapA ?? {},
                              `${snapshotAFileName}.json`
                            )
                            toast.success('已导出 snapshot A')
                          }}
                        />
                      </TabsContent>

                      <TabsContent value="b" className="mt-0 min-h-0 flex-1">
                        <JsonCodePane
                          label="B 视图"
                          title="快照内容"
                          subtitle={
                            hashBValue ? `Hash · ${hashBValue}` : '尚未导出'
                          }
                          code={snapBJson}
                          isEmpty={!snapB}
                          emptyState={
                            <DiffEmptyState
                              title="B 视图为空"
                              description="先在左侧填写快照 B，然后点击「导出 B」即可在此查看明细快照 JSON。"
                              hint={
                                hasHashB
                                  ? '已填写快照 B，可点击「导出 B」'
                                  : '请先填写快照 B'
                              }
                            />
                          }
                          onCopy={() =>
                            detachPromise(
                              copyToClipboard(snapBJson, 'snapshot B JSON')
                            )
                          }
                          onDownload={() => {
                            downloadJson(
                              snapB ?? {},
                              `${snapshotBFileName}.json`
                            )
                            toast.success('已导出 snapshot B')
                          }}
                        />
                      </TabsContent>
                    </Tabs>
                  )}
                </div>
              ) : (
                <SnapshotAuditPanel
                  deltaRows={deltaRows}
                  typeDriftRows={auditDriftRows}
                  severity={auditSeverity}
                  driftScore={driftScore}
                  includeZeroDeltas={includeZeroDeltas}
                  compactRows={compactAuditRows}
                  onIncludeZeroDeltasChange={setIncludeZeroDeltas}
                  onCompactRowsChange={setCompactAuditRows}
                />
              )}
            </section>
            <SnapshotNodeDetailsRail
              selectedNode={selectedStudioNode}
              diffOverview={diffOverview}
            />
          </div>
        </div>
      </div>
    </AppFrame>
  )
}
