'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { AlertCircle, ArrowRight, Blocks, Check, ChevronDown, Clock, Code, Copy, Download, Edit3, FileStack, FileText, Heading1, Image as ImageIcon, Layers, Loader2, MoreHorizontal, Play, RotateCcw, Save, Table2 } from '@/components/icons'

import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { AuthImage } from '@/components/auth-image'
import { ParsingElementsPanel } from '@/components/parsing/parsing-elements-panel'
import { ParsingExtractPanel } from '@/components/parsing/parsing-extract-panel'
import { ParsingRightPanel } from '@/components/parsing/parsing-right-panel'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { ParsingOriginalFile } from './parsing-original-file'
import styles from './parsing-compare.module.css'
import { Skeleton } from '@/components/ui/skeleton'
import {
 buildParsingLayoutEntries,
 getParsingLayoutMeta,
 type ParsingLayoutKind,
} from '@/lib/parsing-layout'
import { findEditSelectionForActiveParsingEntry, type ParsingEditFocusHint } from '@/lib/parsing-edit-focus'
import { cn } from '@/lib/utils'
import { extractRequestIdFromError } from '@/lib/api-errors'
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

type LayoutReviewEntry = {
 type: 'layout'
 entry: ReturnType<typeof buildParsingLayoutEntries>[number]
 layoutIndex: number
 sortPage: number
 sortTop: number
}

type ImageReviewEntry = {
 type: 'image'
 element: ParsingElement
 imageIndex: number
 pageIndex: number | null
 src: string
 sortPage: number
 sortTop: number
}

type ReviewEntry = LayoutReviewEntry | ImageReviewEntry

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


