'use client'

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Copy,
  Download,
  FileText,
  FileStack,
  Gauge,
  Info,
  PanelRightClose,
  PanelRightOpen,
  RotateCcw,
  Settings2,
  ShieldCheck,
  UploadCloud,
} from 'lucide-react'
import { useTranslations } from 'next-intl'

import { AppFrame } from '@/components/app-frame'
import type { DocumentTreeFileItem } from '@/components/document-library/folder-tree'
import { ParsingActiveFilePane } from '@/components/parsing/parsing-active-file-pane'
import { ParsingLibraryPreviewPane } from '@/components/parsing/parsing-library-preview-pane'
import { ParsingMainPanel } from '@/components/parsing/parsing-main-panel'
import { ParsingMobileInspectorContent } from '@/components/parsing/parsing-mobile-inspector-content'
import { ParsingMobileQueueContent } from '@/components/parsing/parsing-mobile-queue-content'
import { ParsingSidebarPane } from '@/components/parsing/parsing-sidebar-pane'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import {
  PipelineRail,
  WorkbenchPanelDialog,
  WorkbenchScaffold,
} from '@/components/workbench'
import type { ParsingElement } from '@/lib/api/parsing'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { UPLOAD_ACCEPT, UPLOAD_ACCEPT_WITH_ZIP } from '@/lib/upload-extensions'
import { cn, detachPromise } from '@/lib/utils'
import type { ParsingBlock } from '@/lib/parsing-positions'
import {
  type FolderNode,
  ROOT_FOLDER_ID,
  type ParsedFileData,
} from '@/store/use-parsed-files-store'

import { countMarkdownHeadings, getLibraryStatusBadge } from './parsing-page-utils'
import type { ParsedFile, ParseRun } from './parsing-types'
import type { ParsingLibrarySourceStatus } from './use-parsing-page-state'

type ParsingWorkbenchShellProps = {
  activeBlockId: string | null
  activeBlocksWithPositions: ParsingBlock[]
  activeFile: ParsedFile | null
  activeFileId: string | null
  activeFolderId: string
  activeLibraryFile: ParsedFileData | null
  activeLibraryFileId: string | null
  activeLibrarySourceStatus: ParsingLibrarySourceStatus
  activeMarkdown: string
  availableDatasets: DatasetScopeOption[]
  activeElements: ParsingElement[]
  activePdfQuality: unknown
  activeQualityGate: unknown
  activeRun: ParseRun | null
  copied: boolean
  copyMarkdown: () => Promise<void>
  currentFolderId: string
  dragOverFolderId: string | null
  downloadMarkdown: () => void
  editedContent: string
  fileInputRef: RefObject<HTMLInputElement | null>
  files: ParsedFile[]
  folderInputRef: RefObject<HTMLInputElement | null>
  folderPathById: Record<string, string>
  folders: FolderNode[]
  handleCancelEdit: () => void
  handleDeleteFolder: (folderIds: string[]) => void
  handleFileDragStart: (
    event: React.DragEvent<HTMLElement>,
    fileId: string
  ) => void
  handleFileSelect: (
    event: React.ChangeEvent<HTMLInputElement>
  ) => Promise<void>
  handleFolderDragLeave: () => void
  handleFolderDragOver: (
    event: React.DragEvent<HTMLElement>,
    folderId: string
  ) => void
  handleFolderDrop: (
    event: React.DragEvent<HTMLElement>,
    folderId: string
  ) => void
  handleRebindFileSelect: (
    event: React.ChangeEvent<HTMLInputElement>
  ) => Promise<void>
  handleSaveEdit: () => Promise<void>
  handleSelectRun: (runId: string) => void
  handleStartEdit: () => void
  handleSubmitToGovernance: () => void
  hoveredBlockId: string | null
  imageCaptionEnabled: boolean
  imageOcrEnabled: boolean
  inspectorOpen: boolean
  isEditing: boolean
  isLibraryLoaded: boolean
  isPdf: boolean
  isQueueRehydrating: boolean
  isSidebarCollapsed: boolean
  libraryFiles: ParsedFileData[]
  moveFileToFolder: (fileId: string, folderId: string) => void
  parseAllPending: () => Promise<void>
  parseFile: (fileId: string, backend?: string) => void
  parserBackend: string
  pdfPreviewResetToken: number
  previewMode: 'raw' | 'rendered'
  queueOpen: boolean
  rebindInputRef: RefObject<HTMLInputElement | null>
  removeFile: (fileId: string) => void
  requestRebindForLibraryFile: (libraryId: string, autoParse: boolean) => void
  requestUploadFolder: (folderId: string) => void
  requestUploadToFolder: (folderId: string) => void
  restoreLibraryFileFromCache: (
    libraryId: string,
    autoParse: boolean
  ) => Promise<void>
  rightPanelMode: 'blocks' | 'markdown'
  setActiveBlockId: (blockId: string | null) => void
  setActiveFileId: (fileId: string | null) => void
  setActiveFolderId: (folderId: string) => void
  setActiveLibraryFileId: (fileId: string | null) => void
  setEditedContent: (value: string) => void
  setHoveredBlockId: (blockId: string | null) => void
  setImageCaptionEnabled: (enabled: boolean) => void
  setImageOcrEnabled: (enabled: boolean) => void
  setInspectorOpen: (open: boolean) => void
  setIsSidebarCollapsed: (collapsed: boolean) => void
  setParserBackend: (backend: string) => void
  setPdfPreviewResetToken: Dispatch<SetStateAction<number>>
  setPreviewMode: (mode: 'raw' | 'rendered') => void
  setQueueOpen: (open: boolean) => void
  setQueueFileParserBackend: (params: {
    fileId: string
    filename: string
    backend: string
  }) => void
  setRightPanelMode: (mode: 'blocks' | 'markdown') => void
  selectedGovernanceFileIds: ReadonlySet<string>
  selectedDatasetId: string | null
  setVlmCorrectionEnabled: (enabled: boolean) => void
  onSubmitSelectedToGovernance: () => void
  onToggleGovernanceFileSelection: (fileId: string) => void
  onDatasetScopeChange: (datasetId: string | null) => void
  tocEnabled: boolean
  updateParsedFile: (
    id: string,
    updates: Partial<Omit<ParsedFileData, 'id'>>
  ) => void
  visibleLibraryOnlyFiles: ParsedFileData[]
  visibleQueueFiles: ParsedFile[]
  vlmCorrectionEnabled: boolean
}

type DatasetScopeOption = {
  id: string
  name: string
}

const PARSING_INSPECTOR_WIDTH_KEY = 'mimirq.parsing.inspectorWidth'
const DEFAULT_PARSING_INSPECTOR_WIDTH = 410
const MIN_PARSING_INSPECTOR_WIDTH = 320
const MAX_PARSING_INSPECTOR_WIDTH = 560
const COLLAPSED_PARSING_INSPECTOR_HOTZONE_WIDTH = 36

function clampParsingInspectorWidth(width: number) {
  return Math.min(
    MAX_PARSING_INSPECTOR_WIDTH,
    Math.max(MIN_PARSING_INSPECTOR_WIDTH, Math.round(width))
  )
}

