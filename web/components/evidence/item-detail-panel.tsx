'use client'

import { BarChart3, Search, ShieldCheck, X } from '@/components/icons'
import type { EvidenceItem } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Panel } from '@/components/ui/panel'
import { Link } from '@/i18n/navigation'

const ITEM_STATUS_LABELS = { draft: '草稿', reviewed: '已复核', approved: '已通过', archived: '已归档' }

type ItemDetailPanelProps = {
  selectedItem: EvidenceItem | null
  itemAction: 'review' | 'approve' | 'archive' | null
  statusBadgeVariant: (status: EvidenceItem['status']) => 'outline' | 'secondary' | 'soft' | 'destructive'
  onReviewItem: (itemId: string) => void
  onApproveItem: (itemId: string) => void
  onOpenWhyMissed: () => void
  onArchiveItem: (itemId: string) => Promise<void>
}

export function ItemDetailPanel({
  selectedItem,
  itemAction,
  statusBadgeVariant,
  onReviewItem,
  onApproveItem,
  onOpenWhyMissed,
  onArchiveItem,
}: Readonly<ItemDetailPanelProps>) {
  return (
    <Panel variant="seamless" padding="none" className="border-0 bg-transparent">
      {selectedItem ? (
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium text-foreground text-pretty">{selectedItem.query}</div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant={statusBadgeVariant(selectedItem.status)} className="font-normal">
                  {ITEM_STATUS_LABELS[selectedItem.status]}
                </Badge>
                {selectedItem.regression_case_id ? (
                  <Badge variant="outline" className="max-w-[220px] truncate">
                    回归用例 {selectedItem.regression_case_id.slice(0, 8)}
                  </Badge>
                ) : null}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {selectedItem.status === 'draft' ? (
                <LoadingButton
                  loading={itemAction === 'review'}
                  disabled={itemAction !== null}
                  size="sm"
                  variant="default"
                  className="gap-2"
                  onClick={() => onReviewItem(selectedItem.id)}
                >
                  <Search className="size-4" aria-hidden="true" />
                  标记已复核
                </LoadingButton>
              ) : null}
              {selectedItem.status === 'reviewed' ? (
                <LoadingButton
                  loading={itemAction === 'approve'}
                  disabled={itemAction !== null}
                  size="sm"
                  className="gap-2"
                  onClick={() => onApproveItem(selectedItem.id)}
                >
                  <ShieldCheck className="size-4" aria-hidden="true" />
                  通过复核
                </LoadingButton>
              ) : null}
              <Button size="sm" variant="outline" className="gap-2" onClick={onOpenWhyMissed}>
                <BarChart3 className="size-4" aria-hidden="true" />
                排查漏召
              </Button>
              <ConfirmDialog
                title="归档该条目？"
                description="归档后条目会保留，可通过“已归档”筛选查看。"
                confirmLabel="归档"
                onConfirm={() => onArchiveItem(selectedItem.id)}
              >
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2 text-destructive hover:text-destructive"
                  disabled={selectedItem.status === 'archived' || itemAction !== null}
                >
                  <X className="size-4" aria-hidden="true" />
                  归档
                </Button>
              </ConfirmDialog>
            </div>
          </div>

          {selectedItem.expected_answer ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">参考答案</div>
              <Panel variant="seamless" padding="none" className="border-0 bg-transparent py-2">
                <div className="text-sm text-pretty whitespace-pre-wrap">{selectedItem.expected_answer}</div>
              </Panel>
            </div>
          ) : null}

          {selectedItem.tags?.length ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">标签</div>
              <div className="flex flex-wrap gap-2">
                {selectedItem.tags.map((tag) => (
                  <Badge key={tag} variant="outline" className="text-xs font-normal">
                    {tag}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          <section aria-label="引用来源">
            <h3 className="mb-1 text-xs font-medium text-muted-foreground">引用来源</h3>
            {selectedItem.reference_sources?.length ? (
              selectedItem.reference_sources.map((reference, index) => (
                <article key={index} className="space-y-2 border-b border-border/60 py-3">
                  <div className="flex flex-col items-start justify-between gap-2 sm:flex-row">
                    <h4 className="min-w-0 text-sm font-medium [overflow-wrap:anywhere]">
                      {reference.label || `引用 ${index + 1}（未提供来源名称）`}
                    </h4>
                    <p className="text-xs tabular-nums text-muted-foreground">
                      {typeof reference.page_number === 'number' ? `第 ${reference.page_number} 页` : null}
                      {typeof reference.chunk_index === 'number' ? ` · 切片 ${reference.chunk_index}` : null}
                    </p>
                  </div>
                  {reference.quote ? (
                    <blockquote className="whitespace-pre-wrap break-words text-sm leading-7">
                      {reference.quote}
                    </blockquote>
                  ) : (
                    <p className="text-xs text-muted-foreground">未保存引用原文。</p>
                  )}
                  <Link
                    className="inline-block text-xs underline underline-offset-4"
                    href={`/knowledge/${reference.document_id}/health`}
                  >
                    查看来源文档
                  </Link>
                  <details className="text-xs text-muted-foreground">
                    <summary className="cursor-pointer">文档与切片标识</summary>
                    <p className="mt-2 break-all font-mono leading-6">
                      文档：{reference.document_id}
                      <br />
                      切片：{reference.chunk_id}
                    </p>
                  </details>
                </article>
              ))
            ) : (
              <p className="py-2 text-sm text-muted-foreground">尚未保存引用来源。</p>
            )}
          </section>

          {selectedItem.source_metadata && Object.keys(selectedItem.source_metadata).length ? (
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">原始来源信息（JSON）</summary>
              <pre
                className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words font-mono"
                tabIndex={0}
                aria-label="原始来源信息（JSON）"
              >
                {JSON.stringify(selectedItem.source_metadata, null, 2)}
              </pre>
            </details>
          ) : null}

          {selectedItem.notes ? (
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">复核备注</div>
              <Panel variant="seamless" padding="none" className="border-0 bg-transparent py-2">
                <div className="text-sm text-pretty whitespace-pre-wrap">{selectedItem.notes}</div>
              </Panel>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground text-pretty">
          选择一个条目查看问题、答案与引用，再标记已复核。
        </div>
      )}
    </Panel>
  )
}
