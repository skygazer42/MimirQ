'use client'

import { useMemo, useState } from 'react'
import { Download, RotateCcw, Trash2, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export function BulkActionBar({
  selectionCount,
  canRetry,
  canCancel,
  canDelete,
  canExport,
  onClear,
  onRetry,
  onCancel,
  onDelete,
  onExport,
}: Readonly<{
  selectionCount: number
  canRetry: boolean
  canCancel: boolean
  canDelete: boolean
  canExport: boolean
  onClear: () => void
  onRetry: () => void
  onCancel: () => void
  onDelete: () => Promise<void> | void
  onExport: () => void
}>) {
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteConfirmValue, setDeleteConfirmValue] = useState('')
  const deleteEnabled = useMemo(
    () => canDelete && deleteConfirmValue === String(selectionCount),
    [canDelete, deleteConfirmValue, selectionCount]
  )

  return (
    <>
      <div
        role="toolbar"
        aria-label="批量操作"
        className="rounded-[1.1rem] border border-sky-400/18 bg-[linear-gradient(180deg,rgba(240,249,255,0.98),rgba(248,252,255,0.94))] px-3 py-3 shadow-[0_18px_50px_rgba(56,189,248,0.14)] ring-1 ring-sky-200/45 backdrop-blur-xl dark:border-sky-400/12 dark:bg-[linear-gradient(180deg,rgba(12,24,34,0.96),rgba(9,16,24,0.96))] dark:ring-white/5"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0 flex items-center gap-3">
            <div className="inline-flex h-8 min-w-8 items-center justify-center rounded-full border border-sky-400/15 bg-sky-500/10 px-2 font-code text-sm font-semibold text-sky-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.55)] dark:border-sky-400/12 dark:bg-sky-400/12 dark:text-sky-300">
              {selectionCount}
            </div>
            <div className="min-w-0">
              <div className="text-[0.66rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground/72">批量操作</div>
              <div className="mt-0.5 text-[0.92rem] font-medium tracking-[-0.01em] text-foreground">选中 {selectionCount} 项</div>
            </div>
          </div>
          <Button variant="ghost" size="sm" className="h-8 rounded-full px-3 text-xs text-muted-foreground hover:bg-black/5 hover:text-foreground dark:hover:bg-card/10" onClick={onClear}>
            清空
          </Button>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          <ActionTile icon={RotateCcw} label="Retry" tone="sky" disabled={!canRetry} onClick={onRetry} />
          <ActionTile icon={XCircle} label="Cancel" tone="amber" disabled={!canCancel} onClick={onCancel} />
          <ActionTile icon={Trash2} label="Delete" tone="rose" disabled={!canDelete} onClick={() => setDeleteOpen(true)} />
          <ActionTile icon={Download} label="Export" tone="emerald" disabled={!canExport} onClick={onExport} />
        </div>
      </div>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除选中的入库任务</DialogTitle>
            <DialogDescription>
              请输入数字 {selectionCount} 以确认删除。这会移除选中的任务记录。
            </DialogDescription>
          </DialogHeader>
          <Input
            value={deleteConfirmValue}
            onChange={(event) => setDeleteConfirmValue(event.target.value)}
            inputMode="numeric"
            placeholder={`输入 ${selectionCount}`}
          />
          <DialogFooter className="mt-4 gap-2">
            <Button variant="ghost" onClick={() => setDeleteOpen(false)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={!deleteEnabled}
              onClick={async () => {
                await onDelete()
                setDeleteConfirmValue('')
                setDeleteOpen(false)
              }}
            >
              Confirm Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function ActionTile({
  icon: Icon,
  label,
  tone,
  disabled,
  onClick,
}: Readonly<{
  icon: typeof RotateCcw
  label: string
  tone: 'sky' | 'amber' | 'rose' | 'emerald'
  disabled: boolean
  onClick: () => void
}>) {
  const toneClass = {
    sky: 'border-sky-400/18 bg-sky-500/[0.07] text-sky-700 hover:border-sky-500/28 hover:bg-sky-500/[0.12] dark:text-sky-300',
    amber: 'border-sky-400/16 bg-sky-500/[0.05] text-slate-700 hover:border-amber-500/26 hover:bg-amber-500/[0.10] hover:text-amber-700 dark:text-slate-200 dark:hover:text-amber-300',
    rose: 'border-sky-400/16 bg-sky-500/[0.05] text-slate-700 hover:border-rose-500/26 hover:bg-rose-500/[0.10] hover:text-rose-700 dark:text-slate-200 dark:hover:text-rose-300',
    emerald: 'border-sky-400/18 bg-sky-500/[0.07] text-sky-700 hover:border-emerald-500/26 hover:bg-emerald-500/[0.10] hover:text-emerald-700 dark:text-sky-300 dark:hover:text-emerald-300',
  }[tone]

  return (
    <Button
      size="sm"
      variant="outline"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'h-10 justify-start gap-2 rounded-[0.95rem] border px-3 text-[0.78rem] font-medium tracking-[0.01em] shadow-[inset_0_1px_0_rgba(255,255,255,0.32)] transition-all hover:-translate-y-0.5 disabled:opacity-35',
        toneClass
      )}
    >
      <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-card/88 ring-1 ring-sky-200/55 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] dark:bg-card/10 dark:ring-white/10">
        <Icon className="h-3.5 w-3.5" />
      </span>
      {label}
    </Button>
  )
}
