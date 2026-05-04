'use client'

import { Play } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { DocumentFolderTree } from '@/components/document-library/folder-tree'
import { FileQueueItem } from '@/components/ui/file-queue-item'
import { Button } from '@/components/ui/button'
import { ROOT_FOLDER_ID, type ParsedFileData } from '@/store/use-parsed-files-store'

import type { ParsedFile } from './parsing-types'

type ParsingMobileQueueContentProps = {
 queueCountLabel: string
 parseableCount: number
 activeFileId: string | null
 activeLibraryFileId: string | null
 visibleQueueFiles: ParsedFile[]
 visibleLibraryOnlyFiles: ParsedFileData[]
 folderPathById: Record<string, string>
 files: ParsedFile[]
 onParseAllPending: () => void
 onRequestUploadToFolder: (folderId: string) => void
 onRequestUploadFolder: (folderId: string) => void
 onSelectQueueFile: (fileId: string) => void
 onSelectLibraryFile: (fileId: string) => void
 onDeleteFolder: (folderIds: string[]) => void
 onMoveFileToFolder: (fileId: string, folderId: string) => void
 onRemoveFile: (fileId: string) => void
 onRetryParse: (fileId: string) => void
 onFileDragStart: (event: React.DragEvent<HTMLElement>, fileId: string) => void
}

export function ParsingMobileQueueContent({
 queueCountLabel,
 parseableCount,
 activeFileId,
 activeLibraryFileId,
 visibleQueueFiles,
 visibleLibraryOnlyFiles,
 folderPathById,
 files,
 onParseAllPending,
 onRequestUploadToFolder,
 onRequestUploadFolder,
 onSelectQueueFile,
 onSelectLibraryFile,
 onDeleteFolder,
 onMoveFileToFolder,
 onRemoveFile,
 onRetryParse,
 onFileDragStart,
}: Readonly<ParsingMobileQueueContentProps>) {
 const t = useTranslations('ParsingWorkbench')

 return (
 <>
 <div className="flex-none border-b border-border/60 bg-card/95 p-3">
 <div className="flex items-center justify-between gap-3">
 <div className="min-w-0">
 <div className="text-sm font-semibold text-foreground">{t('mobileQueue.title')}</div>
 <div className="mt-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">{queueCountLabel}</div>
 </div>

 {parseableCount > 0 ? (
 <Button type="button" variant="outline" size="sm" className="gap-2" onClick={onParseAllPending}>
 <Play className="h-4 w-4" />
 {t('mobileQueue.parseAll')}
 </Button>
 ) : null}
 </div>
 </div>

 <div className="flex-1 min-h-0 space-y-3 overflow-y-auto overscroll-contain no-scrollbar bg-muted/20 p-3">
 <div className="rounded-2xl border border-border/60 bg-card p-2">
 <DocumentFolderTree
 onRequestUpload={onRequestUploadToFolder}
 onRequestUploadFolder={onRequestUploadFolder}
 showFiles="expanded"
 onSelectFile={(fileId) => {
 const queueMatch = files.find((file) => file.libraryId === fileId)
 if (queueMatch) {
 onSelectQueueFile(queueMatch.id)
 return
 }
 onSelectLibraryFile(fileId)
 }}
 onDeleteFolder={onDeleteFolder}
 onFileDrop={onMoveFileToFolder}
 />
 </div>

 {visibleQueueFiles.length > 0 ? (
 <div className="rounded-2xl border border-border/60 bg-card p-2">
 <div className="flex items-center justify-between px-2 pb-2">
 <div className="text-sm font-semibold text-foreground">{t('mobileQueue.currentSession')}</div>
 <div className="font-mono text-[11px] tabular-nums text-muted-foreground">{visibleQueueFiles.length}</div>
 </div>
 <div className="space-y-1">
 {visibleQueueFiles.map((file) => (
 <FileQueueItem
 key={file.id}
 file={{
 id: file.id,
 name: file.name,
 size: file.size,
 status: file.status,
 progress: file.progress,
 parser: file.parserLabel,
 folderPathLabel:
 file.folderId && file.folderId !== ROOT_FOLDER_ID ? folderPathById[file.folderId] : undefined,
 sourcePath: file.sourcePath,
 error: file.error,
 duration: file.duration,
 pageCount: file.stats?.pageCount,
 }}
 draggable
 onDragStart={(event) => onFileDragStart(event, file.id)}
 isActive={activeFileId === file.id}
 onClick={() => onSelectQueueFile(file.id)}
 onRemove={() => onRemoveFile(file.id)}
 onRetry={file.status === 'error' ? () => onRetryParse(file.id) : undefined}
 />
 ))}
 </div>
 </div>
 ) : null}

 {visibleLibraryOnlyFiles.length > 0 ? (
 <div className="rounded-2xl border border-border/60 bg-card p-2">
 <div className="flex items-center justify-between px-2 pb-2">
 <div className="text-sm font-semibold text-foreground">{t('mobileQueue.library')}</div>
 <div className="font-mono text-[11px] tabular-nums text-muted-foreground">
 {visibleLibraryOnlyFiles.length}
 </div>
 </div>
 <div className="space-y-1">
 {visibleLibraryOnlyFiles.map((file) => (
 <FileQueueItem
 key={file.id}
 file={{
 id: file.id,
 name: file.filename,
 size: file.fileSize,
 status: file.status || 'parsed',
 parser: file.parser,
 duration: file.durationSec,
 folderPathLabel:
 file.folderId && file.folderId !== ROOT_FOLDER_ID ? folderPathById[file.folderId] : undefined,
 }}
 isActive={activeLibraryFileId === file.id}
 onClick={() => onSelectLibraryFile(file.id)}
 onRemove={() => onRemoveFile(file.id)}
 />
 ))}
 </div>
 </div>
 ) : null}
 </div>
 </>
 )
}
