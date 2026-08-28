'use client'

import { useEffect, useState } from 'react'
import type { RefObject } from 'react'
import {
  Database,
  FileText,
  FolderUp,
  Loader2,
  Paperclip,
  Play,
  Plus,
  Settings2,
} from 'lucide-react'
import { useTranslations } from 'next-intl'

import {
  DocumentFolderTree,
  type DocumentTreeFileItem,
} from '@/components/document-library/folder-tree'
import { ParsingLeftPanel } from '@/components/parsing/parsing-left-panel'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { ROOT_FOLDER_ID } from '@/store/use-parsed-files-store'

type ParsingSidebarPaneProps = {
  collapsed: boolean
  className?: string
  activeFolderId: string
  activeFolderPathLabel: string
  currentFolderId: string
  currentFolderFileCount: number
  datasetOptions: DatasetScopeOption[]
  selectedDatasetId: string | null
  parseableCount: number
  parserBackend: string
  imageCaptionEnabled: boolean
  imageOcrEnabled: boolean
  vlmCorrectionEnabled: boolean
  isLibraryLoaded: boolean
  sidebarFileItems: DocumentTreeFileItem[]
  fileAccept: string
  rebindAccept: string
  fileInputRef: RefObject<HTMLInputElement | null>
  folderInputRef: RefObject<HTMLInputElement | null>
  rebindInputRef: RefObject<HTMLInputElement | null>
  onToggleCollapsed: () => void
  onDatasetScopeChange: (datasetId: string | null) => void
  onRequestUploadToCurrentFolder: () => void
  onRequestUploadToFolder: (folderId: string) => void
  onRequestUploadFolder: (folderId: string) => void
  onParseAllPending: () => void
  onParserBackendChange: (backend: string) => void
  onImageCaptionEnabledChange: (enabled: boolean) => void
  onImageOcrEnabledChange: (enabled: boolean) => void
  onVlmCorrectionEnabledChange: (enabled: boolean) => void
  onFolderDragOver: (
    event: React.DragEvent<HTMLElement>,
    folderId: string
  ) => void
  onFolderDragLeave: () => void
  onFolderDrop: (event: React.DragEvent<HTMLElement>, folderId: string) => void
  onFolderTreeSelectFile: (fileId: string) => void
  onToggleGovernanceFileSelection: (fileId: string) => void
  onDeleteFolder: (folderIds: string[]) => void
  onMoveFileToFolder: (fileId: string, folderId: string) => void
  onFileDragStart: (event: React.DragEvent<HTMLElement>, fileId: string) => void
  onRetryFile: (fileId: string) => void
  onRemoveFile: (fileId: string) => void
  onFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => void
  onRebindFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => void
}

type DatasetScopeOption = {
  id: string
  name: string
  count?: number
}

const DATASET_ALL_VALUE = '__all__'
const DOCUMENT_EXTENSIONS = new Set([
  'pdf',
  'md',
  'markdown',
  'doc',
  'docx',
  'txt',
  'rtf',
  'rst',
  'adoc',
])
const SPREADSHEET_EXTENSIONS = new Set(['xls', 'xlsx', 'csv', 'tsv'])
const DIRECTORY_INPUT_PROPS = { webkitdirectory: '' }

function getSidebarFileExtension(name: string) {
  return name.split('.').pop()?.trim().toLowerCase() || ''
}