function readStoredParsingInspectorWidth() {
  if (globalThis.window === undefined) {
    return DEFAULT_PARSING_INSPECTOR_WIDTH
  }

  const storedWidth = Number.parseInt(
    readClientStorage(PARSING_INSPECTOR_WIDTH_KEY) || '',
    10
  )
  return Number.isFinite(storedWidth)
    ? clampParsingInspectorWidth(storedWidth)
    : DEFAULT_PARSING_INSPECTOR_WIDTH
}

function formatFileSize(bytes: number | null | undefined) {
  const value = typeof bytes === 'number' && Number.isFinite(bytes) ? bytes : 0
  if (value <= 0) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function getFileExtension(filename: string | null | undefined) {
  const ext = String(filename || '').split('.').pop()?.trim()
  return ext ? ext.toUpperCase() : '-'
}

function countMarkdownParagraphs(markdown: string) {
  return markdown
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter((item) => item && !item.startsWith('#') && !item.startsWith('|'))
    .length
}

function countMarkdownLines(markdown: string, pattern: RegExp) {
  return markdown
    .split('\n')
    .filter((line) => pattern.test(line.trim()))
    .length
}

function parsingStatusLabel(
  activeFile: ParsedFile | null,
  selectedStatus: string | null,
  activeLibraryStatusBadge: ReturnType<typeof getLibraryStatusBadge> | null,
  activeLibraryFile: ParsedFileData | null
) {
  if (activeFile) {
    if (selectedStatus === 'parsed') return '已解析'
    if (selectedStatus === 'parsing') return '解析中'
    if (selectedStatus === 'error') return '失败'
    return '待解析'
  }
  if (activeLibraryStatusBadge?.label) return activeLibraryStatusBadge.label
  if (activeLibraryFile) return '已解析'
  return '未选择'
}

function parsingStatusIcon(isError: boolean, isParsing: boolean) {
  if (isError) return <AlertCircle className="size-3.5" />
  if (isParsing) return <Clock3 className="size-3.5" />
  return <CheckCircle2 className="size-3.5" />
}

function parsingStatusToneClass(
  isError: boolean,
  isPending: boolean,
  isParsing: boolean
) {
  if (isError) return 'border-destructive/25 bg-destructive/[0.08] text-destructive'
  if (isPending) return 'border-warning/25 bg-warning/[0.10] text-warning'
  if (isParsing) return 'border-info/25 bg-info/[0.08] text-info'
  return 'border-success/25 bg-success/[0.08] text-success'
}

function parsingRunActionLabel(status: string | null) {
  if (status === 'error') return '重试'
  return '开始'
}

function parsingGovernanceButtonClass(canSubmitToGovernance: boolean) {
  if (canSubmitToGovernance) {
    return 'border-info/25 bg-[linear-gradient(90deg,hsl(var(--info)),hsl(var(--primary)))] text-info-foreground shadow-[0_12px_24px_-20px_hsl(var(--info)/0.85)] hover:brightness-105'
  }
  return 'border-info/20 bg-info/[0.10] text-info/70'
}

function ParsingInspectorCard({
  title,
  icon: Icon,
  children,
}: Readonly<{
  title: string
  icon: typeof Info
  children: React.ReactNode
}>) {
  return (
    <section className="rounded-[18px] border border-border/60 bg-background/55 p-4 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.24)]">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-lg bg-info/[0.08] text-info">
          <Icon className="size-3.5" />
        </span>
        <h2 className="text-[13px] font-semibold text-foreground">{title}</h2>
      </div>
      {children}
    </section>
  )
}

function ParsingInspectorDisclosure({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
}: Readonly<{
  title: string
  icon: typeof Info
  children: React.ReactNode
  defaultOpen?: boolean
}>) {
  return (
    <details
      open={defaultOpen}
      className="group rounded-[18px] border border-border/60 bg-background/55 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.24)]"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span className="flex min-w-0 items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-lg bg-muted text-muted-foreground">
            <Icon className="size-3.5" />
          </span>
          <span className="truncate text-[13px] font-semibold text-foreground">{title}</span>
        </span>
        <span className="text-[11px] text-muted-foreground">
          <span className="group-open:hidden">展开</span>
          <span className="hidden group-open:inline">收起</span>
        </span>
      </summary>
      <div className="border-t border-border/55 px-4 py-3">{children}</div>
    </details>
  )
}

function ParsingMetricGrid({
  items,
}: Readonly<{
  items: Array<{ label: string; value: string | number }>
}>) {
  return (
    <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-border/55 bg-card/80">
      {items.map((item) => (
        <div key={item.label} className="border-b border-r border-border/50 px-3 py-2 last:border-r-0">
          <div className="text-[11px] text-muted-foreground">{item.label}</div>
          <div className="mt-0.5 font-mono text-[13px] font-semibold tabular-nums text-foreground">
            {item.value}
          </div>
        </div>
      ))}
    </div>
  )
}

type ParsingStatusMetricTone = 'success' | 'info' | 'warning' | 'muted'

const PARSING_STATUS_METRIC_TONES: Record<
  ParsingStatusMetricTone,
  { card: string; dot: string; value: string }
> = {
  success: {
    card: 'border-success/25 bg-success/[0.07]',
    dot: 'bg-success',
    value: 'text-success',
  },
  info: {
    card: 'border-info/25 bg-info/[0.07]',
    dot: 'bg-info',
    value: 'text-info',
  },
  warning: {
    card: 'border-warning/25 bg-warning/[0.08]',
    dot: 'bg-warning',
    value: 'text-warning',
  },
  muted: {
    card: 'border-border/55 bg-muted/35',
    dot: 'bg-muted-foreground/55',
    value: 'text-foreground',
  },
}

function ParsingStatusMetricGrid({
  items,
}: Readonly<{
  items: Array<{
    label: string
    tone: ParsingStatusMetricTone
    value: string | number
  }>
}>) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {items.map((item) => {
        const tone = PARSING_STATUS_METRIC_TONES[item.tone]
        return (
          <div
            key={item.label}
            className={cn(
              'rounded-xl border px-3 py-2 shadow-[inset_0_1px_0_hsl(var(--background)/0.65)]',
              tone.card
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                <span className={cn('size-1.5 shrink-0 rounded-full', tone.dot)} />
                <span className="truncate">{item.label}</span>
              </span>
              <span
                className={cn(
                  'font-mono text-[15px] font-semibold tabular-nums leading-none',
                  tone.value
                )}
              >
                {item.value}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ParsingInspectorPanel({
  activeFile,
  activeLibraryFile,
  activeLibraryFolderPathLabel,
  activeLibraryStatusBadge,
  activeMarkdown,
  copied,
  parsedCount,
  parsingCount,
  pendingCount,
  parserBackend,
  queueFileCount,
  readyGovernanceCount,
  selectedDatasetId,
  selectedReadyGovernanceCount,
  scopeFileCount,
  onCopyMarkdown,
  onDownloadMarkdown,
  onParseFile,
  onRestoreLibraryFile,
  onRequestRebindLibraryFile,
  onSubmitSelectedToGovernance,
  onSubmitToGovernance,
}: Readonly<{
  activeFile: ParsedFile | null
  activeLibraryFile: ParsedFileData | null
  activeLibraryFolderPathLabel: string
  activeLibraryStatusBadge: ReturnType<typeof getLibraryStatusBadge> | null
  activeMarkdown: string
  copied: boolean
  parsedCount: number
  parsingCount: number
  pendingCount: number
  parserBackend: string
  queueFileCount: number
  readyGovernanceCount: number
  selectedDatasetId: string | null
  selectedReadyGovernanceCount: number
  scopeFileCount: number
  onCopyMarkdown: () => void
  onDownloadMarkdown: () => void
  onParseFile: (fileId: string) => void
  onRestoreLibraryFile: (autoParse: boolean) => void
  onRequestRebindLibraryFile: (autoParse: boolean) => void
  onSubmitSelectedToGovernance: () => void
  onSubmitToGovernance: () => void
}>) {
  const selectedName = activeFile?.file.name || activeLibraryFile?.filename || ''
  const selectedSize = activeFile?.file.size ?? activeLibraryFile?.fileSize ?? null
  const selectedParser =
    activeFile?.parserLabel ||
    activeLibraryFile?.parser ||
    getParserLabel(parserBackend)
  const selectedStatus = activeFile?.status || activeLibraryFile?.status || null
  const statusLabel = parsingStatusLabel(
    activeFile,
    selectedStatus,
    activeLibraryStatusBadge,
    activeLibraryFile
  )
  const markdown = activeMarkdown || activeLibraryFile?.markdownContent || ''
  const overview = [
    {
      label: '标题',
      value: activeFile?.stats?.headingCount ?? countMarkdownHeadings(markdown),
    },
    {
      label: '段落',
      value: countMarkdownParagraphs(markdown),
    },
    {
      label: '列表',
      value: countMarkdownLines(markdown, /^([-*+]|\d+\.)\s+/),
    },
    {
      label: '图片',
      value: activeFile?.stats?.imageCount ?? (markdown.match(/!\[/g) || []).length,
    },
    {
      label: '表格',
      value: activeFile?.stats?.tableCount ?? countMarkdownLines(markdown, /^\|.*\|$/),
    },
    {
      label: '代码块',
      value: Math.floor((markdown.match(/```/g) || []).length / 2),
    },
  ]
  const canUseMarkdownActions = Boolean(markdown.trim())
  const canSubmitToGovernance = Boolean(activeFile && canUseMarkdownActions)
  const hasSelection = Boolean(selectedName)
  const selectedError = activeFile?.error || activeLibraryFile?.error || ''
  const selectedProgress = Math.round(activeFile?.progress || (activeFile?.status === 'parsed' ? 100 : 0))
  const isError = selectedStatus === 'error'
  const isParsing = selectedStatus === 'parsing'
  const isPending = selectedStatus === 'pending'
  const statusIcon = parsingStatusIcon(isError, isParsing)
  const statusToneClass = parsingStatusToneClass(isError, isPending, isParsing)
  const fileInfoRows = [
    ['文件类型', getFileExtension(selectedName)],
    ['文件大小', formatFileSize(selectedSize)],
    ['解析器', selectedParser],
    ['文件路径', activeFile?.sourcePath || activeLibraryFolderPathLabel],
  ]

  const quickActions = (
    <div className="grid grid-cols-2 gap-2">
      {activeFile?.status === 'pending' || activeFile?.status === 'error' ? (
        <Button
          type="button"
          size="sm"
          className="h-8 gap-1.5 rounded-xl bg-primary text-[12px]"
          onClick={() => onParseFile(activeFile.id)}
        >
          <RotateCcw className="size-3.5" />
          {parsingRunActionLabel(activeFile.status)}
        </Button>
      ) : null}
      {activeLibraryFile && !activeFile ? (
        <>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 rounded-xl text-[12px]"
            onClick={() => onRestoreLibraryFile(false)}
          >
            <FileStack className="size-3.5" />
            恢复源文
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 rounded-xl text-[12px]"
            onClick={() => onRequestRebindLibraryFile(false)}
          >
            <RotateCcw className="size-3.5" />
            重新上传
          </Button>
        </>
      ) : null}
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 gap-1.5 rounded-xl text-[12px]"
        disabled={!canUseMarkdownActions}
        onClick={onCopyMarkdown}
      >
        <Copy className="size-3.5" />
        {copied ? '已复制' : '复制'}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 gap-1.5 rounded-xl text-[12px]"
        disabled={!canUseMarkdownActions}
        onClick={onDownloadMarkdown}
      >
        <Download className="size-3.5" />
        导出
      </Button>
      <Button
        type="button"
        size="sm"
        className={cn(
          'col-span-2 h-8 gap-1.5 rounded-xl border text-[12px] font-semibold shadow-none disabled:opacity-100',
          parsingGovernanceButtonClass(canSubmitToGovernance)
        )}
        disabled={!canSubmitToGovernance}
        onClick={onSubmitToGovernance}
      >
        <ShieldCheck className="size-3.5" />
        提交到数据治理
      </Button>
    </div>
  )

  return (
    <aside className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto overscroll-contain rounded-[24px] border border-border/70 bg-card/96 p-4 shadow-[0_24px_60px_-46px_rgba(15,23,42,0.42)] backdrop-blur-sm">
      {readyGovernanceCount > 0 ? (
        <ParsingInspectorCard title="批量提交" icon={ShieldCheck}>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 text-[12px]">
              <div className="rounded-xl border border-warning/25 bg-warning/[0.08] px-3 py-2">
                <div className="text-[11px] text-muted-foreground">待提交</div>
                <div className="mt-0.5 font-mono text-[16px] font-semibold text-warning">{readyGovernanceCount}</div>
              </div>
              <div className="rounded-xl border border-info/25 bg-info/[0.08] px-3 py-2">
                <div className="text-[11px] text-muted-foreground">已选择</div>
                <div className="mt-0.5 font-mono text-[16px] font-semibold text-info">{selectedReadyGovernanceCount}</div>
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              className="h-9 w-full gap-1.5 rounded-xl bg-primary text-[12px] font-semibold text-primary-foreground hover:bg-primary/90"
              disabled={selectedReadyGovernanceCount === 0}
              onClick={onSubmitSelectedToGovernance}
            >
              <ShieldCheck className="size-3.5" />
              提交选中文档
            </Button>
          </div>
        </ParsingInspectorCard>
      ) : null}

      {hasSelection ? (
        <>
          <details
            open
            data-testid="parsing-selected-file-summary"
            className="group rounded-[18px] border border-border/70 bg-card/96 shadow-[0_18px_42px_-34px_rgba(15,23,42,0.36)]"
          >
            <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-4 [&::-webkit-details-marker]:hidden">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <div className="truncate text-[13px] font-semibold text-foreground" title={selectedName}>
                    {selectedName}
                  </div>
                  <span className="shrink-0 text-[11px] text-muted-foreground">
                    <span className="group-open:hidden">展开</span>
                    <span className="hidden group-open:inline">收起</span>
                  </span>
                </div>
              </div>
              <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-semibold ${statusToneClass}`}>
                {statusIcon}
                {statusLabel}
              </span>
            </summary>

            <div className="border-t border-border/55 px-4 pb-4 pt-3">
              <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="rounded-full border border-border/60 bg-background px-2 py-0.5">
                  {getFileExtension(selectedName)}
                </span>
                <span className="rounded-full border border-border/60 bg-background px-2 py-0.5">
                  {formatFileSize(selectedSize)}
                </span>
                <span className="rounded-full border border-border/60 bg-background px-2 py-0.5">
                  {selectedParser}
                </span>
              </div>

              {selectedError || activeFile ? (
                <div className="mt-3">
                  {selectedError ? (
                    <div className="rounded-xl border border-destructive/20 bg-destructive/[0.06] p-3">
                      <div className="flex items-center gap-2 text-[12px] font-semibold text-destructive">
                        <AlertCircle className="size-3.5" />
                        解析失败
                      </div>
                      <p className="mt-2 text-[12px] leading-5 text-destructive/85">{selectedError}</p>
                      {activeFile ? (
                        <Button
                          type="button"
                          size="sm"
                          className="mt-3 h-8 gap-1.5 rounded-xl bg-destructive text-[12px] text-destructive-foreground hover:bg-destructive/90"
                          onClick={() => onParseFile(activeFile.id)}
                        >
                          <RotateCcw className="size-3.5" />
                          重试解析
                        </Button>
                      ) : null}
                    </div>
                  ) : null}

                  {activeFile ? (
                    <div className={cn('grid grid-cols-2 gap-2 text-[12px]', selectedError && 'mt-3')}>
                      <div className="rounded-xl border border-border/60 bg-background/70 px-3 py-2">
                        <div className="text-[11px] text-muted-foreground">解析耗时</div>
                        <div className="mt-0.5 font-mono font-semibold text-foreground">
                          {typeof activeFile.duration === 'number' ? `${activeFile.duration}s` : '-'}
                        </div>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-background/70 px-3 py-2">
                        <div className="text-[11px] text-muted-foreground">完成进度</div>
                        <div className="mt-0.5 font-mono font-semibold text-foreground">{selectedProgress}%</div>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </details>

          <ParsingInspectorDisclosure title="解析详情" icon={Info}>
            <div className="space-y-3 text-[12px]">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">解析模式</span>
                <span className="rounded-xl border border-border/60 bg-background px-2.5 py-1 font-semibold text-foreground">
                  自动解析
                </span>
              </div>
              <p className="leading-5 text-muted-foreground">
                系统根据文件类型选择解析策略，并把结果转换为 Markdown，后续可进入治理、切块和对话链路。
              </p>
              <div className="h-px bg-border/60" />
              {fileInfoRows.map(([label, value]) => (
                <div key={label} className="grid grid-cols-[78px_minmax(0,1fr)] gap-2">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="truncate font-medium text-foreground" title={String(value)}>
                    {value}
                  </span>
                </div>
              ))}
            </div>
          </ParsingInspectorDisclosure>

          <ParsingInspectorDisclosure title="快捷操作" icon={Gauge} defaultOpen={isPending || isError}>
            {quickActions}
          </ParsingInspectorDisclosure>

          <ParsingInspectorDisclosure title="内容概览" icon={Clock3}>
            <ParsingMetricGrid items={overview} />
          </ParsingInspectorDisclosure>
        </>
      ) : (
        <>
          <ParsingInspectorCard title="解析信息" icon={Info}>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[12px] font-medium text-muted-foreground">解析模式</div>
                <div className="rounded-xl border border-border/60 bg-background px-2.5 py-1 text-[12px] font-semibold text-foreground">
                  自动解析
                </div>
              </div>
              <p className="text-[12px] leading-5 text-muted-foreground">
                系统根据文件类型选择解析策略，并把结果转换为 Markdown，后续可进入治理、切块和对话链路。
              </p>
            </div>
          </ParsingInspectorCard>

          <ParsingInspectorCard title="文件信息" icon={FileText}>
            <div className="space-y-2.5 text-[12px]">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">当前范围</span>
                <span className="font-medium text-foreground">
                  {selectedDatasetId ? '数据集' : '全部来源'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">文档总数</span>
                <span className="font-mono font-semibold text-foreground">{scopeFileCount}</span>
              </div>
            </div>
          </ParsingInspectorCard>

          <ParsingInspectorCard title="解析状态" icon={CheckCircle2}>
            <div className="space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-success/25 bg-success/[0.08] px-3 py-1 text-[12px] font-semibold text-success">
                <CheckCircle2 className="size-3.5" />
                {statusLabel}
              </div>
              <ParsingStatusMetricGrid
                items={[
                  { label: '已解析', value: parsedCount, tone: 'success' },
                  { label: '解析中', value: parsingCount, tone: 'info' },
                  { label: '待处理', value: pendingCount, tone: 'warning' },
                  { label: '队列', value: queueFileCount, tone: 'muted' },
                ]}
              />
            </div>
          </ParsingInspectorCard>

          <ParsingInspectorCard title="快捷操作" icon={Gauge}>
            {quickActions}
          </ParsingInspectorCard>

          <ParsingInspectorCard title="内容概览" icon={Clock3}>
            <ParsingMetricGrid items={overview} />
          </ParsingInspectorCard>
        </>
      )}
    </aside>
  )
}

function ResizableParsingInspectorRail({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const [inspectorWidth, setInspectorWidth] = useState(
    DEFAULT_PARSING_INSPECTOR_WIDTH
  )
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false)
  const resizeStateRef = useRef<{
    currentWidth: number
    startWidth: number
    startX: number
  } | null>(null)

  useEffect(() => {
    setInspectorWidth(readStoredParsingInspectorWidth())
  }, [])

  const persistInspectorWidth = useCallback((width: number) => {
    if (globalThis.window === undefined) {
      return
    }

    writeClientStorage(
      PARSING_INSPECTOR_WIDTH_KEY,
      String(clampParsingInspectorWidth(width))
    )
  }, [])

  const handleResizePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault()
      resizeStateRef.current = {
        currentWidth: inspectorWidth,
        startWidth: inspectorWidth,
        startX: event.clientX,
      }

      const previousCursor = document.body.style.cursor
      const previousUserSelect = document.body.style.userSelect
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'

      const controller = new AbortController()
      const restorePageInteraction = () => {
        document.body.style.cursor = previousCursor
        document.body.style.userSelect = previousUserSelect
        controller.abort()
      }

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const resizeState = resizeStateRef.current
        if (!resizeState) {
          return
        }

        const nextWidth = clampParsingInspectorWidth(
          resizeState.startWidth + resizeState.startX - moveEvent.clientX
        )
        resizeState.currentWidth = nextWidth
        setInspectorWidth(nextWidth)
      }

      const handlePointerUp = () => {
        const nextWidth =
          resizeStateRef.current?.currentWidth ?? inspectorWidth
        resizeStateRef.current = null
        persistInspectorWidth(nextWidth)
        restorePageInteraction()
      }

      globalThis.window.addEventListener('pointermove', handlePointerMove, {
        signal: controller.signal,
      })
      globalThis.window.addEventListener('pointerup', handlePointerUp, {
        once: true,
        signal: controller.signal,
      })
      globalThis.window.addEventListener('pointercancel', handlePointerUp, {
        once: true,
        signal: controller.signal,
      })
    },
    [inspectorWidth, persistInspectorWidth]
  )

  const handleResizeKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const step = event.shiftKey ? 32 : 16
      const nextWidthByKey: Record<string, number | undefined> = {
        ArrowLeft: inspectorWidth + step,
        ArrowRight: inspectorWidth - step,
        End: MAX_PARSING_INSPECTOR_WIDTH,
        Home: MIN_PARSING_INSPECTOR_WIDTH,
      }
      const nextWidth = nextWidthByKey[event.key]
      if (typeof nextWidth !== 'number') {
        return
      }

      event.preventDefault()
      const clampedWidth = clampParsingInspectorWidth(nextWidth)
      setInspectorWidth(clampedWidth)
      persistInspectorWidth(clampedWidth)
    },
    [inspectorWidth, persistInspectorWidth]
  )

  return (
    <aside
      data-testid="parsing-static-inspector"
      className="group/inspector relative hidden min-h-0 shrink-0 overflow-visible transition-[width] duration-200 ease-out motion-reduce:transition-none xl:flex"
      style={{ width: inspectorCollapsed ? COLLAPSED_PARSING_INSPECTOR_HOTZONE_WIDTH : inspectorWidth }}
    >
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={inspectorCollapsed ? '展开解析信息侧栏' : '收起解析信息侧栏'}
        title={inspectorCollapsed ? '展开解析信息侧栏' : '收起解析信息侧栏'}
        className={cn(
          'absolute top-3 z-30 size-8 rounded-xl border border-border/60 bg-card/95 text-muted-foreground shadow-[0_14px_28px_-22px_rgba(15,23,42,0.50)] backdrop-blur-sm transition-[left,opacity,background-color,color,box-shadow] duration-200 hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-info/35',
          'opacity-0 hover:opacity-100 focus-visible:opacity-100',
          inspectorCollapsed ? 'left-0' : 'left-[-0.875rem]'
        )}
        onClick={() => setInspectorCollapsed((collapsed) => !collapsed)}
      >
        {inspectorCollapsed ? <PanelRightOpen className="size-3.5" /> : <PanelRightClose className="size-3.5" />}
      </Button>

      {!inspectorCollapsed ? (
        <div
          role="slider"
          aria-label="调整解析信息宽度"
          aria-orientation="vertical"
          aria-valuemax={MAX_PARSING_INSPECTOR_WIDTH}
          aria-valuemin={MIN_PARSING_INSPECTOR_WIDTH}
          aria-valuenow={inspectorWidth}
          aria-valuetext={`${inspectorWidth}px`}
          tabIndex={0}
          className="absolute inset-y-4 left-[-6px] z-20 w-3 cursor-col-resize rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/35 before:absolute before:inset-y-8 before:left-1/2 before:w-px before:-translate-x-1/2 before:rounded-full before:bg-border/65 before:transition-colors hover:before:bg-info/70 focus-visible:before:bg-info"
          onKeyDown={handleResizeKeyDown}
          onPointerDown={handleResizePointerDown}
        />
      ) : null}

      <div
        className={cn(
          'h-full w-full min-w-0 transition-opacity duration-150 motion-reduce:transition-none',
          inspectorCollapsed && 'pointer-events-none invisible opacity-0'
        )}
      >
        {children}
      </div>
    </aside>
  )
}

export function ParsingWorkbenchShell({
  activeBlockId,
  activeBlocksWithPositions,
  activeFile,
  activeFileId,
  activeFolderId,
  activeLibraryFile,
  activeLibraryFileId,
  activeLibrarySourceStatus,
  activeMarkdown,
  availableDatasets,
  activeElements,
  activePdfQuality,
  activeQualityGate,
  activeRun,
  copied,
  copyMarkdown,
  currentFolderId,
  dragOverFolderId,
  downloadMarkdown,
  editedContent,
  fileInputRef,
  files,
  folderInputRef,
  folderPathById,
  folders,
  handleCancelEdit,
  handleDeleteFolder,
  handleFileDragStart,
  handleFileSelect,
  handleFolderDragLeave,
  handleFolderDragOver,
  handleFolderDrop,
  handleRebindFileSelect,
  handleSaveEdit,
  handleSelectRun,
  handleStartEdit,
  handleSubmitToGovernance,
  hoveredBlockId,
  imageCaptionEnabled,
  imageOcrEnabled,
  inspectorOpen,
  isEditing,
  isLibraryLoaded,
  isPdf,
  isQueueRehydrating,
  isSidebarCollapsed,
  libraryFiles,
  moveFileToFolder,
  parseAllPending,
  parseFile,
  parserBackend,
  pdfPreviewResetToken,
  previewMode,
  queueOpen,
  rebindInputRef,
  removeFile,
  requestRebindForLibraryFile,
  requestUploadFolder,
  requestUploadToFolder,
  restoreLibraryFileFromCache,
  rightPanelMode,
  setActiveBlockId,
  setActiveFileId,
  setActiveFolderId,
  setActiveLibraryFileId,
  setEditedContent,
  setHoveredBlockId,
  setImageCaptionEnabled,
  setImageOcrEnabled,
  setInspectorOpen,
  setIsSidebarCollapsed,
  setParserBackend,
  setPdfPreviewResetToken,
  setPreviewMode,
  setQueueOpen,
  setQueueFileParserBackend,
  setRightPanelMode,
  setVlmCorrectionEnabled,
  selectedGovernanceFileIds,
  selectedDatasetId,
  onSubmitSelectedToGovernance,
  onToggleGovernanceFileSelection,
  onDatasetScopeChange,
  tocEnabled,
  updateParsedFile,
  visibleLibraryOnlyFiles,
  visibleQueueFiles,
  vlmCorrectionEnabled,
}: Readonly<ParsingWorkbenchShellProps>) {
  const t = useTranslations('ParsingWorkbench')
  const bumpPdfPreviewResetToken = () => setPdfPreviewResetToken((prev) => prev + 1)
  const pendingCount = visibleQueueFiles.filter(
    (file) => file.status === 'pending'
  ).length
  const parsingCount = visibleQueueFiles.filter(
    (file) => file.status === 'parsing'
  ).length
  const parsedCount = visibleQueueFiles.filter(
    (file) => file.status === 'parsed'
  ).length
  const parseableCount = visibleQueueFiles.filter(
    (file) =>
      file.librarySource !== 'knowledge_base' &&
      (file.status === 'pending' || file.status === 'error')
  ).length
  const queueCountLabel =
    visibleQueueFiles.length === 0
      ? '0'
      : `${parsedCount}/${visibleQueueFiles.length}`
  const currentFolderFileCount =
    visibleQueueFiles.length + visibleLibraryOnlyFiles.length
  const readyGovernanceFileIds = useMemo(
    () => [
      ...visibleQueueFiles
        .filter((file) => file.governanceStatus === 'ready')
        .map((file) => file.id),
      ...visibleLibraryOnlyFiles
        .filter((file) => file.governanceStatus === 'ready')
        .map((file) => file.id),
    ],
    [visibleLibraryOnlyFiles, visibleQueueFiles]
  )
  const readyGovernanceCount = readyGovernanceFileIds.length
  const selectedReadyGovernanceCount = readyGovernanceFileIds.filter((fileId) =>
    selectedGovernanceFileIds.has(fileId)
  ).length

  const activeFolderPathLabel =
    folderPathById[activeFolderId || ROOT_FOLDER_ID] || t('rootFolder')
  const activeLibraryFolderId = activeLibraryFile?.folderId || ROOT_FOLDER_ID
  const activeLibraryFolderPathLabel =
    folderPathById[activeLibraryFolderId] || t('rootFolder')
  const activeLibraryFolderName =
    (activeLibraryFolderPathLabel.split('/').pop() || '').trim() ||
    activeLibraryFolderPathLabel
  const activeLibraryStatusBadge = activeLibraryFile?.status
    ? getLibraryStatusBadge(t, activeLibraryFile.status)
    : null
  const filename = String(activeLibraryFile?.filename || '')
  const activeLibraryMarkdownAvailable = Boolean(
    (
      activeLibraryFile?.markdownContent ||
      activeLibraryFile?.originalMarkdownContent ||
      ''
    ).trim()
  )
  const shouldAutoRestoreLibraryPdf =
    !activeFile &&
    activeLibraryFile != null &&
    activeLibraryFile.status === 'parsed' &&
    activeLibraryMarkdownAvailable &&
    filename.toLowerCase().endsWith('.pdf')

  useEffect(() => {
    if (activeFile || !activeLibraryFile) return
    if (!shouldAutoRestoreLibraryPdf) return

    detachPromise(restoreLibraryFileFromCache(activeLibraryFile.id, false))
  }, [
    activeFile,
    activeLibraryFile,
    restoreLibraryFileFromCache,
    shouldAutoRestoreLibraryPdf,
  ])
  const datasetDocumentCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const file of libraryFiles) {
      if (file.source !== 'knowledge_base' || !file.datasetId) continue
      counts.set(file.datasetId, (counts.get(file.datasetId) || 0) + 1)
    }
    return counts
  }, [libraryFiles])
  const datasetOptions = useMemo(
    () =>
      availableDatasets.map((dataset) => ({
        ...dataset,
        count: datasetDocumentCounts.get(dataset.id) || 0,
      })),
    [availableDatasets, datasetDocumentCounts]
  )
  const sidebarFileItems = useMemo<DocumentTreeFileItem[]>(() => {
    const queueFiles = selectedDatasetId ? [] : files
    const libraryFilesForScope = selectedDatasetId
      ? libraryFiles.filter(
          (file) =>
            file.source === 'knowledge_base' &&
            file.datasetId === selectedDatasetId
        )
      : libraryFiles
    const queueLibraryIds = new Set(
      queueFiles
        .map((file) => file.libraryId)
        .filter((value): value is string => Boolean(value))
    )
    const merged: DocumentTreeFileItem[] = queueFiles.map((file) => ({
      id: file.id,
      name: file.name,
      folderId: file.folderId || ROOT_FOLDER_ID,
      sourcePath: file.sourcePath,
      status: file.status,
      error: file.error,
      progress: file.progress,
      parser: file.parserLabel,
      duration: file.duration,
      pageCount: file.stats?.pageCount,
      governanceStatus: file.governanceStatus,
      isActive: activeFileId === file.id,
      isSelectable: file.governanceStatus === 'ready',
      isSelected: selectedGovernanceFileIds.has(file.id),
    }))

    for (const file of libraryFilesForScope) {
      if (queueLibraryIds.has(file.id)) continue
      merged.push({
        id: file.id,
        name: file.filename,
        folderId: file.folderId || ROOT_FOLDER_ID,
        sourcePath: file.sourcePath || file.datasetName || undefined,
        status: file.status || 'parsed',
        parser: file.parser,
        duration: file.durationSec,
        governanceStatus: file.governanceStatus,
        isActive: activeLibraryFileId === file.id,
        isSelectable: file.governanceStatus === 'ready',
        isSelected: selectedGovernanceFileIds.has(file.id),
        readOnly: file.source === 'knowledge_base',
      })
    }

    return merged
  }, [
    activeFileId,
    activeLibraryFileId,
    files,
    libraryFiles,
    selectedGovernanceFileIds,
    selectedDatasetId,
  ])

  return (
    <AppFrame mainClassName="bg-[radial-gradient(circle_at_82%_0%,hsl(var(--info)/0.12),transparent_30%),radial-gradient(circle_at_18%_6%,hsl(var(--primary)/0.06),transparent_24%),linear-gradient(180deg,hsl(var(--background))_0%,hsl(var(--muted)/0.18)_48%,hsl(var(--background))_100%)]">
      <WorkbenchScaffold
        title={t('title')}
        description={t('description')}
        header={
          <header className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div
              data-testid="parsing-workbench-title"
              className="relative flex min-w-0 flex-1 items-center gap-4 overflow-hidden rounded-[28px] border border-transparent bg-[linear-gradient(120deg,hsl(var(--background)/0.98),hsl(var(--info)/0.08))] px-5 py-3.5"
            >
              <div
                className="pointer-events-none absolute inset-0 overflow-hidden rounded-[28px]"
                aria-hidden="true"
              >
                <div className="absolute -right-20 -top-20 h-36 w-72 rounded-full bg-info/10 blur-2xl" />
                <div className="absolute bottom-0 right-0 h-14 w-[34rem] rounded-tl-full bg-[linear-gradient(90deg,transparent,hsl(var(--info)/0.10))]" />
              </div>
              <span
                className="relative flex size-12 shrink-0 items-center justify-center rounded-[18px] border border-info/15 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.10))] text-info shadow-[0_18px_38px_-30px_hsl(var(--info)/0.8)]"
                aria-hidden="true"
              >
                <PageTitleIcon name="parsing" className="size-8" />
              </span>
              <div className="relative min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <h1 className="truncate text-[24px] font-semibold leading-8 tracking-[-0.02em] text-foreground">
                    {t('title')}
                  </h1>
                </div>
                <p className="mt-1 flex max-w-[60ch] items-center gap-2 text-[14px] leading-[1.45] text-muted-foreground">
                  <span className="size-1.5 shrink-0 rounded-full bg-info/55 shadow-[0_0_0_4px_hsl(var(--info)/0.08)]" />
                  {t('description')}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-2 lg:hidden"
                onClick={() => setQueueOpen(true)}
              >
                <FileStack className="w-4 h-4" />
                {t('queue')}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-2 lg:hidden"
                onClick={() => setInspectorOpen(true)}
              >
                <Settings2 className="w-4 h-4" />
                {t('tools')}
              </Button>
            </div>
          </header>
        }
        size="full"
        bodyClassName="pb-5"
        pipelineRail={<PipelineRail />}
        mainPanel={
          <div
            data-testid="parsing-workbench-grid"
            className="flex h-full min-h-0 gap-3"
          >
            <ParsingSidebarPane
              collapsed={isSidebarCollapsed}
              onToggleCollapsed={() =>
                setIsSidebarCollapsed(!isSidebarCollapsed)
              }
              className="hidden lg:flex"
              activeFolderId={activeFolderId || ROOT_FOLDER_ID}
              activeFolderPathLabel={activeFolderPathLabel}
              currentFolderId={currentFolderId}
              currentFolderFileCount={currentFolderFileCount}
              datasetOptions={datasetOptions}
              selectedDatasetId={selectedDatasetId}
              onDatasetScopeChange={onDatasetScopeChange}
              parseableCount={parseableCount}
              parserBackend={parserBackend}
              imageCaptionEnabled={imageCaptionEnabled}
              imageOcrEnabled={imageOcrEnabled}
              vlmCorrectionEnabled={vlmCorrectionEnabled}
              isLibraryLoaded={isLibraryLoaded}
              sidebarFileItems={sidebarFileItems}
              onToggleGovernanceFileSelection={onToggleGovernanceFileSelection}
              fileAccept={UPLOAD_ACCEPT_WITH_ZIP}
              rebindAccept={UPLOAD_ACCEPT}
              fileInputRef={fileInputRef}
              folderInputRef={folderInputRef}
              rebindInputRef={rebindInputRef}
              onRequestUploadToCurrentFolder={() =>
                requestUploadToFolder(currentFolderId)
              }
              onRequestUploadToFolder={requestUploadToFolder}
              onRequestUploadFolder={requestUploadFolder}
              onParseAllPending={() => detachPromise(parseAllPending())}
              onParserBackendChange={setParserBackend}
              onImageCaptionEnabledChange={setImageCaptionEnabled}
              onImageOcrEnabledChange={setImageOcrEnabled}
              onVlmCorrectionEnabledChange={setVlmCorrectionEnabled}
              onFolderDragOver={handleFolderDragOver}
              onFolderDragLeave={handleFolderDragLeave}
              onFolderDrop={handleFolderDrop}
              onFolderTreeSelectFile={(fileId) => {
                const directQueueMatch = files.find(
                  (file) => file.id === fileId
                )
                if (directQueueMatch) {
                  bumpPdfPreviewResetToken()
                  setActiveLibraryFileId(null)
                  setActiveFileId(directQueueMatch.id)
                  return
                }

                const queueMatch = files.find(
                  (file) => file.libraryId === fileId
                )
                if (queueMatch) {
                  bumpPdfPreviewResetToken()
                  setActiveLibraryFileId(null)
                  setActiveFileId(queueMatch.id)
                  return
                }

                bumpPdfPreviewResetToken()
                setActiveFileId(null)
                setActiveLibraryFileId(fileId)
              }}
              onDeleteFolder={handleDeleteFolder}
              onMoveFileToFolder={moveFileToFolder}
              onFileDragStart={handleFileDragStart}
              onRetryFile={(fileId) => detachPromise(parseFile(fileId))}
              onRemoveFile={removeFile}
              onFileSelect={(event) => void handleFileSelect(event)}
              onRebindFileSelect={(event) => void handleRebindFileSelect(event)}
            />

            <ParsingMainPanel
              data-testid="parsing-main-panel"
              className={cn(
                'relative overflow-hidden rounded-[24px] border bg-card/96 shadow-[0_24px_64px_-48px_rgba(15,23,42,0.42)] backdrop-blur-sm',
                activeFile || activeLibraryFile
                  ? 'border-border/70'
                  : 'border-dashed border-info/30'
              )}
            >
              <div className="flex flex-1 min-h-0 min-w-0 flex-col overflow-hidden bg-card dark:bg-background">
                {activeFile || activeLibraryFile ? (
                  <>
                    {!activeFile && activeLibraryFile ? (
                      <ParsingLibraryPreviewPane
                        file={activeLibraryFile}
                        activeMarkdown={activeMarkdown}
                        folderName={activeLibraryFolderName}
                        folderPathLabel={activeLibraryFolderPathLabel}
                        sourceStatus={activeLibrarySourceStatus}
                        defaultParserBackend={parserBackend}
                        statusBadge={activeLibraryStatusBadge}
                        onClose={() => setActiveLibraryFileId(null)}
                        onUpdateParser={(backend) => {
                          const resolved = resolveParserBackendForFilename(
                            activeLibraryFile.filename,
                            backend
                          )
                          updateParsedFile(activeLibraryFile.id, {
                            parserBackend: resolved.backend,
                            parser: getParserLabel(resolved.backend),
                          })
                        }}
                        onRestoreSource={(autoParse) => {
                          detachPromise(
                            restoreLibraryFileFromCache(
                              activeLibraryFile.id,
                              autoParse
                            )
                          )
                        }}
                        onRequestRebind={(autoParse) =>
                          requestRebindForLibraryFile(
                            activeLibraryFile.id,
                            autoParse
                          )
                        }
                      />
                    ) : null}

                    {activeFile ? (
                      <ParsingActiveFilePane
                        activeFile={activeFile}
                        activeRun={activeRun}
                        activeMarkdown={activeMarkdown}
                        activeElements={activeElements}
                        activeQualityGate={activeQualityGate}
                        activePdfQuality={activePdfQuality}
                        activeBlocksWithPositions={activeBlocksWithPositions}
                        isPdf={isPdf}
                        tocEnabled={tocEnabled}
                        previewMode={previewMode}
                        rightPanelMode={rightPanelMode}
                        isEditing={isEditing}
                        editedContent={editedContent}
                        copied={copied}
                        activeBlockId={activeBlockId}
                        hoveredBlockId={hoveredBlockId}
                        onSelectRun={handleSelectRun}
                        onPreviewModeChange={setPreviewMode}
                        onRightPanelModeChange={setRightPanelMode}
                        onStartEdit={handleStartEdit}
                        onCancelEdit={handleCancelEdit}
                        onSaveEdit={() => detachPromise(handleSaveEdit())}
                        onCopyMarkdown={() => detachPromise(copyMarkdown())}
                        onDownloadMarkdown={downloadMarkdown}
                        onParseFile={parseFile}
                        pdfPreviewResetToken={pdfPreviewResetToken}
                        onSetQueueFileParserBackend={setQueueFileParserBackend}
                        onSubmitToGovernance={handleSubmitToGovernance}
                        onEditedContentChange={setEditedContent}
                        onActiveBlockIdChange={setActiveBlockId}
                        onHoveredBlockIdChange={setHoveredBlockId}
                      />
                    ) : null}
                  </>
                ) : (
                  <button
                    type="button"
                    className="relative flex flex-1 items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_50%_38%,hsl(var(--info)/0.10),transparent_24%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.05)_48%,hsl(var(--background)))]"
                    onClick={() => requestUploadToFolder(currentFolderId)}
                    onDragOver={(event) =>
                      handleFolderDragOver(event, currentFolderId)
                    }
                    onDragLeave={handleFolderDragLeave}
                    onDrop={(event) => handleFolderDrop(event, currentFolderId)}
                  >
                    <div
                      aria-hidden="true"
                      className="absolute inset-0 bg-[linear-gradient(hsl(var(--info)/0.055)_1px,transparent_1px),linear-gradient(90deg,hsl(var(--info)/0.055)_1px,transparent_1px)] bg-[size:42px_42px]"
                    />
                    <div className="relative max-w-md px-8 text-center">
                      <div className="mx-auto mb-6 flex size-28 items-center justify-center rounded-[30px] border border-info/20 bg-card shadow-[0_24px_58px_-40px_rgba(37,99,235,0.75)]">
                        <div className="relative flex h-20 w-16 items-center justify-center rounded-[18px] bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.55))] shadow-[0_14px_30px_-20px_rgba(15,23,42,0.45)]">
                          <div className="absolute right-0 top-0 size-7 rounded-bl-2xl bg-info/15" />
                          <div className="space-y-2">
                            <div className="h-1 w-8 rounded-full bg-info" />
                            <div className="h-1 w-11 rounded-full bg-info/35" />
                            <div className="h-1 w-10 rounded-full bg-info/25" />
                          </div>
                          <span className="absolute -bottom-3 -right-3 flex size-10 items-center justify-center rounded-full bg-[#2563eb] text-primary-foreground shadow-[0_18px_32px_-18px_rgba(37,99,235,0.75)]">
                            <UploadCloud className="size-4" />
                          </span>
                        </div>
                      </div>
                      <h3 className="mb-2 text-[22px] font-semibold tracking-[-0.03em] text-foreground">
                        {t('emptyTitle')}
                      </h3>
                      <p className="mx-auto max-w-[34ch] text-[14px] leading-6 text-muted-foreground">
                        {t('emptyDescription')}
                      </p>
                      <span className="mt-6 inline-flex h-11 min-w-36 items-center justify-center gap-2 rounded-[16px] bg-[#2563eb] px-6 text-[14px] font-semibold text-primary-foreground shadow-[0_18px_34px_-20px_rgba(37,99,235,0.78)] transition-colors hover:bg-[#1d4ed8]">
                        <UploadCloud className="size-4" />
                        {t('sidebar.uploadFile')}
                      </span>
                      <div className="mt-3 text-[12px] text-muted-foreground/75">
                        或将文件拖拽到此区域
                      </div>
                    </div>
                  </button>
                )}
              </div>
            </ParsingMainPanel>
            <ResizableParsingInspectorRail>
              <ParsingInspectorPanel
                activeFile={activeFile}
                activeLibraryFile={activeLibraryFile}
                activeLibraryFolderPathLabel={activeLibraryFolderPathLabel}
                activeLibraryStatusBadge={activeLibraryStatusBadge}
                activeMarkdown={activeMarkdown}
                copied={copied}
                parsedCount={parsedCount}
                parsingCount={parsingCount}
                pendingCount={pendingCount}
                parserBackend={parserBackend}
                queueFileCount={visibleQueueFiles.length}
                readyGovernanceCount={readyGovernanceCount}
                selectedDatasetId={selectedDatasetId}
                selectedReadyGovernanceCount={selectedReadyGovernanceCount}
                scopeFileCount={currentFolderFileCount}
                onCopyMarkdown={() => detachPromise(copyMarkdown())}
                onDownloadMarkdown={downloadMarkdown}
                onParseFile={(fileId) => parseFile(fileId)}
                onRestoreLibraryFile={(autoParse) => {
                  if (!activeLibraryFile) return
                  detachPromise(
                    restoreLibraryFileFromCache(activeLibraryFile.id, autoParse)
                  )
                }}
                onRequestRebindLibraryFile={(autoParse) => {
                  if (!activeLibraryFile) return
                  requestRebindForLibraryFile(activeLibraryFile.id, autoParse)
                }}
                onSubmitSelectedToGovernance={onSubmitSelectedToGovernance}
                onSubmitToGovernance={handleSubmitToGovernance}
              />
            </ResizableParsingInspectorRail>
          </div>
        }
      />

      <WorkbenchPanelDialog
        open={queueOpen}
        onOpenChange={setQueueOpen}
        title={t('queue')}
      >
        <ParsingMobileQueueContent
          queueCountLabel={queueCountLabel}
          parseableCount={parseableCount}
          activeFileId={activeFileId}
          activeLibraryFileId={activeLibraryFileId}
          visibleQueueFiles={visibleQueueFiles}
          visibleLibraryOnlyFiles={visibleLibraryOnlyFiles}
          folderPathById={folderPathById}
          files={files}
          onParseAllPending={() => detachPromise(parseAllPending())}
          onRequestUploadToFolder={requestUploadToFolder}
          onRequestUploadFolder={requestUploadFolder}
          onSelectQueueFile={(fileId) => {
            bumpPdfPreviewResetToken()
            setActiveLibraryFileId(null)
            setActiveFileId(fileId)
            setQueueOpen(false)
          }}
          onSelectLibraryFile={(fileId) => {
            bumpPdfPreviewResetToken()
            setActiveFileId(null)
            setActiveLibraryFileId(fileId)
            setQueueOpen(false)
          }}
          onDeleteFolder={handleDeleteFolder}
          onMoveFileToFolder={moveFileToFolder}
          onRemoveFile={removeFile}
          onRetryParse={(fileId) => detachPromise(parseFile(fileId))}
          onFileDragStart={handleFileDragStart}
        />
      </WorkbenchPanelDialog>

      <WorkbenchPanelDialog
        open={inspectorOpen}
        onOpenChange={setInspectorOpen}
        title={t('tools')}
      >
        {activeFile && activeMarkdown ? (
          <ParsingMobileInspectorContent
            documentId={activeFile.libraryId || null}
            activeMarkdown={activeMarkdown}
            rightPanelMode={rightPanelMode}
            previewMode={previewMode}
            activeBlocksWithPositions={activeBlocksWithPositions}
            activeBlockId={activeBlockId}
            activeElements={activeElements}
            onRightPanelModeChange={setRightPanelMode}
            onPreviewModeChange={setPreviewMode}
            onSelectBlock={(blockId) => {
              setActiveBlockId(blockId)
              setInspectorOpen(false)
            }}
            onSelectElement={(elementId) => {
              setActiveBlockId(elementId)
              setRightPanelMode('blocks')
              setInspectorOpen(false)
            }}
            onSelectEvidence={({ evidence }) => {
              const elementId = String(evidence.element_id || '').trim()
              if (elementId) {
                setActiveBlockId(elementId)
              }
              setRightPanelMode('blocks')
              setInspectorOpen(false)
            }}
            onCopyMarkdown={() => detachPromise(copyMarkdown())}
            onDownloadMarkdown={downloadMarkdown}
          />
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain bg-muted/10 p-4 no-scrollbar">
            <div className="text-sm text-muted-foreground">
              {t('inspectorEmpty')}
            </div>
          </div>
        )}
      </WorkbenchPanelDialog>
    </AppFrame>
  )
}
