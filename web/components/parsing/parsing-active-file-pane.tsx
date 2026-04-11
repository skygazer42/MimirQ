'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import {
  Blocks,
  Check,
  ChevronRight,
  Clock,
  Code,
  Copy,
  Download,
  Edit3,
  Eye,
  FileStack,
  FileText,
  Heading1,
  Image,
  Layers,
  Loader2,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
  Table2,
  X,
} from 'lucide-react'

import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { ParsingElementsPanel } from '@/components/parsing/parsing-elements-panel'
import { ParsingExtractPanel } from '@/components/parsing/parsing-extract-panel'
import { ParsingRightPanel } from '@/components/parsing/parsing-right-panel'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  buildParsingLayoutEntries,
  getParsingLayoutMeta,
  type ParsingLayoutKind,
} from '@/lib/parsing-layout'
import { findEditSelectionForActiveParsingEntry, type ParsingEditFocusHint } from '@/lib/parsing-edit-focus'
import { cn } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import type { ParsingElement, ParsingExtractEvidence } from '@/lib/api/parsing'
import type { ParsingBlock, ParsingPosition } from '@/lib/parsing-positions'

import type { ParsedFile, ParseRun } from './parsing-types'

const ParseCompareDialog = dynamic(
  () => import('@/components/parsing/parse-compare-dialog').then((mod) => mod.ParseCompareDialog),
  {
    loading: () => null,
  }
)

const PdfViewer = dynamic(() => import('@/components/parsing/pdf-viewer').then((mod) => mod.PdfViewer), {
  ssr: false,
  loading: () => <Skeleton className="h-[400px] w-full" />,
})

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function getQualityGateGrade(value: unknown): string {
  if (!isRecord(value) || typeof value.grade !== 'string') return 'pass'
  return value.grade
}

function getQualityGateReasons(value: unknown): string[] {
  if (!isRecord(value) || !Array.isArray(value.reasons)) return []
  return value.reasons.filter((item): item is string => typeof item === 'string')
}

function readBackendName(value: unknown): string | null {
  if (typeof value === 'string') {
    const normalized = value.trim()
    return normalized || null
  }
  if (typeof value === 'number') {
    return String(value)
  }
  return null
}

function getQualityBadgeClass(qualityGrade: string): string {
  if (qualityGrade === 'fail') {
    return 'border-destructive/20 bg-destructive/10 text-destructive'
  }
  if (qualityGrade === 'warn') {
    return 'border-warning/20 bg-warning/10 text-warning'
  }
  return 'border-success/20 bg-success/10 text-success'
}

function buildQualityEvidenceSummary(qualityGate: unknown, pdfQuality: unknown): string {
  const pieces: string[] = []
  const gateEvidence = isRecord(qualityGate) && isRecord(qualityGate.evidence) ? qualityGate.evidence : {}
  const textQuality = isRecord(gateEvidence.text_quality) ? gateEvidence.text_quality : {}
  const parseQuality = isRecord(gateEvidence.parse_quality) ? gateEvidence.parse_quality : {}
  const fallbackAttempts = Array.isArray(gateEvidence.fallback_attempts) ? gateEvidence.fallback_attempts : []

  if (isRecord(pdfQuality) && typeof pdfQuality.score === 'number') {
    pieces.push(`pdf_score=${Number(pdfQuality.score).toFixed(3)}`)
  }
  if (typeof parseQuality.score === 'number') pieces.push(`parse_score=${Number(parseQuality.score).toFixed(3)}`)
  if (typeof textQuality.content_chars === 'number') pieces.push(`content_chars=${textQuality.content_chars}`)
  if (typeof textQuality.density === 'number') pieces.push(`density=${Number(textQuality.density).toFixed(3)}`)
  if (typeof textQuality.replacement_ratio === 'number') {
    pieces.push(`replacement_ratio=${Number(textQuality.replacement_ratio).toFixed(3)}`)
  }
  if (fallbackAttempts.length > 0) {
    const fallbackBackends = [
      readBackendName(gateEvidence.fallback_initial_backend),
      readBackendName(gateEvidence.fallback_final_backend),
    ].filter((value): value is string => value != null)
    if (fallbackBackends.length > 0) {
      pieces.push(`fallback=${fallbackBackends.join('→')}`)
    }
  }

  return pieces.join(' · ')
}

function formatElementBbox(bbox: ParsingElement['bbox'] | ParsingExtractEvidence['bbox']): string {
  if (!bbox) return ''
  return `${bbox.x0},${bbox.y0},${bbox.x1},${bbox.y1}`
}

function formatElementPages(element: ParsingElement | null | undefined): string {
  const pages = Array.isArray(element?.pages) ? element.pages.filter((value) => Number.isInteger(value) && value > 0) : []
  if (pages.length >= 2) {
    if (pages.length === 2 && pages[1] === pages[0] + 1) {
      return `跨页 ${pages[0]}-${pages[1]}`
    }
    return `跨页 ${pages.join(',')}`
  }
  if (typeof element?.page === 'number') {
    return `页 ${element.page}`
  }
  return ''
}

function formatEvidencePages(
  evidence: ParsingExtractEvidence | null | undefined,
  element: ParsingElement | null | undefined
): string {
  const rawPages = Array.isArray(element?.pages)
    ? element?.pages
    : Array.isArray(evidence?.pages)
      ? evidence?.pages
      : []
  const pages = rawPages.filter((value) => Number.isInteger(value) && value > 0)
  if (pages.length >= 2) {
    if (pages.length === 2 && pages[1] === pages[0] + 1) {
      return `跨页 ${pages[0]}-${pages[1]}`
    }
    return `跨页 ${pages.join(',')}`
  }
  const page = element?.page ?? evidence?.page
  if (typeof page === 'number') {
    return `页 ${page}`
  }
  return ''
}

