'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { ArrowRightLeft, ChevronDown, ChevronRight, FileText, Folder, FolderOpen, MoreHorizontal, Pencil, Plus, Trash2, FileImage, FileCode, FileSpreadsheet, FileArchive, AlertCircle, Paperclip, FolderUp, FileJson, AlignLeft, FileSignature, RotateCcw, Loader2, Clock3 } from 'lucide-react'
import { toast } from 'sonner'
import { collectFolderDescendantIds } from '@/lib/folder-tree-index'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
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

type FolderFileVisibility = 'none' | 'active' | 'all' | 'expanded'

export type DocumentTreeFileItem = {
  id: string
  name: string
  folderId?: string
  sourcePath?: string
  status?: string
  error?: string
  progress?: number
  parser?: string
  duration?: number
  pageCount?: number
  governanceStatus?: 'draft' | 'ready' | 'submitted'
  isActive?: boolean
  isSelectable?: boolean
  isSelected?: boolean
  readOnly?: boolean
}

const TREE_INDENT_STEP = 14
const TREE_ROW_BASE_PADDING = 8

const smallFileIconToneClasses: Record<
  string,
  {
    bg: string
    border: string
    icon: string
  }
> = {
  red: {
    bg: 'bg-red-50 dark:bg-red-950/20',
    border: 'border-red-200/80 dark:border-red-800/60',
    icon: 'text-red-600 dark:text-red-300',
  },
  blue: {
    bg: 'bg-blue-50 dark:bg-blue-950/20',
    border: 'border-blue-200/80 dark:border-blue-800/60',
    icon: 'text-blue-600 dark:text-blue-300',
  },
  emerald: {
    bg: 'bg-emerald-50 dark:bg-emerald-950/20',
    border: 'border-emerald-200/80 dark:border-emerald-800/60',
    icon: 'text-emerald-700 dark:text-emerald-300',
  },
  amber: {
    bg: 'bg-amber-50 dark:bg-amber-950/20',
    border: 'border-amber-200/80 dark:border-amber-800/60',
    icon: 'text-amber-700 dark:text-amber-300',
  },
  rose: {
    bg: 'bg-rose-50 dark:bg-rose-950/20',
    border: 'border-rose-200/80 dark:border-rose-800/60',
    icon: 'text-rose-600 dark:text-rose-300',
  },
  sky: {
    bg: 'bg-sky-50 dark:bg-sky-950/20',
    border: 'border-sky-200/80 dark:border-sky-800/60',
    icon: 'text-sky-600 dark:text-sky-300',
  },
  teal: {
    bg: 'bg-teal-50 dark:bg-teal-950/20',
    border: 'border-teal-200/80 dark:border-teal-800/60',
    icon: 'text-teal-700 dark:text-teal-300',
  },
  slate: {
    bg: 'bg-muted dark:bg-slate-900/40',
    border: 'border-border/70 dark:border-slate-700/65',
    icon: 'text-muted-foreground',
  },
}

