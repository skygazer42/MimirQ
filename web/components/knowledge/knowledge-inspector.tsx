'use client'

import type { Document } from '@/types'

import { Panel } from '@/components/ui/panel'
import { cn, formatDate, formatFileSize } from '@/lib/utils'

type KnowledgeInspectorProps = {
  selectedDocs: Document[]
  children?: React.ReactNode
  className?: string
}

export function KnowledgeInspector({ selectedDocs, children, className }: KnowledgeInspectorProps) {
  const selected = selectedDocs.length === 1 ? selectedDocs[0] : null

  return (
    <Panel
      padding="none"
      className={cn('min-h-0 overflow-hidden flex flex-col border-border/60 bg-card', className)}
    >
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border/60 bg-card/60">
        <div className="text-sm font-semibold text-foreground">Inspector</div>
        <div className="text-[11px] font-mono tabular-nums text-muted-foreground">
          {selectedDocs.length}
        </div>
      </div>

      <div
        data-page-scroll-container="true"
        className="flex-1 min-h-0 overflow-y-auto overscroll-contain custom-scrollbar p-4 space-y-4"
      >
        {selected ? (
          <div className="space-y-2">
            <div className="text-[11px] uppercase text-muted-foreground/80">Document</div>
            <div className="text-sm font-medium text-foreground break-words">{selected.filename}</div>
            <div className="text-[11px] text-muted-foreground font-mono break-all">{selected.id}</div>
            <div className="pt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
              <div className="rounded-lg border border-border/60 bg-muted/30 px-2 py-1">
                <div className="text-[10px] uppercase text-muted-foreground/70">Size</div>
                <div className="font-mono tabular-nums">{formatFileSize(Number(selected.file_size || 0))}</div>
              </div>
              <div className="rounded-lg border border-border/60 bg-muted/30 px-2 py-1">
                <div className="text-[10px] uppercase text-muted-foreground/70">Created</div>
                <div className="font-mono tabular-nums">{formatDate(selected.created_at)}</div>
              </div>
            </div>
          </div>
        ) : selectedDocs.length > 1 ? (
          <div className="text-xs text-muted-foreground">
            已选择 <span className="font-mono tabular-nums">{selectedDocs.length}</span> 份文档。
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">选择一个文档以查看详情。</div>
        )}

        {children ? (
          <div className="pt-4 border-t border-border/60">{children}</div>
        ) : null}
      </div>
    </Panel>
  )
}

