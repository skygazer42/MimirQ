'use client'

import { useCallback, useMemo, useState } from 'react'
import { Folder, FolderOpen, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
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
import { FolderNode, ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'

type FolderDialogState =
  | { open: false }
  | { open: true; mode: 'create'; parentId: string }
  | { open: true; mode: 'rename'; folderId: string }

export function DocumentFolderTree({ className }: { className?: string }) {
  const {
    files,
    folders,
    activeFolderId,
    setActiveFolderId,
    createFolder,
    renameFolder,
    deleteFolder,
  } = useParsedFiles()

  const [dialog, setDialog] = useState<FolderDialogState>({ open: false })
  const [folderName, setFolderName] = useState('')

  const directCountByFolderId = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const file of files) {
      const folderId = file.folderId || ROOT_FOLDER_ID
      counts[folderId] = (counts[folderId] || 0) + 1
    }
    return counts
  }, [files])

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

  const openCreate = useCallback((parentId: string) => {
    setFolderName('')
    setDialog({ open: true, mode: 'create', parentId })
  }, [])

  const openRename = useCallback((folder: FolderNode) => {
    setFolderName(folder.name)
    setDialog({ open: true, mode: 'rename', folderId: folder.id })
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

  const handleDelete = useCallback(
    (folderId: string) => {
      const ok = window.confirm('确认删除该文件夹及其子文件夹？文件将移动到根目录。')
      if (!ok) return
      deleteFolder(folderId)
      toast.success('文件夹已删除')
    },
    [deleteFolder]
  )

  const renderFolder = useCallback(
    (folder: FolderNode, depth: number) => {
      const isActive = activeFolderId === folder.id
      const count = directCountByFolderId[folder.id] || 0
      const children = childrenByParentId.get(folder.id) || []

      return (
        <div key={folder.id}>
          <div
            className={cn(
              'group flex items-center gap-2 rounded-lg pr-2 py-1.5 transition-colors',
              isActive ? 'bg-indigo-50 text-indigo-700' : 'hover:bg-gray-100 text-gray-700'
            )}
            style={{ paddingLeft: 8 + depth * 14 }}
          >
            <button
              className="flex-1 min-w-0 flex items-center gap-2 text-left"
              onClick={() => setActiveFolderId(folder.id)}
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

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 opacity-0 group-hover:opacity-100"
                  aria-label="Folder actions"
                >
                  <MoreHorizontal className="w-4 h-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => openCreate(folder.id)}>
                  <Plus className="w-4 h-4 mr-2" />
                  新建子文件夹
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

          {children.length > 0 && <div>{children.map((c) => renderFolder(c, depth + 1))}</div>}
        </div>
      )
    },
    [activeFolderId, childrenByParentId, directCountByFolderId, handleDelete, openCreate, openRename, setActiveFolderId]
  )

  const rootCount = files.length
  const rootChildren = childrenByParentId.get(ROOT_FOLDER_ID) || []

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
          <button
            className="flex-1 min-w-0 flex items-center gap-2 text-left"
            onClick={() => setActiveFolderId(ROOT_FOLDER_ID)}
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
        </div>

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
            <DialogTitle>{dialog.open && dialog.mode === 'rename' ? '重命名文件夹' : '新建文件夹'}</DialogTitle>
          </DialogHeader>

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

          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>
              取消
            </Button>
            <Button onClick={handleSubmit} disabled={!folderName.trim()}>
              确定
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