export function getFileIcon(filename: string, className?: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const isLarge = className?.includes('w-12')

  // Color & Label Mapping
  let tone: 'slate' | 'red' | 'blue' | 'emerald' | 'amber' | 'rose' | 'sky' | 'teal' = 'slate'
  let label = ext.toUpperCase().slice(0, 3)
  let Icon = FileText

  // Keep icon shapes distinct; keep colors subtle (Notes-like) and avoid purple.
  if (['pdf'].includes(ext)) { tone = 'red'; label = 'PDF'; Icon = FileSignature }
  else if (['doc', 'docx'].includes(ext)) { tone = 'blue'; label = 'DOC'; Icon = FileText } // Word
  else if (['xls', 'xlsx'].includes(ext)) { tone = 'emerald'; label = 'XLS'; Icon = FileSpreadsheet } // Excel
  else if (['csv'].includes(ext)) { tone = 'emerald'; label = 'CSV'; Icon = FileSpreadsheet }
  else if (['ppt', 'pptx'].includes(ext)) { tone = 'amber'; label = 'PPT'; Icon = FileImage } // PPT
  else if (['md'].includes(ext)) { tone = 'sky'; label = 'MD'; Icon = AlignLeft }
  else if (['txt'].includes(ext)) { tone = 'slate'; label = 'TXT'; Icon = AlignLeft }
  else if (['json'].includes(ext)) { tone = 'teal'; label = 'JSON'; Icon = FileJson } // JSON
  else if (['jpg', 'png', 'jpeg', 'gif', 'webp'].includes(ext)) { tone = 'rose'; label = 'IMG'; Icon = FileImage } // Image
  else if (['zip', 'rar', '7z'].includes(ext)) { tone = 'amber'; label = 'ZIP'; Icon = FileArchive } // Archive
  else if (['js', 'ts', 'jsx', 'tsx', 'py'].includes(ext)) { tone = 'sky'; label = 'CODE'; Icon = FileCode } // Code

  // Small Icon: light file-type square matching the parsing tree visual.
  if (!isLarge) {
    const toneClass = smallFileIconToneClasses[tone] || smallFileIconToneClasses.slate
    return (
      <div
        className={cn(
          'flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-lg border shadow-[inset_0_1px_0_rgba(255,255,255,0.78)]',
          toneClass.bg,
          toneClass.border,
          className
        )}
        aria-hidden="true"
      >
        <Icon className={cn('h-3.5 w-3.5', toneClass.icon)} />
      </div>
    )
  }

  // Large Icon (Detailed Paper Style)
  // Simulating a vertical document page with a colored fold/header
  const paperBand: Record<string, string> = {
    red: "bg-red-500/70",
    blue: "bg-blue-500/70",
    emerald: "bg-emerald-500/70",
    amber: "bg-amber-500/70",
    rose: "bg-rose-500/70",
    sky: "bg-primary/30",
    teal: "bg-teal-500/70",
    slate: "bg-muted-foreground/40",
  }

  const textTone: Record<string, string> = {
    red: "text-red-600",
    blue: "text-blue-600",
    emerald: "text-emerald-600",
    amber: "text-amber-700",
    rose: "text-rose-600",
    sky: "text-primary",
    teal: "text-teal-700",
    slate: "text-muted-foreground",
  }

  const badgeBorder: Record<string, string> = {
    red: "border-red-200",
    blue: "border-blue-200",
    emerald: "border-emerald-200",
    amber: "border-amber-200",
    rose: "border-rose-200",
    sky: "border-primary/25",
    teal: "border-teal-200",
    slate: "border-border/60",
  }

  return (
    <div className={cn("relative flex items-center justify-center", className)}>
      {/* Paper Container */}
      <div className="relative w-9 h-11 bg-card rounded-sm shadow-soft/40 border border-border/60 overflow-hidden flex flex-col">

        {/* Top Color Band / Header */}
        <div className={cn("h-3 w-full opacity-80", paperBand[tone] || paperBand.slate)} />

        {/* Corner Fold Effect (CSS Triangle) */}
        <div className="absolute top-0 right-0 border-t-[8px] border-r-[8px] border-t-black/5 border-r-white/0" />

        {/* Content */}
        <div className="flex-1 flex items-center justify-center bg-background/40">
          {(() => {
    if (['W', 'X', 'P'].includes(label)) {
        return (<span className={cn("font-serif font-semibold text-lg leading-none", textTone[tone])}>
              {label}
            </span>);
    }
    else if (['PDF', 'TXT', 'ZIP', 'IMG'].includes(label)) {
            return (<span className={cn("font-bold text-[9px]  leading-none border-2 rounded px-0.5", textTone[tone], badgeBorder[tone] || badgeBorder.slate)}>
              {label}
            </span>);
        }
        else {
            return (<Icon className={cn("w-5 h-5", textTone[tone])}/>);
        }
})()}
        </div>

        {/* Faux Text Lines (Decorative) */}
        <div className="mb-1.5 px-1.5 space-y-0.5 opacity-20">
          <div className="h-0.5 w-full bg-muted-foreground/30 rounded-full" />
          <div className="h-0.5 w-2/3 bg-muted-foreground/30 rounded-full" />
        </div>
      </div>
    </div>
  )
}

