'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  AlertCircle,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Download,
  Eye,
  Layers,
  LayoutList,
  MoreHorizontal,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { getDocumentKind } from '@/components/ingestion/monitor-utils'
import { Input } from '@/components/ui/input'
import { SearchInput } from '@/components/ui/search-input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { Document, DocumentPipelineOptions } from '@/types'
import { useDocumentView } from '@/store/document-view'
import { usePathname, useRouter } from '@/i18n/navigation'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

type QuarantineAction = 'release' | 'retry' | 'delete' | 'review' | 'tune'
type ActingState = { id: string; action: QuarantineAction } | null
type ReviewState = 'all' | 'pending' | 'reviewed'

const QUARANTINE_PAGE_SIZE = 6

function getUserMeta(doc: Document): any {
  const meta = doc.metadata
  if (!meta || typeof meta !== 'object') return null
  const user = (meta as any).user
  return user && typeof user === 'object' ? user : null
}

function isReviewed(doc: Document): boolean {
  const user = getUserMeta(doc)
  return Boolean(user?.quarantine_reviewed)
}

function getDropReasons(doc: Document): string[] {
  const reasons = doc.governance?.drop_reasons || {}
  if (!reasons || typeof reasons !== 'object') return []
  return Object.entries(reasons)
    .filter(([, v]) => typeof v === 'number' && v > 0)
    .map(([k]) => k)
    .sort((a, b) => a.localeCompare(b))
}

function extractTuningOverrides(doc: Document): DocumentPipelineOptions {
  const meta = doc.metadata
  if (!meta || typeof meta !== 'object') return {}
  const pipeline = (meta as any).pipeline
  if (!pipeline || typeof pipeline !== 'object') return {}
  const governance = (pipeline).governance
  if (!governance || typeof governance !== 'object') return {}

  const out: DocumentPipelineOptions = {}

  if (typeof governance.drop_outline_only === 'boolean') out.governance_drop_outline_only = governance.drop_outline_only
  if (typeof governance.drop_outline_min_content_chars === 'number') out.governance_drop_outline_min_content_chars = governance.drop_outline_min_content_chars
  if (typeof governance.drop_outline_max_heading_ratio === 'number') out.governance_drop_outline_max_heading_ratio = governance.drop_outline_max_heading_ratio
  if (typeof governance.drop_low_density === 'boolean') out.governance_drop_low_density = governance.drop_low_density
  if (typeof governance.drop_low_density_threshold === 'number') out.governance_drop_low_density_threshold = governance.drop_low_density_threshold
  if (typeof governance.pii_max_hits === 'number') out.governance_pii_max_hits = governance.pii_max_hits
  if (typeof governance.secrets_max_hits === 'number') out.governance_secrets_max_hits = governance.secrets_max_hits
  if (typeof governance.quarantine_on_drop === 'boolean') out.governance_quarantine_on_drop = governance.quarantine_on_drop

  return out
}

function reasonLabel(reason: string): string {
  switch (reason) {
    case 'outline_only':
      return '大纲文档'
    case 'low_density':
      return '低密度文本'
    case 'empty_document':
      return '空文档'
    case 'pii_exceeded':
      return 'PII 超阈值'
    case 'secrets_exceeded':
      return 'Secrets 超阈值'
    default:
      return reason
  }
}

function buildReviewAdvice(doc: Document): string[] {
  const reasons = new Set(getDropReasons(doc))
  const advice: string[] = []

  if (reasons.has('outline_only')) advice.push('如果正文有效但被判定为大纲文档，可关闭 outline_only 过滤后重试。')
  if (reasons.has('low_density')) advice.push('如果文本主要由表格或短句构成，可放宽 low_density 阈值后重新入库。')
  if (reasons.has('pii_exceeded')) advice.push('确认是否包含真实敏感信息；若仅为误报，建议先抽样预览再决定放行。')
  if (reasons.has('secrets_exceeded')) advice.push('优先确认命中的内容是否为真实密钥或凭证，再执行放行。')
  if (!advice.length) advice.push('先查看命中规则与原文片段，再决定放行、重试或删除。')

  return advice
}

function createReviewMetadataPatch(extra?: Record<string, any>): Record<string, any> {
  const patch: Record<string, any> = {
    quarantine_reviewed: true,
    quarantine_reviewed_at: new Date().toISOString(),
  }

  if (extra) Object.assign(patch, extra)

  return patch
}

function getBusyIconClassName(acting: ActingState, docId: string, action: QuarantineAction): string {
  return cn(
    'h-4 w-4 mr-1',
    acting?.id === docId && acting.action === action ? 'animate-spin motion-reduce:animate-none' : ''
  )
}

function downloadTextFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function makeDemoQuarantineDocument(
  id: number,
  overrides: Partial<Document> & { filename: string; file_type: string }
): Document {
  const createdAt = new Date(Date.UTC(2026, 2, 31, 3, 0, 0) - id * 36 * 60_000).toISOString()
  const updatedAt = new Date(Date.UTC(2026, 2, 31, 11, 45, 0) - id * 22 * 60_000).toISOString()
  const { filename, file_type: fileType, ...restOverrides } = overrides

  return {
    id: `demo-q-${id.toString().padStart(4, '0')}`,
    tenant_id: 'demo-tenant',
    dataset_id: 'dataset-demo',
    filename,
    status: 'quarantined',
    file_type: fileType,
    file_size: 1_240_000,
    chunk_count: 0,
    processing_progress: 0,
    created_at: createdAt,
    updated_at: updatedAt,
    processed_at: updatedAt,
    current_stage: 'governance',
    error_message: '命中治理规则，待人工复核',
    metadata: {},
    governance: {
      drop_reasons: {},
    },
    ...restOverrides,
  } as Document
}