function toLayoutKind(kind: string | null | undefined): ParsingLayoutKind {
  const normalized = String(kind || '').trim().toLowerCase()
  if (normalized === 'seal') return 'seal'
  if (normalized === 'equation') return 'equation'
  if (normalized === 'table') return 'table'
  if (normalized === 'image') return 'image'
  if (normalized === 'heading') return 'heading'
  if (normalized === 'list') return 'list'
  return 'paragraph'
}

function buildExtractEvidencePosition(
  evidence: ParsingExtractEvidence | null | undefined,
  element: ParsingElement | null | undefined
): ParsingPosition | null {
  const rawPages = Array.isArray(element?.pages)
    ? element?.pages
    : Array.isArray(evidence?.pages)
      ? evidence?.pages
      : []
  const pages = rawPages.filter((value) => Number.isInteger(value) && value > 0)
  const page = element?.page ?? evidence?.page
  const bbox = element?.bbox ?? evidence?.bbox
  if (!bbox) return null
  if (pages.length >= 1) {
    return {
      pages: pages.map((value) => Math.max(0, value - 1)),
      left: bbox.x0,
      right: bbox.x1,
      top: bbox.y0,
      bottom: bbox.y1,
      raw: `extract:${String(evidence?.element_id || element?.id || '')}`,
    }
  }
  if (typeof page !== 'number') return null
  return {
    pages: [Math.max(0, page - 1)],
    left: bbox.x0,
    right: bbox.x1,
    top: bbox.y0,
    bottom: bbox.y1,
    raw: `extract:${String(evidence?.element_id || element?.id || '')}`,
  }
}

const layoutLegendKinds: ParsingLayoutKind[] = ['heading', 'paragraph', 'list', 'table', 'image', 'equation']

type ParsingActiveFilePaneProps = {
  activeFile: ParsedFile
  activeRun: ParseRun | null
  activeMarkdown: string
  activeElements?: ParsingElement[]
  activeQualityGate: unknown
  activePdfQuality: unknown
  activeBlocksWithPositions: ParsingBlock[]
  isPdf: boolean
  tocEnabled: boolean
  previewMode: 'raw' | 'rendered'
  rightPanelMode: 'blocks' | 'markdown'
  isEditing: boolean
  editedContent: string
  copied: boolean
  activeBlockId: string | null
  hoveredBlockId: string | null
  onSelectRun: (runId: string) => void
  onPreviewModeChange: (mode: 'raw' | 'rendered') => void
  onRightPanelModeChange: (mode: 'blocks' | 'markdown') => void
  onStartEdit: () => void
  onCancelEdit: () => void
  onSaveEdit: () => void
  onCopyMarkdown: () => void
  onDownloadMarkdown: () => void
  onParseFile: (fileId: string, backend?: string) => void
  pdfPreviewResetToken: number
  onSetQueueFileParserBackend: (params: { fileId: string; filename: string; backend: string }) => void
  onSubmitToGovernance: () => void
  onEditedContentChange: (value: string) => void
  onActiveBlockIdChange: (blockId: string | null) => void
  onHoveredBlockIdChange: (blockId: string | null) => void
}

