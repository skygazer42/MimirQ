'use client'

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import dynamic from 'next/dynamic'
import {
  AlertCircle,
  ArrowRight,
  Blocks,
  Check,
  Code,
  Copy,
  Download,
  Edit3,
  FileStack,
  FileText,
  Image as ImageIcon,
  Loader2,
  MoreHorizontal,
  Play,
  RotateCcw,
  Save,
} from '@/components/icons'

import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { AuthImage } from '@/components/auth-image'
import { ParsingElementsPanel } from '@/components/parsing/parsing-elements-panel'
import { ParsingExtractPanel, type ParsingEvidenceSelection } from '@/components/parsing/parsing-extract-panel'
import { ParsingRightPanel } from '@/components/parsing/parsing-right-panel'
import { ParsingQualityNotice } from './parsing-quality-notice'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ParsingOriginalFile } from './parsing-original-file'
import styles from './parsing-compare.module.css'
import { Skeleton } from '@/components/ui/skeleton'
import { buildParsingLayoutEntries, getParsingLayoutMeta } from '@/lib/parsing-layout'
import {
  formatParsingPages,
  getParsingElementImageSource,
  getParsingElementLayoutKind,
  getParsingPages,
} from '@/lib/parsing-elements'
import { findEditSelectionForActiveParsingEntry, type ParsingEditFocusHint } from '@/lib/parsing-edit-focus'
import { cn } from '@/lib/utils'
import { extractRequestIdFromError } from '@/lib/api-errors'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import type { ParsingElement, ParsingExtractEvidence } from '@/lib/api/parsing'
import type { ParsingBlock, ParsingPosition } from '@/lib/parsing-positions'
import type { BboxOverlayItem } from './bbox-overlay'

import type { ParsedFile, ParseRun, ParsingStatistics } from './parsing-types'
import { getParsingRunStatistics } from './parsing-page-utils'

const ParseCompareDialog = dynamic(
  () => import('@/components/parsing/parse-compare-dialog').then((mod) => mod.ParseCompareDialog),
  {
    loading: () => null,
  },
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
  src: string | null
  sortPage: number
  sortTop: number
}

type ReviewEntry = LayoutReviewEntry | ImageReviewEntry

type EvidenceTarget =
  { origin: 'element'; elementId: string } | { origin: 'extraction'; payload: ParsingEvidenceSelection }

type ScopedEvidenceTarget = EvidenceTarget & {
  fileId: string
  documentId: string | undefined
  runId: string | undefined
  viewMarkdown: string
}

function getScrollBehavior(reduceMotion: boolean): ScrollBehavior {
  return reduceMotion ? 'auto' : 'smooth'
}

function buildParsedStatItems(stats: ParsingStatistics | undefined, durationSec: number | undefined) {
  if (stats === undefined) return []
  const duration = durationSec !== undefined && Number.isFinite(durationSec) ? `${durationSec}s` : '未提供'
  return [
    { label: '字符', value: stats.charCount.toLocaleString() },
    { label: '标题', value: stats.headingCount.toLocaleString() },
    { label: '表格', value: stats.tableCount === undefined ? '未提供' : stats.tableCount.toLocaleString() },
    { label: '图片', value: stats.imageCount === undefined ? '未提供' : stats.imageCount.toLocaleString() },
    { label: '耗时', value: duration },
  ]
}

function buildExtractEvidencePosition(evidence: ParsingExtractEvidence): ParsingPosition | null {
  const pages = getParsingPages(evidence)
  const bbox = evidence.bbox
  if (bbox === undefined || bbox === null || pages.length === 0) return null
  return {
    pages: pages.map((page) => page - 1),
    left: bbox.x0,
    right: bbox.x1,
    top: bbox.y0,
    bottom: bbox.y1,
    raw: 'extract-evidence',
  }
}

