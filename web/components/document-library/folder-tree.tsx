'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRightLeft, ChevronDown, ChevronRight, FileText, Folder, FolderOpen, MoreHorizontal, Pencil, Plus, Trash2, FileImage, FileCode, FileSpreadsheet, FileArchive, FileMusic, FileVideo, Library, Package, Database, Loader2, CheckCircle2, AlertCircle, XCircle, Ban, Paperclip, FolderUp } from 'lucide-react'
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
import { Separator } from '@/components/ui/separator'
import { FolderNode, ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'

type FolderDialogState =
  | { open: false }
  | { open: true; mode: 'create'; parentId: string }
  | { open: true; mode: 'rename'; folderId: string }
  | { open: true; mode: 'move'; folderId: string }

export function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const baseClass = "w-6 h-6 rounded flex items-center justify-center mr-2 flex-shrink-0"
  const iconClass = "w-3.5 h-3.5"
  
  switch (ext) {
    case 'jpg': case 'jpeg': case 'png': case 'gif': case 'webp': case 'svg': case 'bmp':
      return <div className={cn(baseClass, "bg-purple-100 text-purple-600")}><FileImage className={iconClass} /></div>
    case 'js': case 'jsx': case 'ts': case 'tsx': case 'py': case 'html': case 'css': case 'json': case 'java': case 'go': case 'rs': case 'php':
      return <div className={cn(baseClass, "bg-blue-100 text-blue-600")}><FileCode className={iconClass} /></div>
    case 'xls': case 'xlsx': case 'csv':
      return <div className={cn(baseClass, "bg-green-100 text-green-600")}><FileSpreadsheet className={iconClass} /></div>
    case 'zip': case 'rar': case '7z': case 'tar': case 'gz':
      return <div className={cn(baseClass, "bg-amber-100 text-amber-600")}><FileArchive className={iconClass} /></div>
    case 'mp3': case 'wav': case 'ogg': case 'flac':
      return <div className={cn(baseClass, "bg-pink-100 text-pink-600")}><FileMusic className={iconClass} /></div>
    case 'mp4': case 'mov': case 'avi': case 'mkv':
      return <div className={cn(baseClass, "bg-rose-100 text-rose-600")}><FileVideo className={iconClass} /></div>
    case 'pdf':
      return <div className={cn(baseClass, "bg-red-100 text-red-600")}><FileText className={iconClass} /></div>
    case 'doc': case 'docx':
      return <div className={cn(baseClass, "bg-amber-100/70 text-amber-700")}><FileText className={iconClass} /></div>
    case 'txt': case 'md':
      return <div className={cn(baseClass, "bg-amber-100/70 text-stone-500")}><FileText className={iconClass} /></div>
    default:
      return <div className={cn(baseClass, "bg-amber-50/70 text-stone-400")}><FileText className={iconClass} /></div>
  }
}

function getFolderIconElement(depth: number, isOpen: boolean) {
  const className = "w-4 h-4 flex-shrink-0"
  
  // Root (Depth 0) - handled separately usually, but if passed 0:
  if (depth === 0) {
    return <Library className={cn(className, "text-amber-700")} />
  }
  
  // Level 1 (Top categories)
  if (depth === 1) {
    return <Package className={cn(className, "text-rose-600")} />
  }

  // Level 2 (Sub-categories)
  if (depth === 2) {
    return isOpen 
      ? <FolderOpen className={cn(className, "text-amber-600")} />
      : <Folder className={cn(className, "text-amber-600")} />
  }
  
  // Deep levels
  const colors = [
    "text-orange-600",
    "text-amber-600",
    "text-rose-600",
    "text-yellow-700"
  ]
  const color = colors[Math.min(depth - 3, colors.length - 1)]
  
  return isOpen 
    ? <FolderOpen className={cn(className, color)} />
    : <Folder className={cn(className, color)} />
}

