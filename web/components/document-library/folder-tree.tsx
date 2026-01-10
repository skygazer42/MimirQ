'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowRightLeft, ChevronDown, ChevronRight, FileText, Folder, FolderOpen, MoreHorizontal, Pencil, Plus, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { FolderNode, ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'

type FolderDialogState =
  | { open: false }
  | { open: true; mode: 'create'; parentId: string }
  | { open: true; mode: 'rename'; folderId: string }
  | { open: true; mode: 'move'; folderId: string }

export function DocumentFolderTree({
  className,
  onRequestUpload,
  fileItems,
  showFiles = 'none',
  onSelectFile,
}: {
  className?: string
  onRequestUpload?: (folderId: string) => void
  fileItems?: Array<{ id: string; name: string; folderId?: string; sourcePath?: string }>
  showFiles?: 'none' | 'active' | 'all' | 'expanded'
  onSelectFile?: (fileId: string) => void
}) {
  const {
    files: libraryFiles,
    folders,
    activeFolderId,
    setActiveFolderId,
    createFolder,
    renameFolder,
    deleteFolder,
    moveFolder,
  } = useParsedFiles()

  const [dialog, setDialog] = useState<FolderDialogState>({ open: false })
  const [folderName, setFolderName] = useState('')
  const [moveParentId, setMoveParentId] = useState(ROOT_FOLDER_ID)
  const [expandedFileFolderIds, setExpandedFileFolderIds] = useState<Set<string>>(() => new Set([ROOT_FOLDER_ID]))

  const displayFiles = useMemo(() => {
    if (fileItems) return fileItems
    return libraryFiles.map((f) => ({
      id: f.id,
      name: f.filename,
      folderId: f.folderId,
    }))
  }, [fileItems, libraryFiles])

  const directCountByFolderId = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const file of displayFiles) {
      const folderId = file.folderId || ROOT_FOLDER_ID
      counts[folderId] = (counts[folderId] || 0) + 1
    }
    return counts
  }, [displayFiles])

  const directFilesByFolderId = useMemo(() => {
    const map = new Map<string, Array<{ id: string; name: string; folderId?: string; sourcePath?: string }>>()
    for (const file of displayFiles) {
      const folderId = file.folderId || ROOT_FOLDER_ID
      const list = map.get(folderId) || []
      list.push(file)
      map.set(folderId, list)
    }
    for (const [folderId, list] of map.entries()) {
      list.sort((a, b) => a.name.localeCompare(b.name))
      map.set(folderId, list)
    }
    return map
  }, [displayFiles])

  useEffect(() => {
    if (showFiles !== 'expanded') return
    const id = activeFolderId || ROOT_FOLDER_ID
    setExpandedFileFolderIds((prev) => {
      if (prev.has(id)) return prev
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }, [showFiles, activeFolderId])

  const toggleFileList = useCallback((folderId: string) => {
    const id = folderId || ROOT_FOLDER_ID
    setExpandedFileFolderIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const childrenByParentId = useMemo(() => {
    const map = new Map<string, FolderNode[]>()
    for (const folder of folders) {
      const parentId = folder.parentId || ROOT_FOLDER_ID
      const list = map.get(parentId) || []
      list.push(folder)
      map.set(parentId, list)
    }
    for (const [parentId, list] of map.entries()) {
      list.sort((a, b) => a.name.localeCompare(b.name))
      map.set(parentId, list)
    }
    return map
  }, [folders])

  const folderPathById = useMemo(() => {
    const byId = new Map(folders.map((f) => [f.id, f]))
    const cache = new Map<string, string>()

    const getPath = (folderId: string): string => {
      if (!folderId || folderId === ROOT_FOLDER_ID) return '根目录'
      const cached = cache.get(folderId)
      if (cached) return cached
      const node = byId.get(folderId)
      if (!node) return '根目录'
      const parentPath = node.parentId && node.parentId !== ROOT_FOLDER_ID ? getPath(node.parentId) : '根目录'
      const path = `${parentPath} / ${node.name}`
      cache.set(folderId, path)
      return path
    }

    const result: Record<string, string> = { [ROOT_FOLDER_ID]: '根目录' }
    for (const f of folders) result[f.id] = getPath(f.id)
    return result
  }, [folders])

  const openCreate = useCallback((parentId: string) => {
    setFolderName('')
    setDialog({ open: true, mode: 'create', parentId })
  }, [])

  const openRename = useCallback((folder: FolderNode) => {
    setFolderName(folder.name)
    setDialog({ open: true, mode: 'rename', folderId: folder.id })
  }, [])

  const openMove = useCallback((folder: FolderNode) => {
    setMoveParentId(folder.parentId || ROOT_FOLDER_ID)
    setDialog({ open: true, mode: 'move', folderId: folder.id })
  }, [])

  const closeDialog = useCallback(() => setDialog({ open: false }), [])

  const handleSubmit = useCallback(() => {
    const name = folderName.trim()
    if (!name) return

    if (dialog.open && dialog.mode === 'create') {
      const newId = createFolder(name, dialog.parentId)
      setActiveFolderId(newId)
      toast.success('文件夹已创建')
      closeDialog()
      return
    }

    if (dialog.open && dialog.mode === 'rename') {
      renameFolder(dialog.folderId, name)
      toast.success('文件夹已重命名')
      closeDialog()
    }
  }, [folderName, dialog, createFolder, renameFolder, setActiveFolderId, closeDialog])

  const handleMoveSubmit = useCallback(() => {
    if (!(dialog.open && dialog.mode === 'move')) return
    moveFolder(dialog.folderId, moveParentId || ROOT_FOLDER_ID)
    toast.success('文件夹已移动')
    closeDialog()
  }, [dialog, moveFolder, moveParentId, closeDialog])

  const handleDelete = useCallback(
    (folderId: string) => {
      const ok = window.confirm('确认删除该文件夹及其子文件夹？文件将移动到根目录。')
      if (!ok) return
      deleteFolder(folderId)
      toast.success('文件夹已删除')
    },
    [deleteFolder]
  )

  const moveTargetOptions = useMemo(() => {
    if (!(dialog.open && dialog.mode === 'move')) return []

    const movingFolderId = dialog.folderId
    const blocked = new Set<string>([movingFolderId])
    const stack = [movingFolderId]
    while (stack.length > 0) {
      const current = stack.pop()
      if (!current) continue
      const children = childrenByParentId.get(current) || []
      for (const child of children) {
        if (blocked.has(child.id)) continue
        blocked.add(child.id)
        stack.push(child.id)
      }
    }

    const options = [
      { id: ROOT_FOLDER_ID, label: '根目录' },
      ...folders
        .filter((f) => !blocked.has(f.id))
        .map((f) => ({ id: f.id, label: folderPathById[f.id] || `根目录 / ${f.name}` })),
    ]

    options.sort((a, b) => a.label.localeCompare(b.label))
    return options
  }, [dialog, folders, childrenByParentId, folderPathById])

  const renderFolder = useCallback(
    (folder: FolderNode, depth: number) => {
      const isActive = activeFolderId === folder.id
      const count = directCountByFolderId[folder.id] || 0
      const children = childrenByParentId.get(folder.id) || []
      const showFileNodes =
        showFiles === 'all'
        || (showFiles === 'active' && isActive)
        || (showFiles === 'expanded' && expandedFileFolderIds.has(folder.id))
      const directFiles = showFileNodes ? directFilesByFolderId.get(folder.id) || [] : []

      return (
        <div key={folder.id}>
          <div
            className={cn(
              'group flex items-center gap-2 rounded-lg pr-2 py-1.5 transition-colors',
              isActive ? 'bg-indigo-50 text-indigo-700' : 'hover:bg-gray-100 text-gray-700'
            )}
            style={{ paddingLeft: 8 + depth * 14 }}
          >
            {showFiles === 'expanded' && count > 0 && (
              <button
                type="button"
                className="w-5 h-5 flex items-center justify-center rounded hover:bg-white/60 text-gray-500"
                onClick={(e) => {
                  e.stopPropagation()
                  toggleFileList(folder.id)
                }}
                aria-label={expandedFileFolderIds.has(folder.id) ? 'Collapse files' : 'Expand files'}
              >
                {expandedFileFolderIds.has(folder.id) ? (
                  <ChevronDown className="w-4 h-4" />
                ) : (
                  <ChevronRight className="w-4 h-4" />
                )}
              </button>
            )}
            <button
              className="flex-1 min-w-0 flex items-center gap-2 text-left"
              onClick={() => {
                setActiveFolderId(folder.id)
                if (showFiles === 'expanded') {
                  setExpandedFileFolderIds((prev) => {
                    if (prev.has(folder.id)) return prev
                    const next = new Set(prev)
                    next.add(folder.id)
                    return next
                  })
                }
              }}
              type="button"
              title={folder.name}
            >
              {isActive ? (
                <FolderOpen className="w-4 h-4 flex-shrink-0" />
              ) : (
                <Folder className="w-4 h-4 flex-shrink-0" />
              )}
              <span className="text-sm truncate">{folder.name}</span>
              <span className="ml-auto text-xs text-gray-400">{count}</span>
            </button>

            {onRequestUpload && (
              <Button
                variant="ghost"
                size="icon"
                className={cn('h-7 w-7', isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100')}
                aria-label="Upload to folder"
                onClick={(e) => {
                  e.stopPropagation()
                  setActiveFolderId(folder.id)
                  onRequestUpload(folder.id)
                }}
              >
                <Upload className="w-4 h-4" />
              </Button>
            )}

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className={cn('h-7 w-7', isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100')}
                  aria-label="Folder actions"
                >
                  <MoreHorizontal className="w-4 h-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {onRequestUpload && (
                  <DropdownMenuItem
                    onClick={() => {
                      setActiveFolderId(folder.id)
                      onRequestUpload(folder.id)
                    }}
                  >
                    <Upload className="w-4 h-4 mr-2" />
                    上传到此目录
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => openCreate(folder.id)}>
                  <Plus className="w-4 h-4 mr-2" />
                  新建子文件夹
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => openMove(folder)}>
                  <ArrowRightLeft className="w-4 h-4 mr-2" />
                  移动到…
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => openRename(folder)}>
                  <Pencil className="w-4 h-4 mr-2" />
                  重命名
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-red-600 focus:text-red-600"
                  onClick={() => handleDelete(folder.id)}
                >
                  <Trash2 className="w-4 h-4 mr-2" />
                  删除
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {directFiles.length > 0 && (
            <div className="space-y-0.5">
              {directFiles.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={cn(
                    'w-full flex items-center gap-2 rounded-lg py-1.5 pr-2 text-left text-gray-600 hover:bg-gray-50',
                    'text-sm'
                  )}
                  style={{ paddingLeft: 8 + (depth + 1) * 14 }}
                  title={f.sourcePath ? `${f.name} · ${f.sourcePath}` : f.name}
                  onClick={() => {
                    setActiveFolderId(folder.id)
                    onSelectFile?.(f.id)
                  }}
                >
                  <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  <span className="truncate">{f.name}</span>
                </button>
              ))}
            </div>
          )}

          {children.length > 0 && <div>{children.map((c) => renderFolder(c, depth + 1))}</div>}
        </div>
      )
    },
    [
      activeFolderId,
      childrenByParentId,
      directCountByFolderId,
      directFilesByFolderId,
      expandedFileFolderIds,
      handleDelete,
      openCreate,
      openMove,
      openRename,
      onRequestUpload,
      onSelectFile,
      showFiles,
      setActiveFolderId,
      toggleFileList,
    ]
  )

  const rootCount = displayFiles.length
  const rootChildren = childrenByParentId.get(ROOT_FOLDER_ID) || []
  const rootDirectFiles = (showFiles === 'all'
    || (showFiles === 'active' && activeFolderId === ROOT_FOLDER_ID)
    || (showFiles === 'expanded' && expandedFileFolderIds.has(ROOT_FOLDER_ID)))
    ? directFilesByFolderId.get(ROOT_FOLDER_ID) || []
    : []
  const rootDirectCount = directCountByFolderId[ROOT_FOLDER_ID] || 0

  return (
    <div className={cn('flex flex-col', className)}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider">文档库</div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs gap-1"
          onClick={() => openCreate(activeFolderId || ROOT_FOLDER_ID)}
        >
          <Plus className="w-3.5 h-3.5" />
          新建
        </Button>
      </div>

      <div className="space-y-0.5">
        <div
          className={cn(
            'group flex items-center gap-2 rounded-lg pr-2 py-1.5 transition-colors',
            activeFolderId === ROOT_FOLDER_ID
              ? 'bg-indigo-50 text-indigo-700'
              : 'hover:bg-gray-100 text-gray-700'
          )}
          style={{ paddingLeft: 8 }}
        >
          {showFiles === 'expanded' && rootDirectCount > 0 && (
            <button
              type="button"
              className="w-5 h-5 flex items-center justify-center rounded hover:bg-white/60 text-gray-500"
              onClick={(e) => {
                e.stopPropagation()
                toggleFileList(ROOT_FOLDER_ID)
              }}
              aria-label={expandedFileFolderIds.has(ROOT_FOLDER_ID) ? 'Collapse files' : 'Expand files'}
            >
              {expandedFileFolderIds.has(ROOT_FOLDER_ID) ? (
                <ChevronDown className="w-4 h-4" />
              ) : (
                <ChevronRight className="w-4 h-4" />
              )}
            </button>
          )}
          <button
            className="flex-1 min-w-0 flex items-center gap-2 text-left"
            onClick={() => {
              setActiveFolderId(ROOT_FOLDER_ID)
              if (showFiles === 'expanded') {
                setExpandedFileFolderIds((prev) => {
                  if (prev.has(ROOT_FOLDER_ID)) return prev
                  const next = new Set(prev)
                  next.add(ROOT_FOLDER_ID)
                  return next
                })
              }
            }}
            type="button"
          >
            {activeFolderId === ROOT_FOLDER_ID ? (
              <FolderOpen className="w-4 h-4 flex-shrink-0" />
            ) : (
              <Folder className="w-4 h-4 flex-shrink-0" />
            )}
            <span className="text-sm truncate">根目录</span>
            <span className="ml-auto text-xs text-gray-400">{rootCount}</span>
          </button>

          {onRequestUpload && (
            <Button
              variant="ghost"
              size="icon"
              className={cn('h-7 w-7', activeFolderId === ROOT_FOLDER_ID ? 'opacity-100' : 'opacity-0 group-hover:opacity-100')}
              aria-label="Upload to root folder"
              onClick={(e) => {
                e.stopPropagation()
                setActiveFolderId(ROOT_FOLDER_ID)
                onRequestUpload(ROOT_FOLDER_ID)
              }}
            >
              <Upload className="w-4 h-4" />
            </Button>
          )}
        </div>

        {rootDirectFiles.length > 0 && (
          <div className="space-y-0.5">
            {rootDirectFiles.map((f) => (
              <button
                key={f.id}
                type="button"
                className="w-full flex items-center gap-2 rounded-lg py-1.5 pr-2 text-left text-gray-600 hover:bg-gray-50 text-sm"
                style={{ paddingLeft: 8 + 14 }}
                title={f.sourcePath ? `${f.name} · ${f.sourcePath}` : f.name}
                onClick={() => {
                  setActiveFolderId(ROOT_FOLDER_ID)
                  onSelectFile?.(f.id)
                }}
              >
                <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                <span className="truncate">{f.name}</span>
              </button>
            ))}
          </div>
        )}

        {rootChildren.map((folder) => renderFolder(folder, 1))}
      </div>

      <Dialog
        open={dialog.open}
        onOpenChange={(open) => {
          if (!open) closeDialog()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialog.open && dialog.mode === 'rename'
                ? '重命名文件夹'
                : dialog.open && dialog.mode === 'move'
                  ? '移动文件夹'
                  : '新建文件夹'}
            </DialogTitle>
          </DialogHeader>

          {dialog.open && dialog.mode === 'move' ? (
            <div className="space-y-3">
              <div className="text-sm text-gray-700">
                将 <span className="font-medium">{folders.find((f) => f.id === dialog.folderId)?.name || '文件夹'}</span> 移动到：
              </div>
              <Select value={moveParentId || ROOT_FOLDER_ID} onValueChange={setMoveParentId}>
                <SelectTrigger>
                  <SelectValue placeholder="选择目标目录" />
                </SelectTrigger>
                <SelectContent>
                  {moveTargetOptions.map((opt) => (
                    <SelectItem key={opt.id} value={opt.id}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="text-xs text-gray-500">不支持移动到自身或子目录。</div>
            </div>
          ) : (
            <div className="space-y-2">
              <Input
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
                placeholder="输入文件夹名称"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleSubmit()
                  }
                }}
                autoFocus
              />
              <div className="text-xs text-gray-500">支持多级目录：在任意文件夹下创建子文件夹。</div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>
              取消
            </Button>
            {dialog.open && dialog.mode === 'move' ? (
              <Button
                onClick={handleMoveSubmit}
                disabled={moveTargetOptions.length === 0 || !moveParentId || moveParentId === dialog.folderId}
              >
                移动
              </Button>
            ) : (
              <Button onClick={handleSubmit} disabled={!folderName.trim()}>
                确定
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