export function ParsingSidebarPane({
  collapsed,
  className,
  activeFolderId,
  activeFolderPathLabel,
  currentFolderId,
  currentFolderFileCount,
  datasetOptions,
  selectedDatasetId,
  parseableCount,
  parserBackend,
  imageCaptionEnabled,
  imageOcrEnabled,
  vlmCorrectionEnabled,
  isLibraryLoaded,
  sidebarFileItems,
  fileAccept,
  rebindAccept,
  fileInputRef,
  folderInputRef,
  rebindInputRef,
  onToggleCollapsed,
  onDatasetScopeChange,
  onRequestUploadToCurrentFolder,
  onRequestUploadToFolder,
  onRequestUploadFolder,
  onParseAllPending,
  onParserBackendChange,
  onImageCaptionEnabledChange,
  onImageOcrEnabledChange,
  onVlmCorrectionEnabledChange,
  onFolderDragOver,
  onFolderDragLeave,
  onFolderDrop,
  onFolderTreeSelectFile,
  onToggleGovernanceFileSelection,
  onDeleteFolder,
  onMoveFileToFolder,
  onFileDragStart,
  onRetryFile,
  onRemoveFile,
  onFileSelect,
  onRebindFileSelect,
}: Readonly<ParsingSidebarPaneProps>) {
  const t = useTranslations('ParsingWorkbench')
  const [parserSettingsOpen, setParserSettingsOpen] = useState(false)
  const [draftParserBackend, setDraftParserBackend] = useState(parserBackend)
  const hasParserDraftChange = draftParserBackend !== parserBackend

  useEffect(() => {
    if (parserSettingsOpen) {
      setDraftParserBackend(parserBackend)
    }
  }, [parserBackend, parserSettingsOpen])

  const fileTypeCounts = sidebarFileItems.reduce(
    (acc, file) => {
      const extension = getSidebarFileExtension(file.name)
      if (SPREADSHEET_EXTENSIONS.has(extension)) {
        acc.spreadsheets += 1
      } else if (DOCUMENT_EXTENSIONS.has(extension)) {
        acc.documents += 1
      } else {
        acc.other += 1
      }
      return acc
    },
    { documents: 0, other: 0, spreadsheets: 0 }
  )
  const fileTypeSummary = [
    { label: '全部', value: sidebarFileItems.length, icon: Paperclip },
    { label: '文档', value: fileTypeCounts.documents, icon: FileText },
    { label: '表格', value: fileTypeCounts.spreadsheets, icon: Database },
    { label: '其他', value: fileTypeCounts.other, icon: Settings2 },
  ]

  return (
    <ParsingLeftPanel
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      className={className}
    >
      <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-border/55 bg-background px-3 py-2">
        <button
          type="button"
          className="group flex min-w-0 flex-1 items-center gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/40"
          onClick={onRequestUploadToCurrentFolder}
          onDragOver={(event) => onFolderDragOver(event, currentFolderId)}
          onDragLeave={onFolderDragLeave}
          onDrop={(event) => onFolderDrop(event, currentFolderId)}
          title={t('sidebar.uploadCurrentFolderTitle')}
          aria-label={`${t('sidebar.uploadCurrentFolderTitle')} · ${activeFolderPathLabel}`}
        >
          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-info/20 bg-info/[0.08] text-info">
            <FileText className="size-3.5" />
          </div>
          <span className="truncate text-[13px] font-semibold text-foreground">
            {t('sidebar.documentList')}
          </span>
          <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/70">
            {currentFolderFileCount}
          </span>
        </button>

        <div className="flex shrink-0 items-center gap-0.5">
          {parseableCount > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onParseAllPending}
              className="h-7 gap-1 rounded-md px-2 text-[11px] font-medium text-info hover:bg-info/[0.08] hover:text-info"
            >
              <Play className="size-3" />
              {t('sidebar.parse')}
            </Button>
          ) : null}

          <Popover open={parserSettingsOpen} onOpenChange={setParserSettingsOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
                title={t('sidebar.defaultParser')}
                aria-label={t('sidebar.defaultParser')}
              >
                <Settings2 className="size-3.5" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-3">
              <div className="space-y-3">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">
                      {t('sidebar.defaultParser')}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {t('sidebar.newUploadDefault')}
                    </div>
                  </div>
                  <ParserDropdown
                    value={draftParserBackend}
                    onChange={setDraftParserBackend}
                  />
                  <div className="rounded-xl border border-info/20 bg-info/[0.07] px-3 py-2 text-xs leading-snug text-info">
                    {t('sidebar.parserApplyHint')}
                  </div>
                  <p className="text-xs leading-snug text-muted-foreground">
                    {t('sidebar.defaultParserDescription')}
                  </p>
                  <div className="flex items-center justify-end gap-2 pt-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 rounded-lg px-3 text-xs"
                      onClick={() => {
                        setDraftParserBackend(parserBackend)
                        setParserSettingsOpen(false)
                      }}
                    >
                      {t('sidebar.cancelParserSelection')}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      className="h-8 rounded-lg px-3 text-xs"
                      disabled={!hasParserDraftChange}
                      onClick={() => {
                        if (!hasParserDraftChange) return
                        onParserBackendChange(draftParserBackend)
                        setParserSettingsOpen(false)
                      }}
                    >
                      {t('sidebar.confirmParserSelection')}
                    </Button>
                  </div>
                </div>

                <div className="h-px bg-border/60" />

                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {t('sidebar.imageCaptionTitle')}
                    </div>
                    <div className="mt-1 text-xs leading-snug text-muted-foreground">
                      {t('sidebar.imageCaptionDescription')}
                    </div>
                  </div>
                  <Switch
                    checked={imageCaptionEnabled}
                    onCheckedChange={onImageCaptionEnabledChange}
                  />
                </div>

                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {t('sidebar.imageOcrTitle')}
                    </div>
                    <div className="mt-1 text-xs leading-snug text-muted-foreground">
                      {t('sidebar.imageOcrDescription')}
                    </div>
                  </div>
                  <Switch
                    checked={imageOcrEnabled}
                    onCheckedChange={onImageOcrEnabledChange}
                  />
                </div>

                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      {t('sidebar.vlmCorrectionTitle')}
                    </div>
                    <div className="mt-1 text-xs leading-snug text-muted-foreground">
                      {t('sidebar.vlmCorrectionDescription')}
                    </div>
                  </div>
                  <Switch
                    checked={vlmCorrectionEnabled}
                    onCheckedChange={onVlmCorrectionEnabledChange}
                  />
                </div>
              </div>
            </PopoverContent>
          </Popover>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={t('sidebar.uploadActions')}
                title={t('sidebar.uploadActions')}
              >
                <Plus className="size-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuItem
                onClick={() =>
                  onRequestUploadToFolder(activeFolderId || ROOT_FOLDER_ID)
                }
              >
                <Paperclip className="mr-2 size-4 text-muted-foreground" />
                {t('sidebar.uploadFile')}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  onRequestUploadFolder(activeFolderId || ROOT_FOLDER_ID)
                }
              >
                <FolderUp className="mr-2 size-4 text-muted-foreground" />
                {t('sidebar.uploadFolder')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {collapsed ? null : (
        <div className="flex items-center gap-2 border-b border-border/55 bg-background px-3 py-2">
          <span className="shrink-0 text-[11px] font-medium text-muted-foreground">
            {t('sidebar.datasetScope')}
          </span>
          <div className="min-w-0 flex-1">
            <Select
              value={selectedDatasetId || DATASET_ALL_VALUE}
              onValueChange={(value) =>
                onDatasetScopeChange(value === DATASET_ALL_VALUE ? null : value)
              }
            >
              <SelectTrigger
                aria-label={t('sidebar.datasetScope')}
                className="h-8 min-w-0 flex-1 rounded-lg border-border/55 bg-muted/25 px-2.5 text-[11px] font-medium text-foreground shadow-none transition-colors duration-200 hover:border-info/40 focus:border-info/60 focus-visible:ring-2 focus-visible:ring-info/20 focus-visible:ring-offset-0 data-[state=open]:border-info/60 motion-reduce:transition-none"
              >
                <div className="flex min-w-0 items-center gap-1.5">
                  <Database className="size-3 shrink-0 text-info/80" />
                  <span className="min-w-0 truncate">
                    <SelectValue placeholder={t('sidebar.allDatasetScope')} />
                  </span>
                </div>
              </SelectTrigger>
              <SelectContent className="border-border/60 bg-popover text-foreground">
                <SelectItem value={DATASET_ALL_VALUE} className="text-[12px]">
                  <span className="flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className="size-1.5 rounded-full bg-muted-foreground/50"
                    />
                    {t('sidebar.allDatasetScope')}
                  </span>
                </SelectItem>
                {datasetOptions.map((dataset) => (
                  <SelectItem
                    key={dataset.id}
                    value={dataset.id}
                    className="text-[12px]"
                  >
                    <span className="flex items-center gap-1.5">
                      <span
                        aria-hidden
                        className="size-1.5 rounded-full bg-info/70"
                      />
                      <span className="truncate">{dataset.name}</span>
                      {typeof dataset.count === 'number' ? (
                        <span className="ml-auto pl-2 text-[10px] tabular-nums text-muted-foreground/70">
                          {dataset.count}
                        </span>
                      ) : null}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-background px-2.5 py-2">
        {isLibraryLoaded ? (
          <DocumentFolderTree
            className="pb-1"
            fileItems={sidebarFileItems}
            onRequestUpload={onRequestUploadToFolder}
            onRequestUploadFolder={onRequestUploadFolder}
            showFiles="expanded"
            onSelectFile={onFolderTreeSelectFile}
            onToggleFileSelected={onToggleGovernanceFileSelection}
            onDeleteFolder={onDeleteFolder}
            onFileDrop={onMoveFileToFolder}
            onRetryFile={onRetryFile}
            onRemoveFile={onRemoveFile}
            onFileDragStart={onFileDragStart}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
            <div className="mb-3 flex size-12 items-center justify-center rounded-xl bg-muted/60">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground motion-reduce:animate-none" />
            </div>
            <p className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">
              {t('sidebar.loadingLibraryTitle')}
            </p>
            <p className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground">
              {t('sidebar.loadingLibraryDescription')}
            </p>
          </div>
        )}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={fileAccept}
        className="hidden"
        onChange={onFileSelect}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        {...DIRECTORY_INPUT_PROPS}
        className="hidden"
        onChange={onFileSelect}
      />
      <input
        ref={rebindInputRef}
        type="file"
        accept={rebindAccept}
        className="hidden"
        onChange={onRebindFileSelect}
      />

      {currentFolderFileCount > 0 ? (
        <div className="border-t border-border/60 bg-[linear-gradient(180deg,hsl(var(--background)/0.82),hsl(var(--muted)/0.28))] px-3.5 py-3 backdrop-blur-sm">
          <div className="grid grid-cols-4 gap-1.5 text-[11px] tabular-nums">
            {fileTypeSummary.map(({ icon: Icon, label, value }) => (
              <span
                key={label}
                className="inline-flex items-center justify-center gap-1 rounded-md border border-border/60 bg-card/70 px-1.5 py-1 text-muted-foreground/80 transition-colors"
              >
                <Icon className="size-3 text-muted-foreground/70" />
                <span>{label}</span>
                <span className="font-semibold text-foreground">{value}</span>
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </ParsingLeftPanel>
  )
}