export function DocumentFolderTree({
  className,
  onRequestUpload,
  onRequestUploadFolder,
  fileItems,
  showFiles = 'none',
  onSelectFile,
  onDeleteFolder,
  onFileDrop,
}: {
  className?: string
  onRequestUpload?: (folderId: string) => void
  onRequestUploadFolder?: (folderId: string) => void
  fileItems?: Array<{ id: string; name: string; folderId?: string; sourcePath?: string; status?: string; error?: string }>
  showFiles?: 'none' | 'active' | 'all' | 'expanded'
  onSelectFile?: (fileId: string) => void
  onDeleteFolder?: (folderIds: string[]) => void
  onFileDrop?: (fileId: string, folderId: string) => void
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
  const [dragOverId, setDragOverId] = useState<string | null>(null)
  const dragExpandTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const dragActivateTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const dragScrollRafRef = useRef<number | null>(null)
  const dragScrollDirRef = useRef<1 | -1 | 0>(0)

  const handleDelete = useCallback(
    (folderId: string) => {
      const ok = window.confirm('确认删除该文件夹及其子文件夹？所有内容将被永久删除。')
      if (!ok) return

      const collectDescendants = (fid: string): string[] => {
        const children = folders.filter((f) => f.parentId === fid)
        return children.flatMap((c) => [c.id, ...collectDescendants(c.id)])
      }
      const idsToDelete = [folderId, ...collectDescendants(folderId)]

      deleteFolder(folderId)
      onDeleteFolder?.(idsToDelete)
      toast.success('文件夹已删除')
    },
    [deleteFolder, folders, onDeleteFolder]
  )

  const displayFiles = useMemo(() => {
    if (fileItems) return fileItems
    return libraryFiles.map((f) => ({
      id: f.id,
      name: f.filename,
      folderId: f.folderId,
      status: 'parsed',
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
    const map = new Map<string, Array<{ id: string; name: string; folderId?: string; sourcePath?: string; status?: string; error?: string }>>()
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

  useEffect(() => {
    const expandTimers = dragExpandTimersRef.current
    const activateTimers = dragActivateTimersRef.current
    return () => {
      if (dragScrollRafRef.current != null) {
        cancelAnimationFrame(dragScrollRafRef.current)
      }
      for (const timer of expandTimers.values()) {
        clearTimeout(timer)
      }
      for (const timer of activateTimers.values()) {
        clearTimeout(timer)
      }
    }
  }, [])

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
      
      const isExpanded = 
        showFiles === 'all' 
        || (showFiles === 'active' && isActive)
        || (showFiles === 'expanded' && expandedFileFolderIds.has(folder.id))

      const hasContent = count > 0 || children.length > 0
      const directFiles = isExpanded ? directFilesByFolderId.get(folder.id) || [] : []

      const requestExpand = (targetId: string) => {
        if (showFiles !== 'expanded') return
        if (expandedFileFolderIds.has(targetId)) return
        const existing = dragExpandTimersRef.current.get(targetId)
        if (existing) return
        const timer = setTimeout(() => {
          dragExpandTimersRef.current.delete(targetId)
          setExpandedFileFolderIds((prev) => {
            if (prev.has(targetId)) return prev
            const next = new Set(prev)
            next.add(targetId)
            return next
          })
        }, 350)
        dragExpandTimersRef.current.set(targetId, timer)
      }

      const clearExpandTimer = (targetId: string) => {
        const timer = dragExpandTimersRef.current.get(targetId)
        if (timer) {
          clearTimeout(timer)
          dragExpandTimersRef.current.delete(targetId)
        }
      }

      const requestActivate = (targetId: string) => {
        const existing = dragActivateTimersRef.current.get(targetId)
        if (existing) return
        const timer = setTimeout(() => {
          dragActivateTimersRef.current.delete(targetId)
          setActiveFolderId(targetId)
        }, 220)
        dragActivateTimersRef.current.set(targetId, timer)
      }

      const clearActivateTimer = (targetId: string) => {
        const timer = dragActivateTimersRef.current.get(targetId)
        if (timer) {
          clearTimeout(timer)
          dragActivateTimersRef.current.delete(targetId)
        }
      }

      const autoScrollOnDrag = (e: React.DragEvent) => {
        const container = scrollContainerRef.current
        if (!container) return
        const rect = container.getBoundingClientRect()
        const edge = 24
        let dir: 1 | -1 | 0 = 0
        if (e.clientY < rect.top + edge) dir = -1
        else if (e.clientY > rect.bottom - edge) dir = 1
        dragScrollDirRef.current = dir
        if (dir === 0) return
        if (dragScrollRafRef.current != null) return
        const step = () => {
          const d = dragScrollDirRef.current
          if (!container || d === 0) {
            dragScrollRafRef.current = null
            return
          }
          container.scrollTop += d * 6
          dragScrollRafRef.current = requestAnimationFrame(step)
        }
        dragScrollRafRef.current = requestAnimationFrame(step)
      }

      return (
        <div key={folder.id}>
          <div
            className={cn(
              'group relative flex items-center gap-2 rounded-xl px-3 py-2 transition-all',
              isActive ? 'bg-white shadow-sm ring-1 ring-amber-100 text-stone-900' : 'bg-white/70 hover:bg-white hover:shadow-sm text-stone-700',
              dragOverId === folder.id && 'bg-amber-50/70 ring-1 ring-amber-200'
            )}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOverId(folder.id)
              requestExpand(folder.id)
              autoScrollOnDrag(e)
              requestActivate(folder.id)
            }}
            onDragLeave={() => {
              setDragOverId((prev) => (prev === folder.id ? null : prev))
              clearExpandTimer(folder.id)
              clearActivateTimer(folder.id)
            }}
            onDrop={(e) => {
              e.preventDefault()
              const fileId = e.dataTransfer.getData('text/plain')
              if (fileId) onFileDrop?.(fileId, folder.id)
              setDragOverId(null)
              clearExpandTimer(folder.id)
              clearActivateTimer(folder.id)
              dragScrollDirRef.current = 0
            }}
          >
            {dragOverId === folder.id && (
              <div className="absolute left-2 right-2 bottom-0 h-0.5 bg-indigo-400 rounded-full" />
            )}
            {showFiles === 'expanded' && hasContent && (
              <button
                type="button"
                className="w-5 h-5 flex items-center justify-center rounded hover:bg-white/60 text-stone-500"
                onClick={(e) => {
                  e.stopPropagation()
                  toggleFileList(folder.id)
                }}
                aria-label={isExpanded ? 'Collapse' : 'Expand'}
              >
                {isExpanded ? (
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
              {getFolderIconElement(depth, isActive)}
              <span className="text-sm truncate">{folder.name}</span>
              <span className="ml-auto text-[10px] text-stone-500 bg-amber-100/70 px-2 py-0.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity">
                {count}
              </span>
            </button>

            {onRequestUpload && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity text-stone-500 hover:text-amber-700 hover:bg-amber-50 rounded-md"
                    aria-label="Add content"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Plus className="w-4 h-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-48 p-1">
                  <DropdownMenuItem
                    className="py-2"
                    onClick={() => {
                      setActiveFolderId(folder.id)
                      onRequestUpload(folder.id)
                    }}
                  >
                    <Paperclip className="w-4 h-4 mr-2 text-amber-700" />
                    上传文件
                  </DropdownMenuItem>
                  {onRequestUploadFolder && (
                    <DropdownMenuItem
                      className="py-2"
                      onClick={() => {
                        setActiveFolderId(folder.id)
                        onRequestUploadFolder(folder.id)
                      }}
                    >
                      <FolderUp className="w-4 h-4 mr-2 text-amber-600" />
                      上传文件夹
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem className="py-2" onClick={() => openCreate(folder.id)}>
                    <Folder className="w-4 h-4 mr-2 text-amber-600" />
                    新建文件夹
                  </DropdownMenuItem>
                  <DropdownMenuItem className="py-2" onClick={() => openMove(folder)}>
                    <ArrowRightLeft className="w-4 h-4 mr-2 text-stone-600" />
                    移动目录
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-stone-500 hover:text-stone-900 hover:bg-amber-100/70 rounded-lg"
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
                    <Paperclip className="w-4 h-4 mr-2" />
                    上传文件
                  </DropdownMenuItem>
                )}
                {onRequestUploadFolder && (
                  <DropdownMenuItem
                    onClick={() => {
                      setActiveFolderId(folder.id)
                      onRequestUploadFolder(folder.id)
                    }}
                  >
                    <FolderUp className="w-4 h-4 mr-2" />
                    上传文件夹
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

          {isExpanded && (directFiles.length > 0 || children.length > 0) && (
            <div className="ml-3 pl-2 border-l border-amber-100/70">
              {directFiles.length > 0 && (
                <div className="space-y-0.5">
                  {directFiles.map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      className={cn(
                        'w-full flex items-center gap-2 rounded-lg py-1.5 px-2 text-left text-stone-600 bg-white/60 border border-transparent hover:border-amber-200/70 hover:bg-amber-50/80',
                        'text-sm',
                        f.status === 'error' && 'bg-red-50 hover:bg-red-100 text-red-700',
                        f.status === 'parsing' && 'bg-amber-50/50'
                      )}
                      title={f.error || (f.sourcePath ? `${f.name} · ${f.sourcePath}` : f.name)}
                      onClick={() => {
                        setActiveFolderId(folder.id)
                        onSelectFile?.(f.id)
                      }}
                    >
                      {getFileIcon(f.name)}
                      <span className="truncate flex-1">{f.name}</span>
                      
                      {f.status === 'parsing' ? (
                        <div className="w-16 h-1.5 bg-amber-100 rounded-full overflow-hidden ml-2 flex-shrink-0">
                          <div className="h-full bg-amber-500 animate-[progress_1s_ease-in-out_infinite] w-full origin-left scale-x-50" />
                        </div>
                      ) : (
                        <>
                          {f.status === 'pending' && <div className="w-1.5 h-1.5 rounded-full bg-stone-300 ml-2" />}
                          {f.status === 'error' && <AlertCircle className="w-3.5 h-3.5 text-red-500 ml-2" />}
                        </>
                      )}
                    </button>
                  ))}
                </div>
              )}
              {directFiles.length > 0 && children.length > 0 && <Separator className="my-1.5 ml-2 w-auto" />}
              {children.map((c) => renderFolder(c, depth + 1))}
            </div>
          )}
        </div>
      )
    },
    [
      activeFolderId,
      childrenByParentId,
      directCountByFolderId,
      directFilesByFolderId,
      expandedFileFolderIds,
      dragOverId,
      handleDelete,
      openCreate,
      openMove,
      openRename,
      onFileDrop,
      onRequestUpload,
      onRequestUploadFolder,
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
    <div className={cn('flex flex-col', className)} ref={scrollContainerRef}>
      <div className="flex items-center justify-between mb-2 group">
        <div className="text-xs font-semibold text-stone-500 uppercase tracking-wider pl-1">文档库</div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity text-stone-500 hover:text-amber-700 hover:bg-amber-50 rounded-lg"
          title="新建根目录文件夹"
          onClick={() => openCreate(ROOT_FOLDER_ID)}
        >
          <FolderOpen className="w-4 h-4" />
        </Button>
      </div>

      <div className="space-y-0.5">
        <div
          className={cn(
            'group relative flex items-center gap-2 rounded-xl px-3 py-2 transition-all',
            activeFolderId === ROOT_FOLDER_ID
              ? 'bg-white shadow-sm ring-1 ring-amber-100 text-stone-900'
              : 'bg-white/70 hover:bg-white hover:shadow-sm text-stone-700',
            dragOverId === ROOT_FOLDER_ID && 'bg-amber-50/70 ring-1 ring-amber-200'
          )}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOverId(ROOT_FOLDER_ID)
            const existing = dragActivateTimersRef.current.get(ROOT_FOLDER_ID)
            if (!existing) {
              const timer = setTimeout(() => {
                dragActivateTimersRef.current.delete(ROOT_FOLDER_ID)
                setActiveFolderId(ROOT_FOLDER_ID)
              }, 220)
              dragActivateTimersRef.current.set(ROOT_FOLDER_ID, timer)
            }
            if (showFiles === 'expanded' && !expandedFileFolderIds.has(ROOT_FOLDER_ID)) {
              setExpandedFileFolderIds((prev) => {
                if (prev.has(ROOT_FOLDER_ID)) return prev
                const next = new Set(prev)
                next.add(ROOT_FOLDER_ID)
                return next
              })
            }
            const container = scrollContainerRef.current
            if (container) {
              const rect = container.getBoundingClientRect()
              const edge = 24
              let dir: 1 | -1 | 0 = 0
              if (e.clientY < rect.top + edge) dir = -1
              else if (e.clientY > rect.bottom - edge) dir = 1
              dragScrollDirRef.current = dir
              if (dir !== 0 && dragScrollRafRef.current == null) {
                const step = () => {
                  const d = dragScrollDirRef.current
                  if (!container || d === 0) {
                    dragScrollRafRef.current = null
                    return
                  }
                  container.scrollTop += d * 6
                  dragScrollRafRef.current = requestAnimationFrame(step)
                }
                dragScrollRafRef.current = requestAnimationFrame(step)
              }
            }
          }}
          onDragLeave={() => {
            setDragOverId((prev) => (prev === ROOT_FOLDER_ID ? null : prev))
            const timer = dragActivateTimersRef.current.get(ROOT_FOLDER_ID)
            if (timer) {
              clearTimeout(timer)
              dragActivateTimersRef.current.delete(ROOT_FOLDER_ID)
            }
          }}
          onDrop={(e) => {
            e.preventDefault()
            const fileId = e.dataTransfer.getData('text/plain')
            if (fileId) onFileDrop?.(fileId, ROOT_FOLDER_ID)
            setDragOverId(null)
            const timer = dragActivateTimersRef.current.get(ROOT_FOLDER_ID)
            if (timer) {
              clearTimeout(timer)
              dragActivateTimersRef.current.delete(ROOT_FOLDER_ID)
            }
            dragScrollDirRef.current = 0
          }}
        >
          {dragOverId === ROOT_FOLDER_ID && (
            <div className="absolute left-2 right-2 bottom-0 h-0.5 bg-indigo-400 rounded-full" />
          )}
          {showFiles === 'expanded' && (rootDirectCount > 0 || rootChildren.length > 0) && (
            <button
              type="button"
              className="w-5 h-5 flex items-center justify-center rounded hover:bg-white/60 text-stone-500"
              onClick={(e) => {
                e.stopPropagation()
                toggleFileList(ROOT_FOLDER_ID)
              }}
              aria-label={expandedFileFolderIds.has(ROOT_FOLDER_ID) ? 'Collapse' : 'Expand'}
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
            {getFolderIconElement(0, activeFolderId === ROOT_FOLDER_ID)}
            <span className="text-sm truncate">根目录</span>
            <span className="ml-auto text-[10px] text-stone-500 bg-amber-100/70 px-2 py-0.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity">
              {rootCount}
            </span>
          </button>

          {onRequestUpload && (
             <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity text-stone-500 hover:text-amber-700 hover:bg-amber-50 rounded-md"
                    aria-label="Upload to root folder"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Plus className="w-4 h-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-48 p-1">
                  <DropdownMenuItem
                    className="py-2"
                    onClick={() => {
                      setActiveFolderId(ROOT_FOLDER_ID)
                      onRequestUpload(ROOT_FOLDER_ID)
                    }}
                  >
                    <Paperclip className="w-4 h-4 mr-2 text-amber-700" />
                    上传文件
                  </DropdownMenuItem>
                  {onRequestUploadFolder && (
                    <DropdownMenuItem
                      className="py-2"
                      onClick={() => {
                        setActiveFolderId(ROOT_FOLDER_ID)
                        onRequestUploadFolder(ROOT_FOLDER_ID)
                      }}
                    >
                      <FolderUp className="w-4 h-4 mr-2 text-amber-600" />
                      上传文件夹
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem className="py-2" onClick={() => openCreate(ROOT_FOLDER_ID)}>
                    <Folder className="w-4 h-4 mr-2 text-amber-600" />
                    新建文件夹
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
          )}
        </div>

        {(showFiles === 'all' || (showFiles === 'active' && activeFolderId === ROOT_FOLDER_ID) || (showFiles === 'expanded' && expandedFileFolderIds.has(ROOT_FOLDER_ID))) && (rootDirectFiles.length > 0 || rootChildren.length > 0) && (
          <div className="ml-3 pl-2 border-l border-amber-100/70">
            {rootDirectFiles.length > 0 && (
              <div className="space-y-0.5">
                {rootDirectFiles.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    className={cn(
                      'w-full flex items-center gap-2 rounded-lg py-1.5 px-2 text-left text-stone-600 hover:bg-amber-50/70 text-sm',
                      f.status === 'error' && 'bg-red-50 hover:bg-red-100 text-red-700',
                      f.status === 'parsing' && 'bg-amber-50/50'
                    )}
                    title={f.error || (f.sourcePath ? `${f.name} · ${f.sourcePath}` : f.name)}
                    onClick={() => {
                      setActiveFolderId(ROOT_FOLDER_ID)
                      onSelectFile?.(f.id)
                    }}
                  >
                    {getFileIcon(f.name)}
                    <span className="truncate flex-1">{f.name}</span>

                    {f.status === 'parsing' ? (
                      <div className="w-16 h-1.5 bg-amber-100 rounded-full overflow-hidden ml-2 flex-shrink-0">
                        <div className="h-full bg-amber-500 animate-[progress_1s_ease-in-out_infinite] w-full origin-left scale-x-50" />
                      </div>
                    ) : (
                      <>
                        {f.status === 'pending' && <div className="w-1.5 h-1.5 rounded-full bg-stone-300 ml-2" />}
                        {f.status === 'error' && <AlertCircle className="w-3.5 h-3.5 text-red-500 ml-2" />}
                      </>
                    )}
                  </button>
                ))}
              </div>
            )}
            {rootDirectFiles.length > 0 && rootChildren.length > 0 && <Separator className="my-1.5 ml-2 w-auto" />}
            {rootChildren.map((folder) => renderFolder(folder, 1))}
          </div>
        )}
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
              <div className="text-sm text-stone-700">
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
              <div className="text-xs text-stone-500">不支持移动到自身或子目录。</div>
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
              <div className="text-xs text-stone-500">支持多级目录：在任意文件夹下创建子文件夹。</div>
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
