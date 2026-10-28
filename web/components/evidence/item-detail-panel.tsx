'use client'

import type { RefObject } from 'react'
import { BarChart3, Download, FileUp, Loader2, RefreshCw, Search, ShieldCheck, TestTube2, X } from '@/components/icons'

import type { EvidenceItem, EvidenceSuite } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'

type SuiteCounts = {
  total: number
  draft: number
  reviewed: number
  approved: number
  archived: number
}

type ItemDetailPanelProps = {
  selectedItem: EvidenceItem | null
  selectedSuite: EvidenceSuite | null
  statusBadgeVariant: (status: EvidenceItem['status']) => 'outline' | 'secondary' | 'soft' | 'destructive'
  onReviewItem: (itemId: string) => void
  onApproveItem: (itemId: string) => void
  onOpenWhyMissed: () => void
  onArchiveItem: (itemId: string) => void
}

export function ItemDetailPanel({
  selectedItem,
  selectedSuite,
  statusBadgeVariant,
  onReviewItem,
  onApproveItem,
  onOpenWhyMissed,
  onArchiveItem,
}: Readonly<ItemDetailPanelProps>) {
  return <Panel variant="seamless" padding="none" className="border-0 bg-transparent">
      {selectedItem ? (
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground text-pretty">{selectedItem.query}</div>
              <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-xs text-muted-foreground">
                <Badge variant={statusBadgeVariant(selectedItem.status)} className="uppercase">
                  {selectedItem.status}
                </Badge>
                {selectedItem.regression_case_id ? (
                  <Badge variant="outline" className="max-w-[220px] truncate">
                    case {String(selectedItem.regression_case_id).slice(0, 8)}
                  </Badge>
                ) : null}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {selectedItem.status === 'draft' ? (
                <Button size="sm" variant="outline" className="gap-2" onClick={() => onReviewItem(String(selectedItem.id))}>
                  <Search className="size-4" aria-hidden="true" />
                  Review
                </Button>
              ) : null}
              {selectedItem.status === 'reviewed' ? (
                <Button size="sm" className="gap-2" onClick={() => onApproveItem(String(selectedItem.id))}>
                  <ShieldCheck className="size-4" aria-hidden="true" />
                  Approve
                </Button>
              ) : null}
              <Button size="sm" variant="outline" className="gap-2" onClick={onOpenWhyMissed}>
                <BarChart3 className="size-4" aria-hidden="true" />
                Why missed?
              </Button>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="sm" variant="destructive" className="gap-2" disabled={selectedItem.status === 'archived'}>
                    <X className="size-4" aria-hidden="true" />
                    归档
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>归档该 Item？</AlertDialogTitle>
                    <AlertDialogDescription className="text-pretty">
                      归档后不会从数据库删除，但默认列表会隐藏。该操作可用于标记“已废弃/不再维护”的证据。
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>取消</AlertDialogCancel>
                    <AlertDialogAction onClick={() => onArchiveItem(String(selectedItem.id))}>归档</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>

          {selectedItem.expected_answer ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">Expected Answer (optional)</div>
              <Panel className="p-3">
                <div className="text-sm text-pretty whitespace-pre-wrap">{selectedItem.expected_answer}</div>
              </Panel>
            </div>
          ) : null}

          {selectedItem.tags?.length ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">Tags</div>
              <div className="flex flex-wrap gap-2">
                {selectedItem.tags.map((tag) => (
                  <Badge key={tag} variant="outline" className="font-mono text-[11px]">
                    {tag}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          {selectedItem.source_metadata && Object.keys(selectedItem.source_metadata).length ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">Source Metadata</div>
              <Panel className="p-3">
                <ScrollArea className="h-[180px] pr-2">
                  <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap break-words">
                    {JSON.stringify(selectedItem.source_metadata, null, 2)}
                  </pre>
                </ScrollArea>
              </Panel>
            </div>
          ) : null}

          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Reference Sources</div>
            <Panel className="p-3">
              <div className="space-y-2">
                {(selectedItem.reference_sources || []).length ? (
                  (selectedItem.reference_sources || []).map((reference) => (
                    <div key={`${String(reference.document_id)}:${String(reference.chunk_id)}`} className="rounded-md border border-border/60 p-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-xs font-mono text-foreground">
                            {String(reference.document_id).slice(0, 8)}:{String(reference.chunk_id).slice(0, 8)}
                          </div>
                          {reference.label ? (
                            <div className="mt-1 line-clamp-1 text-xs text-muted-foreground text-pretty">{reference.label}</div>
                          ) : null}
                        </div>
                        <div className="flex-shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                          {typeof reference.page_number === 'number' ? `P.${reference.page_number}` : null}
                          {typeof reference.chunk_index === 'number' ? ` · #${reference.chunk_index}` : null}
                        </div>
                      </div>
                      {reference.quote ? (
                        <div className="mt-2 line-clamp-3 text-xs text-muted-foreground text-pretty">{reference.quote}</div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground text-pretty">暂无 reference_sources。</div>
                )}
              </div>
            </Panel>
          </div>

          {selectedItem.notes ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">Notes</div>
              <Panel className="p-3">
                <div className="text-sm text-pretty whitespace-pre-wrap">{selectedItem.notes}</div>
              </Panel>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground text-pretty">
          选择一个 Item 查看详情。你可以在 draft 状态下修改内容，然后提交 review → approve → sync。
        </div>
      )}
  </Panel>
}