export function ParsingActiveFilePane({
  activeFile,
  activeRun,
  activeMarkdown,
  activeElements = [],
  activeQualityGate,
  activePdfQuality,
  activeBlocksWithPositions,
  isPdf,
  tocEnabled,
  previewMode,
  rightPanelMode,
  isEditing,
  editedContent,
  copied,
  activeBlockId,
  hoveredBlockId,
  onSelectRun,
  onPreviewModeChange,
  onRightPanelModeChange,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onCopyMarkdown,
  onDownloadMarkdown,
  onParseFile,
  pdfPreviewResetToken,
  onSetQueueFileParserBackend,
  onSubmitToGovernance,
  onEditedContentChange,
  onActiveBlockIdChange,
  onHoveredBlockIdChange,
}: Readonly<ParsingActiveFilePaneProps>) {
  const [compareOpen, setCompareOpen] = useState(false)
  const [activePdfEditHint, setActivePdfEditHint] = useState<{
    blockId: string
    hint: ParsingEditFocusHint
  } | null>(null)
  const [selectedExtractEvidence, setSelectedExtractEvidence] = useState<{
    fieldName: string
    evidence: ParsingExtractEvidence
  } | null>(null)
  const editorRef = useRef<HTMLTextAreaElement | null>(null)
  const didInitializeEditSelectionRef = useRef(false)
  const pdfViewerKey = `${activeFile.id}:${activeFile.activeRunId || activeRun?.id || 'default'}:${pdfPreviewResetToken}`
  const qualityGrade = getQualityGateGrade(activeQualityGate)
  const qualityReasons = getQualityGateReasons(activeQualityGate)
  const qualityEvidenceSummary = buildQualityEvidenceSummary(activeQualityGate, activePdfQuality)
  const layoutEntries = useMemo(() => buildParsingLayoutEntries(activeBlocksWithPositions), [activeBlocksWithPositions])
  const layoutBoxesByPage = useMemo(() => {
    const next = new Map<number, Array<{ id: string; kind: ParsingLayoutKind; position: (typeof layoutEntries)[number]['position'] }>>()
    for (const entry of layoutEntries) {
      if (entry.pageIndex == null) continue
      const list = next.get(entry.pageIndex) || []
      list.push({ id: entry.id, kind: entry.kind, position: entry.position })
      next.set(entry.pageIndex, list)
    }
    return next
  }, [layoutEntries])
  const layoutEntryIdToPageIndex = useMemo(() => {
    const next = new Map<string, number>()
    for (const entry of layoutEntries) {
      if (entry.pageIndex == null) continue
      next.set(entry.id, entry.pageIndex)
    }
    return next
  }, [layoutEntries])
  const activeEditSelection = useMemo(
    () =>
      findEditSelectionForActiveParsingEntry(
        editedContent || activeMarkdown,
        layoutEntries,
        activeBlockId,
        activePdfEditHint?.blockId === activeBlockId ? activePdfEditHint.hint : null
      ),
    [activeBlockId, activeMarkdown, activePdfEditHint, editedContent, layoutEntries]
  )
  const selectedExtractElement = useMemo(() => {
    const targetId = String(selectedExtractEvidence?.evidence.element_id || '').trim()
    if (!targetId) return null
    return (activeElements || []).find((element) => String(element.id || '').trim() === targetId) || null
  }, [activeElements, selectedExtractEvidence])
  const selectedExtractOverlayId = useMemo(() => {
    if (!selectedExtractEvidence) return null
    const targetId = String(selectedExtractEvidence.evidence.element_id || '').trim()
    if (!targetId) return null
    if (layoutEntries.some((entry) => entry.id === targetId)) return null
    const position = buildExtractEvidencePosition(selectedExtractEvidence.evidence, selectedExtractElement)
    if (!position) return null
    return `extract-evidence:${targetId}`
  }, [layoutEntries, selectedExtractElement, selectedExtractEvidence])
  const pdfBoxesByPage = useMemo(() => {
    if (!selectedExtractOverlayId || !selectedExtractEvidence) return layoutBoxesByPage
    const position = buildExtractEvidencePosition(selectedExtractEvidence.evidence, selectedExtractElement)
    if (!position) return layoutBoxesByPage
    const pageIndex = position.pages[0] ?? 0
    const next = new Map(layoutBoxesByPage)
    const list = [...(next.get(pageIndex) || [])]
    list.push({
      id: selectedExtractOverlayId,
      kind: toLayoutKind(selectedExtractElement?.kind || selectedExtractEvidence.evidence.kind),
      position,
    })
    next.set(pageIndex, list)
    return next
  }, [layoutBoxesByPage, selectedExtractElement, selectedExtractEvidence, selectedExtractOverlayId])
  const pdfBlockIdToPageIndex = useMemo(() => {
    if (!selectedExtractOverlayId || !selectedExtractEvidence) return layoutEntryIdToPageIndex
    const position = buildExtractEvidencePosition(selectedExtractEvidence.evidence, selectedExtractElement)
    if (!position) return layoutEntryIdToPageIndex
    const next = new Map(layoutEntryIdToPageIndex)
    next.set(selectedExtractOverlayId, position.pages[0] ?? 0)
    return next
  }, [layoutEntryIdToPageIndex, selectedExtractElement, selectedExtractEvidence, selectedExtractOverlayId])
  const pdfActiveBlockIds = useMemo(() => {
    const ids: string[] = []
    if (selectedExtractOverlayId) ids.push(selectedExtractOverlayId)
    if (activeBlockId) ids.push(activeBlockId)
    return ids
  }, [activeBlockId, selectedExtractOverlayId])

  const handleSelectPdfBlock = (blockId: string, hint?: ParsingEditFocusHint) => {
    setActivePdfEditHint(hint ? { blockId, hint } : null)
    onActiveBlockIdChange(blockId)
  }

  const handleSelectReviewBlock = (blockId: string) => {
    setActivePdfEditHint(null)
    onActiveBlockIdChange(blockId)
  }
  const handleSelectExtractEvidence = (payload: { fieldName: string; evidence: ParsingExtractEvidence }) => {
    setSelectedExtractEvidence(payload)
    const targetId = String(payload.evidence.element_id || '').trim()
    if (!targetId) return
    if (layoutEntries.some((entry) => entry.id === targetId)) {
      onActiveBlockIdChange(targetId)
      onRightPanelModeChange('blocks')
    }
  }
  const handleSelectElement = (element: ParsingElement) => {
    handleSelectExtractEvidence({
      fieldName: 'element',
      evidence: {
        element_id: String(element.id || '').trim() || null,
        kind: element.kind,
        page: element.page ?? null,
        pages: element.pages ?? null,
        visual_kind: element.visual_kind ?? null,
        bbox: element.bbox ?? null,
        text: element.text ?? null,
        score: element.confidence ?? null,
      },
    })
  }

  useEffect(() => {
    if (!isEditing) {
      didInitializeEditSelectionRef.current = false
      return
    }
    if (didInitializeEditSelectionRef.current) return

    const textarea = editorRef.current
    if (!textarea) return

    didInitializeEditSelectionRef.current = true
    const start = activeEditSelection?.start ?? 0
    const rafId = globalThis.window.requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(start, start)
    })

    return () => {
      globalThis.window.cancelAnimationFrame(rafId)
    }
  }, [activeEditSelection, isEditing])
  useEffect(() => {
    setSelectedExtractEvidence(null)
  }, [activeFile.id, activeRun?.id])

  const parsedStatItems =
    activeFile.status === 'parsed' && activeFile.stats
      ? [
          { icon: FileText, label: '字符', value: activeFile.stats.charCount.toLocaleString() },
          { icon: FileStack, label: '行数', value: activeFile.stats.lineCount.toLocaleString() },
          { icon: Heading1, label: '标题', value: (activeFile.stats.headingCount || 0).toLocaleString() },
          {
            icon: Layers,
            label: '页数',
            value:
              typeof activeFile.stats.pageCount === 'number' && activeFile.stats.pageCount > 0
                ? activeFile.stats.pageCount
                : '-',
          },
          { icon: Blocks, label: '定位块', value: Math.floor(activeFile.stats.blockCount || 0) },
          { icon: Table2, label: '表格', value: Math.floor(activeFile.stats.tableCount || 0) },
          { icon: Image, label: '图片', value: activeFile.stats.imageCount || 0 },
          {
            icon: Clock,
            label: '耗时',
            value:
              typeof activeFile.duration === 'number' && Number.isFinite(activeFile.duration)
                ? `${activeFile.duration}s`
                : '-',
          },
        ]
      : []
  const activeElementSummaryItems = useMemo(() => {
    const counts = new Map<string, number>()
    for (const element of activeElements || []) {
      const kind = String(element.kind || '').trim()
      if (!kind) continue
      counts.set(kind, (counts.get(kind) || 0) + 1)
    }
    const descriptors = [
      { kind: 'seal', label: '印章' },
      { kind: 'equation', label: '公式' },
      { kind: 'table', label: '表格元素' },
      { kind: 'image', label: '图片元素' },
      { kind: 'heading', label: '标题元素' },
    ]
    return descriptors
      .map((descriptor) => ({
        ...descriptor,
        count: counts.get(descriptor.kind) || 0,
      }))
      .filter((descriptor) => descriptor.count > 0)
  }, [activeElements])
  const activeElementHighlightItems = useMemo(() => {
    const highlights: Array<{
      key: string
      label: string
      value: string
      meta?: string
    }> = []

    const primarySeal = (activeElements || [])
      .filter((element) => element.kind === 'seal' && typeof element.text === 'string' && element.text.trim())
      .sort((left, right) => Number(right.confidence || 0) - Number(left.confidence || 0))[0]
    if (primarySeal) {
      const sealMeta: string[] = []
      if (formatElementPages(primarySeal)) sealMeta.push(formatElementPages(primarySeal))
      if (typeof primarySeal.confidence === 'number') sealMeta.push(primarySeal.confidence.toFixed(2))
      highlights.push({
        key: 'primary-seal',
        label: '主印章',
        value: String(primarySeal.text || '').trim(),
        meta: sealMeta.join(' · ') || undefined,
      })
    }

    const equations = (activeElements || []).filter(
      (element) => element.kind === 'equation' && typeof element.text === 'string' && element.text.trim()
    )
    if (equations.length > 0) {
      const leadEquation = String(equations[0]?.text || '').replace(/\s+/g, ' ').trim()
      const extraCount = Math.max(0, equations.length - 1)
      highlights.push({
        key: 'equation-preview',
        label: '公式样例',
        value: leadEquation,
        meta: extraCount > 0 ? `另 ${extraCount} 条` : undefined,
      })
    }

    const imageSubtypeCounts = new Map<string, number>()
    for (const element of activeElements || []) {
      if (element.kind !== 'image') continue
      const visualKind = String(element.visual_kind || '').trim()
      if (!visualKind) continue
      imageSubtypeCounts.set(visualKind, (imageSubtypeCounts.get(visualKind) || 0) + 1)
    }
    if (imageSubtypeCounts.size > 0) {
      const rankedSubtypes = Array.from(imageSubtypeCounts.entries()).sort((left, right) => right[1] - left[1])
      const [leadKind, leadCount] = rankedSubtypes[0]
      const remainingKinds = rankedSubtypes.slice(1).map(([kind, count]) => `${kind}×${count}`)
      highlights.push({
        key: 'image-visual-kinds',
        label: '图片子类',
        value: `${leadKind}×${leadCount}`,
        meta: remainingKinds.length > 0 ? remainingKinds.join(' · ') : undefined,
      })
    }

    return highlights
  }, [activeElements])
  const submitToGovernanceButton = isEditing ? null : (
    <Button
      onClick={onSubmitToGovernance}
      className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
    >
      <ShieldCheck className="h-4 w-4" />
      提交到数据治理
      <ChevronRight className="h-4 w-4" />
    </Button>
  )

  return (
    <>
      <ParseCompareDialog
        open={compareOpen}
        onOpenChange={setCompareOpen}
        runs={activeFile.runs || []}
        defaultBaseRunId={activeFile.activeRunId || activeRun?.id || null}
        onUseRun={(runId) => {
          onSelectRun(runId)
          setCompareOpen(false)
        }}
      />

      <>
        {parsedStatItems.length > 0 || activeQualityGate || activeElementSummaryItems.length > 0 ? (
          <div className="border-b border-border/60 bg-background/80 px-5 py-2.5 dark:bg-background/50">
            {parsedStatItems.length > 0 ? (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                {parsedStatItems.map(({ icon: Icon, label, value }) => (
                  <div key={label} className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <Icon className="h-3.5 w-3.5 text-muted-foreground/80" />
                    <span>{label}</span>
                    <span className="font-mono text-[12px] font-semibold tabular-nums text-foreground">
                      {value}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
            {activeQualityGate ? (
              <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border/50 pt-2">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em]',
                      getQualityBadgeClass(qualityGrade)
                    )}
                    title="解析质量门禁（best-effort）"
                  >
                    {String(qualityGrade || 'pass')}
                  </span>
                  <div className="text-[11px] text-muted-foreground">
                    {qualityReasons.length ? qualityReasons.join(' · ') : '无明显风险信号'}
                  </div>
                </div>
                {qualityEvidenceSummary ? (
                  <div className="font-mono text-[10px] text-muted-foreground/90">{qualityEvidenceSummary}</div>
                ) : null}
              </div>
            ) : null}
            {activeElementSummaryItems.length > 0 ? (
              <div
                className={cn(
                  'flex flex-wrap items-center gap-1.5',
                  activeQualityGate ? 'mt-2 border-t border-border/50 pt-2' : 'mt-2'
                )}
              >
                <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/75">
                  结构元素
                </span>
                {activeElementSummaryItems.map((item) => (
                  <span
                    key={item.kind}
                    className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-background/88 px-2 py-0.5 text-[10px] text-muted-foreground"
                  >
                    <span>{item.label}</span>
                    <span className="font-mono font-semibold text-foreground">{item.count}</span>
                  </span>
                ))}
              </div>
            ) : null}
            {activeElementHighlightItems.length > 0 ? (
              <div
                className={cn(
                  'flex flex-wrap items-center gap-1.5',
                  activeElementSummaryItems.length > 0 || activeQualityGate ? 'mt-2 border-t border-border/50 pt-2' : 'mt-2'
                )}
              >
                {activeElementHighlightItems.map((item) => (
                  <div
                    key={item.key}
                    className="inline-flex max-w-full items-center gap-2 rounded-lg border border-border/60 bg-background/90 px-2.5 py-1 text-[10px] text-muted-foreground"
                  >
                    <span className="font-semibold uppercase tracking-[0.1em] text-foreground/78">{item.label}</span>
                    <span className="max-w-[280px] truncate font-medium text-foreground">{item.value}</span>
                    {item.meta ? <span className="font-mono text-muted-foreground/85">{item.meta}</span> : null}
                  </div>
                ))}
              </div>
            ) : null}
            {selectedExtractEvidence ? (
              <div className="mt-2 border-t border-border/50 pt-2">
                <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/75">证据定位</div>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 rounded-lg border border-border/60 bg-background/92 px-2.5 py-1.5 text-[10px] text-muted-foreground">
                  <span className="font-semibold text-foreground/80">{selectedExtractEvidence.fieldName}</span>
                  <span>{selectedExtractElement?.kind || selectedExtractEvidence.evidence.kind || 'unknown'}</span>
                  {selectedExtractEvidence.evidence.visual_kind ? <span>{selectedExtractEvidence.evidence.visual_kind}</span> : null}
                  {selectedExtractElement?.id || selectedExtractEvidence.evidence.element_id ? (
                    <span>{selectedExtractElement?.id || selectedExtractEvidence.evidence.element_id}</span>
                  ) : null}
                  {formatEvidencePages(selectedExtractEvidence.evidence, selectedExtractElement) ? (
                    <span>{formatEvidencePages(selectedExtractEvidence.evidence, selectedExtractElement)}</span>
                  ) : null}
                  {formatElementBbox(selectedExtractElement?.bbox || selectedExtractEvidence.evidence.bbox) ? (
                    <span className="font-mono">
                      {formatElementBbox(selectedExtractElement?.bbox || selectedExtractEvidence.evidence.bbox)}
                    </span>
                  ) : null}
                  {selectedExtractElement?.text || selectedExtractEvidence.evidence.text ? (
                    <span className="truncate font-medium text-foreground">
                      {selectedExtractElement?.text || selectedExtractEvidence.evidence.text}
                    </span>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border/60 bg-background/88 px-5 py-2.5 dark:bg-background/75">
          <div className="flex min-w-0 flex-wrap items-center gap-2.5">
            <span className="max-w-[260px] truncate text-[13px] font-semibold text-foreground dark:text-foreground">
              {activeFile.file.name}
            </span>
            <span className="rounded-md bg-muted/70 px-2 py-0.5 text-[10px] font-medium text-muted-foreground dark:bg-muted dark:text-muted-foreground">
              {activeFile.parserLabel}
            </span>
            {activeFile.runs && activeFile.runs.length > 1 ? (
              <select
                value={activeRun?.id || ''}
                onChange={(event) => onSelectRun(event.target.value)}
                className="h-7 rounded-md border border-border/70 bg-background px-2 py-1 text-[11px] text-foreground/80 dark:border-border dark:bg-muted dark:text-muted-foreground"
              >
                {activeFile.runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.parserLabel} {run.createdAt ? `· ${new Date(run.createdAt).toLocaleTimeString()}` : ''}
                  </option>
                ))}
              </select>
            ) : null}
            {isEditing ? (
              <span className="flex items-center gap-1 rounded-md bg-sky-100 px-2 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
                <Edit3 className="h-3 w-3" />
                编辑中
              </span>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {activeFile.status === 'parsed' ? (
              <>
                {activeFile.runs && activeFile.runs.length > 1 ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCompareOpen(true)}
                    disabled={isEditing}
                    className="h-8 gap-1.5 rounded-lg px-2.5 text-xs"
                  >
                    <FileStack className="h-4 w-4" />
                    对比
                  </Button>
                ) : null}

                {isEditing ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={onCancelEdit}
                      className="h-8 gap-1.5 rounded-lg px-2.5 text-xs text-muted-foreground"
                    >
                      <X className="h-4 w-4" />
                      取消
                    </Button>
                    <Button
                      onClick={onSaveEdit}
                      size="sm"
                      className="h-8 gap-1.5 rounded-lg px-2.5 text-xs bg-sky-600 hover:bg-sky-700"
                    >
                      <Save className="h-4 w-4" />
                      保存修改
                    </Button>
                  </>
                ) : (
                  <>
                    {rightPanelMode === 'markdown' ? (
                      <div className="flex items-center rounded-lg bg-muted/80 p-0.5 dark:bg-muted">
                        <button
                          onClick={() => onPreviewModeChange('rendered')}
                          className={cn(
                            'focus-ring flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] transition-colors duration-200 motion-reduce:transition-none',
                            previewMode === 'rendered'
                              ? 'bg-card text-foreground shadow-sm dark:bg-background dark:text-foreground dark:shadow-none'
                              : 'text-muted-foreground hover:text-foreground/80 dark:text-muted-foreground dark:hover:text-muted-foreground'
                          )}
                        >
                          <Eye className="h-3.5 w-3.5" />
                          预览
                        </button>
                        <button
                          onClick={() => onPreviewModeChange('raw')}
                          className={cn(
                            'focus-ring flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] transition-colors duration-200 motion-reduce:transition-none',
                            previewMode === 'raw'
                              ? 'bg-card text-foreground shadow-sm dark:bg-background dark:text-foreground dark:shadow-none'
                              : 'text-muted-foreground hover:text-foreground/80 dark:text-muted-foreground dark:hover:text-muted-foreground'
                          )}
                        >
                          <Code className="h-3.5 w-3.5" />
                          源码
                        </button>
                      </div>
                    ) : null}

                    {activeBlocksWithPositions.length > 0 ? (
                      <div className="flex items-center rounded-lg bg-muted/80 p-0.5 dark:bg-muted">
                        <button
                          onClick={() => onRightPanelModeChange('blocks')}
                          className={cn(
                            'focus-ring flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] transition-colors duration-200 motion-reduce:transition-none',
                            rightPanelMode === 'blocks'
                              ? 'bg-card text-foreground shadow-sm dark:bg-background dark:text-foreground dark:shadow-none'
                              : 'text-muted-foreground hover:text-foreground/80 dark:text-muted-foreground dark:hover:text-muted-foreground'
                          )}
                        >
                          <FileStack className="h-3.5 w-3.5" />
                          版面
                        </button>
                        <button
                          onClick={() => onRightPanelModeChange('markdown')}
                          className={cn(
                            'focus-ring flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] transition-colors duration-200 motion-reduce:transition-none',
                            rightPanelMode === 'markdown'
                              ? 'bg-card text-foreground shadow-sm dark:bg-background dark:text-foreground dark:shadow-none'
                              : 'text-muted-foreground hover:text-foreground/80 dark:text-muted-foreground dark:hover:text-muted-foreground'
                          )}
                        >
                          <FileText className="h-3.5 w-3.5" />
                          Markdown
                        </button>
                      </div>
                    ) : null}

                    <Button variant="outline" size="sm" onClick={onStartEdit} className="h-8 gap-1.5 rounded-lg px-2.5 text-xs">
                      <Edit3 className="h-4 w-4" />
                      编辑
                    </Button>

                    <Button variant="outline" size="sm" onClick={onCopyMarkdown} className="h-8 gap-1.5 rounded-lg px-2.5 text-xs">
                      {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
                      {copied ? '已复制' : '复制'}
                    </Button>

                    <Button variant="outline" size="sm" onClick={onDownloadMarkdown} className="h-8 gap-1.5 rounded-lg px-2.5 text-xs">
                      <Download className="h-4 w-4" />
                      下载
                    </Button>
                  </>
                )}
              </>
            ) : null}

            {activeFile.status === 'pending' || activeFile.status === 'error' ? (
              <div className="mr-2 flex items-center gap-2">
                <span className="text-xs font-medium text-muted-foreground">解析方式</span>
                <ParserDropdown
                  value={activeFile.parserBackend}
                  filename={activeFile.file.name}
                  onChange={(backend) =>
                    onSetQueueFileParserBackend({
                      fileId: activeFile.id,
                      filename: activeFile.file.name,
                      backend,
                    })
                  }
                  className="w-56"
                />
              </div>
            ) : null}

            {activeFile.status === 'pending' ? (
              <Button onClick={() => onParseFile(activeFile.id)} className="gap-2 bg-sky-600 hover:bg-sky-700">
                <Sparkles className="h-4 w-4 text-sky-200" />
                开始解析
              </Button>
            ) : null}

            {activeFile.status === 'error' ? (
              <Button onClick={() => onParseFile(activeFile.id)} variant="outline" className="gap-2">
                <RotateCcw className="h-4 w-4" />
                重试
              </Button>
            ) : null}
          </div>
        </div>

         <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar">
          {activeFile.status === 'parsed' ? (
           <ParsingExtractPanel
              documentId={activeFile.libraryId || null}
              activeElements={activeElements}
              onSelectEvidence={handleSelectExtractEvidence}
            />
          ) : null}
          {activeFile.status === 'parsed' ? (
            <ParsingElementsPanel elements={activeElements} onSelectElement={handleSelectElement} />
          ) : null}

           {activeFile.status === 'pending' ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-xl bg-sky-100 dark:bg-sky-900/30">
                  <Sparkles className="h-8 w-8 text-sky-700 dark:text-sky-300" />
                </div>
                <p className="mb-2 text-foreground/80 dark:text-muted-foreground">准备就绪</p>
                <p className="text-sm text-muted-foreground dark:text-muted-foreground">
                  先在上方选择解析方式（当前：{activeFile.parserLabel}），再点击开始解析
                </p>
              </div>
            </div>
          ) : null}

          {activeFile.status === 'parsing' ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <div className="relative">
                  <Loader2 className="mx-auto h-12 w-12 animate-spin text-sky-700 motion-reduce:animate-none dark:text-sky-300" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-xs font-medium text-sky-700 dark:text-sky-200">
                      {Math.round(activeFile.progress || 0)}%
                    </span>
                  </div>
                </div>
                <p className="mt-4 text-foreground/80 dark:text-muted-foreground">正在解析...</p>
                <p className="mt-1 text-sm text-muted-foreground dark:text-muted-foreground">{activeFile.parserLabel}</p>
              </div>
            </div>
          ) : null}

          {activeFile.status === 'error' ? (
            <div className="flex h-full items-center justify-center">
              <div className="max-w-md text-center">
                <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-xl bg-destructive/10">
                  <FileText className="h-8 w-8 text-destructive" />
                </div>
                <p className="mb-2 font-medium text-destructive">解析失败</p>
                <p className="text-sm text-muted-foreground dark:text-muted-foreground">{activeFile.error}</p>

                {Array.isArray(activeFile.parseDiagnostics?.suggested_backends) &&
                activeFile.parseDiagnostics.suggested_backends.length > 0 ? (
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    {activeFile.parseDiagnostics.suggested_backends.slice(0, 6).map((backend) => {
                      const resolved = resolveParserBackendForFilename(activeFile.file.name, backend)
                      const label = getParserLabel(resolved.backend)
                      return (
                        <Button
                          key={backend}
                          variant="outline"
                          size="sm"
                          className="gap-2"
                          onClick={() => onParseFile(activeFile.id, backend)}
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                          用 {label} 重试
                        </Button>
                      )
                    })}
                  </div>
                ) : null}

                {activeFile.parseDiagnostics?.pdf_sample ? (
                  <div className="mt-4 text-left">
                    <div className="text-xs text-muted-foreground">
                      PDF 采样
                      {typeof activeFile.parseDiagnostics.pdf_sample.page_count === 'number'
                        ? `（${activeFile.parseDiagnostics.pdf_sample.page_count} 页）`
                        : ''}
                      {activeFile.parseDiagnostics.pdf_sample.is_scanned ? ' · 可能是扫描件（可选文本很少）' : ''}
                    </div>
                    {Array.isArray(activeFile.parseDiagnostics.pdf_sample.samples) &&
                    activeFile.parseDiagnostics.pdf_sample.samples.length > 0 ? (
                      <div className="mt-2 max-h-48 space-y-2 overflow-y-auto overscroll-contain rounded-lg border border-border/50 bg-muted/30 p-2 dark:border-border/60 dark:bg-background/40">
                        {activeFile.parseDiagnostics.pdf_sample.samples.slice(0, 3).map((sample) => (
                          <div
                            key={sample.page}
                            className="rounded-md border border-border/40 bg-card/70 p-2 dark:border-border/60 dark:bg-background/60"
                          >
                            <div className="text-xs text-muted-foreground">
                              页 {sample.page} · {sample.text_chars} 字符
                            </div>
                            {sample.excerpt ? (
                              <div className="mt-1 whitespace-pre-wrap text-xs text-foreground/80 dark:text-muted-foreground">
                                {sample.excerpt}
                              </div>
                            ) : (
                              <div className="mt-1 text-xs italic text-muted-foreground">无可选中文本</div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {activeFile.status === 'parsed' && activeMarkdown ? (
            <div className="h-full">
              {isEditing ? (
                <div className="p-6">
                  <textarea
                    ref={editorRef}
                    value={editedContent}
                    onChange={(event) => onEditedContentChange(event.target.value)}
                    className="min-h-[500px] w-full resize-none rounded-xl border border-border bg-muted p-4 font-mono text-sm leading-relaxed text-foreground/80 whitespace-pre-wrap focus:border-transparent focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-border dark:bg-background dark:text-muted-foreground"
                    placeholder="在此编辑内容..."
                    autoFocus
                  />
                </div>
              ) : (
                <div className="flex h-full min-h-[520px] flex-col lg:flex-row">
                  {isPdf ? (
                    <div className="relative flex h-full min-h-0 w-full flex-col border-b border-border/70 bg-muted/70 dark:border-border/60 dark:bg-background/40 lg:w-1/2 lg:border-b-0 lg:border-r">
                      {layoutEntries.length > 0 ? (
                        <div className="border-b border-border/60 bg-background/88 px-4 py-2.5 dark:bg-background/72">
                          <div className="flex flex-wrap items-start justify-between gap-2.5">
                            <div className="min-w-0">
                              <div className="text-[11px] font-semibold tracking-[0.06em] text-foreground/78">
                                原始版面
                              </div>
                              <div className="mt-0.5 text-[11px] leading-5 text-muted-foreground/78">
                                <span className="font-medium text-foreground/72">版面图例</span>
                                <span className="mx-1.5 text-border">·</span>
                                点击右侧片段可定位到左侧 PDF 原页
                              </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-1.5">
                              {layoutLegendKinds.map((kind) => {
                                const meta = getParsingLayoutMeta(kind)
                                return (
                                  <span
                                    key={kind}
                                    className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-background/85 px-2 py-1 text-[10px] font-medium text-muted-foreground"
                                  >
                                    <span className={cn('h-1.5 w-1.5 rounded-full', meta.dotClassName)} />
                                    {meta.shortLabel}
                                  </span>
                                )
                              })}
                            </div>
                          </div>
                        </div>
                      ) : null}
                      <div className="min-h-0 flex-1">
                        <PdfViewer
                          key={pdfViewerKey}
                          file={activeFile.file}
                          blocks={activeBlocksWithPositions}
                          boxesByPage={pdfBoxesByPage}
                          blockIdToPageIndex={pdfBlockIdToPageIndex}
                          activeBlockIds={pdfActiveBlockIds}
                          hoveredBlockIds={hoveredBlockId ? [hoveredBlockId] : []}
                          onHoverBlockId={onHoveredBlockIdChange}
                          onClickBlockId={handleSelectPdfBlock}
                        />
                      </div>
                    </div>
                  ) : null}
                  <div className={isPdf ? 'w-full lg:w-1/2' : 'w-full'}>
                    {rightPanelMode === 'blocks' && layoutEntries.length > 0 ? (
                      <ParsingRightPanel className="h-full no-scrollbar p-4 lg:p-5">
                        <div className="overflow-hidden rounded-xl border border-border/60 bg-card/95">
                          <div className="border-b border-border/60 bg-background/82 px-4 py-3 dark:bg-background/72">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="min-w-0">
                                <div className="text-[11px] font-semibold tracking-[0.06em] text-foreground/78">
                                  版面定位流
                                </div>
                                <div className="mt-0.5 text-[11px] leading-5 text-muted-foreground/78">
                                  左侧显示原页框选，右侧按定位片段连续审阅
                                </div>
                              </div>
                              <div className="font-mono text-[10px] text-muted-foreground">
                                {layoutEntries.length} segments
                              </div>
                            </div>
                          </div>
                          <div className="divide-y divide-border/50">
                            {layoutEntries.map((entry, index) => {
                              const layoutMeta = getParsingLayoutMeta(entry.kind)
                              const isActive = entry.id === activeBlockId
                              return (
                                <button
                                  key={entry.id}
                                  type="button"
                                  onClick={() => handleSelectReviewBlock(entry.id)}
                                  onMouseEnter={() => onHoveredBlockIdChange(entry.id)}
                                  onMouseLeave={() => onHoveredBlockIdChange(null)}
                                  className={cn(
                                    'group w-full px-4 py-3 text-left transition',
                                    isActive ? 'bg-primary/5' : 'hover:bg-accent/25'
                                  )}
                                >
                                  <div className="flex items-start gap-3">
                                    <span className={cn('mt-1.5 h-1.5 w-1.5 flex-none rounded-full', layoutMeta.dotClassName)} />
                                    <div className="min-w-0 flex-1">
                                      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                                        <span
                                          className={cn(
                                            'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium',
                                            layoutMeta.chipClassName
                                          )}
                                        >
                                          {layoutMeta.label}
                                        </span>
                                        <span className="font-mono text-[10px] text-muted-foreground">
                                          片段 {index + 1}
                                        </span>
                                        {Number.isFinite(entry.pageIndex) ? (
                                          <span className="font-mono text-[10px] text-muted-foreground">
                                            页 {Number(entry.pageIndex) + 1}
                                          </span>
                                        ) : null}
                                        <span className="font-mono text-[10px] text-muted-foreground">
                                          {entry.charCount} 字
                                        </span>
                                        {entry.lineCount > 1 ? (
                                          <span className="font-mono text-[10px] text-muted-foreground">
                                            {entry.lineCount} 行
                                          </span>
                                        ) : null}
                                      </div>
                                      <div className="relative pl-3">
                                        <span
                                          className={cn(
                                            'absolute bottom-1 left-0 top-1 w-px rounded-full transition-colors',
                                            isActive ? 'bg-primary/45' : 'bg-border/50 group-hover:bg-border/70'
                                          )}
                                        />
                                        <div className="prose prose-slate prose-sm max-w-none prose-headings:mb-1 prose-headings:mt-0 prose-headings:text-foreground prose-p:my-0 prose-p:text-foreground/82 prose-a:text-sky-700 prose-code:rounded prose-code:bg-sky-500/10 prose-code:px-1 prose-code:py-0.5 prose-code:text-sky-700 prose-pre:my-1 prose-pre:bg-slate-900 prose-table:my-1 prose-table:border-collapse prose-td:border prose-td:border-sky-200 prose-td:p-2 prose-th:border prose-th:border-sky-200 prose-th:bg-sky-500/10 prose-th:p-2 dark:prose-invert dark:prose-headings:text-foreground dark:prose-p:text-muted-foreground dark:prose-a:text-sky-300 dark:prose-code:bg-muted dark:prose-code:text-sky-300 dark:prose-th:border-sky-500/30 dark:prose-th:bg-sky-500/20 dark:prose-td:border-sky-500/30">
                                          <MarkdownRenderer markdown={entry.text} />
                                        </div>
                                      </div>
                                    </div>
                                  </div>
                                </button>
                              )
                            })}
                          </div>
                        </div>
                      </ParsingRightPanel>
                    ) : (
                      <ParsingRightPanel
                        dragScroll={rightPanelMode === 'markdown'}
                        className="h-full no-scrollbar p-6 parsing-md-scroll"
                      >
                        {previewMode === 'rendered' ? (
                          <div className="flex gap-8">
                            <div className="prose prose-slate min-w-0 max-w-none flex-1 prose-headings:text-foreground prose-p:text-foreground/80 prose-a:text-sky-700 prose-code:rounded prose-code:bg-sky-500/10 prose-code:px-1 prose-code:py-0.5 prose-code:text-sky-700 prose-pre:bg-slate-900 prose-table:border-collapse prose-td:border prose-td:border-sky-200 prose-td:p-2 prose-th:border prose-th:border-sky-200 prose-th:bg-sky-500/10 prose-th:p-2 dark:prose-invert dark:prose-headings:text-foreground dark:prose-p:text-muted-foreground dark:prose-a:text-sky-300 dark:prose-code:bg-muted dark:prose-code:text-sky-300 dark:prose-th:border-sky-500/30 dark:prose-th:bg-sky-500/20 dark:prose-td:border-sky-500/30">
                              <MarkdownRenderer
                                markdown={activeMarkdown}
                                autoScrollToHash
                                scrollContainerSelector=".parsing-md-scroll"
                              />
                            </div>
                            {tocEnabled ? (
                              <aside className="hidden w-64 shrink-0 xl:block self-start sticky top-0">
                                <div className="max-h-[calc(100%-2rem)] overflow-y-auto overscroll-contain no-scrollbar pl-2">
                                  <MarkdownToc markdown={activeMarkdown} scrollContainerSelector=".parsing-md-scroll" />
                                </div>
                              </aside>
                            ) : null}
                          </div>
                        ) : (
                          <pre className="whitespace-pre-wrap rounded-xl border border-border bg-muted/70 p-6 font-mono text-sm leading-relaxed text-foreground/80 dark:border-border dark:bg-background/40 dark:text-muted-foreground">
                            {activeMarkdown}
                          </pre>
                        )}
                      </ParsingRightPanel>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {activeFile.status === 'parsed' && activeMarkdown ? (
          <div className="relative z-10 border-t border-border/75 bg-background/94 px-6 py-4 shadow-[0_-10px_24px_-18px_rgba(15,23,42,0.22)] backdrop-blur-xl dark:bg-background/88 dark:shadow-[0_-12px_28px_-18px_rgba(0,0,0,0.42)]">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-[11px] leading-5 text-muted-foreground/72 dark:text-muted-foreground/70">
                {isEditing ? '编辑完成后点击"保存修改"，然后提交到数据治理' : '确认解析内容无误后，提交到数据治理工作台'}
              </div>
              <div className="flex items-center gap-3">
                {submitToGovernanceButton}
              </div>
            </div>
          </div>
        ) : null}
      </>
    </>
  )
}
