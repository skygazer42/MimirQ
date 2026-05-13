'use client'

import {
  useEffect,
  useMemo,
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
import {
  PipelineRail,
  WorkbenchPanelDialog,
  WorkbenchScaffold,
} from '@/components/workbench'
import type { ParsingElement } from '@/lib/api/parsing'
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
  selectedDatasetId: string | null
  onDatasetScopeChange: (datasetId: string | null) => void
  tocEnabled: boolean
  updateParsedFile: (
    id: string,
    updates: Partial<Omit<ParsedFileData, 'id'>>
  ) => void
  visibleLibraryOnlyFiles: ParsedFileData[]
  visibleQueueFiles: ParsedFile[]
}

type DatasetScopeOption = {
  id: string
  name: string
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
    <section className="rounded-[18px] border border-border/70 bg-card/96 p-4 shadow-[0_18px_42px_-34px_rgba(15,23,42,0.36)]">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-lg bg-primary/[0.08] text-primary">
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
      className="group rounded-[18px] border border-border/65 bg-card/92 shadow-[0_18px_42px_-36px_rgba(15,23,42,0.34)]"
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
    <div className="grid grid-cols-2 overflow-hidden rounded-xl border border-border/60 bg-background/70">
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

function ParsingInspectorPanel({
  activeFile,
  activeLibraryFile,
  activeLibraryFolderPathLabel,
  activeLibraryStatusBadge,
  activeMarkdown,
  copied,
  files,
  parsedCount,
  parsingCount,
  pendingCount,
  parserBackend,
  selectedDatasetId,
  onCopyMarkdown,
  onDownloadMarkdown,
  onParseFile,
  onRestoreLibraryFile,
  onRequestRebindLibraryFile,
  onSubmitToGovernance,
}: Readonly<{
  activeFile: ParsedFile | null
  activeLibraryFile: ParsedFileData | null
  activeLibraryFolderPathLabel: string
  activeLibraryStatusBadge: ReturnType<typeof getLibraryStatusBadge> | null
  activeMarkdown: string
  copied: boolean
  files: ParsedFile[]
  parsedCount: number
  parsingCount: number
  pendingCount: number
  parserBackend: string
  selectedDatasetId: string | null
  onCopyMarkdown: () => void
  onDownloadMarkdown: () => void
  onParseFile: (fileId: string) => void
  onRestoreLibraryFile: (autoParse: boolean) => void
  onRequestRebindLibraryFile: (autoParse: boolean) => void
  onSubmitToGovernance: () => void
}>) {
  const selectedName = activeFile?.file.name || activeLibraryFile?.filename || ''
  const selectedSize = activeFile?.file.size ?? activeLibraryFile?.fileSize ?? null
  const selectedParser =
    activeFile?.parserLabel ||
    activeLibraryFile?.parser ||
    getParserLabel(parserBackend)
  const selectedStatus = activeFile?.status || activeLibraryFile?.status || null
  const statusLabel = activeFile
    ? selectedStatus === 'parsed'
      ? '已解析'
      : selectedStatus === 'parsing'
        ? '解析中'
        : selectedStatus === 'error'
          ? '失败'
          : '待解析'
    : activeLibraryStatusBadge?.label || (activeLibraryFile ? '已解析' : '未选择')
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
  const hasSelection = Boolean(selectedName)
  const selectedError = activeFile?.error || activeLibraryFile?.error || ''
  const selectedProgress = Math.round(activeFile?.progress || (activeFile?.status === 'parsed' ? 100 : 0))
  const isError = selectedStatus === 'error'
  const isParsing = selectedStatus === 'parsing'
  const isPending = selectedStatus === 'pending'
  const StatusIcon = isError ? AlertCircle : isParsing ? Clock3 : CheckCircle2
  const statusToneClass = isError
    ? 'border-destructive/25 bg-destructive/[0.08] text-destructive'
    : isPending
      ? 'border-warning/25 bg-warning/[0.10] text-warning'
      : isParsing
        ? 'border-info/25 bg-info/[0.08] text-info'
        : 'border-success/25 bg-success/[0.08] text-success'
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
          {activeFile.status === 'error' ? '重试' : '开始'}
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
        className="col-span-2 h-8 gap-1.5 rounded-xl bg-primary text-[12px] text-primary-foreground"
        disabled={!activeFile || !canUseMarkdownActions}
        onClick={onSubmitToGovernance}
      >
        <ShieldCheck className="size-3.5" />
        提交到数据治理
      </Button>
    </div>
  )

  return (
    <aside className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto overscroll-contain rounded-[22px] border border-border/70 bg-[linear-gradient(180deg,hsl(var(--background)/0.98),hsl(var(--muted)/0.30))] p-3 shadow-[0_22px_58px_-42px_rgba(15,23,42,0.38)]">
      {hasSelection ? (
        <>
          <section className="rounded-[18px] border border-border/70 bg-card/96 p-4 shadow-[0_18px_42px_-34px_rgba(15,23,42,0.36)]">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-[13px] font-semibold text-foreground" title={selectedName}>
                  {selectedName}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
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
              </div>
              <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-semibold ${statusToneClass}`}>
                <StatusIcon className="size-3.5" />
                {statusLabel}
              </span>
            </div>

            {selectedError ? (
              <div className="mt-3 rounded-xl border border-destructive/20 bg-destructive/[0.06] p-3">
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
              <div className="mt-3 grid grid-cols-2 gap-2 text-[12px]">
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
          </section>

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
                <span className="font-mono font-semibold text-foreground">{files.length}</span>
              </div>
            </div>
          </ParsingInspectorCard>

          <ParsingInspectorCard title="解析状态" icon={CheckCircle2}>
            <div className="space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-success/25 bg-success/[0.08] px-3 py-1 text-[12px] font-semibold text-success">
                <CheckCircle2 className="size-3.5" />
                {statusLabel}
              </div>
              <ParsingMetricGrid
                items={[
                  { label: '已解析', value: parsedCount },
                  { label: '解析中', value: parsingCount },
                  { label: '待处理', value: pendingCount },
                  { label: '队列', value: files.length },
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

function ParsingInspectorDock({
  open,
  children,
  onOpenChange,
}: Readonly<{
  open: boolean
  children: React.ReactNode
  onOpenChange: (open: boolean) => void
}>) {
  return (
    <div className="pointer-events-none fixed bottom-5 right-4 top-[148px] z-30 hidden xl:block">
      <div
        data-testid="parsing-inspector-dock"
        data-state={open ? 'open' : 'closed'}
        className={cn(
          'pointer-events-auto relative h-full w-[408px] transition-transform duration-300 ease-out motion-reduce:transition-none',
          open ? 'translate-x-0' : 'translate-x-[360px]'
        )}
      >
        <button
          type="button"
          aria-label={open ? '收起解析信息面板' : '展开解析信息面板'}
          aria-expanded={open}
          className={cn(
            'absolute z-10 border border-border/70 bg-card/96 text-muted-foreground shadow-[0_14px_34px_-24px_rgba(15,23,42,0.48)] backdrop-blur transition-colors hover:text-foreground',
            open
              ? 'left-0 top-3 flex h-[124px] w-9 flex-col items-center justify-start gap-2 rounded-l-[18px] rounded-r-none border-r-0 px-1.5 py-3'
              : 'left-[-80px] top-0 flex h-8 w-[112px] items-center justify-center gap-1.5 rounded-full px-3'
          )}
          onClick={() => onOpenChange(!open)}
        >
          {open ? (
            <PanelRightClose className="pointer-events-none size-3.5" />
          ) : (
            <PanelRightOpen className="pointer-events-none size-3.5" />
          )}
          <span
            className={cn(
              'pointer-events-none font-semibold',
              open
                ? 'writing-mode-vertical-rl [writing-mode:vertical-rl] text-[11px] tracking-[0.14em]'
                : 'text-[12px] tracking-normal'
            )}
          >
            解析信息
          </span>
        </button>
        <div
          className={cn(
            'ml-11 h-full w-[360px] transition-opacity duration-200 motion-reduce:transition-none',
            open ? 'opacity-100' : 'opacity-0'
          )}
          aria-hidden={!open}
        >
          {children}
        </div>
      </div>
    </div>
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
  setInspectorOpen,
  setIsSidebarCollapsed,
  setParserBackend,
  setPdfPreviewResetToken,
  setPreviewMode,
  setQueueOpen,
  setQueueFileParserBackend,
  setRightPanelMode,
  selectedDatasetId,
  onDatasetScopeChange,
  tocEnabled,
  updateParsedFile,
  visibleLibraryOnlyFiles,
  visibleQueueFiles,
}: Readonly<ParsingWorkbenchShellProps>) {
  const t = useTranslations('ParsingWorkbench')
  const [desktopInspectorOpen, setDesktopInspectorOpen] = useState(true)
  const bumpPdfPreviewResetToken = () =>
    setPdfPreviewResetToken((prev) => prev + 1)
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

  const activeFolderPathLabel =
    folderPathById[activeFolderId || ROOT_FOLDER_ID] || t('rootFolder')
  const activeLibraryFolderId = activeLibraryFile?.folderId || ROOT_FOLDER_ID
  const activeLibraryFolderPathLabel =
    folderPathById[activeLibraryFolderId] || t('rootFolder')
  const activeLibraryFolderName =
    (activeLibraryFolderPathLabel.split('/').pop() || '').trim() ||
    activeLibraryFolderPathLabel
  const activeLibraryStatusBadge = activeLibraryFile?.status
    ? getLibraryStatusBadge(activeLibraryFile.status, t)
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
    activeLibraryFile &&
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
      isActive: activeFileId === file.id,
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
        isActive: activeLibraryFileId === file.id,
        readOnly: file.source === 'knowledge_base',
      })
    }

    return merged
  }, [
    activeFileId,
    activeLibraryFileId,
    files,
    libraryFiles,
    selectedDatasetId,
  ])

  return (
    <AppFrame mainClassName="bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.20))]">
      <WorkbenchScaffold
        title={t('title')}
        description={t('description')}
        header={
          <header className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div
              data-testid="parsing-workbench-title"
              className="relative flex min-w-0 flex-1 items-center gap-3 overflow-hidden rounded-[24px] border border-border/70 bg-[linear-gradient(135deg,hsl(var(--card)/0.98),hsl(var(--muted)/0.36))] px-4 py-3 shadow-[0_18px_46px_-38px_rgba(15,23,42,0.48)]"
            >
              <div
                className="pointer-events-none absolute inset-y-3 left-0 w-1 rounded-r-full bg-[linear-gradient(180deg,hsl(var(--info)),hsl(var(--primary)))]"
                aria-hidden="true"
              />
              <div
                className="pointer-events-none absolute -right-8 -top-10 size-28 rounded-full bg-info/10 blur-2xl"
                aria-hidden="true"
              />
              <span
                className="relative flex size-11 shrink-0 items-center justify-center rounded-[18px] border border-info/18 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.10))] text-info shadow-[inset_0_1px_0_hsl(var(--background)),0_14px_30px_-24px_hsl(var(--info)/0.75)]"
                aria-hidden="true"
              >
                <FileText className="size-5" />
              </span>
              <div className="relative min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <h1 className="truncate text-[24px] font-semibold leading-8 tracking-[-0.02em] text-foreground">
                    <span className="bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent">
                      {t('title')}
                    </span>
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
          <ParsingMainPanel
            data-testid="parsing-main-panel"
            className="overflow-hidden rounded-[22px] border border-border/70 bg-card shadow-[0_24px_64px_-46px_rgba(15,23,42,0.48)]"
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
              pendingCount={pendingCount}
              parsingCount={parsingCount}
              parsedCount={parsedCount}
              parseableCount={parseableCount}
              parserBackend={parserBackend}
              imageCaptionEnabled={imageCaptionEnabled}
              isLibraryLoaded={isLibraryLoaded}
              sidebarFileItems={sidebarFileItems}
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
                <div className="flex flex-1 items-center justify-center bg-[radial-gradient(circle_at_50%_42%,hsl(var(--primary)/0.055),transparent_28%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.18))]">
                  <div className="max-w-md text-center">
                    <div className="mx-auto mb-5 flex size-20 items-center justify-center rounded-[22px] border border-border/70 bg-card shadow-[0_18px_44px_-32px_rgba(15,23,42,0.5)]">
                      <FileText className="h-10 w-10 text-muted-foreground" />
                    </div>
                    <h3 className="mb-2 text-[18px] font-semibold text-foreground">
                      {t('emptyTitle')}
                    </h3>
                    <p className="text-sm text-muted-foreground">
                      {t('emptyDescription')}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </ParsingMainPanel>
        }
      />

      <ParsingInspectorDock
        open={desktopInspectorOpen}
        onOpenChange={setDesktopInspectorOpen}
      >
        <ParsingInspectorPanel
          activeFile={activeFile}
          activeLibraryFile={activeLibraryFile}
          activeLibraryFolderPathLabel={activeLibraryFolderPathLabel}
          activeLibraryStatusBadge={activeLibraryStatusBadge}
          activeMarkdown={activeMarkdown}
          copied={copied}
          files={visibleQueueFiles}
          parsedCount={parsedCount}
          parsingCount={parsingCount}
          pendingCount={pendingCount}
          parserBackend={parserBackend}
          selectedDatasetId={selectedDatasetId}
          onCopyMarkdown={() => detachPromise(copyMarkdown())}
          onDownloadMarkdown={downloadMarkdown}
          onParseFile={(fileId) => parseFile(fileId)}
          onRestoreLibraryFile={(autoParse) => {
            if (!activeLibraryFile) return
            detachPromise(restoreLibraryFileFromCache(activeLibraryFile.id, autoParse))
          }}
          onRequestRebindLibraryFile={(autoParse) => {
            if (!activeLibraryFile) return
            requestRebindForLibraryFile(activeLibraryFile.id, autoParse)
          }}
          onSubmitToGovernance={handleSubmitToGovernance}
        />
      </ParsingInspectorDock>

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
