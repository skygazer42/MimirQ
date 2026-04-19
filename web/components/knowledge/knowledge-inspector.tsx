'use client'

import type { Document } from '@/types'

import { Panel } from '@/components/ui/panel'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { cn, formatDate, formatFileSize } from '@/lib/utils'

type KnowledgeInspectorProps = {
  selectedDocs: Document[]
  children?: React.ReactNode
  className?: string
  embedded?: boolean
}

export function KnowledgeInspector({
  selectedDocs,
  children,
  className,
  embedded = false,
}: Readonly<KnowledgeInspectorProps>) {
  const selected = selectedDocs.length === 1 ? selectedDocs[0] : null
  const fileType = selected ? getFileTypeMeta(selected) : null
  const TypeIcon = fileType?.icon
  const sourcePath = selected ? String((selected.metadata as any)?.source_path || '').trim() : ''
  const folderPath = sourcePath.includes('/') ? sourcePath.split('/').slice(0, -1).join('/') : ''

  const header = (
    <div
      className={cn(
        'flex items-center justify-between gap-3 border-b border-border/60',
        embedded ? 'bg-background/40 px-4 py-3 backdrop-blur-sm' : 'bg-card/60 px-4 py-3'
      )}
    >
      <div className="text-sm font-semibold text-foreground">Inspector</div>
      <div className="text-[11px] font-mono tabular-nums text-muted-foreground">{selectedDocs.length}</div>
    </div>
  )

  const summary = (() => {
    if (selected) {
      return (
        <div className="space-y-3.5">
          <div className="rounded-xl border border-border/60 bg-background/70 p-3.5 shadow-soft/10">
            <div className="flex items-start gap-3">
              {fileType && TypeIcon ? (
                <div className={cn('shrink-0 rounded-xl border p-2.5 shadow-soft/20', fileType.bg, fileType.border, fileType.color)}>
                  <TypeIcon className="h-4 w-4" />
                </div>
              ) : null}

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="text-sm font-semibold text-foreground break-words">{selected.filename}</div>
                  {fileType ? (
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase',
                        fileType.bg,
                        fileType.border,
                        fileType.color
                      )}
                      title={fileType.label}
                    >
                      {fileType.label}
                    </span>
                  ) : null}
                </div>

                <div className="mt-1 break-all font-mono text-[11px] text-muted-foreground">{selected.id}</div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2.5 text-[11px] text-muted-foreground">
            <div className="rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
              <div className="text-[11px] uppercase text-muted-foreground/70">Size</div>
              <div className="font-mono tabular-nums text-foreground">{formatFileSize(Number(selected.file_size || 0))}</div>
            </div>
            <div className="rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
              <div className="text-[11px] uppercase text-muted-foreground/70">Created</div>
              <div className="font-mono tabular-nums text-foreground">{formatDate(selected.created_at)}</div>
            </div>

            {selected.dataset_id ? (
              <div className="col-span-2 rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
                <div className="text-[11px] uppercase text-muted-foreground/70">Dataset</div>
                <div className="break-all font-mono text-foreground">{selected.dataset_id}</div>
              </div>
            ) : null}

            {sourcePath ? (
              <div className="col-span-2 rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[11px] uppercase text-muted-foreground/70">Source</div>
                  {folderPath ? (
                    <div className="max-w-[160px] truncate text-[11px] text-muted-foreground/70" title={folderPath}>
                      {folderPath}
                    </div>
                  ) : null}
                </div>
                <div className="break-all font-mono text-foreground">{sourcePath}</div>
              </div>
            ) : null}
          </div>
        </div>
      )
    }

    if (selectedDocs.length > 1) {
      return (
        <div className="rounded-xl border border-dashed border-border/60 bg-transparent px-3 py-3 text-xs text-muted-foreground">
          已选择 <span className="font-mono tabular-nums text-foreground">{selectedDocs.length}</span> 份文档。请收窄选择范围以查看单文档详情。
        </div>
      )
    }

    return (
      <div className="rounded-xl border border-dashed border-border/60 bg-transparent px-3 py-3 text-xs text-muted-foreground">
        选择一个文档以查看详情。
      </div>
    )
  })()

  if (embedded) {
    return (
      <div className={cn('flex flex-col border-0 bg-transparent', className)}>
        {header}
        <div className="space-y-3.5 p-3.5 lg:p-4">
          {summary}
          {children ? <div className="rounded-xl border border-border/60 bg-background/70 p-3.5">{children}</div> : null}
        </div>
      </div>
    )
  }

  return (
    <Panel
      padding="none"
      className={cn('min-h-0 overflow-hidden flex flex-col border-border/60 bg-card', className)}
    >
      {header}

      <div
        data-page-scroll-container="true"
        className="flex-1 min-h-0 overflow-y-auto overscroll-contain custom-scrollbar p-4 space-y-4"
      >
        {summary}
        {children ? <div className="pt-4 border-t border-border/60">{children}</div> : null}
      </div>
    </Panel>
  )
}