function buildQualityEvidenceSummary(qualityGate: unknown, pdfQuality: unknown): string {
 const pieces: string[] = []
 const gateEvidence = isRecord(qualityGate) && isRecord(qualityGate.evidence) ? qualityGate.evidence : {}
 const textQuality = isRecord(gateEvidence.text_quality) ? gateEvidence.text_quality : {}
 const parseQuality = isRecord(gateEvidence.parse_quality) ? gateEvidence.parse_quality : {}
 const parseQualityGate = isRecord(gateEvidence.parse_quality_gate) ? gateEvidence.parse_quality_gate : {}
 const parseQualityFlags = isRecord(parseQualityGate.flags) ? parseQualityGate.flags : {}
 const fallbackAttempts = Array.isArray(gateEvidence.fallback_attempts) ? gateEvidence.fallback_attempts : []
 const flagLabels: Record<string, string> = {
 parse_score_low: '解析分低',
 ocr_low_confidence: 'OCR低置信',
 table_structure_low_confidence: '表格结构低置信',
 reading_order_unstable: '版面顺序不稳',
 noise_removal_risky: '噪声清理风险',
 tag_sidecar_recommended: '建议TAG',
 }

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
 const activeFlags = Object.entries(parseQualityFlags)
 .filter(([, value]) => value === true)
 .map(([key]) => flagLabels[key] || key)
 if (activeFlags.length > 0) {
 pieces.push(`质量标记=${activeFlags.slice(0, 3).join('、')}`)
 }

 return pieces.join(' · ')
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

function getElementImageSrc(element: ParsingElement | null | undefined): string {
 if (!element || element.kind !== 'image') return ''
 const attributes = element.attributes as Record<string, unknown> | null
 const raw = attributes?.src || attributes?.image_src || attributes?.url
 return typeof raw === 'string' ? raw.trim() : ''
}

function readEvidenceRawPages(
 evidence: ParsingExtractEvidence | null | undefined,
 element: ParsingElement | null | undefined
): unknown[] {
 if (Array.isArray(element?.pages)) return element.pages
 if (Array.isArray(evidence?.pages)) return evidence.pages
 return []
}

function isPositiveIntegerPage(value: unknown): value is number {
 return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function filterPositiveIntegerPages(values: unknown[]): number[] {
 return values.filter(isPositiveIntegerPage)
}

function formatEvidencePages(
 evidence: ParsingExtractEvidence | null | undefined,
 element: ParsingElement | null | undefined
): string {
 const rawPages = readEvidenceRawPages(evidence, element)
 const pages = filterPositiveIntegerPages(rawPages)
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

function buildElementPageIndexes(element: ParsingElement): number[] {
 const rawPages = Array.isArray(element.pages)
 ? element.pages.filter((value) => Number.isInteger(value) && value > 0)
 : []
 if (rawPages.length > 0) {
 return rawPages.map((value) => Math.max(0, value - 1))
 }
 if (typeof element.page === 'number') {
 return [Math.max(0, element.page - 1)]
 }
 return []
}

function buildQualityEvidenceItems(summary: string): string[] {
 if (!summary) return []
 return summary.split(' · ').map((item) => item.trim()).filter(Boolean)
}

function getScrollBehavior(reduceMotion: boolean): ScrollBehavior {
 return reduceMotion ? 'auto' : 'smooth'
}

function buildParsedStatItems(activeFile: ParsedFile) {
 if (activeFile.status !== 'parsed' || !activeFile.stats) return []
 const pageCount =
 typeof activeFile.stats.pageCount === 'number' && activeFile.stats.pageCount > 0
 ? activeFile.stats.pageCount
 : '-'
 const duration =
 typeof activeFile.duration === 'number' && Number.isFinite(activeFile.duration)
 ? `${activeFile.duration}s`
 : '-'
 return [
 { icon: FileText, label: '字符', value: activeFile.stats.charCount.toLocaleString() },
 { icon: FileStack, label: '行数', value: activeFile.stats.lineCount.toLocaleString() },
 { icon: Heading1, label: '标题', value: (activeFile.stats.headingCount || 0).toLocaleString() },
 { icon: Layers, label: '页数', value: pageCount },
 { icon: Blocks, label: '定位块', value: Math.floor(activeFile.stats.blockCount || 0) },
 { icon: Table2, label: '表格', value: Math.floor(activeFile.stats.tableCount || 0) },
 { icon: ImageIcon, label: '图片', value: activeFile.stats.imageCount || 0 },
 { icon: Clock, label: '耗时', value: duration },
 ]
}



function buildExtractEvidencePosition(
 evidence: ParsingExtractEvidence | null | undefined,
 element: ParsingElement | null | undefined
): ParsingPosition | null {
 const rawPages = readEvidenceRawPages(evidence, element)
 const pages = filterPositiveIntegerPages(rawPages)
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

type ParsingActiveFilePaneProps = {
 activeFile: ParsedFile
 activeRun: ParseRun | null
 activeMarkdown: string
 activeElements?: ParsingElement[]
 activeQualityGate: unknown
 activePdfQuality: unknown
 activeBlocksWithPositions: ParsingBlock[]
 isPdf: boolean
 tocEnabled?: boolean
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
 onSaveEdit: () => void | Promise<void>
 onCopyMarkdown: () => void
 onDownloadMarkdown: () => void
 onParseFile: (fileId: string, backend?: string) => void
 pdfPreviewResetToken: number
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
 onSubmitToGovernance,
 onEditedContentChange,
 onActiveBlockIdChange,
 onHoveredBlockIdChange,
}: Readonly<ParsingActiveFilePaneProps>) {
 const [compareOpen, setCompareOpen] = useState(false)
 const [resourceView, setResourceView] = useState(false)
 const [narrowView, setNarrowView] = useState<'source' | 'result'>('result')
 const [savePending, setSavePending] = useState(false)
 const [activePdfEditHint, setActivePdfEditHint] = useState<{
 blockId: string
 hint: ParsingEditFocusHint
 } | null>(null)
 const [selectedExtractEvidence, setSelectedExtractEvidence] = useState<{
 fieldName: string
 evidence: ParsingExtractEvidence
 } | null>(null)
 const editorRef = useRef<HTMLTextAreaElement | null>(null)
 const layoutReviewCardRefs = useRef<Map<string, HTMLButtonElement>>(new Map())
 const didInitializeEditSelectionRef = useRef(false)
 const pdfViewerKey = `${activeFile.id}:${activeFile.activeRunId || activeRun?.id || 'default'}:${pdfPreviewResetToken}`
 const qualityGrade = getQualityGateGrade(activeQualityGate)
 const qualityReasons = getQualityGateReasons(activeQualityGate)
 const qualityEvidenceSummary = buildQualityEvidenceSummary(activeQualityGate, activePdfQuality)
 const qualityEvidenceItems = buildQualityEvidenceItems(qualityEvidenceSummary)
 const layoutEntries = useMemo(() => buildParsingLayoutEntries(activeBlocksWithPositions), [activeBlocksWithPositions])
 const elementOverlayItems = useMemo(() => {
 return (activeElements || [])
 .map((element) => {
 const bbox = element.bbox
 if (!bbox) return null
 const pages = buildElementPageIndexes(element)
 if (pages.length === 0) return null
 return {
 id: String(element.id || '').trim(),
 kind: toLayoutKind(element.kind),
 position: {
 pages,
 left: bbox.x0,
 right: bbox.x1,
 top: bbox.y0,
 bottom: bbox.y1,
 raw: `element:${String(element.id || '')}`,
 },
 }
 })
 .filter((item): item is { id: string; kind: ParsingLayoutKind; position: ParsingPosition } => Boolean(item?.id))
 }, [activeElements])
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
 const fallbackElementBoxesByPage = useMemo(() => {
 const next = new Map<number, Array<{ id: string; kind: ParsingLayoutKind; position: ParsingPosition }>>()
 for (const entry of elementOverlayItems) {
 const pageIndex = entry.position.pages[0]
 if (typeof pageIndex !== 'number') continue
 const list = next.get(pageIndex) || []
 list.push(entry)
 next.set(pageIndex, list)
 }
 return next
 }, [elementOverlayItems])
 const layoutEntryIdToPageIndex = useMemo(() => {
 const next = new Map<string, number>()
 for (const entry of layoutEntries) {
 if (entry.pageIndex == null) continue
 next.set(entry.id, entry.pageIndex)
 }
 return next
 }, [layoutEntries])
 const fallbackElementIdToPageIndex = useMemo(() => {
 const next = new Map<string, number>()
 for (const entry of elementOverlayItems) {
 const pageIndex = entry.position.pages[0]
 if (typeof pageIndex !== 'number') continue
 next.set(entry.id, pageIndex)
 }
 return next
 }, [elementOverlayItems])
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
 const basePdfBoxesByPage = useMemo(() => {
 if (layoutBoxesByPage.size > 0) return layoutBoxesByPage
 return fallbackElementBoxesByPage
 }, [fallbackElementBoxesByPage, layoutBoxesByPage])
 const pdfBoxesByPage = useMemo(() => {
 if (!selectedExtractOverlayId || !selectedExtractEvidence) return basePdfBoxesByPage
 const position = buildExtractEvidencePosition(selectedExtractEvidence.evidence, selectedExtractElement)
 if (!position) return basePdfBoxesByPage
 const pageIndex = position.pages[0] ?? 0
 const next = new Map(basePdfBoxesByPage)
 const list = [...(next.get(pageIndex) || [])]
 list.push({
 id: selectedExtractOverlayId,
 kind: toLayoutKind(selectedExtractElement?.kind || selectedExtractEvidence.evidence.kind),
 position,
 })
 next.set(pageIndex, list)
 return next
 }, [basePdfBoxesByPage, selectedExtractElement, selectedExtractEvidence, selectedExtractOverlayId])
 const basePdfBlockIdToPageIndex = useMemo(() => {
 if (layoutEntryIdToPageIndex.size > 0) return layoutEntryIdToPageIndex
 return fallbackElementIdToPageIndex
 }, [fallbackElementIdToPageIndex, layoutEntryIdToPageIndex])
 const pdfBlockIdToPageIndex = useMemo(() => {
 if (!selectedExtractOverlayId || !selectedExtractEvidence) return basePdfBlockIdToPageIndex
 const position = buildExtractEvidencePosition(selectedExtractEvidence.evidence, selectedExtractElement)
 if (!position) return basePdfBlockIdToPageIndex
 const next = new Map(basePdfBlockIdToPageIndex)
 next.set(selectedExtractOverlayId, position.pages[0] ?? 0)
 return next
 }, [basePdfBlockIdToPageIndex, selectedExtractElement, selectedExtractEvidence, selectedExtractOverlayId])
 const pdfActiveBlockIds = useMemo(() => {
 const ids: string[] = []
 if (selectedExtractOverlayId) ids.push(selectedExtractOverlayId)
 if (activeBlockId) ids.push(activeBlockId)
 return ids
 }, [activeBlockId, selectedExtractOverlayId])

 const handleSelectPdfBlock = (blockId: string, hint?: ParsingEditFocusHint) => {
 const hasLayoutEntry = layoutEntries.some((entry) => entry.id === blockId)
 const fallbackElement = (activeElements || []).find((element) => String(element.id || '').trim() === blockId)
 if (fallbackElement && !hasLayoutEntry) {
 handleSelectElement(fallbackElement)
 return
 }
 setActivePdfEditHint(hint ? { blockId, hint } : null)
 if (hasLayoutEntry) {
 setResourceView(false)
 onRightPanelModeChange('blocks')
 }
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
 setResourceView(false)
 }, [activeFile.id, activeRun?.id])

 useEffect(() => {
 if (!activeBlockId || rightPanelMode !== 'blocks') return
 const targetCard = layoutReviewCardRefs.current.get(activeBlockId)
 if (!targetCard) return
 if (typeof targetCard.scrollIntoView !== 'function') return
 const reduceMotion =
 globalThis.window !== undefined &&
 typeof globalThis.window.matchMedia === 'function' &&
 globalThis.window.matchMedia('(prefers-reduced-motion: reduce)').matches
 targetCard.scrollIntoView({
 behavior: getScrollBehavior(reduceMotion),
 block: 'nearest',
 inline: 'nearest',
 })
 }, [activeBlockId, layoutEntries, rightPanelMode])

 const activeImageElements = useMemo(
 () => (activeElements || []).filter((element) => element.kind === 'image'),
 [activeElements]
 )
 const imageReviewEntries = useMemo<ImageReviewEntry[]>(
 () =>
 activeImageElements.map((element, index) => {
 const pageIndexes = buildElementPageIndexes(element)
 const pageIndex = pageIndexes[0] ?? null
 const src = getElementImageSrc(element)
 return {
 type: 'image',
 element,
 imageIndex: index,
 pageIndex,
 src,
 sortPage: pageIndex ?? Number.MAX_SAFE_INTEGER,
 sortTop: element.bbox?.y0 ?? Number.MAX_SAFE_INTEGER,
 }
 }),
 [activeImageElements]
 )
 const reviewEntries = useMemo<ReviewEntry[]>(() => {
 const layoutReviewEntries: LayoutReviewEntry[] = layoutEntries.map((entry, index) => ({
 type: 'layout',
 entry,
 layoutIndex: index,
 sortPage: entry.pageIndex ?? Number.MAX_SAFE_INTEGER,
 sortTop: entry.position.top,
 }))

 return [...layoutReviewEntries, ...imageReviewEntries].sort((left, right) => {
 if (left.sortPage !== right.sortPage) return left.sortPage - right.sortPage
 if (left.sortTop !== right.sortTop) return left.sortTop - right.sortTop
 if (left.type !== right.type) return left.type === 'layout' ? -1 : 1
 const leftIndex = left.type === 'layout' ? left.layoutIndex : left.imageIndex
 const rightIndex = right.type === 'layout' ? right.layoutIndex : right.imageIndex
 return leftIndex - rightIndex
 })
 }, [imageReviewEntries, layoutEntries])

 const resultReady = activeFile.status === 'parsed' && Boolean(activeMarkdown)
 const failureRequestId = extractRequestIdFromError(activeFile.error)
 const failureMessage = (activeFile.error || '未能完成解析，请重试。').replace(/\s*[（(]?\brequest_id=[A-Za-z0-9._:-]+[）)]?/g, '').trim()
 const stats = buildParsedStatItems(activeFile).filter((item) => ['字符', '标题', '表格', '图片', '耗时'].includes(item.label))
 const resultTab = resourceView ? 'resources' : rightPanelMode
 const selectResultTab = (tab: 'markdown' | 'blocks' | 'resources') => {
   setResourceView(tab === 'resources')
   if (tab !== 'blocks') {
     onActiveBlockIdChange(null)
     onHoveredBlockIdChange(null)
   }
   if (tab !== 'resources') onRightPanelModeChange(tab)
 }
 const save = async () => {
   setSavePending(true)
   try { await onSaveEdit() } finally { setSavePending(false) }
 }

 return (
   <>
     <ParseCompareDialog open={compareOpen} onOpenChange={setCompareOpen} runs={activeFile.runs || []} defaultBaseRunId={activeFile.activeRunId || activeRun?.id || null} onUseRun={(runId) => { onSelectRun(runId); setCompareOpen(false) }} />
     <div className={styles.mobileTabs} role="group" aria-label="核对视图">
       <span className={styles.mobileIndicator} style={{ transform: narrowView === 'source' ? 'translateX(0)' : 'translateX(100%)' }} />
       <button type="button" aria-pressed={narrowView === 'source'} onClick={() => setNarrowView('source')}>原文</button>
       <button type="button" aria-pressed={narrowView === 'result'} onClick={() => setNarrowView('result')}>解析结果</button>
     </div>
     <div className={styles.workspace} data-narrow-view={narrowView} data-testid="parsing-compare-workspace">
       <section className={styles.source} aria-label="原文">
         {isPdf ? <PdfViewer key={pdfViewerKey} file={activeFile.file} showToolbar
           showAllBoxes={rightPanelMode === 'blocks' && !resourceView}
           blocks={activeBlocksWithPositions} boxesByPage={pdfBoxesByPage} blockIdToPageIndex={pdfBlockIdToPageIndex}
           activeBlockIds={pdfActiveBlockIds} hoveredBlockIds={hoveredBlockId ? [hoveredBlockId] : []}
           onHoverBlockId={onHoveredBlockIdChange} onClickBlockId={handleSelectPdfBlock}
         /> : <ParsingOriginalFile file={activeFile.file} />}
       </section>

       <section className={styles.result} aria-label="解析结果">
         <div className={styles.resultToolbar}>
           <div className={styles.resultTabs} role="group" aria-label="结果视图">
             {([{ id: 'markdown', label: 'Markdown' }, { id: 'blocks', label: '内容块' }, { id: 'resources', label: '提取资源' }] as const).map((tab) =>
               <button key={tab.id} type="button" disabled={!resultReady || isEditing} aria-pressed={resultTab === tab.id} onClick={() => selectResultTab(tab.id)}>
                 {tab.label}{tab.id === 'blocks' && layoutEntries.length ? <span>{layoutEntries.length}</span> : null}
               </button>
             )}
           </div>
           {resultReady ? <div className={styles.resultActions}>
             {!isEditing ? <>
               {resultTab === 'markdown' ? <Button size="icon" variant="ghost" className="size-8" aria-label={previewMode === 'raw' ? '预览 Markdown' : '查看 Markdown 源码'} aria-pressed={previewMode === 'raw'} title={previewMode === 'raw' ? '预览' : '源码'} onClick={() => onPreviewModeChange(previewMode === 'raw' ? 'rendered' : 'raw')}><Code className="size-4" /></Button> : null}
               <Button size="icon" variant="ghost" className="size-8" aria-label={copied ? '已复制 Markdown' : '复制 Markdown'} title="复制" onClick={onCopyMarkdown}>{copied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}</Button>
               <Button size="icon" variant="ghost" className="size-8" aria-label="下载 Markdown" title="下载" onClick={onDownloadMarkdown}><Download className="size-4" /></Button>
               <DropdownMenu>
                 <DropdownMenuTrigger asChild><Button size="icon" variant="ghost" className="size-8" aria-label="更多结果操作"><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger>
                 <DropdownMenuContent align="end" className="w-60">
                   <DropdownMenuItem onSelect={onStartEdit}><Edit3 className="mr-2 size-4" />{rightPanelMode === 'blocks' && activeBlockId ? '编辑选中内容块' : '编辑 Markdown'}</DropdownMenuItem>
                   {activeFile.runs && activeFile.runs.length > 1 ? <>
                     <DropdownMenuSeparator />
                     <label className="block px-2 py-1.5 text-xs text-muted-foreground" htmlFor="parsing-run">解析版本</label>
                     <select id="parsing-run" className={styles.runSelect} value={activeRun?.id || activeFile.activeRunId || ''} onChange={(event) => onSelectRun(event.target.value)}>
                       {activeFile.runs.map((run) => <option key={run.id} value={run.id}>{run.parserLabel}{run.createdAt ? ' · ' + new Date(run.createdAt).toLocaleTimeString() : ''}</option>)}
                     </select>
                     <DropdownMenuItem onSelect={() => setCompareOpen(true)}><FileStack className="mr-2 size-4" />对比解析版本</DropdownMenuItem>
                   </> : null}
                 </DropdownMenuContent>
               </DropdownMenu>
             </> : <span className="px-2 text-xs text-muted-foreground">编辑中</span>}
           </div> : null}
         </div>

         {!resultReady ? <div className={styles.resultState} role={activeFile.status === 'error' ? 'alert' : 'status'}>
           {activeFile.status === 'parsing' ? <>
             <Loader2 className="size-7 animate-spin text-info motion-reduce:animate-none" />
             <h2>正在解析</h2><p>{activeFile.parserLabel} · {Math.round(activeFile.progress || 0)}%</p>
             <div className={styles.progress} role="progressbar" aria-label="解析进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(activeFile.progress || 0)}><span style={{ width: Math.min(100, Math.max(0, activeFile.progress || 0)) + '%' }} /></div>
           </> : activeFile.status === 'error' ? <>
             <AlertCircle className="size-7 text-destructive" /><h2>解析失败</h2><p>{failureMessage}</p>
             <Button className="gap-2" onClick={() => onParseFile(activeFile.id, activeFile.parserBackend)}><RotateCcw className="size-4" />重试解析</Button>
             {failureRequestId ? <details className={styles.diagnostics}><summary>请求详情</summary><p className="font-mono">request_id={failureRequestId}</p></details> : null}
             {activeFile.parseDiagnostics?.suggested_backends?.length ? <div className={styles.recovery}>
               {activeFile.parseDiagnostics.suggested_backends.slice(0, 6).map((backend) => <Button key={backend} size="sm" variant="outline" onClick={() => onParseFile(activeFile.id, backend)}>用 {getParserLabel(resolveParserBackendForFilename(activeFile.file.name, backend).backend)} 重试</Button>)}
             </div> : null}
             {activeFile.parseDiagnostics?.pdf_sample ? <details className={styles.diagnostics}><summary>查看 PDF 诊断</summary>
               <p>{activeFile.parseDiagnostics.pdf_sample.page_count || '–'} 页{activeFile.parseDiagnostics.pdf_sample.is_scanned ? ' · 可能为扫描件' : ''}</p>
               {activeFile.parseDiagnostics.pdf_sample.samples?.slice(0, 3).map((sample) => <p key={sample.page}>第 {sample.page} 页 · {sample.text_chars} 字符<br />{sample.excerpt || '未检测到可选文字'}</p>)}
             </details> : null}
           </> : <>
             <FileText className="size-7 text-muted-foreground" /><h2>{activeFile.status === 'parsed' ? '没有可用的解析内容' : '文档已就绪'}</h2>
             <p>{activeFile.status === 'parsed' ? '请检查原文，或更换解析器重新运行。' : '选择解析器，开始提取文档内容。'}</p>
             <Button className="gap-2" onClick={() => onParseFile(activeFile.id, activeFile.parserBackend)}><Play className="size-4" />开始解析</Button>
           </>}
         </div> : isEditing ? <div className={styles.editor}>
           <textarea ref={editorRef} aria-label="编辑 Markdown" value={editedContent} disabled={savePending} onChange={(event) => onEditedContentChange(event.target.value)} spellCheck={false} />
         </div> : resourceView ? <div className={styles.resourceBody}>
           {selectedExtractEvidence ? <div className={styles.evidence}>
             <span>{selectedExtractEvidence.fieldName} · {formatEvidencePages(selectedExtractEvidence.evidence, selectedExtractElement)}</span>
             <span>{selectedExtractElement?.text || selectedExtractEvidence.evidence.text}</span>
             <Button size="sm" variant="ghost" onClick={() => setNarrowView('source')}>查看原文</Button>
           </div> : null}
           <ParsingExtractPanel documentId={activeFile.libraryId || null} activeElements={activeElements} onSelectEvidence={handleSelectExtractEvidence} className="bg-background" />
           <ParsingElementsPanel elements={activeElements} onSelectElement={handleSelectElement} />
         </div> : rightPanelMode === 'blocks' ? <ParsingRightPanel className={styles.blockBody}>
           {reviewEntries.length ? reviewEntries.map((reviewEntry, index) => {
             const id = reviewEntry.type === 'layout' ? reviewEntry.entry.id : String(reviewEntry.element.id || '')
             const isActive = reviewEntry.type === 'layout' ? id === activeBlockId : String(selectedExtractElement?.id || '') === id
             const meta = reviewEntry.type === 'layout' ? getParsingLayoutMeta(reviewEntry.entry.kind) : getParsingLayoutMeta('image')
             return <button key={reviewEntry.type + ':' + id + ':' + index} ref={(node) => { if (node) layoutReviewCardRefs.current.set(id, node); else layoutReviewCardRefs.current.delete(id) }}
               data-layout-entry-id={id} type="button" className={styles.blockRow} aria-pressed={isActive}
               onClick={() => reviewEntry.type === 'layout' ? handleSelectReviewBlock(id) : handleSelectElement(reviewEntry.element)}
               onMouseEnter={() => onHoveredBlockIdChange(id)} onMouseLeave={() => onHoveredBlockIdChange(null)}>
               <div className={styles.blockMeta}><span className={cn('size-1.5 rounded-full', meta.dotClassName)} /><strong>{meta.label}</strong>
                 <span>{reviewEntry.type === 'layout' && reviewEntry.entry.pageIndex != null ? '第 ' + (reviewEntry.entry.pageIndex + 1) + ' 页' : reviewEntry.type === 'image' ? formatElementPages(reviewEntry.element) : '无页码'}</span>
                 <span className="ml-auto">{reviewEntry.type === 'layout' ? reviewEntry.entry.charCount + ' 字' : reviewEntry.element.bbox ? '可定位' : '无坐标'}</span>
               </div>
               {reviewEntry.type === 'layout' ? <div className={styles.markdown}><MarkdownRenderer markdown={reviewEntry.entry.text} /></div> : <div className={styles.imageEntry}>
                 {reviewEntry.src ? <AuthImage src={reviewEntry.src} alt={String(reviewEntry.element.text || '文档图片')} width={280} height={200} unoptimized className="max-h-40 w-full object-contain" /> : <ImageIcon className="size-7 text-muted-foreground" />}
                 <span>{reviewEntry.element.text || '图片 ' + (reviewEntry.imageIndex + 1)}</span>
               </div>}
             </button>
           }) : <div className={styles.empty}><Blocks className="size-6 text-muted-foreground" /><h2>没有可定位的内容块</h2><p>可以切换到 Markdown 查看解析内容。</p></div>}
         </ParsingRightPanel> : <ParsingRightPanel dragScroll className={cn(styles.markdownBody, 'parsing-md-scroll')}>
           {previewMode === 'raw' ? <pre className={styles.raw}>{activeMarkdown}</pre> : <article className={styles.markdown}><MarkdownRenderer markdown={activeMarkdown} autoScrollToHash scrollContainerSelector=".parsing-md-scroll" /></article>}
         </ParsingRightPanel>}

         {resultReady && !isEditing && activeQualityGate && qualityGrade !== 'pass' ? <details className={cn(styles.quality, qualityGrade === 'fail' && styles.qualityFail)}>
           <summary><AlertCircle className="size-3.5 shrink-0" /><span>{qualityGrade === 'fail' ? '解析质量未通过检查' : '解析内容需要核对'}</span><ChevronDown className="ml-auto size-3.5" /></summary>
           <div><p>{qualityReasons.join(' · ') || '请对照原文检查解析结果。'}</p>{qualityEvidenceItems.length ? <p>{qualityEvidenceItems.join(' · ')}</p> : null}</div>
         </details> : null}
       </section>
     </div>

     {resultReady || isEditing ? <footer className={styles.footer}>
       <div className={styles.stats}>{isEditing ? <span>正在编辑{rightPanelMode === 'blocks' && activeBlockId ? '内容块' : ' Markdown'}</span> : resultReady ? <>
         {layoutEntries.length > 0 ? <span><Blocks className="size-3.5" /><b>{layoutEntries.length}</b> 个内容块</span> : null}
         {stats.map(({ label, value }) => <span key={label}>{label} <b>{value}</b></span>)}
       </> : <span>{activeFile.parserLabel}</span>}</div>
       <div className={styles.footerActions}>{isEditing ? <>
         <Button variant="ghost" size="sm" disabled={savePending} onClick={onCancelEdit}>取消</Button>
         <Button size="sm" disabled={savePending} className="gap-2" onClick={() => void save()}>{savePending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}{savePending ? '正在保存' : '保存修改'}</Button>
       </> : resultReady ? <Button variant="outline" size="sm" className="gap-2" onClick={onSubmitToGovernance}><ArrowRight className="size-4" />继续数据治理</Button> : null}</div>
     </footer> : null}
   </>
 )
}