function getFolderIconElement(depth: number, isOpen: boolean) {
  const className = "w-4 h-4 flex-shrink-0"

  return isOpen
    ? <FolderOpen className={cn(className, "text-muted-foreground/90")} />
    : <Folder className={cn(className, "text-muted-foreground/80")} />
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
  onRetryFile,
  onRemoveFile,
  onFileDragStart,
  onToggleFileSelected,
}: Readonly<{
  className?: string
  onRequestUpload?: (folderId: string) => void
  onRequestUploadFolder?: (folderId: string) => void
  fileItems?: DocumentTreeFileItem[]
  showFiles?: FolderFileVisibility
  onSelectFile?: (fileId: string) => void
  onDeleteFolder?: (folderIds: string[]) => void
  onFileDrop?: (fileId: string, folderId: string) => void
  onRetryFile?: (fileId: string) => void
  onRemoveFile?: (fileId: string) => void
  onFileDragStart?: (event: React.DragEvent<HTMLElement>, fileId: string) => void
  onToggleFileSelected?: (fileId: string) => void
}>) {
  const libraryFiles = useParsedFiles((state) => state.files)
  const folders = useParsedFiles((state) => state.folders)
  const activeFolderId = useParsedFiles((state) => state.activeFolderId)
  const setActiveFolderId = useParsedFiles((state) => state.setActiveFolderId)
  const createFolder = useParsedFiles((state) => state.createFolder)
  const renameFolder = useParsedFiles((state) => state.renameFolder)
  const deleteFolder = useParsedFiles((state) => state.deleteFolder)
  const moveFolder = useParsedFiles((state) => state.moveFolder)

  const [dialog, setDialog] = useState<FolderDialogState>({ open: false })
  const [folderName, setFolderName] = useState('')
  const [moveParentId, setMoveParentId] = useState(ROOT_FOLDER_ID)
  const [confirmingFolderId, setConfirmingFolderId] = useState<string | null>(null)
  const [expandedFileFolderIds, setExpandedFileFolderIds] = useState<Set<string>>(() => new Set([ROOT_FOLDER_ID]))
  const [dragOverId, setDragOverId] = useState<string | null>(null)
  const draggedFolderIdRef = useRef<string | null>(null)
  const dragExpandTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const dragActivateTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const dragScrollRafRef = useRef<number | null>(null)
  const dragScrollDirRef = useRef<1 | -1 | 0>(0)

  const handleDelete = useCallback(
    (folderId: string) => {
      const idsToDelete = [folderId, ...collectFolderDescendantIds(folders, folderId)]

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
    const map = new Map<string, DocumentTreeFileItem[]>()
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

  const DND_FOLDER_MIME = 'application/x-mimirq-folder'

  const moveFolderWithToast = useCallback(
    (folderId: string, targetParentId: string) => {
      const target = targetParentId || ROOT_FOLDER_ID
      const ok = moveFolder(folderId, target)
      if (ok) {
        toast.success('文件夹已移动')
        return true
      }
      const currentParentId = folders.find((f) => f.id === folderId)?.parentId || ROOT_FOLDER_ID
      if ((currentParentId || ROOT_FOLDER_ID) === (target || ROOT_FOLDER_ID)) {
        toast.info('该文件夹已在目标目录')
      } else {
        toast.error('移动失败：目标目录不合法（可能是自身/子目录/不存在）')
      }
      return false
    },
    [moveFolder, folders]
  )

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
    const targetParentId = moveParentId || ROOT_FOLDER_ID
    const ok = moveFolder(dialog.folderId, targetParentId)
    if (ok) {
      toast.success('文件夹已移动')
      closeDialog()
      return
    }
    // Provide accurate feedback instead of always reporting success.
    const currentParentId = folders.find((f) => f.id === dialog.folderId)?.parentId || ROOT_FOLDER_ID
    if ((currentParentId || ROOT_FOLDER_ID) === (targetParentId || ROOT_FOLDER_ID)) {
      toast.info('该文件夹已在目标目录')
    } else {
      toast.error('移动失败：目标目录不合法（可能是自身/子目录/不存在）')
    }
    closeDialog()
  }, [dialog, moveFolder, moveParentId, closeDialog, folders])



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

  const requestExpand = useCallback((targetId: string) => {
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
  }, [expandedFileFolderIds, showFiles])

  const clearExpandTimer = useCallback((targetId: string) => {
    const timer = dragExpandTimersRef.current.get(targetId)
    if (timer) {
      clearTimeout(timer)
      dragExpandTimersRef.current.delete(targetId)
    }
  }, [])

  const requestActivate = useCallback((targetId: string) => {
    const existing = dragActivateTimersRef.current.get(targetId)
    if (existing) return
    const timer = setTimeout(() => {
      dragActivateTimersRef.current.delete(targetId)
      setActiveFolderId(targetId)
    }, 220)
    dragActivateTimersRef.current.set(targetId, timer)
  }, [setActiveFolderId])

  const clearActivateTimer = useCallback((targetId: string) => {
    const timer = dragActivateTimersRef.current.get(targetId)
    if (timer) {
      clearTimeout(timer)
      dragActivateTimersRef.current.delete(targetId)
    }
  }, [])

  const autoScrollOnDrag = useCallback((e: React.DragEvent) => {
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
  }, [])

  const renderIndentGuides = (level: number) => {
    if (level <= 0) return null

    return (
      <div aria-hidden className="pointer-events-none absolute inset-y-1 left-0">
        {Array.from({ length: level }).map((_, index) => (
          <span
            key={`${level}-${index}`}
            className="absolute inset-y-0 w-px bg-border/22"
            style={{ left: `${TREE_ROW_BASE_PADDING + index * TREE_INDENT_STEP + 6}px` }}
          />
        ))}
      </div>
    )
  }

  const renderFileRow = useCallback(
    (file: DocumentTreeFileItem, parentFolderId: string, level: number) => {
      const status = String(file.status || 'parsed')
      const isParsing = status === 'parsing'
      const isError = status === 'error'
      const isPending = status === 'pending'
      const governanceStatusLabel =
        file.governanceStatus === 'ready' ? '待提交' : file.governanceStatus === 'submitted' ? '已提交' : ''
      const progress =
        file.progress == null || !Number.isFinite(Number(file.progress))
          ? null
          : Math.max(0, Math.min(100, Number(file.progress)))
      const hasInlineActions = !file.readOnly && Boolean(onRetryFile || onRemoveFile)

      return (
        <div
          key={file.id}
          className={cn(
            'group/file relative overflow-hidden rounded-xl before:absolute before:bottom-1.5 before:left-0 before:top-1.5 before:w-0.5 before:rounded-full before:bg-primary/0 before:transition-colors',
            file.isActive
              ? 'bg-info/[0.085] text-foreground shadow-[inset_0_0_0_1px_hsl(var(--info)/0.10)] before:bg-info/70'
              : 'text-foreground/72 hover:bg-muted/36 hover:text-foreground/88',
            isError && !file.isActive && 'bg-destructive/7 text-destructive/90 hover:bg-destructive/8'
          )}
        >
          {renderIndentGuides(level)}
          <div
            className={cn(
              'flex h-9 w-full items-center gap-2 pr-2 text-left',
              hasInlineActions && 'pr-10',
              file.isSelectable && 'pl-1'
            )}
            style={{ paddingLeft: `${TREE_ROW_BASE_PADDING + level * TREE_INDENT_STEP}px` }}
            title={file.error || (file.sourcePath ? `${file.name} · ${file.sourcePath}` : file.name)}
            draggable={Boolean(onFileDragStart) && !file.readOnly}
            onDragStart={!file.readOnly && onFileDragStart ? (event) => onFileDragStart(event, file.id) : undefined}
          >
            {file.isSelectable ? (
              <button
                type="button"
                aria-label={file.isSelected ? '取消选择待提交文档' : '选择待提交文档'}
                className={cn(
                  'flex size-4 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold transition-colors focus-ring',
                  file.isSelected
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border/70 bg-background text-transparent group-hover/file:border-primary/50 group-hover/file:text-primary/40'
                )}
                onClick={(event) => {
                  event.stopPropagation()
                  onToggleFileSelected?.(file.id)
                }}
              >
                ✓
              </button>
            ) : null}
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-1.5 text-left focus-ring"
              onClick={() => {
                setActiveFolderId(parentFolderId || ROOT_FOLDER_ID)
                onSelectFile?.(file.id)
              }}
            >
              {getFileIcon(file.name, 'h-6 w-6 rounded-lg')}
              <span className="flex min-w-0 flex-1 items-center gap-1.5">
                <span className="min-w-0 flex-1 truncate text-[12px] font-medium leading-4">{file.name}</span>
                {governanceStatusLabel ? (
                  <span
                    className={cn(
                      'shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-medium',
                      file.governanceStatus === 'ready'
                        ? 'border-warning/25 bg-warning/[0.10] text-warning'
                        : 'border-success/25 bg-success/[0.08] text-success'
                    )}
                  >
                    {governanceStatusLabel}
                  </span>
                ) : null}
                {isParsing ? (
                  <span className="shrink-0 text-primary" title={progress != null ? `处理中 ${Math.round(progress)}%` : '处理中'}>
                    <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
                  </span>
                ) : null}
                {isPending ? (
                  <span className="shrink-0 text-amber-600/80 dark:text-amber-300/80" title="待解析">
                    <Clock3 className="h-3 w-3" />
                  </span>
                ) : null}
                {isError ? <AlertCircle className="h-3.5 w-3.5 shrink-0 text-destructive" /> : null}
              </span>
            </button>
          </div>

          {hasInlineActions ? (
            <div className="pointer-events-none absolute right-1 top-1 flex items-center gap-0.5 opacity-0 transition-opacity duration-150 group-hover/file:pointer-events-auto group-hover/file:opacity-100">
              {isError && onRetryFile ? (
                <button
                  type="button"
                  className="flex h-5 w-5 items-center justify-center rounded-md text-muted-foreground/80 hover:bg-muted/40 hover:text-foreground focus-ring"
                  title="重试"
                  aria-label="重试"
                  onClick={(event) => {
                    event.stopPropagation()
                    onRetryFile(file.id)
                  }}
                >
                  <RotateCcw className="h-3 w-3" />
                </button>
              ) : null}
              {onRemoveFile ? (
                <button
                  type="button"
                  className="flex h-5 w-5 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive focus-ring"
                  title="删除"
                  aria-label="删除"
                  onClick={(event) => {
                    event.stopPropagation()
                    onRemoveFile(file.id)
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              ) : null}
            </div>
          ) : null}

          {isParsing ? (
            <div className="pointer-events-none absolute inset-x-2 bottom-0 h-0.5 overflow-hidden rounded-full bg-primary/12">
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-300 motion-reduce:transition-none"
                style={{ width: `${progress ?? 45}%` }}
              />
            </div>
          ) : null}
        </div>
      )
    },
    [onFileDragStart, onRemoveFile, onRetryFile, onSelectFile, onToggleFileSelected, setActiveFolderId]
  )

  const expandVisibleFolder = useCallback((folderId: string) => {
    if (showFiles !== 'expanded') return
    setExpandedFileFolderIds((prev) => {
      if (prev.has(folderId)) return prev
      const next = new Set(prev)
      next.add(folderId)
      return next
    })
  }, [showFiles])

  const collapseVisibleFolder = useCallback((folderId: string) => {
    if (showFiles !== 'expanded') return
    setExpandedFileFolderIds((prev) => {
      if (!prev.has(folderId)) return prev
      const next = new Set(prev)
      next.delete(folderId)
      return next
    })
  }, [showFiles])

  const selectFolder = useCallback((folderId: string) => {
    setActiveFolderId(folderId)
    expandVisibleFolder(folderId)
  }, [expandVisibleFolder, setActiveFolderId])

  const handleFolderRowKeyDown = useCallback((
    event: ReactKeyboardEvent<HTMLDivElement>,
    folderId: string,
    hasContent: boolean
  ) => {
    if (event.target !== event.currentTarget) return

    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      selectFolder(folderId)
      return
    }

    if (!hasContent || showFiles !== 'expanded') return

    if (event.key === 'ArrowRight') {
      event.preventDefault()
      expandVisibleFolder(folderId)
      return
    }

    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      collapseVisibleFolder(folderId)
    }
  }, [collapseVisibleFolder, expandVisibleFolder, selectFolder, showFiles])

  function renderFolder(folder: FolderNode, depth: number) {
      const isActive = activeFolderId === folder.id
      const count = directCountByFolderId[folder.id] || 0
      const children = childrenByParentId.get(folder.id) || []

      const isExpanded =
        showFiles === 'all'
        || (showFiles === 'active' && isActive)
        || (showFiles === 'expanded' && expandedFileFolderIds.has(folder.id))

      const hasContent = count > 0 || children.length > 0
      const directFiles = isExpanded ? directFilesByFolderId.get(folder.id) || [] : []

      return (
        <div key={folder.id}>
          <div
            role="treeitem"
            tabIndex={0}
            aria-selected={isActive}
            aria-expanded={hasContent ? isExpanded : undefined}
            className={cn(
              'group relative flex items-center gap-1 rounded-xl py-1.5 transition-colors before:absolute before:bottom-1.5 before:left-0 before:top-1.5 before:w-0.5 before:rounded-full before:bg-primary/0 before:transition-colors',
              isActive
                ? 'text-foreground before:bg-muted-foreground/35'
                : 'text-foreground/72 hover:bg-muted/36 hover:text-foreground/88',
              dragOverId === folder.id && 'bg-info/[0.08] before:bg-info/50'
            )}
            style={{
              paddingLeft: `${TREE_ROW_BASE_PADDING + depth * TREE_INDENT_STEP}px`,
              paddingRight: '0.5rem',
            }}
            draggable
            onKeyDown={(e) => handleFolderRowKeyDown(e, folder.id, hasContent)}
            onDragStart={(e) => {
              // Folder drag
              draggedFolderIdRef.current = folder.id
              try {
                e.dataTransfer.setData(DND_FOLDER_MIME, folder.id)
              } catch {
                // ignore
              }
              e.dataTransfer.effectAllowed = 'move'
            }}
            onDragEnd={() => {
              draggedFolderIdRef.current = null
              setDragOverId(null)
              dragScrollDirRef.current = 0
            }}
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
              // Folder drop has priority over file drop.
              const draggedFolderId =
                e.dataTransfer.getData(DND_FOLDER_MIME) || draggedFolderIdRef.current || ''
              if (draggedFolderId) {
                moveFolderWithToast(draggedFolderId, folder.id)
              } else {
                const fileId = e.dataTransfer.getData('text/plain')
                if (fileId) onFileDrop?.(fileId, folder.id)
              }
              setDragOverId(null)
              clearExpandTimer(folder.id)
              clearActivateTimer(folder.id)
              dragScrollDirRef.current = 0
            }}
          >
            {renderIndentGuides(depth)}
            {dragOverId === folder.id && (
              <div className="absolute left-2 right-2 bottom-0 h-0.5 bg-primary rounded-full" />
            )}
            {showFiles === 'expanded' && hasContent && (
              <button
                type="button"
                className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground/75 hover:bg-muted/40 hover:text-foreground focus-ring"
                onClick={(e) => {
                  e.stopPropagation()
                  toggleFileList(folder.id)
                }}
                aria-label={isExpanded ? 'Collapse' : 'Expand'}
              >
                {isExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
              </button>
            )}
            <button
              className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
              onClick={() => selectFolder(folder.id)}
              type="button"
              title={folder.name}
            >
              {getFolderIconElement(depth, isActive)}
              <span className="truncate text-[12px] font-medium leading-4">{folder.name}</span>
              <span className="ml-auto rounded-md bg-muted/55 px-1.5 py-0.5 text-[9px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                {count}
              </span>
            </button>

            {onRequestUpload && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 rounded-md text-muted-foreground opacity-0 transition-opacity duration-150 group-hover:opacity-100 hover:bg-muted/60 hover:text-foreground"
                    aria-label="Add content"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Plus className="h-3.5 w-3.5" />
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
                    <Paperclip className="w-4 h-4 mr-2 text-muted-foreground" />
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
                      <FolderUp className="w-4 h-4 mr-2 text-muted-foreground" />
                      上传文件夹
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem className="py-2" onClick={() => openCreate(folder.id)}>
                    <Folder className="w-4 h-4 mr-2 text-muted-foreground" />
                    新建文件夹
                  </DropdownMenuItem>
                  <DropdownMenuItem className="py-2" onClick={() => openMove(folder)}>
                    <ArrowRightLeft className="w-4 h-4 mr-2 text-muted-foreground" />
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
                  className="h-5 w-5 rounded-md text-muted-foreground opacity-0 transition-opacity duration-150 group-hover:opacity-100 hover:bg-muted/40 hover:text-foreground"
                  aria-label="Folder actions"
                >
                  <MoreHorizontal className="h-3.5 w-3.5" />
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
                  className="text-red-600 dark:text-red-400 focus:text-red-600 dark:focus:text-red-400"
                  onSelect={() => setConfirmingFolderId(folder.id)}
                >
                  <Trash2 className="w-4 h-4 mr-2" />
                  删除
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            <ConfirmDialog
              open={confirmingFolderId === folder.id}
              onOpenChange={(open) => {
                setConfirmingFolderId(open ? folder.id : null)
              }}
              title="删除该文件夹？"
              description="将删除该文件夹及其子文件夹，且所有内容将被永久删除。此操作不可恢复。"
              confirmLabel="删除"
              cancelLabel="返回"
              confirmVariant="destructive"
              onConfirm={() => {
                handleDelete(folder.id)
                setConfirmingFolderId(null)
              }}
            >
              <span className="sr-only">删除该文件夹</span>
            </ConfirmDialog>
          </div>

          {isExpanded && directFiles.map((f) => renderFileRow(f, folder.id, depth + 1))}
          {isExpanded && children.map((c) => renderFolder(c, depth + 1))}
        </div>
      )
  }

  const rootCount = displayFiles.length
  const rootChildren = childrenByParentId.get(ROOT_FOLDER_ID) || []
  const rootDirectFiles = (showFiles === 'all'
    || (showFiles === 'active' && activeFolderId === ROOT_FOLDER_ID)
    || (showFiles === 'expanded' && expandedFileFolderIds.has(ROOT_FOLDER_ID)))
    ? directFilesByFolderId.get(ROOT_FOLDER_ID) || []
    : []
  const rootDirectCount = directCountByFolderId[ROOT_FOLDER_ID] || 0
  const rootHasContent = rootDirectCount > 0 || rootChildren.length > 0
  const isRootExpanded = expandedFileFolderIds.has(ROOT_FOLDER_ID)

  return (
    <div className={cn('flex flex-col', className)} ref={scrollContainerRef} role="tree" aria-label="文档目录">
      <div className="space-y-0.5">
        <div
          role="treeitem"
          tabIndex={0}
          aria-selected={activeFolderId === ROOT_FOLDER_ID}
          aria-expanded={rootHasContent ? isRootExpanded : undefined}
          className={cn(
            'group relative flex items-center gap-1 rounded-xl py-1.5 transition-colors before:absolute before:bottom-1.5 before:left-0 before:top-1.5 before:w-0.5 before:rounded-full before:bg-primary/0 before:transition-colors',
            activeFolderId === ROOT_FOLDER_ID
              ? 'text-foreground before:bg-muted-foreground/35'
              : 'text-foreground/72 hover:bg-muted/36 hover:text-foreground/88',
            dragOverId === ROOT_FOLDER_ID && 'bg-info/[0.08] before:bg-info/50'
          )}
          style={{ paddingLeft: `${TREE_ROW_BASE_PADDING}px`, paddingRight: '0.5rem' }}
          onKeyDown={(e) => handleFolderRowKeyDown(e, ROOT_FOLDER_ID, rootHasContent)}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOverId(ROOT_FOLDER_ID)
            requestActivate(ROOT_FOLDER_ID)
            if (showFiles === 'expanded' && !expandedFileFolderIds.has(ROOT_FOLDER_ID)) {
              setExpandedFileFolderIds((prev) => {
                if (prev.has(ROOT_FOLDER_ID)) return prev
                const next = new Set(prev)
                next.add(ROOT_FOLDER_ID)
                return next
              })
            }
            autoScrollOnDrag(e)
          }}
          onDragLeave={() => {
            setDragOverId((prev) => (prev === ROOT_FOLDER_ID ? null : prev))
            clearActivateTimer(ROOT_FOLDER_ID)
          }}
          onDrop={(e) => {
            e.preventDefault()
            const draggedFolderId =
              e.dataTransfer.getData(DND_FOLDER_MIME) || draggedFolderIdRef.current || ''
            if (draggedFolderId) {
              moveFolderWithToast(draggedFolderId, ROOT_FOLDER_ID)
            } else {
              const fileId = e.dataTransfer.getData('text/plain')
              if (fileId) onFileDrop?.(fileId, ROOT_FOLDER_ID)
            }
            setDragOverId(null)
            clearActivateTimer(ROOT_FOLDER_ID)
            dragScrollDirRef.current = 0
          }}
        >
          {dragOverId === ROOT_FOLDER_ID && (
            <div className="absolute left-2 right-2 bottom-0 h-0.5 bg-primary rounded-full" />
          )}
          {showFiles === 'expanded' && rootHasContent && (
            <button
              type="button"
              className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground/75 hover:bg-muted/40 hover:text-foreground focus-ring"
              onClick={(e) => {
                e.stopPropagation()
                toggleFileList(ROOT_FOLDER_ID)
              }}
              aria-label={isRootExpanded ? 'Collapse' : 'Expand'}
            >
              {isRootExpanded ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
            </button>
          )}
          <button
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
            onClick={() => selectFolder(ROOT_FOLDER_ID)}
            type="button"
          >
            {getFolderIconElement(0, activeFolderId === ROOT_FOLDER_ID)}
            <span className="truncate text-[12px] font-medium leading-4">根目录</span>
            <span className="ml-auto rounded-md bg-muted/55 px-1.5 py-0.5 text-[9px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
              {rootCount}
            </span>
          </button>

          {onRequestUpload && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5 rounded-md text-muted-foreground opacity-0 transition-opacity duration-150 group-hover:opacity-100 hover:bg-muted/60 hover:text-foreground"
                  aria-label="Upload to root folder"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Plus className="h-3.5 w-3.5" />
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
                  <Paperclip className="w-4 h-4 mr-2 text-muted-foreground" />
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
                    <FolderUp className="w-4 h-4 mr-2 text-muted-foreground" />
                    上传文件夹
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem className="py-2" onClick={() => openCreate(ROOT_FOLDER_ID)}>
                  <Folder className="w-4 h-4 mr-2 text-muted-foreground" />
                  新建文件夹
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        {(showFiles === 'all' || (showFiles === 'active' && activeFolderId === ROOT_FOLDER_ID) || (showFiles === 'expanded' && expandedFileFolderIds.has(ROOT_FOLDER_ID))) && rootDirectFiles.map((f) => renderFileRow(f, ROOT_FOLDER_ID, 1))}
        {(showFiles === 'all' || (showFiles === 'active' && activeFolderId === ROOT_FOLDER_ID) || (showFiles === 'expanded' && expandedFileFolderIds.has(ROOT_FOLDER_ID))) && rootChildren.map((folder) => renderFolder(folder, 1))}
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
              {(() => {
    if (dialog.open && dialog.mode === 'rename') {
        return '重命名文件夹';
    }
    else if (dialog.open && dialog.mode === 'move') {
            return '移动文件夹';
        }
        else {
            return '新建文件夹';
        }
})()}
            </DialogTitle>
          </DialogHeader>

          {dialog.open && dialog.mode === 'move' ? (
            <div className="space-y-3">
              <div className="text-sm text-foreground">
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
              <div className="text-xs text-muted-foreground">不支持移动到自身或子目录。</div>
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
              <div className="text-xs text-muted-foreground">支持多级目录：在任意文件夹下创建子文件夹。</div>
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
