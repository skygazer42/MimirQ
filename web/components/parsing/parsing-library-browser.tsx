'use client'

import { FolderOpen } from 'lucide-react'

import { FileQueueItem } from '@/components/ui/file-queue-item'
import { cn } from '@/lib/utils'
import { ROOT_FOLDER_ID, type FolderNode, type ParsedFileData } from '@/store/use-parsed-files-store'

import type { ParsedFile } from './parsing-types'

type FolderStats = {
  count: number
  latestTs: number
}

type ParsingLibraryBrowserProps = {
  currentFolderId: string
  activeFolderId: string
  activeFileId: string | null
  activeLibraryFileId: string | null
  dragOverFolderId: string | null
  isLibraryLoaded: boolean
  isQueueRehydrating: boolean
  folders: FolderNode[]
  files: ParsedFile[]
  libraryFiles: ParsedFileData[]
  visibleQueueFiles: ParsedFile[]
  visibleLibraryOnlyFiles: ParsedFileData[]
  folderPathById: Record<string, string>
  onFolderSelect: (folderId: string) => void
  onFolderDragOver: (event: React.DragEvent<HTMLElement>, folderId: string) => void
  onFolderDragLeave: () => void
  onFolderDrop: (event: React.DragEvent<HTMLElement>, folderId: string) => void
  onQueueFileDragStart: (event: React.DragEvent<HTMLElement>, fileId: string) => void
  onSelectQueueFile: (fileId: string) => void
  onSelectLibraryFile: (fileId: string) => void
  onRemoveFile: (fileId: string) => void
  onRetryParse: (fileId: string) => void
}

