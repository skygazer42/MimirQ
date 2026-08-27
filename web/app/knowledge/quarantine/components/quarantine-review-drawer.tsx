'use client'

import {
  CheckCircle2,
  Eye,
  Layers,
  RefreshCw,
  RotateCcw,
  Settings2,
  Trash2,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatDate } from '@/lib/utils'
import type { Document } from '@/types'

import { TYPO_EYEBROW } from '../constants'
import { getBusyIconClassName, isReviewed } from '../quarantine-signals'
import type { ActingState } from '../types'
import { QuarantineDetailPanel } from './quarantine-detail-panel'
import { StatusPill } from './status-pill'

interface QuarantineReviewDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  selected: Document | null
  acting: ActingState
  onRelease: (doc: Document) => void
  onRetry: (doc: Document) => void
  onTune: (doc: Document) => void
  onPreview: (docId: string) => void
  onShowDetails: (docId: string) => void
  onMarkReviewed: (doc: Document) => void
  onDelete: (doc: Document) => void
}

export function QuarantineReviewDrawer({
  open,
  onOpenChange,
  selected,
  acting,
  onRelease,
  onRetry,
  onTune,
  onPreview,
  onShowDetails,
  onMarkReviewed,
  onDelete,
}: Readonly<QuarantineReviewDrawerProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-auto right-0 top-0 h-dvh w-[min(520px,100vw)] max-w-[520px] translate-x-0 translate-y-0 overflow-hidden rounded-none border-l border-foreground/15 bg-background p-0 shadow-none backdrop-blur-none">
        <DialogHeader className="sr-only">
          <DialogTitle>{selected?.filename || '隔离记录审核'}</DialogTitle>
          <DialogDescription>{selected?.id || ''}</DialogDescription>
        </DialogHeader>

        <div className="flex h-full min-h-0 flex-col">
          <div className="border-b border-foreground/15 bg-background px-6 py-6">
            <div className="flex items-start justify-between gap-3 pr-8">
              <div className="min-w-0">
                <div className={TYPO_EYEBROW}>Audit Inspection</div>
                <div className="mt-1.5 truncate text-xl font-semibold text-foreground">
                  {selected?.filename || '未选择记录'}
                </div>
                {selected ? (
                  <div className="mt-1 flex items-center gap-2">
                    <span className="font-mono text-[10px] font-medium uppercase text-muted-foreground/45">
                      {selected.id}
                    </span>
                    <div className="h-1 w-1 rounded-full bg-border" />
                    <span className="font-mono text-[10px] font-medium text-muted-foreground/50">
                      {formatDate(selected.updated_at)}
                    </span>
                  </div>
                ) : null}
              </div>
              {selected ? (
                <div className="shrink-0 pt-1">
                  <StatusPill
                    status={isReviewed(selected) ? 'completed' : 'quarantined'}
                  />
                </div>
              ) : null}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar">
            <div className="p-6">
              <QuarantineDetailPanel selected={selected} />
            </div>
          </div>

          {selected ? (
            <div className="border-t border-foreground/15 bg-background p-6">
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    size="sm"
                    className="h-10 rounded-lg bg-warning font-medium text-primary-foreground shadow-none hover:bg-warning"
                    disabled={acting?.id === selected.id}
                    onClick={() => onRelease(selected)}
                  >
                    <RotateCcw
                      className={getBusyIconClassName(
                        acting,
                        selected.id,
                        'release'
                      )}
                    />
                    放行并重试
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-10 rounded-lg border border-foreground/10 bg-background font-medium shadow-none"
                    disabled={acting?.id === selected.id}
                    onClick={() => onRetry(selected)}
                  >
                    <RefreshCw
                      className={getBusyIconClassName(
                        acting,
                        selected.id,
                        'retry'
                      )}
                    />
                    直接重试
                  </Button>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-9 rounded-md text-xs font-medium"
                    disabled={acting?.id === selected.id}
                    onClick={() => onTune(selected)}
                  >
                    <Settings2 className="mr-1.5 size-3.5" />
                    调参
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-9 rounded-md text-xs font-medium"
                    disabled={acting?.id === selected.id}
                    onClick={() => onPreview(selected.id)}
                  >
                    <Eye className="mr-1.5 size-3.5" />
                    预览
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-9 rounded-md text-xs font-medium"
                    onClick={() => onShowDetails(selected.id)}
                  >
                    <Layers className="mr-1.5 size-3.5" />
                    任务
                  </Button>
                </div>

                <div className="h-px w-full bg-border/40" />

                <div className="flex items-center justify-between gap-3">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-9 flex-1 rounded-md border border-success/25 bg-success/[0.06] text-[11px] font-medium text-success hover:bg-success/[0.12]"
                    disabled={
                      acting?.id === selected.id || isReviewed(selected)
                    }
                    onClick={() => onMarkReviewed(selected)}
                  >
                    <CheckCircle2
                      className={getBusyIconClassName(
                        acting,
                        selected.id,
                        'review'
                      )}
                    />
                    标记为已解决
                  </Button>

                  <ConfirmDialog
                    title="确定物理删除？"
                    description="此操作不可恢复，文档记录将从数据库中移除。"
                    confirmLabel="物理删除"
                    cancelLabel="取消"
                    confirmVariant="destructive"
                    onConfirm={() => onDelete(selected)}
                  >
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-9 w-9 rounded-md p-0 text-destructive/50 hover:bg-destructive/10 hover:text-destructive"
                      disabled={acting?.id === selected.id}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </ConfirmDialog>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}