type ParsingActiveFilePaneProps = {
  activeFile: ParsedFile
  activeRun: ParseRun | null
  isRunUnavailable: boolean
  activeMarkdown: string
  contentFeedback: ReactNode
  activeElements: ParsingElement[]
  activeQualityGate: unknown
  activePdfQuality: unknown
  activeBlocksWithPositions: ParsingBlock[]
  isPdf: boolean
  tocEnabled?: boolean
  previewMode: 'raw' | 'rendered'
  rightPanelMode: 'blocks' | 'markdown'
  isEditing: boolean
  isSubmittingGovernance: boolean
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
  onSubmitToGovernance: () => Promise<void>
  onEditedContentChange: (value: string) => void
  onActiveBlockIdChange: (blockId: string | null) => void
  onHoveredBlockIdChange: (blockId: string | null) => void
}

export function ParsingActiveFilePane({
  activeFile,
  activeRun,
  isRunUnavailable,
  activeMarkdown,
  contentFeedback,
  activeElements,
  activeQualityGate,
  activePdfQuality,
  activeBlocksWithPositions,
  isPdf,

  previewMode,
  rightPanelMode,
  isEditing,
  isSubmittingGovernance,
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
  const [evidenceSelection, setEvidenceSelection] = useState<ScopedEvidenceTarget | null>(null)
  const selectedExtractEvidence = useMemo<
    (ParsingEvidenceSelection & { origin: EvidenceTarget['origin'] }) | null
  >(() => {
    if (
      evidenceSelection === null ||
      evidenceSelection.fileId !== activeFile.id ||
      evidenceSelection.documentId !== activeFile.libraryId ||
      evidenceSelection.runId !== activeRun?.id ||
      evidenceSelection.viewMarkdown !== activeMarkdown
    )
      return null
    if (evidenceSelection.origin === 'extraction') {
      return {
        origin: 'extraction',
        fieldName: evidenceSelection.payload.fieldName,
        evidence: evidenceSelection.payload.evidence,
      }
    }
    const elementId = evidenceSelection.elementId
    const element = activeElements.find((item) => item.id === elementId)
    if (element === undefined) return null
    return {
      origin: 'element',
      fieldName: 'element',
      evidence: {
        element_id: element.id,
        kind: element.kind,
        page: element.page,
        pages: element.pages,
        visual_kind: element.visual_kind,
        bbox: element.bbox,
        text: element.text,
        score: element.confidence,
      },
    }
  }, [activeElements, activeFile.id, activeFile.libraryId, activeMarkdown, activeRun?.id, evidenceSelection])
  const editorRef = useRef<HTMLTextAreaElement | null>(null)
  const layoutReviewCardRefs = useRef<Map<string, HTMLDivElement>>(new Map())
  const didInitializeEditSelectionRef = useRef(false)
  const pdfViewerKey = JSON.stringify([activeFile.id, pdfPreviewResetToken])
  const layoutEntries = useMemo(() => buildParsingLayoutEntries(activeBlocksWithPositions), [activeBlocksWithPositions])
  const elementOverlayItems = useMemo(() => {
    const items: BboxOverlayItem[] = []
    for (const element of activeElements) {
      const bbox = element.bbox
      if (bbox === null || bbox === undefined) continue
      const pages = getParsingPages(element)
      if (pages.length === 0) continue
      items.push({
        id: element.id,
        kind: getParsingElementLayoutKind(element.kind),
        position: {
          pages: pages.map((page) => page - 1),
          left: bbox.x0,
          right: bbox.x1,
          top: bbox.y0,
          bottom: bbox.y1,
          raw: `element:${element.id}`,
        },
      })
    }
    return items
  }, [activeElements])
  const layoutBoxesByPage = useMemo(() => {
    const next = new Map<number, BboxOverlayItem[]>()
    for (const entry of layoutEntries) {
      if (entry.pageIndex === null) continue
      const item = { id: entry.id, kind: entry.kind, position: entry.position }
      const list = next.get(entry.pageIndex)
      if (list === undefined) next.set(entry.pageIndex, [item])
      else list.push(item)
    }
    return next
  }, [layoutEntries])
  const fallbackElementBoxesByPage = useMemo(() => {
    const next = new Map<number, BboxOverlayItem[]>()
    for (const entry of elementOverlayItems) {
      const pageIndex = entry.position.pages[0]
      const list = next.get(pageIndex)
      if (list === undefined) next.set(pageIndex, [entry])
      else list.push(entry)
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
        isEditing ? editedContent : activeMarkdown,
        layoutEntries,
        activeBlockId,
        activePdfEditHint?.blockId === activeBlockId ? activePdfEditHint.hint : null,
      ),
    [activeBlockId, activeMarkdown, activePdfEditHint, editedContent, isEditing, layoutEntries],
  )
  const selectedEvidencePosition = useMemo(
    () => (selectedExtractEvidence === null ? null : buildExtractEvidencePosition(selectedExtractEvidence.evidence)),
    [selectedExtractEvidence],
  )
  const selectedExtractOverlayId = useMemo(() => {
    if (selectedExtractEvidence === null || selectedEvidencePosition === null) return null
    const targetId = selectedExtractEvidence.evidence.element_id
    return JSON.stringify([
      'evidence',
      selectedExtractEvidence.origin,
      selectedExtractEvidence.fieldName,
      targetId,
      selectedEvidencePosition.pages,
      selectedEvidencePosition.left,
      selectedEvidencePosition.right,
      selectedEvidencePosition.top,
      selectedEvidencePosition.bottom,
    ])
  }, [selectedEvidencePosition, selectedExtractEvidence])
  const basePdfBoxesByPage = useMemo(() => {
    if (layoutBoxesByPage.size > 0) return layoutBoxesByPage
    return fallbackElementBoxesByPage
  }, [fallbackElementBoxesByPage, layoutBoxesByPage])
  const pdfBoxesByPage = useMemo(() => {
    if (selectedExtractOverlayId === null || selectedExtractEvidence === null || selectedEvidencePosition === null)
      return basePdfBoxesByPage
    const pageIndex = selectedEvidencePosition.pages[0]
    const next = new Map(basePdfBoxesByPage)
    const item: BboxOverlayItem = {
      id: selectedExtractOverlayId,
      kind: getParsingElementLayoutKind(selectedExtractEvidence.evidence.kind),
      position: selectedEvidencePosition,
    }
    const list = next.get(pageIndex)
    next.set(pageIndex, list === undefined ? [item] : [...list, item])
    return next
  }, [basePdfBoxesByPage, selectedEvidencePosition, selectedExtractEvidence, selectedExtractOverlayId])
  const basePdfBlockIdToPageIndex = useMemo(() => {
    if (layoutEntryIdToPageIndex.size > 0) return layoutEntryIdToPageIndex
    return fallbackElementIdToPageIndex
  }, [fallbackElementIdToPageIndex, layoutEntryIdToPageIndex])
  const pdfBlockIdToPageIndex = useMemo(() => {
    if (selectedExtractOverlayId === null || selectedEvidencePosition === null) return basePdfBlockIdToPageIndex
    const next = new Map(basePdfBlockIdToPageIndex)
    next.set(selectedExtractOverlayId, selectedEvidencePosition.pages[0])
    return next
  }, [basePdfBlockIdToPageIndex, selectedEvidencePosition, selectedExtractOverlayId])
  const pdfActiveBlockIds = useMemo(() => {
    const ids: string[] = []
    if (selectedExtractOverlayId) ids.push(selectedExtractOverlayId)
    if (activeBlockId) ids.push(activeBlockId)
    return ids
  }, [activeBlockId, selectedExtractOverlayId])

  const handleSelectPdfBlock = (blockId: string, hint?: ParsingEditFocusHint) => {
    if (blockId === selectedExtractOverlayId) {
      setResourceView(true)
      setNarrowView('source')
      return
    }
    const hasLayoutEntry = layoutEntries.some((entry) => entry.id === blockId)
    const fallbackElement = activeElements.find((element) => element.id === blockId)
    if (fallbackElement && !hasLayoutEntry) {
      handleSelectElement(fallbackElement)
      return
    }
    setEvidenceSelection(null)
    setActivePdfEditHint(hint === undefined ? null : { blockId, hint })
    if (hasLayoutEntry) {
      setResourceView(false)
      onRightPanelModeChange('blocks')
    }
    onActiveBlockIdChange(blockId)
  }

  const handleSelectReviewBlock = (blockId: string) => {
    setEvidenceSelection(null)
    setActivePdfEditHint(null)
    onActiveBlockIdChange(blockId)
  }
  function selectEvidence(target: EvidenceTarget) {
    setEvidenceSelection({
      fileId: activeFile.id,
      documentId: activeFile.libraryId,
      runId: activeRun?.id,
      viewMarkdown: activeMarkdown,
      ...target,
    })
    setActivePdfEditHint(null)
    onActiveBlockIdChange(null)
  }

  function handleSelectExtractEvidence(payload: ParsingEvidenceSelection) {
    selectEvidence({ origin: 'extraction', payload })
  }
  const handleSelectElement = (element: ParsingElement) => {
    selectEvidence({ origin: 'element', elementId: element.id })
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
    setEvidenceSelection(null)
    setResourceView(false)
  }, [activeFile.id, activeFile.libraryId, activeMarkdown, activeRun?.id])

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
    () => activeElements.filter((element) => element.kind === 'image'),
    [activeElements],
  )
  const imageReviewEntries = useMemo<ImageReviewEntry[]>(
    () =>
      activeImageElements.map((element, index) => {
        const pageIndexes = getParsingPages(element).map((page) => page - 1)
        const pageIndex = pageIndexes[0] ?? null
        const src = getParsingElementImageSource(element)
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
    [activeImageElements],
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

  const resultReady = activeFile.status === 'parsed' && !isRunUnavailable
  const hasResult = !isRunUnavailable && (activeFile.markdownContent !== null || activeRun !== null)
  const isSavedRun = activeRun !== null && activeRun.id === activeFile.savedRunId
  const failureRequestId = extractRequestIdFromError(activeFile.error)
  const failureMessage = (activeFile.error ?? '未能完成解析，请重试。')
    .replace(/\s*[（(]?\brequest_id=[A-Za-z0-9._:-]+[）)]?/g, '')
    .trim()
  const stats = buildParsedStatItems(
    activeRun === null ? activeFile.stats : getParsingRunStatistics(activeRun),
    activeRun === null ? activeFile.duration : activeRun.durationSec,
  )
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
    try {
      await onSaveEdit()
    } finally {
      setSavePending(false)
    }
  }

  return (
    <>
      <ParseCompareDialog
        open={compareOpen}
        onOpenChange={setCompareOpen}
        runs={activeFile.runs ?? []}
        defaultBaseRunId={activeFile.activeRunId ?? activeRun?.id ?? null}
        onUseRun={(runId) => {
          onSelectRun(runId)
          setCompareOpen(false)
        }}
      />
      <div className={styles.mobileTabs} role="group" aria-label="核对视图">
        <span
          className={styles.mobileIndicator}
          style={{ transform: narrowView === 'source' ? 'translateX(0)' : 'translateX(100%)' }}
        />
        <button type="button" aria-pressed={narrowView === 'source'} onClick={() => setNarrowView('source')}>
          原文
        </button>
        <button type="button" aria-pressed={narrowView === 'result'} onClick={() => setNarrowView('result')}>
          解析结果
        </button>
      </div>
      <div className={styles.workspace} data-narrow-view={narrowView} data-testid="parsing-compare-workspace">
        <section className={styles.source} aria-label="原文">
          {isPdf ? (
            <PdfViewer
              key={pdfViewerKey}
              file={activeFile.file}
              showToolbar
              showAllBoxes={rightPanelMode === 'blocks' && !resourceView}
              boxesByPage={pdfBoxesByPage}
              blockIdToPageIndex={pdfBlockIdToPageIndex}
              activeBlockIds={pdfActiveBlockIds}
              hoveredBlockIds={hoveredBlockId ? [hoveredBlockId] : []}
              onHoverBlockId={onHoveredBlockIdChange}
              onClickBlockId={handleSelectPdfBlock}
            />
          ) : (
            <ParsingOriginalFile file={activeFile.file} />
          )}
        </section>

        <section className={styles.result} aria-label="解析结果">
          <div className={styles.resultToolbar}>
            <div className={styles.resultTabs} role="group" aria-label="结果视图">
              {(
                [
                  { id: 'markdown', label: 'Markdown' },
                  { id: 'blocks', label: '内容块' },
                  { id: 'resources', label: '提取资源' },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  disabled={!resultReady || isEditing}
                  aria-pressed={resultTab === tab.id}
                  onClick={() => selectResultTab(tab.id)}
                >
                  {tab.label}
                  {tab.id === 'blocks' && layoutEntries.length ? <span>{layoutEntries.length}</span> : null}
                </button>
              ))}
            </div>
            {resultReady ? (
              <div className={styles.resultActions}>
                {!isEditing ? (
                  <>
                    {resultTab === 'markdown' ? (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-8"
                        aria-label={previewMode === 'raw' ? '预览 Markdown' : '查看 Markdown 源码'}
                        aria-pressed={previewMode === 'raw'}
                        title={previewMode === 'raw' ? '预览' : '源码'}
                        onClick={() => onPreviewModeChange(previewMode === 'raw' ? 'rendered' : 'raw')}
                      >
                        <Code className="size-4" />
                      </Button>
                    ) : null}
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8"
                      aria-label={copied ? '已复制 Markdown' : '复制 Markdown'}
                      title="复制"
                      onClick={onCopyMarkdown}
                    >
                      {copied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8"
                      aria-label="下载 Markdown"
                      title="下载"
                      onClick={onDownloadMarkdown}
                    >
                      <Download className="size-4" />
                    </Button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button size="icon" variant="ghost" className="size-8" aria-label="更多结果操作">
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-60">
                        <DropdownMenuItem
                          disabled={activeFile.librarySource === 'knowledge_base'}
                          onSelect={onStartEdit}
                        >
                          <Edit3 className="mr-2 size-4" />
                          {rightPanelMode === 'blocks' && activeBlockId ? '编辑选中内容块' : '编辑 Markdown'}
                        </DropdownMenuItem>
                        {activeFile.runs && activeFile.runs.length > 1 ? (
                          <>
                            <DropdownMenuSeparator />
                            <label className="block px-2 py-1.5 text-xs text-muted-foreground" htmlFor="parsing-run">
                              解析版本
                            </label>
                            <select
                              id="parsing-run"
                              className={styles.runSelect}
                              value={activeRun?.id ?? activeFile.activeRunId}
                              onChange={(event) => onSelectRun(event.target.value)}
                            >
                              {activeFile.runs.map((run) => (
                                <option key={run.id} value={run.id}>
                                  {run.parserLabel}
                                  {' · ' + new Date(run.createdAt).toLocaleTimeString()}
                                </option>
                              ))}
                            </select>
                            <DropdownMenuItem onSelect={() => setCompareOpen(true)}>
                              <FileStack className="mr-2 size-4" />
                              对比解析版本
                            </DropdownMenuItem>
                          </>
                        ) : null}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </>
                ) : (
                  <span className="px-2 text-xs text-muted-foreground">编辑中</span>
                )}
              </div>
            ) : null}
          </div>

          {contentFeedback}
          {hasResult && (activeRun === null ? activeFile.contentEdited : activeRun.contentEdited) === true ? (
            <p role="status" className="shrink-0 border-b border-border px-4 py-2 text-xs text-muted-foreground">
              正文已编辑，原解析的内容块、提取资源和质量评价已失效。
            </p>
          ) : null}
          {hasResult && activeFile.status === 'parsing' ? (
            <p role="status" className="shrink-0 border-b border-border px-4 py-2 text-xs text-muted-foreground">
              正在重新解析，当前显示上次保存的正文。
            </p>
          ) : null}
          {activeFile.status === 'error' ? (
            <div className={hasResult ? styles.failureNotice : styles.resultState} role="alert">
              {!hasResult ? <AlertCircle className="size-7 text-destructive" /> : null}
              <h2>解析失败</h2>
              <p>{failureMessage}</p>
              {hasResult ? <p>已保留上次保存的正文。</p> : null}
              <Button className="gap-2" onClick={() => onParseFile(activeFile.id, activeFile.parserBackend)}>
                <RotateCcw className="size-4" />
                重试解析
              </Button>
              {failureRequestId ? (
                <details className={styles.diagnostics}>
                  <summary>请求详情</summary>
                  <p className="font-mono">request_id={failureRequestId}</p>
                </details>
              ) : null}
              {activeFile.parseDiagnostics?.suggested_backends?.length ? (
                <div className={styles.recovery}>
                  {activeFile.parseDiagnostics.suggested_backends.slice(0, 6).map((backend) => (
                    <Button
                      key={backend}
                      size="sm"
                      variant="outline"
                      onClick={() => onParseFile(activeFile.id, backend)}
                    >
                      用 {getParserLabel(resolveParserBackendForFilename(activeFile.name, backend).backend)} 重试
                    </Button>
                  ))}
                </div>
              ) : null}
              {activeFile.parseDiagnostics?.pdf_sample ? (
                <details className={styles.diagnostics}>
                  <summary>查看 PDF 诊断</summary>
                  <p>
                    {activeFile.parseDiagnostics.pdf_sample.page_count ?? '–'} 页
                    {activeFile.parseDiagnostics.pdf_sample.is_scanned ? ' · 可能为扫描件' : ''}
                  </p>
                  {activeFile.parseDiagnostics.pdf_sample.samples?.slice(0, 3).map((sample) => (
                    <p key={sample.page}>
                      第 {sample.page} 页 · {sample.text_chars} 字符
                      <br />
                      {sample.excerpt.length === 0 ? '未检测到可选文字' : sample.excerpt}
                    </p>
                  ))}
                </details>
              ) : null}
            </div>
          ) : null}
          {hasResult && !isEditing ? (
            <div className={styles.resourceBody} hidden={!resourceView}>
              {resourceView && selectedExtractEvidence ? (
                <div className={styles.evidence}>
                  <span>
                    {selectedExtractEvidence.fieldName} ·{' '}
                    {formatParsingPages(getParsingPages(selectedExtractEvidence.evidence))}
                  </span>
                  <span>{selectedExtractEvidence.evidence.text}</span>
                  <Button size="sm" variant="ghost" onClick={() => setNarrowView('source')}>
                    查看原文
                  </Button>
                </div>
              ) : null}
              {activeFile.librarySource === 'parsing_workspace' && resultReady ? (
                isSavedRun && (activeMarkdown.length > 0 || activeElements.length > 0) ? (
                  <ParsingExtractPanel
                    key={JSON.stringify([activeFile.libraryId, activeRun.id])}
                    documentId={activeFile.libraryId}
                    activeElements={activeElements}
                    onSelectEvidence={handleSelectExtractEvidence}
                    className="bg-background"
                  />
                ) : resourceView ? (
                  <p className={styles.evidence}>
                    {isSavedRun ? '当前版本没有可提取的内容。' : '切换到服务器已保存的解析版本后可提取字段。'}
                  </p>
                ) : null
              ) : null}
              {resourceView ? (
                <ParsingElementsPanel
                  key={activeFile.id}
                  elements={activeElements}
                  onSelectElement={handleSelectElement}
                />
              ) : null}
            </div>
          ) : null}

          {isRunUnavailable ? (
            <div className={styles.resultState} role="alert">
              <AlertCircle className="size-7 text-destructive" />
              <h2>所选解析版本不可用</h2>
              <p>请选择现有解析版本，或重新解析文档。</p>
              {activeFile.runs !== undefined && activeFile.runs.length > 0 ? (
                <label className="flex flex-col gap-2">
                  切换解析版本
                  <select
                    className={styles.runSelect}
                    value={activeFile.activeRunId}
                    onChange={(event) => onSelectRun(event.target.value)}
                  >
                    <option value={activeFile.activeRunId} disabled>
                      所选版本不可用
                    </option>
                    {activeFile.runs.map((run) => (
                      <option key={run.id} value={run.id}>
                        {run.parserLabel} · {new Date(run.createdAt).toLocaleTimeString()}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <Button className="gap-2" onClick={() => onParseFile(activeFile.id, activeFile.parserBackend)}>
                <RotateCcw className="size-4" />
                重新解析
              </Button>
            </div>
          ) : !hasResult ? (
            activeFile.status === 'error' ? null : (
              <div className={styles.resultState} role="status">
                {activeFile.status === 'parsing' ? (
                  <>
                    <Loader2 className="size-7 animate-spin text-info motion-reduce:animate-none" />
                    <h2>正在解析</h2>
                    <p>
                      {activeFile.parserLabel} · {Math.round(activeFile.progress || 0)}%
                    </p>
                    <div
                      className={styles.progress}
                      role="progressbar"
                      aria-label="解析进度"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(activeFile.progress || 0)}
                    >
                      <span style={{ width: Math.min(100, Math.max(0, activeFile.progress || 0)) + '%' }} />
                    </div>
                  </>
                ) : (
                  <>
                    <FileText className="size-7 text-muted-foreground" />
                    <h2>文档已就绪</h2>
                    <p>选择解析器，开始提取文档内容。</p>
                    <Button className="gap-2" onClick={() => onParseFile(activeFile.id, activeFile.parserBackend)}>
                      <Play className="size-4" />
                      开始解析
                    </Button>
                  </>
                )}
              </div>
            )
          ) : isEditing ? (
            <div className={styles.editor}>
              <textarea
                ref={editorRef}
                aria-label="编辑 Markdown"
                value={editedContent}
                disabled={savePending}
                onChange={(event) => onEditedContentChange(event.target.value)}
                spellCheck={false}
              />
            </div>
          ) : resourceView ? null : rightPanelMode === 'blocks' ? (
            <ParsingRightPanel className={styles.blockBody}>
              {reviewEntries.length ? (
                reviewEntries.map((reviewEntry) => {
                  const id = reviewEntry.type === 'layout' ? reviewEntry.entry.id : reviewEntry.element.id
                  const isActive =
                    reviewEntry.type === 'layout'
                      ? id === activeBlockId
                      : selectedExtractEvidence?.origin === 'element' &&
                        selectedExtractEvidence.evidence.element_id === id
                  const meta =
                    reviewEntry.type === 'layout'
                      ? getParsingLayoutMeta(reviewEntry.entry.kind)
                      : getParsingLayoutMeta('image')
                  return (
                    <div
                      key={`${reviewEntry.type}:${id}`}
                      ref={(node) => {
                        if (node) layoutReviewCardRefs.current.set(id, node)
                        else layoutReviewCardRefs.current.delete(id)
                      }}
                      data-layout-entry-id={id}
                      data-active={isActive}
                      className={styles.blockRow}
                      onMouseEnter={() => onHoveredBlockIdChange(id)}
                      onMouseLeave={() => onHoveredBlockIdChange(null)}
                    >
                      <button
                        type="button"
                        className={styles.blockMeta}
                        aria-pressed={isActive}
                        onClick={() =>
                          reviewEntry.type === 'layout'
                            ? handleSelectReviewBlock(id)
                            : handleSelectElement(reviewEntry.element)
                        }
                      >
                        <span className={cn('size-1.5 rounded-full', meta.dotClassName)} />
                        <strong>{meta.label}</strong>
                        <span>
                          {reviewEntry.type === 'layout' && reviewEntry.entry.pageIndex != null
                            ? '第 ' + (reviewEntry.entry.pageIndex + 1) + ' 页'
                            : reviewEntry.type === 'image'
                              ? (formatParsingPages(getParsingPages(reviewEntry.element)) ?? '无页码')
                              : '无页码'}
                        </span>
                        <span className="ml-auto">
                          {reviewEntry.type === 'layout'
                            ? reviewEntry.entry.charCount + ' 字'
                            : reviewEntry.element.bbox === undefined || reviewEntry.element.bbox === null
                              ? '无坐标'
                              : reviewEntry.pageIndex === null
                                ? '缺少页码'
                                : '可定位'}
                        </span>
                      </button>
                      {reviewEntry.type === 'layout' ? (
                        <div className={styles.markdown}>
                          <MarkdownRenderer markdown={reviewEntry.entry.text} />
                        </div>
                      ) : (
                        <div className={styles.imageEntry}>
                          {reviewEntry.src !== null ? (
                            <AuthImage
                              src={reviewEntry.src}
                              alt={reviewEntry.element.text ?? reviewEntry.element.id}
                              width={280}
                              height={200}
                              unoptimized
                              className="max-h-40 w-full object-contain"
                            />
                          ) : (
                            <ImageIcon className="size-7 text-muted-foreground" />
                          )}
                          <span>{reviewEntry.element.text ?? `图片 ${reviewEntry.imageIndex + 1}`}</span>
                        </div>
                      )}
                    </div>
                  )
                })
              ) : (
                <div className={styles.empty}>
                  <Blocks className="size-6 text-muted-foreground" />
                  <h2>没有可定位的内容块</h2>
                  <p>可以切换到 Markdown 查看解析内容。</p>
                </div>
              )}
            </ParsingRightPanel>
          ) : activeMarkdown.length === 0 ? (
            <div className={styles.resultState}>
              <FileText className="size-7 text-muted-foreground" />
              <h2>正文为空</h2>
              <p>
                {activeFile.librarySource === 'knowledge_base'
                  ? '当前保存的解析正文没有内容。'
                  : '当前保存的解析正文没有内容，可以编辑或重新解析。'}
              </p>
            </div>
          ) : (
            <ParsingRightPanel dragScroll className={cn(styles.markdownBody, 'parsing-md-scroll')}>
              {previewMode === 'raw' ? (
                <pre className={styles.raw}>{activeMarkdown}</pre>
              ) : (
                <article className={styles.markdown}>
                  <MarkdownRenderer
                    markdown={activeMarkdown}
                    autoScrollToHash
                    scrollContainerSelector=".parsing-md-scroll"
                  />
                </article>
              )}
            </ParsingRightPanel>
          )}

          {resultReady && !isEditing ? (
            <ParsingQualityNotice qualityGate={activeQualityGate} pdfQuality={activePdfQuality} />
          ) : null}
        </section>
      </div>

      {resultReady || isEditing ? (
        <footer className={styles.footer}>
          <div className={styles.stats}>
            {isEditing ? (
              <span>正在编辑{rightPanelMode === 'blocks' && activeBlockId ? '内容块' : ' Markdown'}</span>
            ) : resultReady ? (
              <>
                {layoutEntries.length > 0 ? (
                  <span>
                    <Blocks className="size-3.5" />
                    <b>{layoutEntries.length}</b> 个内容块
                  </span>
                ) : null}
                {stats.map(({ label, value }) => (
                  <span key={label}>
                    {label} <b>{value}</b>
                  </span>
                ))}
              </>
            ) : (
              <span>{activeFile.parserLabel}</span>
            )}
          </div>
          <div className={styles.footerActions}>
            {isEditing ? (
              <>
                <Button variant="ghost" size="sm" disabled={savePending} onClick={onCancelEdit}>
                  取消
                </Button>
                <Button size="sm" disabled={savePending} className="gap-2" onClick={() => void save()}>
                  {savePending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
                  {savePending ? '正在保存' : '保存修改'}
                </Button>
              </>
            ) : resultReady ? (
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                disabled={isSubmittingGovernance}
                onClick={() => void onSubmitToGovernance()}
              >
                {isSubmittingGovernance ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ArrowRight className="size-4" />
                )}
                {isSubmittingGovernance ? '正在移交' : '继续数据治理'}
              </Button>
            ) : null}
          </div>
        </footer>
      ) : null}
    </>
  )
}