export function ParsingLibraryBrowser({
  currentFolderId,
  activeFolderId,
  activeFileId,
  activeLibraryFileId,
  dragOverFolderId,
  isLibraryLoaded,
  isQueueRehydrating,
  folders,
  files,
  libraryFiles,
  visibleQueueFiles,
  visibleLibraryOnlyFiles,
  folderPathById,
  onFolderSelect,
  onFolderDragOver,
  onFolderDragLeave,
  onFolderDrop,
  onQueueFileDragStart,
  onSelectQueueFile,
  onSelectLibraryFile,
  onRemoveFile,
  onRetryParse,
}: Readonly<ParsingLibraryBrowserProps>) {
  const childrenByParentId = new Map<string, string[]>()
  for (const folder of folders) {
    const parentId = folder.parentId || ROOT_FOLDER_ID
    const list = childrenByParentId.get(parentId) || []
    list.push(folder.id)
    childrenByParentId.set(parentId, list)
  }

  const directFolders = folders
    .filter((folder) => (folder.parentId || ROOT_FOLDER_ID) === currentFolderId)
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))

  const byFolder = new Map<string, FolderStats>()
  const bump = (folderId: string, ts: number) => {
    const current = byFolder.get(folderId) || { count: 0, latestTs: 0 }
    byFolder.set(folderId, { count: current.count + 1, latestTs: Math.max(current.latestTs, ts) })
  }

  for (const file of libraryFiles) {
    bump(file.folderId || ROOT_FOLDER_ID, Math.max(0, Date.parse(file.parsedAt)))
  }
  for (const file of files) {
    bump(file.folderId || ROOT_FOLDER_ID, file.createdAt || 0)
  }

  const folderStatsById = new Map<string, FolderStats>()
  const collect = (folderId: string): FolderStats => {
    const cached = folderStatsById.get(folderId)
    if (cached) return cached

    let count = 0
    let latestTs = 0
    const direct = byFolder.get(folderId)
    if (direct) {
      count += direct.count
      latestTs = Math.max(latestTs, direct.latestTs)
    }

    const children = childrenByParentId.get(folderId) || []
    for (const childId of children) {
      const child = collect(childId)
      count += child.count
      latestTs = Math.max(latestTs, child.latestTs)
    }

    const result = { count, latestTs }
    folderStatsById.set(folderId, result)
    return result
  }

  for (const folder of folders) {
    collect(folder.id)
  }

  const isLibraryEmpty =
    isLibraryLoaded &&
    directFolders.length === 0 &&
    visibleQueueFiles.length === 0 &&
    visibleLibraryOnlyFiles.length === 0

  if (!isLibraryLoaded) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
        <div className="mb-3 flex size-14 items-center justify-center rounded-2xl border border-border/60 bg-card shadow-sm">
          <FolderOpen className="h-6 w-6 text-muted-foreground" />
        </div>
        <p className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">正在加载文档库…</p>
        <p className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground">首次进入或刷新时会稍等片刻</p>
      </div>
    )
  }

  if (isLibraryEmpty) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
        <div className="mb-3 flex size-14 items-center justify-center rounded-2xl border border-border/60 bg-card shadow-sm">
          <FolderOpen className="h-6 w-6 text-muted-foreground" />
        </div>
        <p className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">暂无文件</p>
        <p className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground">拖拽文件到此处或点击上方按钮添加</p>
        {isQueueRehydrating ? (
          <p className="mt-3 text-[11px] text-muted-foreground dark:text-muted-foreground">正在恢复队列…</p>
        ) : null}
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {directFolders.map((folder) => {
        const stats = folderStatsById.get(folder.id)
        const latestTs = stats?.latestTs || Date.parse(folder.createdAt)

        return (
          <button
            key={folder.id}
            type="button"
            className={cn(
              'group relative flex w-full cursor-pointer items-center gap-2.5 rounded-lg p-2 text-left transition-colors hover:bg-muted/55 dark:hover:bg-muted/40',
              dragOverFolderId === folder.id && 'bg-muted/70 ring-1 ring-border/60 dark:bg-muted/40',
              activeFolderId === folder.id && 'bg-primary/[0.055] dark:bg-primary/10'
            )}
            draggable
            onDragStart={(event) => {
              try {
                event.dataTransfer.setData('application/x-mimirq-folder', folder.id)
              } catch {
                // ignore
              }
              event.dataTransfer.effectAllowed = 'move'
            }}
            onClick={() => onFolderSelect(folder.id)}
            onDragOver={(event) => onFolderDragOver(event, folder.id)}
            onDragLeave={onFolderDragLeave}
            onDrop={(event) => onFolderDrop(event, folder.id)}
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted/80 text-muted-foreground dark:bg-muted dark:text-muted-foreground">
              <FolderOpen className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between">
                <div
                  className={cn(
                    'truncate pr-4 text-[13px] font-medium',
                    activeFolderId === folder.id ? 'text-foreground dark:text-foreground' : 'text-foreground/80 dark:text-muted-foreground'
                  )}
                >
                  {folder.name}
                </div>
                <span className="shrink-0 text-[11px] text-muted-foreground dark:text-muted-foreground">
                  {Number.isFinite(latestTs) && latestTs > 0
                    ? new Date(latestTs).toLocaleString([], {
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : ''}
                </span>
              </div>
              <div className="mt-0.5 flex min-h-[16px] items-center gap-2">
                <span className="text-[11px] text-muted-foreground dark:text-muted-foreground">{stats?.count || 0} 项</span>
              </div>
            </div>
          </button>
        )
      })}

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
            folderPathLabel: file.folderId && file.folderId !== ROOT_FOLDER_ID ? folderPathById[file.folderId] : undefined,
          }}
          isActive={activeLibraryFileId === file.id}
          onClick={() => onSelectLibraryFile(file.id)}
          onRemove={() => onRemoveFile(file.id)}
        />
      ))}

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
            folderPathLabel: file.folderId && file.folderId !== ROOT_FOLDER_ID ? folderPathById[file.folderId] : undefined,
            sourcePath: file.sourcePath,
            error: file.error,
            duration: file.duration,
            pageCount: file.stats?.pageCount,
          }}
          draggable
          onDragStart={(event) => onQueueFileDragStart(event, file.id)}
          isActive={activeFileId === file.id}
          onClick={() => onSelectQueueFile(file.id)}
          onRemove={() => onRemoveFile(file.id)}
          onRetry={file.status === 'error' ? () => onRetryParse(file.id) : undefined}
        />
      ))}
    </div>
  )
}
