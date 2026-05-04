'use client'

import type { RefObject } from 'react'
import { Check, ChevronDown, Clock, Database, FileText, FolderUp, Loader2, Paperclip, Play, Plus, Settings2 } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { DocumentFolderTree, type DocumentTreeFileItem } from '@/components/document-library/folder-tree'
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
 datasetOptions: DatasetScopeOption[]
 selectedDatasetId: string | null
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
 onDatasetScopeChange: (datasetId: string | null) => void
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

type DatasetScopeOption = {
 id: string
 name: string
 count?: number
}

const DATASET_ALL_VALUE = '__all__'

export function ParsingSidebarPane({
 collapsed,
 className,
 activeFolderId,
 activeFolderPathLabel,
 currentFolderId,
 currentFolderFileCount,
 datasetOptions,
 selectedDatasetId,
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
 onDatasetScopeChange,
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
 'sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-border/60 bg-card px-3 py-2'
 )}
 >
 <button
 type="button"
 className="group flex min-w-0 flex-1 items-center gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/40"
 onClick={onRequestUploadToCurrentFolder}
 onDragOver={(event) => onFolderDragOver(event, currentFolderId)}
 onDragLeave={onFolderDragLeave}
 onDrop={(event) => onFolderDrop(event, currentFolderId)}
 title={t('sidebar.uploadCurrentFolderTitle')}
 >
 <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-info/20 bg-info/[0.08] text-info">
 <FileText className="size-3.5" />
 </div>
 <div className="min-w-0 flex-1">
 <div className="flex items-baseline gap-1.5">
 <span className="truncate text-[12px] font-medium text-foreground">{t('sidebar.documentList')}</span>
 <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/75">{currentFolderFileCount}</span>
 </div>
 <div
 className="mt-0.5 truncate text-[10px] text-muted-foreground/65"
 title={activeFolderPathLabel}
 >
 {activeFolderPathLabel}
 </div>
 </div>
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

 <Popover>
 <PopoverTrigger asChild>
 <Button
 variant="ghost"
 size="icon"
 className="size-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
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
 <div className="text-sm font-medium">{t('sidebar.defaultParser')}</div>
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
 <div className="text-sm font-medium">{t('sidebar.imageCaptionTitle')}</div>
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
 className="size-7 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
 aria-label={t('sidebar.uploadActions')}
 title={t('sidebar.uploadActions')}
 >
 <Plus className="size-3.5" />
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent align="end" className="w-52">
 <DropdownMenuItem onClick={() => onRequestUploadToFolder(activeFolderId || ROOT_FOLDER_ID)}>
 <Paperclip className="mr-2 size-4 text-muted-foreground" />
 {t('sidebar.uploadFile')}
 </DropdownMenuItem>
 <DropdownMenuItem onClick={() => onRequestUploadFolder(activeFolderId || ROOT_FOLDER_ID)}>
 <FolderUp className="mr-2 size-4 text-muted-foreground" />
 {t('sidebar.uploadFolder')}
 </DropdownMenuItem>
 </DropdownMenuContent>
 </DropdownMenu>
 </div>
 </div>

 {!collapsed ? (
 <div className="relative border-b border-border/60">
 <div aria-hidden className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full bg-info/70" />
 <div className="space-y-1.5 bg-gradient-to-r from-info/[0.06] via-info/[0.02] to-transparent py-2 pl-3.5 pr-2 dark:from-info/[0.10]">
 <div className="flex items-center justify-between gap-2">
 <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-info/85 dark:text-info">
 {t('sidebar.datasetScope')}
 </span>
 <span
 className={cn(
 'rounded-full border px-1.5 py-0.5 text-[10px] font-medium tabular-nums transition-colors',
 selectedDatasetId
 ? 'border-info/30 bg-info/15 text-info'
 : 'border-border/60 bg-muted/60 text-muted-foreground'
 )}
 >
 {selectedDatasetId ? t('sidebar.datasetScoped') : t('sidebar.datasetAll')}
 </span>
 </div>
 <Select
 value={selectedDatasetId || DATASET_ALL_VALUE}
 onValueChange={(value) => onDatasetScopeChange(value === DATASET_ALL_VALUE ? null : value)}
 >
 <SelectTrigger
 className={cn(
 'h-8 text-[11px] font-medium bg-card border-border/60 text-foreground transition-colors duration-200 motion-reduce:transition-none',
 'hover:border-info/40 focus:border-info/60 data-[state=open]:border-info/60',
 'focus-visible:ring-2 focus-visible:ring-info/20 focus-visible:ring-offset-0'
 )}
 >
 <div className="flex items-center gap-1.5 truncate">
 <Database className="size-3.5 shrink-0 text-info/80" />
 <SelectValue placeholder={t('sidebar.allDatasetScope')} />
 </div>
 </SelectTrigger>
 <SelectContent className="bg-card border-border/60 text-foreground">
 <SelectItem value={DATASET_ALL_VALUE} className="text-[12px]">
 <span className="flex items-center gap-1.5">
 <span aria-hidden className="size-1.5 rounded-full bg-muted-foreground/50" />
 {t('sidebar.allDatasetScope')}
 </span>
 </SelectItem>
 {datasetOptions.map((dataset) => (
 <SelectItem key={dataset.id} value={dataset.id} className="text-[12px]">
 <span className="flex items-center gap-1.5">
 <span aria-hidden className="size-1.5 rounded-full bg-info/70" />
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
 ) : null}

 <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-card px-2 py-1.5 dark:bg-card">
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
 <div className="mb-3 flex size-12 items-center justify-center rounded-xl bg-muted/60">
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
 <div className="border-t border-border/60 bg-gradient-to-b from-muted/20 to-muted/40 px-3 py-2 backdrop-blur-sm">
 <div className="grid grid-cols-3 gap-1.5 text-[11px] tabular-nums">
 <span className={cn(
 'inline-flex items-center justify-center gap-1 rounded-md border px-1.5 py-1 transition-colors',
 pendingCount > 0
 ? 'border-warning/25 bg-warning/[0.08] text-warning'
 : 'border-border/60 bg-muted/40 text-muted-foreground/70'
 )}>
 <Clock className="size-3" />
 <span className="font-medium">{pendingCount}</span>
 </span>
 <span className={cn(
 'inline-flex items-center justify-center gap-1 rounded-md border px-1.5 py-1 transition-colors',
 parsingCount > 0
 ? 'border-info/25 bg-info/[0.08] text-info'
 : 'border-border/60 bg-muted/40 text-muted-foreground/70'
 )}>
 <Loader2 className={cn('size-3', parsingCount > 0 && 'animate-spin motion-reduce:animate-none')} />
 <span className="font-medium">{parsingCount}</span>
 </span>
 <span className={cn(
 'inline-flex items-center justify-center gap-1 rounded-md border px-1.5 py-1 transition-colors',
 parsedCount > 0
 ? 'border-success/25 bg-success/[0.08] text-success'
 : 'border-border/60 bg-muted/40 text-muted-foreground/70'
 )}>
 <Check className="size-3" />
 <span className="font-medium">{parsedCount}</span>
 </span>
 </div>
 </div>
 ) : null}
 </ParsingLeftPanel>
 )
}
