'use client'

import type { RefObject } from 'react'
import { Check, Clock, FileText, FolderUp, Loader2, Paperclip, Play, Plus, Settings2 } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { DocumentFolderTree, type DocumentTreeFileItem } from '@/components/document-library/folder-tree'
import { ParsingLeftPanel } from '@/components/parsing/parsing-left-panel'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { ROOT_FOLDER_ID } from '@/store/use-parsed-files-store'
import { cn } from '@/lib/utils'

type ParsingSidebarPaneProps = {
  collapsed: boolean
  className?: string
  activeFolderId: string
  activeFolderPathLabel: string
  currentFolderId: string
  currentFolderFileCount: number
  pendingCount: number
  parsingCount: number
  parsedCount: number
  parseableCount: number
  parserBackend: string
  imageCaptionEnabled: boolean
  isLibraryLoaded: boolean
  sidebarFileItems: DocumentTreeFileItem[]
  fileAccept: string
  rebindAccept: string
  fileInputRef: RefObject<HTMLInputElement | null>
  folderInputRef: RefObject<HTMLInputElement | null>
  rebindInputRef: RefObject<HTMLInputElement | null>
  onToggleCollapsed: () => void
  onRequestUploadToCurrentFolder: () => void
  onRequestUploadToFolder: (folderId: string) => void
  onRequestUploadFolder: (folderId: string) => void
  onParseAllPending: () => void
  onParserBackendChange: (backend: string) => void
  onImageCaptionEnabledChange: (enabled: boolean) => void
  onFolderDragOver: (event: React.DragEvent<HTMLElement>, folderId: string) => void
  onFolderDragLeave: () => void
  onFolderDrop: (event: React.DragEvent<HTMLElement>, folderId: string) => void
  onFolderTreeSelectFile: (fileId: string) => void
  onDeleteFolder: (folderIds: string[]) => void
  onMoveFileToFolder: (fileId: string, folderId: string) => void
  onFileDragStart: (event: React.DragEvent<HTMLElement>, fileId: string) => void
  onRetryFile: (fileId: string) => void
  onRemoveFile: (fileId: string) => void
  onFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => void
  onRebindFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => void
}