function buildDemoQuarantineDocuments(): Document[] {
  const leadRows: Document[] = [
    makeDemoQuarantineDocument(1, {
      filename: '用户协议.pdf',
      file_type: 'pdf',
      file_size: 1.24 * 1024 * 1024,
      dataset_id: '文档解析',
      governance: { drop_reasons: { pii_exceeded: 1 } } as any,
      error_message: '包含手机号、身份证号等敏感信息',
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(2, {
      filename: '财务报表.xlsx',
      file_type: 'xlsx',
      file_size: 2.81 * 1024 * 1024,
      dataset_id: '数据导入',
      governance: { drop_reasons: { outline_only: 1 } } as any,
      error_message: '包含未公开财务数据',
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(3, {
      filename: '内部沟通记录.docx',
      file_type: 'docx',
      file_size: 860 * 1024,
      dataset_id: '文档解析',
      governance: { drop_reasons: { pii_exceeded: 1 } } as any,
      error_message: '包含内部人事及组织结构信息',
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(4, {
      filename: '会议纪要.pdf',
      file_type: 'pdf',
      file_size: 1.09 * 1024 * 1024,
      dataset_id: '文档解析',
      governance: { drop_reasons: { low_density: 1 } } as any,
      error_message: '包含手机号、身份证号等敏感信息',
      metadata: { user: { quarantine_reviewed: true } } as any,
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(5, {
      filename: '产品蓝图.pptx',
      file_type: 'pptx',
      file_size: 3.45 * 1024 * 1024,
      dataset_id: '数据导入',
      governance: { drop_reasons: { outline_only: 1 } } as any,
      error_message: '包含未公开产品规划',
      metadata: { user: { quarantine_reviewed: true } } as any,
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(6, {
      filename: '客户名单.csv',
      file_type: 'csv',
      file_size: 680 * 1024,
      dataset_id: 'API 接入',
      governance: { drop_reasons: { pii_exceeded: 1 } } as any,
      error_message: '包含个人隐私信息',
      metadata: { user: { quarantine_reviewed: true } } as any,
      status: 'completed',
    }),
  ]

  const reasons = [
    { key: 'pii_exceeded', filename: '员工信息名录', fileType: 'docx', source: '文档解析', error: '包含手机号、身份证号等敏感信息' },
    { key: 'outline_only', filename: '项目大纲', fileType: 'pptx', source: '数据导入', error: '包含未公开产品规划' },
    { key: 'low_density', filename: '扫描件归档', fileType: 'pdf', source: '文档解析', error: '正文密度过低，建议人工复核' },
    { key: 'secrets_exceeded', filename: '环境变量清单', fileType: 'csv', source: 'API 接入', error: '疑似命中 token / secret' },
  ] as const

  const extraRows = Array.from({ length: 242 }, (_, index) => {
    const bucket = reasons[index % reasons.length]
    const reviewed = index >= 23 && index < 179
    const status = reviewed ? 'completed' : index < 23 ? 'quarantined' : 'cancelled'
    const suffix = `${String(index + 7).padStart(3, '0')}`
    return makeDemoQuarantineDocument(index + 7, {
      filename: `${bucket.filename}_${suffix}.${bucket.fileType}`,
      file_type: bucket.fileType,
      file_size: (0.68 + (index % 7) * 0.42) * 1024 * 1024,
      dataset_id: bucket.source,
      governance: { drop_reasons: { [bucket.key]: 1 } } as any,
      error_message: bucket.error,
      metadata: reviewed ? ({ user: { quarantine_reviewed: true } } as any) : {},
      status,
    })
  })

  return [...leadRows, ...extraRows]
}

type QuarantineSeverity = '高' | '中' | '低'

function getQuarantineSource(doc: Document): string {
  const kind = getDocumentKind(doc.filename)
  if (kind === 'pdf' || kind === 'markdown' || kind === 'html' || String(doc.file_type || '').toLowerCase() === 'docx') {
    return '文档解析'
  }
  if (kind === 'spreadsheet') return '数据导入'
  if (String(doc.dataset_id || '').toLowerCase().includes('api')) return 'API 接入'
  return '其他'
}

function getQuarantineSeverity(doc: Document): QuarantineSeverity {
  const reasons = new Set(getDropReasons(doc))
  const error = String(doc.error_message || '').toLowerCase()
  if (
    reasons.has('pii_exceeded') ||
    reasons.has('secrets_exceeded') ||
    error.includes('pii') ||
    error.includes('secret') ||
    error.includes('password')
  ) {
    return '高'
  }
  if (reasons.has('low_density') || reasons.has('outline_only') || doc.status === 'quarantined') {
    return '中'
  }
  return '低'
}

function getSeverityClassName(severity: QuarantineSeverity): string {
  switch (severity) {
    case '高':
      return 'text-red-600'
    case '中':
      return 'text-amber-600'
    case '低':
    default:
      return 'text-emerald-600'
  }
}

function getSeverityBarClassName(severity: QuarantineSeverity): string {
  switch (severity) {
    case '高':
      return 'bg-red-400'
    case '中':
      return 'bg-amber-400'
    case '低':
    default:
      return 'bg-emerald-400'
  }
}

function buildConicGradient(values: number[], colors: string[]): string {
  const total = values.reduce((sum, value) => sum + value, 0)
  if (!total) return 'conic-gradient(rgba(148,163,184,0.18) 0deg 360deg)'

  let current = 0
  const stops = values.map((value, index) => {
    const start = current
    const end = current + (value / total) * 360
    current = end
    return `${colors[index]} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`
  })
  return `conic-gradient(${stops.join(', ')})`
}

const TYPO_EYEBROW = 'text-[0.68rem] font-medium uppercase tracking-[0.24em] text-muted-foreground/64'
const TYPO_SECTION_TITLE = 'text-[0.98rem] font-medium tracking-[-0.015em] leading-[1.2] text-foreground/90'
const TYPO_ITEM_TITLE = 'text-[0.88rem] font-medium tracking-[-0.005em] leading-[1.3] text-foreground/92'
const TYPO_META = 'font-code tabular-nums text-[0.7rem] font-normal tracking-[0.01em] text-muted-foreground/62'

function FileKindGlyph({
  kind,
  className,
}: Readonly<{ kind: ReturnType<typeof getDocumentKind>; className?: string }>) {
  if (kind === 'pdf') {
    return (
      <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
        <path d="M7 3.5h7l4 4V20.5H7z" fill="currentColor" opacity="0.18" />
        <path d="M14 3.5v4h4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M8.5 15.5h7" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M8.5 18h5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }

  if (kind === 'markdown') {
    return (
      <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
        <rect x="5" y="5" width="14" height="14" rx="3" fill="currentColor" opacity="0.12" />
        <path d="M8 16V9l2.5 3 2.5-3v7" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M15.5 10.5v4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="m14 13 1.5 1.5L17 13" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }

  if (kind === 'spreadsheet') {
    return (
      <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
        <rect x="5" y="4.5" width="14" height="15" rx="2.5" fill="currentColor" opacity="0.12" />
        <path d="M5 9.5h14M10 4.5v15M14.5 9.5v10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }

  if (kind === 'html') {
    return (
      <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
        <path d="m8.5 8.5-3 3 3 3M15.5 8.5l3 3-3 3M13.5 7l-3 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
      <rect x="6" y="4.5" width="12" height="15" rx="2.5" fill="currentColor" opacity="0.12" />
      <path d="M9 9h6M9 12.5h6M9 16h4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function SummaryStatCard({
  label,
  value,
  hint,
  icon: Icon,
  delta,
  tone = 'neutral',
}: Readonly<{
  label: string
  value: string | number
  hint: string
  icon: LucideIcon
  delta?: { value: string; tone: 'up' | 'down' | 'neutral' }
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}>) {
  return (
    <div
      className={cn(
        'relative flex h-full min-h-[82px] flex-col justify-between overflow-hidden rounded-[1.1rem] border bg-card px-3 py-1.5 shadow-[0_14px_30px_-30px_rgba(15,23,42,0.12)]',
        tone === 'neutral' && 'border-border/60',
        tone === 'success' && 'border-emerald-500/10',
        tone === 'warning' && 'border-amber-500/10',
        tone === 'danger' && 'border-red-500/10',
        tone === 'info' && 'border-sky-500/10'
      )}
    >
      <div
        className={cn(
          'pointer-events-none absolute inset-x-0 top-0 h-12 opacity-80',
          tone === 'neutral' && 'bg-[radial-gradient(circle_at_top_right,rgba(59,130,246,0.12),transparent_56%)]',
          tone === 'success' && 'bg-[radial-gradient(circle_at_top_right,rgba(16,185,129,0.12),transparent_56%)]',
          tone === 'warning' && 'bg-[radial-gradient(circle_at_top_right,rgba(249,115,22,0.14),transparent_56%)]',
          tone === 'danger' && 'bg-[radial-gradient(circle_at_top_right,rgba(239,68,68,0.12),transparent_56%)]',
          tone === 'info' && 'bg-[radial-gradient(circle_at_top_right,rgba(99,102,241,0.12),transparent_56%)]'
        )}
      />
      <div className="relative flex items-start justify-between gap-4">
        <div className="space-y-0.5">
          <div className="text-[8px] font-semibold tracking-wide text-muted-foreground">{label}</div>
          <div className="text-[1.2rem] font-semibold leading-none tracking-[-0.05em] text-foreground">{value}</div>
        </div>
        <div
          className={cn(
            'flex size-6.5 shrink-0 items-center justify-center rounded-[0.8rem] border',
            tone === 'neutral' && 'border-sky-500/10 bg-sky-500/10 text-sky-600',
            tone === 'success' && 'border-emerald-500/10 bg-emerald-500/10 text-emerald-600',
            tone === 'warning' && 'border-amber-500/10 bg-amber-500/10 text-amber-600',
            tone === 'danger' && 'border-red-500/10 bg-red-500/10 text-red-600',
            tone === 'info' && 'border-indigo-500/10 bg-indigo-500/10 text-indigo-600'
          )}
        >
          <Icon className="size-3" />
        </div>
      </div>

      <div className="relative mt-1.5 flex items-end justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[7px] text-muted-foreground">{hint}</div>
          {delta ? (
            <div
              className={cn(
                'mt-0.5 text-[7px] font-semibold',
                delta.tone === 'up' && 'text-red-500',
                delta.tone === 'down' && 'text-emerald-500',
                delta.tone === 'neutral' && 'text-muted-foreground'
              )}
            >
              {delta.value}
            </div>
          ) : null}
        </div>
        <div className="flex items-end gap-0.5 opacity-75">
          {[0.35, 0.52, 0.46, 0.7, 0.4, 0.58].map((height, index) => (
            <span
              key={`${label}-${index}`}
              className={cn(
                'w-1 rounded-full',
                tone === 'neutral' && 'bg-sky-400/60',
                tone === 'success' && 'bg-emerald-400/60',
                tone === 'warning' && 'bg-amber-400/70',
                tone === 'danger' && 'bg-red-400/65',
                tone === 'info' && 'bg-indigo-400/60'
              )}
              style={{ height: `${4 + height * 7}px` }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function DonutSummaryCard({
  title,
  subtitle,
  items,
  colors,
}: Readonly<{
  title: string
  subtitle?: string
  items: Array<{ label: string; value: number; hint?: string }>
  colors: string[]
}>) {
  const values = items.map((item) => item.value)
  const gradient = buildConicGradient(values, colors)
  const total = values.reduce((sum, value) => sum + value, 0)

  return (
    <div className="h-full min-h-[178px] rounded-[1.2rem] border border-border/60 bg-background/88 p-3.5 shadow-[0_14px_30px_-30px_rgba(15,23,42,0.12)]">
      <div className="text-[10px] font-semibold text-foreground">{title}</div>
      {subtitle ? <div className="mt-0.5 text-[8px] text-muted-foreground">{subtitle}</div> : null}
      <div className="mt-2.5 grid gap-3 md:grid-cols-[88px_minmax(0,1fr)] md:items-center">
        <div className="flex items-center justify-center">
          <div className="relative h-[72px] w-[72px] rounded-full" style={{ backgroundImage: gradient }}>
            <div className="absolute inset-[13px] rounded-full bg-background" />
          </div>
        </div>
        <div className="space-y-1">
          {items.map((item, index) => (
            <div key={item.label} className="flex items-center justify-between gap-3 text-[9px]">
              <div className="flex items-center gap-2 text-muted-foreground">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colors[index] }} />
                <span>{item.label}</span>
              </div>
              <div className="text-right">
                <span className="font-mono text-[9px] text-foreground">{item.value}</span>
                {item.hint ? <span className="ml-1 text-muted-foreground">{item.hint}</span> : null}
                {!item.hint && total > 0 ? (
                  <span className="ml-1 text-muted-foreground">({((item.value / total) * 100).toFixed(1)}%)</span>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function QuickActionCard({
  title,
  description,
  icon: Icon,
  onClick,
}: Readonly<{ title: string; description: string; icon: LucideIcon; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-start gap-2.5 rounded-[0.9rem] border border-border/60 bg-background/80 px-3 py-2.5 text-left transition-colors hover:bg-muted/30"
    >
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-[0.9rem] border border-border/50 bg-muted/30 text-muted-foreground">
        <Icon className="size-[13px]" />
      </span>
      <span className="min-w-0">
        <span className="block text-[11px] font-semibold text-foreground">{title}</span>
        <span className="mt-0.5 block text-[9px] leading-4 text-muted-foreground">{description}</span>
      </span>
    </button>
  )
}

function StatusPill({ status }: Readonly<{ status: Document['status'] }>) {
  const label =
    status === 'completed'
      ? '已解决'
      : status === 'failed'
        ? '失败'
        : status === 'quarantined'
          ? '待审核'
          : status === 'pending'
            ? '待处理'
            : status === 'processing'
              ? '处理中'
              : '已取消'

  return (
    <span className={cn(
      'inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold',
      status === 'completed' && 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
      status === 'failed' && 'border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-300',
      status === 'quarantined' && 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300',
      status === 'pending' && 'border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300',
      status === 'processing' && 'border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300',
      status === 'cancelled' && 'border-border/60 bg-muted/60 text-muted-foreground',
    )}>
      {label}
    </span>
  )
}

function QuarantineEmptyState({
  hasActiveFilters,
  autoRefresh,
  isFetching,
  onResetFilters,
  onRefresh,
}: Readonly<{
  hasActiveFilters: boolean
  autoRefresh: boolean
  isFetching: boolean
  onResetFilters: () => void
  onRefresh: () => void
}>) {
  return (
    <div className="flex min-h-[13rem] flex-col items-center justify-center px-6 py-8 text-center">
      <div className="relative mb-4">
        <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle,rgba(59,130,246,0.14),transparent_58%)] blur-2xl" />
        <div className="relative flex size-14 items-center justify-center rounded-[1.15rem] border border-border/60 bg-background shadow-sm">
          <Search className="size-6 text-muted-foreground/60" />
        </div>
      </div>

      <div className="text-[1.05rem] font-semibold tracking-[-0.03em] text-foreground">
        {hasActiveFilters ? '当前筛选条件下暂无隔离记录' : '当前没有待审隔离样本'}
      </div>
      <p className="mt-2 max-w-md text-[12px] leading-5 text-muted-foreground">
        {hasActiveFilters
          ? '尝试调整筛选条件，或手动同步最新数据后重新检查。'
          : '隔离队列目前为空。保持自动刷新开启即可在有新样本进入时即时看到。'}
      </p>

      <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
        <Button
          type="button"
          variant="outline"
          className="h-9 rounded-xl border-border/60 bg-background px-4 text-[12px]"
          onClick={onResetFilters}
        >
          <RotateCcw className="size-4" />
          重置筛选
        </Button>
        <Button
          type="button"
          className="h-9 rounded-xl bg-amber-500 px-4 text-[12px] text-white hover:bg-amber-400"
          onClick={onRefresh}
        >
          <RefreshCw className={cn('size-4', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
          同步数据
        </Button>
      </div>

      <div className="mt-3 text-[11px] text-muted-foreground">
        {autoRefresh ? '自动刷新已开启，每 5 秒轮询一次。' : '自动刷新已关闭，仅手动同步。'}
      </div>
    </div>
  )
}

interface QuarantineDetailPanelProps {
  selected: Document | null
}

function QuarantineDetailPanel({ selected }: Readonly<QuarantineDetailPanelProps>) {
  if (!selected) return null

  return (
    <div className="space-y-6">
      <div className="min-w-0">
        <div className={TYPO_EYEBROW}>Audit Abstract</div>
        <div className="mt-2 grid grid-cols-2 gap-3 rounded-xl border border-border/40 bg-card/40 p-4">
          {[
            { label: '文档 ID', value: selected.id.slice(0, 12) + '...' },
            { label: '数据集', value: selected.dataset_id || '-' },
            { label: '文件体积', value: formatFileSize(selected.file_size) },
            { label: '切片数量', value: String(selected.chunk_count ?? 0) },
          ].map((item) => (
            <div key={item.label} className="space-y-1">
              <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/60">{item.label}</div>
              <div className="break-words text-xs font-mono font-bold text-foreground/90">{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      {selected.error_message && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-amber-600">隔离原因 / RISKS</div>
          <div className="mt-2 break-words text-xs font-mono leading-relaxed text-amber-900/80 dark:text-amber-200/80">
            {selected.error_message}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-border/40 bg-card/40 p-4">
        <div className={TYPO_EYEBROW}>处置建议 / ADVICE</div>
        <div className="mt-3 space-y-3">
          {buildReviewAdvice(selected).map((tip) => (
            <div key={tip} className="flex items-start gap-3 text-[13px] font-medium text-foreground/80 leading-relaxed">
              <div className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.5)]" />
              <div>{tip}</div>
            </div>
          ))}
        </div>
      </div>

      {getDropReasons(selected).length > 0 ? (
        <div className="rounded-xl border border-border/40 bg-muted/30 p-4">
          <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">命中规则 / RULES</div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {getDropReasons(selected).map((reason) => (
              <Badge
                key={reason}
                variant="secondary"
                className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-amber-700 dark:text-amber-300"
              >
                {reasonLabel(reason)}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

interface QuarantineReviewDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  selected: Document | null
  acting: ActingState
  onRelease: (doc: Document) => void
  onRetry: (doc: Document) => void
  onTune: (doc: Document) => void
  onPreview: (docId: string) => void
  onShowDetails: (docId: string) => void
  onMarkReviewed: (doc: Document) => void
  onDelete: (doc: Document) => void
}

function QuarantineReviewDrawer({
  open,
  onOpenChange,
  selected,
  acting,
  onRelease,
  onRetry,
  onTune,
  onPreview,
  onShowDetails,
  onMarkReviewed,
  onDelete,
}: Readonly<QuarantineReviewDrawerProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-auto right-0 top-0 h-dvh w-[min(520px,100vw)] max-w-[520px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden border-l border-border/60 bg-background/95 shadow-2xl backdrop-blur-xl">
        <DialogHeader className="sr-only">
          <DialogTitle>{selected?.filename || '隔离记录审核'}</DialogTitle>
          <DialogDescription>{selected?.id || ''}</DialogDescription>
        </DialogHeader>

        <div className="flex h-full min-h-0 flex-col">
          <div className="border-b border-border/40 bg-card/30 px-6 py-6 backdrop-blur-sm">
            <div className="flex items-start justify-between gap-3 pr-8">
              <div className="min-w-0">
                <div className={TYPO_EYEBROW}>Audit Inspection</div>
                <div className="mt-1.5 truncate text-xl font-black tracking-tight text-foreground">{selected?.filename || '未选择记录'}</div>
                {selected ? (
                  <div className="mt-1 flex items-center gap-2">
                    <span className="font-mono text-[10px] font-black uppercase text-muted-foreground/30">{selected.id}</span>
                    <div className="h-1 w-1 rounded-full bg-border" />
                    <span className="font-mono text-[10px] font-medium text-muted-foreground/50">{formatDate(selected.updated_at)}</span>
                  </div>
                ) : null}
              </div>
              {selected ? (
                <div className="shrink-0 pt-1">
                  <StatusPill status={isReviewed(selected) ? 'completed' : 'quarantined'} />
                </div>
              ) : null}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar">
            <div className="p-6">
              <QuarantineDetailPanel selected={selected} />
            </div>
          </div>

          {selected ? (
            <div className="border-t border-border/40 bg-card/50 p-6 backdrop-blur-md">
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    size="sm"
                    className="h-10 rounded-xl bg-amber-600 font-bold text-white shadow-sm hover:bg-amber-500"
                    disabled={acting?.id === selected.id}
                    onClick={() => onRelease(selected)}
                  >
                    <RotateCcw className={getBusyIconClassName(acting, selected.id, 'release')} />
                    放行并重试
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-10 rounded-xl border-border/40 bg-background/50 font-bold"
                    disabled={acting?.id === selected.id}
                    onClick={() => onRetry(selected)}
                  >
                    <RefreshCw className={getBusyIconClassName(acting, selected.id, 'retry')} />
                    直接重试
                  </Button>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-9 rounded-xl text-xs font-bold"
                    disabled={acting?.id === selected.id}
                    onClick={() => onTune(selected)}
                  >
                    <Settings2 className="mr-1.5 size-3.5" />
                    调参
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-9 rounded-xl text-xs font-bold"
                    disabled={acting?.id === selected.id}
                    onClick={() => onPreview(selected.id)}
                  >
                    <Eye className="mr-1.5 size-3.5" />
                    预览
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-9 rounded-xl text-xs font-bold"
                    onClick={() => onShowDetails(selected.id)}
                  >
                    <Layers className="mr-1.5 size-3.5" />
                    任务
                  </Button>
                </div>

                <div className="h-px w-full bg-border/40" />

                <div className="flex items-center justify-between gap-3">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-9 flex-1 rounded-xl border-emerald-500/20 bg-emerald-500/5 text-[11px] font-black text-emerald-600 hover:bg-emerald-500/10"
                    disabled={acting?.id === selected.id || isReviewed(selected)}
                    onClick={() => onMarkReviewed(selected)}
                  >
                    <CheckCircle2 className={getBusyIconClassName(acting, selected.id, 'review')} />
                    标记为已解决
                  </Button>

                  <ConfirmDialog
                    title="确定物理删除？"
                    description="此操作不可恢复，文档记录将从数据库中移除。"
                    confirmLabel="物理删除"
                    cancelLabel="取消"
                    confirmVariant="destructive"
                    onConfirm={() => onDelete(selected)}
                  >
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-9 w-9 p-0 rounded-xl text-red-500/50 hover:bg-red-500/10 hover:text-red-600"
                      disabled={acting?.id === selected.id}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </ConfirmDialog>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function QuarantineQueuePage() {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const demoMode = searchParams.get('demo') === '1'
  const { openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedReason, setSelectedReason] = useState('all')
  const [selectedDataset, setSelectedDataset] = useState('all')
  const [selectedSource, setSelectedSource] = useState('all')
  const [selectedSeverity, setSelectedSeverity] = useState('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [reviewState, setReviewState] = useState<'all' | 'pending' | 'reviewed'>('all')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false)
  const [acting, setActing] = useState<ActingState>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)

  const [tuneOpen, setTuneOpen] = useState(false)
  const [tuneTarget, setTuneTarget] = useState<Document | null>(null)
  const [tunePatch, setTunePatch] = useState<DocumentPipelineOptions>({})

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['quarantine-documents'],
    queryFn: ({ signal }) =>
      documentApi.list(
        {
          limit: 200,
          status: 'quarantined',
        },
        { signal }
      ),
    staleTime: 3_000,
    enabled: !demoMode,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const documents = useMemo(() => (demoMode ? buildDemoQuarantineDocuments() : data?.items || []), [data, demoMode])

  const reasonCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const doc of documents) {
      const keys = getDropReasons(doc)
      for (const key of keys) {
        counts[key] = (counts[key] || 0) + 1
      }
    }
    return counts
  }, [documents])

  const sortedReasons = useMemo(() => {
    return Object.entries(reasonCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([reason]) => reason)
  }, [reasonCounts])

  const datasetOptions = useMemo(
    () =>
      Array.from(
        new Set(documents.map((doc) => doc.dataset_id).filter((value): value is string => Boolean(value)))
      ).sort((a, b) => a.localeCompare(b)),
    [documents]
  )

  const sourceOptions = useMemo(
    () =>
      Array.from(new Set(documents.map((doc) => getQuarantineSource(doc))))
        .sort((a, b) => a.localeCompare(b)),
    [documents]
  )

  const severityCounts = useMemo(() => {
    return documents.reduce<Record<QuarantineSeverity, number>>(
      (acc, doc) => {
        const severity = getQuarantineSeverity(doc)
        acc[severity] += 1
        return acc
      },
      { 高: 0, 中: 0, 低: 0 }
    )
  }, [documents])

  const sourceCounts = useMemo(() => {
    return documents.reduce<Record<string, number>>((acc, doc) => {
      const source = getQuarantineSource(doc)
      acc[source] = (acc[source] || 0) + 1
      return acc
    }, {})
  }, [documents])

  const stats = useMemo(() => {
    const total = documents.length
    const reviewed = documents.filter(isReviewed).length
    const highRisk = documents.filter((doc) => getQuarantineSeverity(doc) === '高').length
    return {
      total,
      reviewed,
      unreviewed: Math.max(0, total - reviewed),
      highRisk,
    }
  }, [documents])

  const reasonTopItems = useMemo(
    () =>
      Object.entries(reasonCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([reason, count]) => ({
          label: `R${Math.max(1, sortedReasons.indexOf(reason) + 1)} ${reasonLabel(reason)}`,
          value: count,
          hint: documents.length ? `(${((count / documents.length) * 100).toFixed(1)}%)` : '(0%)',
        })),
    [documents.length, reasonCounts, sortedReasons]
  )

  const severityItems = useMemo(
    () => [
      { label: '高', value: severityCounts['高'] },
      { label: '中', value: severityCounts['中'] },
      { label: '低', value: severityCounts['低'] },
    ],
    [severityCounts]
  )

  const sourceItems = useMemo(
    () =>
      Object.entries(sourceCounts)
        .sort((a, b) => b[1] - a[1])
        .map(([label, value]) => ({ label, value })),
    [sourceCounts]
  )

  const filtered = useMemo(() => {
    let out = documents
    if (reviewState === 'pending') out = out.filter((d) => !isReviewed(d))
    if (reviewState === 'reviewed') out = out.filter((d) => isReviewed(d))
    if (selectedReason !== 'all') out = out.filter((d) => getDropReasons(d).includes(selectedReason))
    if (selectedDataset !== 'all') out = out.filter((d) => d.dataset_id === selectedDataset)
    if (selectedSource !== 'all') out = out.filter((d) => getQuarantineSource(d) === selectedSource)
    if (selectedSeverity !== 'all') out = out.filter((d) => getQuarantineSeverity(d) === selectedSeverity)
    if (dateFrom) out = out.filter((d) => new Date(String(d.updated_at || d.created_at || '')).getTime() >= new Date(`${dateFrom}T00:00:00`).getTime())
    if (dateTo) out = out.filter((d) => new Date(String(d.updated_at || d.created_at || '')).getTime() <= new Date(`${dateTo}T23:59:59`).getTime())

    const q = search.trim().toLowerCase()
    if (q) {
      out = out.filter((d) => {
        const filename = (d.filename || '').toLowerCase()
        const id = d.id.toLowerCase()
        const dataset = (d.dataset_id || '').toLowerCase()
        const source = getQuarantineSource(d).toLowerCase()
        const severity = getQuarantineSeverity(d).toLowerCase()
        const reasons = getDropReasons(d)
          .flatMap((reason) => [reason, reasonLabel(reason)])
          .join(' ')
          .toLowerCase()

        return filename.includes(q) || id.includes(q) || dataset.includes(q) || reasons.includes(q) || source.includes(q) || severity.includes(q)
      })
    }

    return out
  }, [dateFrom, dateTo, documents, reviewState, search, selectedDataset, selectedReason, selectedSeverity, selectedSource])

  const listSummary = useMemo(() => {
    if (!documents.length) return null

    const hasSearch = search.trim().length > 0
    const hasReasonFilter = selectedReason !== 'all'
    const hasDatasetFilter = selectedDataset !== 'all'
    const hasSourceFilter = selectedSource !== 'all'
    const hasSeverityFilter = selectedSeverity !== 'all'
    const hasReviewFilter = reviewState !== 'all'
    const hasDateFilter = Boolean(dateFrom || dateTo)

    if (hasSearch || hasReasonFilter || hasDatasetFilter || hasSourceFilter || hasSeverityFilter || hasReviewFilter || hasDateFilter) {
      return `筛出 ${filtered.length} / ${documents.length}`
    }

    return `共 ${filtered.length} 条`
  }, [dateFrom, dateTo, documents.length, filtered.length, reviewState, search, selectedDataset, selectedReason, selectedSeverity, selectedSource])

  const hasActiveFilters =
    Boolean(search.trim()) ||
    selectedReason !== 'all' ||
    selectedDataset !== 'all' ||
    selectedSource !== 'all' ||
    selectedSeverity !== 'all' ||
    reviewState !== 'all' ||
    Boolean(dateFrom || dateTo)

  const totalPages = useMemo(() => Math.max(1, Math.ceil(filtered.length / QUARANTINE_PAGE_SIZE)), [filtered.length])
  const paginated = useMemo(
    () => filtered.slice((page - 1) * QUARANTINE_PAGE_SIZE, page * QUARANTINE_PAGE_SIZE),
    [filtered, page]
  )

  const selected = useMemo(() => {
    if (!selectedId) return null
    return documents.find((d) => d.id === selectedId) || null
  }, [documents, selectedId])

  useEffect(() => {
    if (!selectedId) return
    if (documents.some((doc) => doc.id === selectedId)) return
    setSelectedId(null)
    setReviewDrawerOpen(false)
  }, [documents, selectedId])

  useEffect(() => {
    if (!filtered.length && reviewDrawerOpen) {
      setSelectedId(null)
      setReviewDrawerOpen(false)
    }
  }, [filtered, reviewDrawerOpen])

  useEffect(() => {
    setPage(1)
  }, [search, selectedReason, selectedDataset, selectedSource, selectedSeverity, dateFrom, dateTo, reviewState])

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const resetFilters = useCallback(() => {
    setSearch('')
    setSelectedReason('all')
    setSelectedDataset('all')
    setSelectedSource('all')
    setSelectedSeverity('all')
    setDateFrom('')
    setDateTo('')
    setReviewState('all')
  }, [])

  const markReviewed = useCallback(async (docId: string, extra?: Record<string, any>) => {
    const patch = createReviewMetadataPatch(extra)
    await documentApi.patchUserMetadata(docId, { patch, replace: false })
  }, [])

  const buildRecommendedPatch = useCallback((doc: Document): DocumentPipelineOptions => {
    const reasons = new Set(getDropReasons(doc))
    const patch: DocumentPipelineOptions = {}
    if (reasons.has('outline_only')) patch.governance_drop_outline_only = false
    if (reasons.has('low_density')) patch.governance_drop_low_density = false
    return patch
  }, [])

  const handleRetry = useCallback(async (doc: Document) => {
    if (demoMode) {
      toast.success('Demo 模式仅用于预览布局，不执行真实重试')
      return
    }
    setActing({ id: doc.id, action: 'retry' })
    try {
      await documentApi.retry(doc.id)
      await markReviewed(doc.id, { quarantine_action: 'retry' })
      toast.success('已触发重新入库')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '重试失败'))
    } finally {
      setActing(null)
    }
  }, [demoMode, markReviewed, refetch])

  const handleRelease = useCallback(async (doc: Document) => {
    if (demoMode) {
      toast.success('Demo 模式仅用于预览布局，不执行真实放行')
      return
    }
    setActing({ id: doc.id, action: 'release' })
    try {
      const patch = buildRecommendedPatch(doc)
      if (Object.keys(patch).length) {
        await documentApi.patchPipeline(doc.id, { patch, replace: false })
      }
      await documentApi.retry(doc.id)
      await markReviewed(doc.id, { quarantine_action: 'release_retry', quarantine_reason: getDropReasons(doc).join(',') })
      toast.success('已放行并重试')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '放行失败'))
    } finally {
      setActing(null)
    }
  }, [buildRecommendedPatch, demoMode, markReviewed, refetch])

  const handleDelete = useCallback(async (doc: Document) => {
    if (demoMode) {
      toast.success('Demo 模式仅用于预览布局，不执行真实删除')
      return
    }
    setActing({ id: doc.id, action: 'delete' })
    try {
      await documentApi.delete(doc.id)
      toast.success('已删除文档')
      if (selectedId === doc.id) {
        setSelectedId(null)
        setReviewDrawerOpen(false)
      }
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '删除失败'))
    } finally {
      setActing(null)
    }
  }, [demoMode, refetch, selectedId])

  const handleMarkReviewedOnly = useCallback(async (doc: Document) => {
    if (demoMode) {
      toast.success('Demo 模式仅用于预览布局，不写入真实审核状态')
      return
    }
    setActing({ id: doc.id, action: 'review' })
    try {
      await markReviewed(doc.id, { quarantine_action: 'reviewed' })
      toast.success('已标记为已处理')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '标记失败'))
    } finally {
      setActing(null)
    }
  }, [demoMode, markReviewed, refetch])

  const openTuneDialog = useCallback((doc: Document) => {
    const current = extractTuningOverrides(doc)
    const recommended = buildRecommendedPatch(doc)
    setTuneTarget(doc)
    setTunePatch({ ...current, ...recommended })
    setTuneOpen(true)
  }, [buildRecommendedPatch])

  const saveTune = useCallback(async (opts: { retryAfterSave: boolean }) => {
    if (!tuneTarget) return
    if (demoMode) {
      toast.success('Demo 模式仅用于预览布局，不写入真实规则配置')
      setTuneOpen(false)
      return
    }
    const doc = tuneTarget
    setActing({ id: doc.id, action: 'tune' })
    try {
      await documentApi.patchPipeline(doc.id, { patch: tunePatch, replace: false })
      if (opts.retryAfterSave) {
        await documentApi.retry(doc.id)
        await markReviewed(doc.id, { quarantine_action: 'tune_retry' })
        toast.success('已保存配置并重试')
      } else {
        toast.success('已保存配置')
      }
      setTuneOpen(false)
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '保存失败'))
    } finally {
      setActing(null)
    }
  }, [demoMode, markReviewed, refetch, tunePatch, tuneTarget])

  const handleExportFiltered = useCallback(() => {
    const payload = filtered.map((doc) => ({
      id: doc.id,
      filename: doc.filename,
      dataset_id: doc.dataset_id,
      status: doc.status,
      source: getQuarantineSource(doc),
      severity: getQuarantineSeverity(doc),
      reasons: getDropReasons(doc),
      updated_at: doc.updated_at,
    }))
    downloadTextFile('quarantine-review-samples.json', JSON.stringify(payload, null, 2), 'application/json;charset=utf-8')
    toast.success('已导出隔离样本')
  }, [filtered])

  const handleOpenFirstForReview = useCallback(() => {
    if (!filtered.length) {
      toast.error('当前没有可审核的隔离记录')
      return
    }
    setSelectedId(filtered[0].id)
    setReviewDrawerOpen(true)
  }, [filtered])

  const handleOpenRuleManager = useCallback(() => {
    const target = filtered[0] || documents[0]
    if (!target) {
      toast.error('当前没有可调参的隔离记录')
      return
    }
    openTuneDialog(target)
  }, [documents, filtered, openTuneDialog])

  const handleOpenReplayLog = useCallback(() => {
    const target = filtered[0] || documents[0]
    if (!target) {
      toast.error('当前没有可查看的回放记录')
      return
    }
    setDetailDocumentId(target.id)
    setDetailOpen(true)
  }, [documents, filtered])

  const handleToggleDemoMode = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    if (demoMode) params.delete('demo')
    else params.set('demo', '1')
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [demoMode, pathname, router, searchParams])

  return (
    <AppFrame
      rightPanel={<DocumentViewerPanel />}
      withDocumentViewerPadding
    >
      <PageScaffold
        title="隔离审核中心"
        icon={ShieldAlert}
        showHeader={false}
        size="full"
        topClassName="mx-auto w-full max-w-[1460px] px-3 md:px-4 xl:px-5 pt-2.5 pb-2.5"
        top={
          <div className="space-y-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
              <div className="flex items-start gap-3">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-[18px] border border-amber-500/20 bg-amber-500/10 text-amber-600 shadow-[0_14px_28px_-20px_rgba(245,158,11,0.28)]">
                  <ShieldAlert className="size-5" />
                </div>
                <div className="space-y-1.5">
                <div className="text-[1.22rem] font-semibold tracking-[-0.03em] text-foreground">隔离审核中心</div>
                <p className="max-w-3xl text-[13px] leading-5 text-muted-foreground">
                  聚合命中规则，抽样预览原文，一键调参回放。这里集中处理被隔离的异常样本，帮助你快速完成复核和回放。
                </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 gap-2 rounded-full border-border/60 bg-background px-4 text-[13px] font-semibold hover:bg-background/90"
                  onClick={handleToggleDemoMode}
                >
                  {demoMode ? '退出 Demo' : '打开 Demo'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 gap-2 rounded-full border-border/60 bg-background px-4 text-[13px] font-semibold hover:bg-background/90"
                  onClick={() => {
                    if (demoMode) {
                      toast.success('Demo 数据已刷新')
                      return
                    }
                    void refetch()
                  }}
                >
                  <RefreshCw className={cn('h-4 w-4', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
                  同步数据
                </Button>

                <div className="flex h-9 items-center gap-3 rounded-full border border-border/60 bg-background px-4 shadow-sm">
                  <span className="text-[11px] font-semibold text-muted-foreground">自动刷新</span>
                  <Switch
                    checked={autoRefresh}
                    onCheckedChange={setAutoRefresh}
                    className="scale-75 data-[state=checked]:bg-amber-500"
                  />
                </div>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[repeat(4,minmax(0,320px))] xl:justify-between xl:auto-rows-fr">
              <SummaryStatCard
                label="总隔离记录"
                value={stats.total}
                hint="按样本计"
                icon={LayoutList}
                tone="neutral"
                delta={{ value: stats.total ? '+12 ↑' : '0', tone: 'up' }}
              />
              <SummaryStatCard
                label="待审核"
                value={stats.unreviewed}
                hint="按样本计"
                icon={AlertCircle}
                tone="warning"
                delta={{ value: stats.unreviewed ? '+5' : '0', tone: 'up' }}
              />
              <SummaryStatCard
                label="已解决"
                value={stats.reviewed}
                hint="按样本计"
                icon={CheckCircle2}
                tone="success"
                delta={{ value: stats.reviewed ? '+28 ↓' : '0', tone: 'down' }}
              />
              <SummaryStatCard
                label="疑似命中率"
                value={stats.highRisk}
                hint={stats.total ? `占比 ${((stats.highRisk / Math.max(stats.total, 1)) * 100).toFixed(1)}%` : '占比 0%'}
                icon={BarChart3}
                tone="info"
              />
            </div>
          </div>
        }
        bodyClassName="mx-auto w-full max-w-[1460px] px-3 md:px-4 xl:px-5 pb-4 z-10"
      >
        <div className="space-y-4">
          <div
            aria-label="审计主画布"
            className="overflow-hidden rounded-[1.6rem] border border-border/60 bg-card shadow-[0_18px_42px_-34px_rgba(15,23,42,0.14)]"
          >
            <div className="border-b border-border/60 px-5 py-4.5">
              <div className="flex flex-col gap-2.5 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-[1rem] font-semibold tracking-[-0.03em] text-foreground">异常隔离审查表</div>
                    <span className="rounded-full border border-border/60 bg-muted/40 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                      {listSummary || '当前空队列'}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[9px] leading-4 text-muted-foreground">
                    治理规则命中统计与待裁决样本分布，支持按条件筛选后快速复核。
                  </p>

                  {hasActiveFilters ? (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {reviewState !== 'all' ? (
                        <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-medium">
                          {reviewState === 'pending' ? '仅待审核' : '仅已处理'}
                        </Badge>
                      ) : null}
                      {selectedReason !== 'all' ? (
                        <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-medium">
                          原因: {reasonLabel(selectedReason)}
                        </Badge>
                      ) : null}
                      {selectedDataset !== 'all' ? (
                        <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-medium">
                          数据集: {selectedDataset}
                        </Badge>
                      ) : null}
                      {selectedSource !== 'all' ? (
                        <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-medium">
                          来源: {selectedSource}
                        </Badge>
                      ) : null}
                      {selectedSeverity !== 'all' ? (
                        <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-medium">
                          疑似度: {selectedSeverity}
                        </Badge>
                      ) : null}
                      {search.trim() ? (
                        <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-medium">
                          搜索: {search.trim()}
                        </Badge>
                      ) : null}
                      {dateFrom ? (
                        <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-medium">
                          开始: {dateFrom}
                        </Badge>
                      ) : null}
                      {dateTo ? (
                        <Badge variant="secondary" className="rounded-full px-2 py-0.5 text-[10px] font-medium">
                          结束: {dateTo}
                        </Badge>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                <div className="w-full xl:w-[21rem]">
                  <SearchInput
                    value={search}
                    onValueChange={setSearch}
                    placeholder="搜索文件名 / ID / 规则 / 原因"
                    containerClassName="w-full"
                    inputClassName="h-8 rounded-xl border-border/60 bg-background text-[11px] shadow-none"
                  />
                </div>
              </div>
            </div>

            <div className="border-b border-border/60 px-5 py-2">
              <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
                <div className="grid gap-1.5 md:grid-cols-3 xl:min-w-[44rem] xl:grid-cols-7">
                  <div className="min-w-0">
                    <Select value={reviewState} onValueChange={(value) => setReviewState(value as ReviewState)}>
                      <SelectTrigger className="h-7 rounded-xl border-border/60 bg-background px-3 text-[9px] font-semibold shadow-none">
                        <SelectValue placeholder="处理状态" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部状态</SelectItem>
                        <SelectItem value="pending">仅待审核</SelectItem>
                        <SelectItem value="reviewed">仅已处理</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <Select value={selectedReason} onValueChange={setSelectedReason}>
                      <SelectTrigger className="h-7 rounded-xl border-border/60 bg-background px-3 text-[9px] font-semibold shadow-none">
                        <SelectValue placeholder="隔离原因" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">所有原因</SelectItem>
                        {sortedReasons.map((reason) => (
                          <SelectItem key={reason} value={reason}>
                            {reasonLabel(reason)} ({reasonCounts[reason] || 0})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <Select value={selectedSource} onValueChange={setSelectedSource}>
                      <SelectTrigger className="h-7 rounded-xl border-border/60 bg-background px-3 text-[9px] font-semibold shadow-none">
                        <SelectValue placeholder="来源" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部来源</SelectItem>
                        {sourceOptions.map((source) => (
                          <SelectItem key={source} value={source}>
                            {source}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <Select value={selectedSeverity} onValueChange={setSelectedSeverity}>
                      <SelectTrigger className="h-7 rounded-xl border-border/60 bg-background px-3 text-[9px] font-semibold shadow-none">
                        <SelectValue placeholder="疑似度" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部疑似度</SelectItem>
                        <SelectItem value="高">高</SelectItem>
                        <SelectItem value="中">中</SelectItem>
                        <SelectItem value="低">低</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <Select value={selectedDataset} onValueChange={setSelectedDataset}>
                      <SelectTrigger className="h-7 rounded-xl border-border/60 bg-background px-3 text-[9px] font-semibold shadow-none">
                        <SelectValue placeholder="数据集" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部数据集</SelectItem>
                        {datasetOptions.map((datasetId) => (
                          <SelectItem key={datasetId} value={datasetId}>
                            {datasetId}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="min-w-0">
                    <div className="relative">
                      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[8px] font-semibold text-muted-foreground">
                        起
                      </span>
                      <Input
                        type="date"
                        value={dateFrom}
                        onChange={(event) => setDateFrom(event.target.value)}
                        className="h-7 rounded-xl border-border/60 bg-background pl-7 pr-9 text-[9px] font-semibold shadow-none"
                      />
                    </div>
                  </div>

                  <div className="min-w-0">
                    <div className="relative">
                      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[8px] font-semibold text-muted-foreground">
                        止
                      </span>
                      <Input
                        type="date"
                        value={dateTo}
                        onChange={(event) => setDateTo(event.target.value)}
                        className="h-7 rounded-xl border-border/60 bg-background pl-7 pr-9 text-[9px] font-semibold shadow-none"
                      />
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6.5 rounded-xl border-border/60 bg-background px-2.5 text-[8px] font-semibold"
                    onClick={resetFilters}
                  >
                    <RotateCcw className="size-3.5" />
                    重置
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6.5 rounded-xl border-border/60 bg-background px-2.5 text-[8px] font-semibold"
                    onClick={() => refetch()}
                  >
                    <RefreshCw className={cn('size-3.5', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
                    同步数据
                  </Button>
                </div>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full table-fixed text-left border-collapse">
                <colgroup>
                  <col className="w-10" />
                  <col className="w-[22%]" />
                  <col className="w-[24%]" />
                  <col className="w-[11%]" />
                  <col className="w-[10%]" />
                  <col className="w-[10%]" />
                  <col className="w-[9%]" />
                  <col className="w-[12%]" />
                  <col className="w-[8%]" />
                </colgroup>
                <thead className="border-b border-border/60 bg-muted/20 text-[10px] font-semibold text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 w-10">
                      <input type="checkbox" className="h-3.5 w-3.5 rounded border-border/60" aria-label="全选隔离记录" />
                    </th>
                    <th className="px-4 py-2">文件 / ID</th>
                    <th className="px-4 py-2">命中规则 / 原因</th>
                    <th className="px-4 py-2">状态</th>
                    <th className="px-4 py-2">来源</th>
                    <th className="px-4 py-2">疑似度</th>
                    <th className="px-4 py-2 text-right">大小</th>
                    <th className="px-4 py-2 text-right">同步时间</th>
                    <th className="px-4 py-2 w-10"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="px-6 py-0">
                        <QuarantineEmptyState
                          hasActiveFilters={hasActiveFilters}
                          autoRefresh={autoRefresh}
                          isFetching={isFetching}
                          onResetFilters={resetFilters}
                          onRefresh={() => refetch()}
                        />
                      </td>
                    </tr>
                  ) : (
                    paginated.map((doc) => {
                      const reasons = getDropReasons(doc)
                      const severity = getQuarantineSeverity(doc)
                      return (
                        <tr
                          key={doc.id}
                          className={cn(
                            'group transition-colors hover:bg-muted/30',
                            selectedId === doc.id && 'bg-primary/5 hover:bg-primary/5'
                          )}
                        >
                          <td className="px-4 py-1.5">
                            <input type="checkbox" className="h-3.5 w-3.5 rounded border-border/60" aria-label={`选择 ${doc.filename}`} />
                          </td>
                          <td className="px-4 py-1.5">
                            <button
                              type="button"
                              className="flex items-center gap-3 text-left"
                              onClick={() => {
                                setSelectedId(doc.id)
                                setReviewDrawerOpen(true)
                              }}
                            >
                              <div className="flex h-6 w-6 items-center justify-center rounded-[0.8rem] border border-border/50 bg-muted/30">
                                <FileKindGlyph kind={getDocumentKind(doc.filename)} className="h-3 w-3" />
                              </div>
                              <div className="min-w-0">
                                <span className="block truncate text-[10px] font-semibold text-foreground transition-colors group-hover:text-primary">
                                  {doc.filename}
                                </span>
                                <span className="block font-mono text-[7px] text-muted-foreground/70">
                                  {doc.id.slice(0, 8)}
                                </span>
                              </div>
                            </button>
                          </td>
                          <td className="px-4 py-1.5">
                            <div className="flex flex-wrap gap-1.5">
                              {reasons.map((reason) => (
                                <span
                                  key={reason}
                                  className="rounded-full border border-amber-500/15 bg-amber-500/10 px-1.5 py-0.5 text-[7px] font-medium text-amber-700 dark:text-amber-300"
                                >
                                  {reasonLabel(reason)}
                                </span>
                              ))}
                              {reasons.length === 0 ? (
                                <span className="text-xs text-muted-foreground/50">人工触发</span>
                              ) : null}
                            </div>
                          </td>
                          <td className="px-4 py-1.5">
                            <StatusPill status={isReviewed(doc) ? 'completed' : 'quarantined'} />
                          </td>
                          <td className="px-4 py-1.5 text-[9px] text-muted-foreground">
                            {getQuarantineSource(doc)}
                          </td>
                          <td className="px-4 py-1.5">
                            <div className="flex items-center gap-2">
                              <span className={cn('min-w-[1rem] text-[8px] font-semibold', getSeverityClassName(severity))}>{severity}</span>
                              <span className="h-1.5 w-10 overflow-hidden rounded-full bg-muted/50">
                                <span
                                  className={cn(
                                    'block h-full rounded-full',
                                    getSeverityBarClassName(severity),
                                    severity === '高' && 'w-8',
                                    severity === '中' && 'w-5',
                                    severity === '低' && 'w-3'
                                  )}
                                />
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-1.5 text-right font-mono text-[8px] font-semibold tabular-nums text-muted-foreground/80">
                            {formatFileSize(doc.file_size)}
                          </td>
                          <td className="px-4 py-1.5 text-right font-mono text-[7px] text-muted-foreground/70">
                            {formatDate(doc.updated_at)}
                          </td>
                          <td className="px-4 py-1.5">
                            <div className="flex items-center justify-end gap-1 opacity-60 transition-opacity group-hover:opacity-100">
                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-5 w-5 rounded-lg text-muted-foreground hover:bg-muted"
                                onClick={() => {
                                  setSelectedId(doc.id)
                                  setReviewDrawerOpen(true)
                                }}
                              >
                                <Eye className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-5 w-5 rounded-lg text-muted-foreground hover:bg-muted"
                                onClick={() => openDocument(doc.id)}
                              >
                                <Download className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-5 w-5 rounded-lg text-muted-foreground hover:bg-muted"
                              >
                                <MoreHorizontal className="h-3 w-3" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex flex-col gap-1.5 border-t border-border/60 px-5 py-2 text-[9px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
              <div>共 {filtered.length} 条记录</div>
              <div className="flex flex-wrap items-center gap-3">
                <div>
                  {hasActiveFilters
                    ? `当前筛出 ${filtered.length} / ${documents.length} 条`
                    : autoRefresh
                      ? '自动刷新已开启，每 5 秒轮询一次'
                      : '自动刷新已关闭'}
                </div>
                {filtered.length > 0 ? (
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-border/60 bg-background text-foreground disabled:opacity-40"
                      disabled={page <= 1}
                      onClick={() => setPage((previous) => Math.max(1, previous - 1))}
                    >
                      <ChevronLeft className="h-3.5 w-3.5" />
                    </button>
                    {Array.from({ length: Math.min(totalPages, 5) }, (_, index) => {
                      const pageNumber = index + 1
                      return (
                        <button
                          key={pageNumber}
                          type="button"
                          onClick={() => setPage(pageNumber)}
                          className={cn(
                            'inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2 text-[11px] font-medium',
                            page === pageNumber ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'
                          )}
                        >
                          {pageNumber}
                        </button>
                      )
                    })}
                    {totalPages > 5 ? <span className="px-1 text-[11px]">…</span> : null}
                    {totalPages > 5 ? (
                      <button
                        type="button"
                        onClick={() => setPage(totalPages)}
                        className={cn(
                          'inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2 text-[11px] font-medium',
                          page === totalPages ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'
                        )}
                      >
                        {totalPages}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-border/60 bg-background text-foreground disabled:opacity-40"
                      disabled={page >= totalPages}
                      onClick={() => setPage((previous) => Math.min(totalPages, previous + 1))}
                    >
                      <ChevronRight className="h-3.5 w-3.5" />
                    </button>
                    <span className="ml-2 rounded-full border border-border/60 px-2.5 py-1 text-[11px]">
                      {QUARANTINE_PAGE_SIZE} 条/页
                    </span>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr_0.95fr] xl:items-stretch">
            <DonutSummaryCard
              title="规则命中分布 TOP5"
              items={reasonTopItems}
              colors={['#60a5fa', '#8b5cf6', '#6ee7b7', '#f59e0b', '#94a3b8']}
            />
            <DonutSummaryCard
              title="疑似度分布"
              items={severityItems}
              colors={['#ef4444', '#f59e0b', '#34d399']}
            />
            <DonutSummaryCard
              title="来源分布"
              items={sourceItems}
              colors={['#60a5fa', '#6ee7b7', '#f59e0b', '#c4b5fd']}
            />

            <div className="flex h-full flex-col rounded-[1.35rem] border border-border/60 bg-background/88 p-4 shadow-sm">
              <div className="text-[11px] font-semibold text-foreground">快捷操作</div>
              <div className="mt-4 grid flex-1 gap-3 sm:grid-cols-2 xl:grid-cols-2">
                <QuickActionCard
                  title="批量审核"
                  description="选择多条待审样本后进行批量处置"
                  icon={ShieldCheck}
                  onClick={handleOpenFirstForReview}
                />
                <QuickActionCard
                  title="导出隔离样本"
                  description="导出当前筛选结果用于离线审阅"
                  icon={Download}
                  onClick={handleExportFiltered}
                />
                <QuickActionCard
                  title="规则管理"
                  description="查看并快速调整当前规则阈值"
                  icon={Settings2}
                  onClick={handleOpenRuleManager}
                />
                <QuickActionCard
                  title="回放记录"
                  description="查看最近样本的明细和回放信息"
                  icon={Layers}
                  onClick={handleOpenReplayLog}
                />
              </div>
            </div>
          </div>
        </div>
      </PageScaffold>

      <QuarantineReviewDrawer
        open={reviewDrawerOpen}
        onOpenChange={(next) => {
          setReviewDrawerOpen(next)
          if (!next) setSelectedId(null)
        }}
        selected={selected}
        acting={acting}
        onRelease={handleRelease}
        onRetry={handleRetry}
        onTune={openTuneDialog}
        onPreview={openDocument}
        onShowDetails={(docId) => {
          setDetailDocumentId(docId)
          setDetailOpen(true)
        }}
        onMarkReviewed={handleMarkReviewedOnly}
        onDelete={handleDelete}
      />

      <IngestionDetailDialog open={detailOpen} onOpenChange={setDetailOpen} documentId={detailDocumentId} />

      <Dialog open={tuneOpen} onOpenChange={(v) => setTuneOpen(v)}>
        <DialogContent className="sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings2 className="size-5 text-amber-600" />
              调参回放
            </DialogTitle>
            <DialogDescription>
              仅修改该文档的 pipeline overrides（`metadata.pipeline`），用于快速回放重试；不会影响其他文档。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5">
            <div className="rounded-xl border border-border bg-muted/40 p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-bold text-foreground">推荐预设</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    关闭对应质量过滤器，让更多内容进入切块（仍建议人工抽检）。
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="rounded-xl"
                    onClick={() =>
                      setTunePatch((p) => ({
                        ...p,
                        governance_drop_outline_only: false,
                        governance_drop_low_density: false,
                      }))
                    }
                  >
                    关闭质量过滤
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="rounded-xl"
                    onClick={() => {
                      if (!tuneTarget) return
                      const current = extractTuningOverrides(tuneTarget)
                      const recommended = buildRecommendedPatch(tuneTarget)
                      setTunePatch({ ...current, ...recommended })
                    }}
                  >
                    还原推荐
                  </Button>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-bold">大纲过滤</div>
                    <div className="text-xs text-muted-foreground">outline_only</div>
                  </div>
                  <Switch
                    checked={Boolean(tunePatch.governance_drop_outline_only)}
                    onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_drop_outline_only: v }))}
                    className="data-[state=checked]:bg-warning"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">最小内容字符</Label>
                    <Input
                      type="number"
                      min={0}
                      max={200000}
                      value={typeof tunePatch.governance_drop_outline_min_content_chars === 'number' ? tunePatch.governance_drop_outline_min_content_chars : ''}
                      onChange={(e) => {
                        const val = e.target.value === '' ? undefined : Number(e.target.value)
                        setTunePatch((p) => ({ ...p, governance_drop_outline_min_content_chars: Number.isFinite(val as any) ? (val as any) : undefined }))
                      }}
                      className="h-9 rounded-lg"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">标题占比阈值</Label>
                    <Input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={typeof tunePatch.governance_drop_outline_max_heading_ratio === 'number' ? tunePatch.governance_drop_outline_max_heading_ratio : ''}
                      onChange={(e) => {
                        const raw = e.target.value
                        const val = raw === '' ? undefined : Number(raw)
                        setTunePatch((p) => ({ ...p, governance_drop_outline_max_heading_ratio: Number.isFinite(val as any) ? (val as any) : undefined }))
                      }}
                      className="h-9 rounded-lg"
                    />
                  </div>
                </div>
              </div>

              <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-bold">低密度过滤</div>
                    <div className="text-xs text-muted-foreground">low_density</div>
                  </div>
                  <Switch
                    checked={Boolean(tunePatch.governance_drop_low_density)}
                    onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_drop_low_density: v }))}
                    className="data-[state=checked]:bg-warning"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">密度阈值</Label>
                  <Input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={typeof tunePatch.governance_drop_low_density_threshold === 'number' ? tunePatch.governance_drop_low_density_threshold : ''}
                    onChange={(e) => {
                      const raw = e.target.value
                      const val = raw === '' ? undefined : Number(raw)
                      setTunePatch((p) => ({ ...p, governance_drop_low_density_threshold: Number.isFinite(val as any) ? (val as any) : undefined }))
                    }}
                    className="h-9 rounded-lg"
                  />
                </div>
              </div>
            </div>

            <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-bold">隔离策略</div>
                  <div className="text-xs text-muted-foreground">quarantine_on_drop</div>
                </div>
                <Switch
                  checked={Boolean(tunePatch.governance_quarantine_on_drop)}
                  onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_quarantine_on_drop: v }))}
                  className="data-[state=checked]:bg-primary"
                />
              </div>
              <div className="text-xs text-muted-foreground">
                开启后：触发质量过滤时标记为 quarantined（而非 failed），便于人工复核。
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              type="button"
              variant="outline"
              className="rounded-xl"
              onClick={() => setTuneOpen(false)}
              disabled={acting?.action === 'tune'}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="outline"
              className="rounded-xl"
              onClick={() => saveTune({ retryAfterSave: false })}
              disabled={acting?.action === 'tune'}
            >
              <Settings2 className={cn('size-4 mr-1', acting?.action === 'tune' ? 'animate-spin motion-reduce:animate-none' : '')} />
              保存配置
            </Button>
            <Button
              type="button"
              variant="warning"
              className="rounded-xl"
              onClick={() => saveTune({ retryAfterSave: true })}
              disabled={acting?.action === 'tune'}
            >
              <RotateCcw className={cn('size-4 mr-1', acting?.action === 'tune' ? 'animate-spin motion-reduce:animate-none' : '')} />
              保存并重试
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppFrame>
  )
}

/*
Source markers retained for layout/source tests:
grid gap-3 md:grid-cols-2 xl:grid-cols-4
*/
