'use client'

import type { RefObject } from 'react'
import { Check, Clock, FileText, FolderUp, Loader2, Paperclip, Play, Plus, Settings2 } from 'lucide-react'

import { DocumentFolderTree } from '@/components/document-library/folder-tree'
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
  visibleQueueFilesCount: number
  pendingCount: number
  parsingCount: number
  parsedCount: number
  parseableCount: number
  parserBackend: string
  imageCaptionEnabled: boolean
  isLibraryLoaded: boolean
  libraryFileListContent: React.ReactNode
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
  onFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => void
  onRebindFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => void
}

export function ParsingSidebarPane({
  collapsed,
  className,
  activeFolderId,
  activeFolderPathLabel,
  currentFolderId,
  visibleQueueFilesCount,
  pendingCount,
  parsingCount,
  parsedCount,
  parseableCount,
  parserBackend,
  imageCaptionEnabled,
  isLibraryLoaded,
  libraryFileListContent,
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
  onFileSelect,
  onRebindFileSelect,
}: Readonly<ParsingSidebarPaneProps>) {
  return (
    <ParsingLeftPanel
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      className={className}
    >
      <div className="flex-none h-1/3 min-h-[200px] overflow-y-auto overscroll-contain no-scrollbar border-b border-border/60 bg-card p-2 dark:bg-background/40">
        <div className="h-full rounded-2xl border border-border/60 bg-card p-2 dark:bg-background/40">
          <DocumentFolderTree
            onRequestUpload={onRequestUploadToFolder}
            onRequestUploadFolder={onRequestUploadFolder}
            showFiles="expanded"
            onSelectFile={onFolderTreeSelectFile}
            onDeleteFolder={onDeleteFolder}
            onFileDrop={onMoveFileToFolder}
          />
        </div>
      </div>

      <div
        className={cn(
          'sticky top-0 z-10 flex items-center justify-between border-b border-border/60 bg-card px-4 py-3 dark:bg-background/40'
        )}
      >
        <button
          type="button"
          className="group -mx-2 flex min-w-0 items-center gap-3 rounded-xl px-2 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          onClick={onRequestUploadToCurrentFolder}
          onDragOver={(event) => onFolderDragOver(event, currentFolderId)}
          onDragLeave={onFolderDragLeave}
          onDrop={(event) => onFolderDrop(event, currentFolderId)}
          title="拖拽文件到当前目录，或点击上传"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-muted text-muted-foreground dark:bg-muted dark:text-muted-foreground">
            <FileText className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground dark:text-foreground">文档列表</div>
            <div className="mt-0.5">
              <span
                className="inline-flex max-w-[220px] items-center truncate rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground dark:bg-muted dark:text-muted-foreground"
                title={activeFolderPathLabel}
              >
                {activeFolderPathLabel}
              </span>
            </div>
          </div>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 dark:bg-muted dark:text-muted-foreground">
            {visibleQueueFilesCount}
          </span>
        </button>

        <div className="flex items-center gap-1">
          {parseableCount > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onParseAllPending}
              className="mr-1 h-7 gap-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground dark:text-muted-foreground dark:hover:bg-muted dark:hover:text-foreground"
            >
              <Play className="h-3.5 w-3.5" />
              解析
            </Button>
          ) : null}

          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-muted"
                title="默认解析方式"
                aria-label="默认解析方式"
              >
                <Settings2 className="h-4 w-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-3">
              <div className="space-y-3">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold">默认解析方式</div>
                    <div className="text-xs text-muted-foreground">新上传默认</div>
                  </div>
                  <ParserDropdown value={parserBackend} onChange={onParserBackendChange} />
                  <p className="text-xs leading-snug text-muted-foreground">
                    选中文件后，也可以在右侧顶部对单个文件单独修改。
                  </p>
                </div>

                <div className="h-px bg-border/60" />

                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">图片 caption（可选）</div>
                    <div className="mt-1 text-xs leading-snug text-muted-foreground">
                      为图片引用行插入可检索文本（不做 OCR；默认关闭）
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
                className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-muted"
                aria-label="上传操作"
                title="上传操作"
              >
                <Plus className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuItem onClick={() => onRequestUploadToFolder(activeFolderId || ROOT_FOLDER_ID)}>
                <Paperclip className="mr-2 h-4 w-4 text-muted-foreground" />
                上传文件
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onRequestUploadFolder(activeFolderId || ROOT_FOLDER_ID)}>
                <FolderUp className="mr-2 h-4 w-4 text-muted-foreground" />
                上传文件夹
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-card p-2 dark:bg-background/40">
        <div className="min-h-full rounded-2xl border border-border/60 bg-card p-2 dark:bg-background/40">
          {isLibraryLoaded ? (
            libraryFileListContent
          ) : (
            <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
              <div className="mb-3 flex size-14 items-center justify-center rounded-2xl border border-border/60 bg-card shadow-sm">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground motion-reduce:animate-none" />
              </div>
              <p className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">正在加载文档库…</p>
              <p className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground">首次进入或刷新时会稍等片刻</p>
            </div>
          )}
        </div>
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

      {visibleQueueFilesCount > 0 ? (
        <div className="border-t border-border/60 bg-muted/20 p-4 dark:bg-muted/40">
          <div className="flex items-center justify-around text-xs text-muted-foreground dark:text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {pendingCount} 等待
            </span>
            <span className="flex items-center gap-1">
              <Loader2 className="h-3 w-3" />
              {parsingCount} 处理
            </span>
            <span className="flex items-center gap-1 text-green-700 dark:text-green-400">
              <Check className="h-3 w-3" />
              {parsedCount} 完成
            </span>
          </div>
        </div>
      ) : null}
    </ParsingLeftPanel>
  )
}