export function ParsingSidebarPane({
  collapsed,
  className,
  activeFolderId,
  activeFolderPathLabel,
  currentFolderId,
  currentFolderFileCount,
  pendingCount,
  parsingCount,
  parsedCount,
  parseableCount,
  parserBackend,
  imageCaptionEnabled,
  isLibraryLoaded,
  sidebarFileItems,
  fileAccept,
  rebindAccept,
  fileInputRef,
  folderInputRef,
  rebindInputRef,
  onToggleCollapsed,
  onRequestUploadToCurrentFolder,
  onRequestUploadToFolder,
  onRequestUploadFolder,
  onParseAllPending,
  onParserBackendChange,
  onImageCaptionEnabledChange,
  onFolderDragOver,
  onFolderDragLeave,
  onFolderDrop,
  onFolderTreeSelectFile,
  onDeleteFolder,
  onMoveFileToFolder,
  onFileDragStart,
  onRetryFile,
  onRemoveFile,
  onFileSelect,
  onRebindFileSelect,
}: Readonly<ParsingSidebarPaneProps>) {
  const t = useTranslations('ParsingWorkbench')

  return (
    <ParsingLeftPanel
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      className={className}
    >
      <div
        className={cn(
          'sticky top-0 z-10 flex items-center justify-between gap-1.5 border-b border-border/40 bg-background/92 px-2 py-1.5 backdrop-blur dark:bg-background/85'
        )}
      >
        <button
          type="button"
          className="group -mx-0.5 flex min-w-0 items-center gap-2 rounded-lg px-0.5 py-0.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          onClick={onRequestUploadToCurrentFolder}
          onDragOver={(event) => onFolderDragOver(event, currentFolderId)}
          onDragLeave={onFolderDragLeave}
          onDrop={(event) => onFolderDrop(event, currentFolderId)}
          title={t('sidebar.uploadCurrentFolderTitle')}
        >
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-muted/65 text-muted-foreground dark:bg-muted dark:text-muted-foreground">
            <FileText className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0">
            <div className="text-[12px] font-semibold leading-4 text-foreground dark:text-foreground">{t('sidebar.documentList')}</div>
            <div className="mt-0.5">
              <span
                className="inline-flex max-w-[176px] items-center truncate rounded-md bg-muted/65 px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground dark:bg-muted dark:text-muted-foreground"
                title={activeFolderPathLabel}
              >
                {activeFolderPathLabel}
              </span>
            </div>
          </div>
          <span className="shrink-0 rounded-md bg-muted/65 px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground dark:bg-muted dark:text-muted-foreground">
            {currentFolderFileCount}
          </span>
        </button>

        <div className="flex items-center gap-1">
          {parseableCount > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onParseAllPending}
              className="mr-0.5 h-6 gap-1 rounded-md px-1.5 text-[11px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground dark:text-muted-foreground dark:hover:bg-muted dark:hover:text-foreground"
            >
              <Play className="h-3 w-3" />
              {t('sidebar.parse')}
            </Button>
          ) : null}

          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 rounded-md text-muted-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-muted"
                title={t('sidebar.defaultParser')}
                aria-label={t('sidebar.defaultParser')}
              >
                <Settings2 className="h-3.5 w-3.5" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-3">
              <div className="space-y-3">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold">{t('sidebar.defaultParser')}</div>
                    <div className="text-xs text-muted-foreground">{t('sidebar.newUploadDefault')}</div>
                  </div>
                  <ParserDropdown value={parserBackend} onChange={onParserBackendChange} />
                  <p className="text-xs leading-snug text-muted-foreground">
                    {t('sidebar.defaultParserDescription')}
                  </p>
                </div>

                <div className="h-px bg-border/60" />

                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">{t('sidebar.imageCaptionTitle')}</div>
                    <div className="mt-1 text-xs leading-snug text-muted-foreground">
                      {t('sidebar.imageCaptionDescription')}
                    </div>
                  </div>
                  <Switch checked={imageCaptionEnabled} onCheckedChange={onImageCaptionEnabledChange} />
                </div>
              </div>
            </PopoverContent>
          </Popover>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 rounded-md text-muted-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-muted"
                aria-label={t('sidebar.uploadActions')}
                title={t('sidebar.uploadActions')}
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuItem onClick={() => onRequestUploadToFolder(activeFolderId || ROOT_FOLDER_ID)}>
                <Paperclip className="mr-2 h-4 w-4 text-muted-foreground" />
                {t('sidebar.uploadFile')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onRequestUploadFolder(activeFolderId || ROOT_FOLDER_ID)}>
                <FolderUp className="mr-2 h-4 w-4 text-muted-foreground" />
                {t('sidebar.uploadFolder')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-background/70 px-2 py-1.5 dark:bg-background/30">
        {isLibraryLoaded ? (
          <DocumentFolderTree
            className="pb-1"
            fileItems={sidebarFileItems}
            onRequestUpload={onRequestUploadToFolder}
            onRequestUploadFolder={onRequestUploadFolder}
            showFiles="expanded"
            onSelectFile={onFolderTreeSelectFile}
            onDeleteFolder={onDeleteFolder}
            onFileDrop={onMoveFileToFolder}
            onRetryFile={onRetryFile}
            onRemoveFile={onRemoveFile}
            onFileDragStart={onFileDragStart}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
            <div className="mb-3 flex size-12 items-center justify-center rounded-xl bg-muted/70">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground motion-reduce:animate-none" />
            </div>
            <p className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">{t('sidebar.loadingLibraryTitle')}</p>
            <p className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground">{t('sidebar.loadingLibraryDescription')}</p>
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
        {...({ webkitdirectory: '' } as { webkitdirectory: string })}
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
        <div className="border-t border-border/50 bg-background/80 px-3 py-2.5 dark:bg-background/65">
          <div className="grid grid-cols-3 gap-2 text-[11px] text-muted-foreground dark:text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {t('sidebar.pendingCount', { count: pendingCount })}
            </span>
            <span className="inline-flex items-center justify-center gap-1">
              <Loader2 className="h-3 w-3" />
              {t('sidebar.parsingCount', { count: parsingCount })}
            </span>
            <span className="inline-flex items-center justify-end gap-1 text-success">
              <Check className="h-3 w-3" />
              {t('sidebar.completedCount', { count: parsedCount })}
            </span>
          </div>
        </div>
      ) : null}
    </ParsingLeftPanel>
  )
}
