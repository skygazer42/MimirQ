'use client'

import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import { buildEvidenceSlotReason, buildEvidenceSlotTags } from '@/components/ingestion/monitor-utils'
import { anonymizeEvidenceName } from '@/app/knowledge/ingestion/demo-precheck'
import type { SampleDisposition } from '@/app/knowledge/ingestion/types'
import type { DatasetPrecheckFileOut, Document } from '@/types'
import { formatDate, formatFileSize } from '@/lib/utils'

type IngestionDetailSurfaceProps = {
  activeAuditDocument: Document | null
  activeAuditIsDemo: boolean
  activeDetailId: string | null
  selectedEvidenceFile: DatasetPrecheckFileOut | null
  onCloseActiveDetail: () => void
  onCloseEvidenceFile: () => void
  onSampleDisposition: (
    documentId: string,
    disposition: SampleDisposition
  ) => void
}

export function IngestionDetailSurface({
  activeAuditDocument,
  activeAuditIsDemo,
  activeDetailId,
  selectedEvidenceFile,
  onCloseActiveDetail,
  onCloseEvidenceFile,
  onSampleDisposition,
}: Readonly<IngestionDetailSurfaceProps>) {
  if (selectedEvidenceFile) {
    return (
      <Sheet open onOpenChange={(open) => !open && onCloseEvidenceFile()}>
        <SheetContent
          side="right"
          className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
        >
          <SheetHeader className="sr-only">
            <SheetTitle>
              {anonymizeEvidenceName(selectedEvidenceFile.name)}
            </SheetTitle>
            <SheetDescription>
              {selectedEvidenceFile.file_type}
            </SheetDescription>
          </SheetHeader>
          <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-border/60 px-6 py-5">
              <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                入库依据
              </div>
              <div className="mt-1 text-lg font-semibold text-foreground">
                {anonymizeEvidenceName(selectedEvidenceFile.name)}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="font-mono tabular-nums">
                  {selectedEvidenceFile.file_type.toUpperCase()}
                </span>
                <span className="font-mono tabular-nums">
                  {formatFileSize(selectedEvidenceFile.file_size || 0)}
                </span>
                <span className="font-mono tabular-nums">
                  {selectedEvidenceFile.text_characters} chars
                </span>
              </div>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
              <div className="rounded-[1.3rem] border border-border/60 bg-muted/20 p-4">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  处理标签
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {buildEvidenceSlotTags(selectedEvidenceFile).map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full border border-border/60 bg-background/86 px-2.5 py-1 text-[11px] font-medium text-foreground"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>

              <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  为何复杂
                </div>
                <div className="mt-2 text-sm leading-6 text-foreground">
                  {buildEvidenceSlotReason(selectedEvidenceFile)}
                </div>
              </div>

              {selectedEvidenceFile.pdf_pages ? (
                <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    PDF 类型分流依据
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                      总页数：{selectedEvidenceFile.pdf_pages.page_count}
                    </div>
                    <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                      扫描页：{selectedEvidenceFile.pdf_pages.scanned_pages}
                    </div>
                    <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                      文字页：{selectedEvidenceFile.pdf_pages.text_pages}
                    </div>
                    <div className="rounded-[1rem] border border-border/55 bg-muted/20 px-3 py-2.5 text-sm">
                      扫描占比：
                      {Math.round(selectedEvidenceFile.pdf_pages.scan_ratio * 100)}%
                    </div>
                  </div>
                </div>
              ) : null}

              {selectedEvidenceFile.pii_samples?.length ? (
                <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                    敏感信息待审核列表
                  </div>
                  <div className="mt-3 space-y-3">
                    {selectedEvidenceFile.pii_samples
                      .slice(0, 3)
                      .map((item, index) => (
                        <div
                          key={`${item.kind}-${index}`}
                          className="rounded-[1rem] border border-border/55 bg-muted/20 p-3 text-sm"
                        >
                          <div className="font-mono text-xs text-muted-foreground">
                            {item.kind}
                          </div>
                          <div className="mt-1 font-mono text-foreground">
                            {item.masked}
                          </div>
                          <div className="mt-2 rounded-lg border border-border/50 bg-background/80 px-3 py-2 font-mono text-xs text-muted-foreground">
                            {item.context}
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              ) : null}

              <div className="rounded-[1.3rem] border border-border/60 bg-background/80 p-4">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  本地复核
                </div>
                <div className="mt-2 text-sm leading-6 text-muted-foreground">
                  一键打开本地文件仅在本地入库复核模式可用；普通 Web 部署默认禁用。
                </div>
                <Button className="mt-3 rounded-xl" disabled>
                  打开本地文件
                </Button>
              </div>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    )
  }

  if (activeAuditIsDemo && activeAuditDocument) {
    return (
      <Sheet open onOpenChange={(open) => !open && onCloseActiveDetail()}>
        <SheetContent
          side="right"
          className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
        >
          <SheetHeader className="sr-only">
            <SheetTitle>{activeAuditDocument.filename || '入库快照'}</SheetTitle>
            <SheetDescription>{activeAuditDocument.id || ''}</SheetDescription>
          </SheetHeader>
          <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-border/60 px-6 py-5">
              <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                入库快照
              </div>
              <div className="mt-1 text-lg font-semibold text-foreground">
                {activeAuditDocument.filename}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="font-mono tabular-nums">
                  {formatFileSize(activeAuditDocument.file_size || 0)}
                </span>
                <span>
                  {formatDate(
                    activeAuditDocument.updated_at ||
                      activeAuditDocument.created_at
                  )}
                </span>
              </div>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
              <div className="rounded-[1.4rem] border border-border/60 bg-muted/20 p-4">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  Sensitive Data Policy
                </div>
                <div className="mt-2 text-sm leading-6 text-foreground/82">
                  默认仅展示脱敏后的聚合事实与待确认线索，不做主观评分。该快照用于演示侧边抽屉入库依据视图。
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {[
                  ['状态', String(activeAuditDocument.status || '-')],
                  ['阶段', String(activeAuditDocument.current_stage || '-')],
                  ['数据集', String(activeAuditDocument.dataset_id || '-')],
                  [
                    '风险线索',
                    activeAuditDocument.error_message || '无明确错误，建议抽样核查',
                  ],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-[1.2rem] border border-border/60 bg-background/80 p-4"
                  >
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                      {label}
                    </div>
                    <div className="mt-2 text-sm font-medium text-foreground">
                      {value}
                    </div>
                  </div>
                ))}
              </div>
              <div className="rounded-[1.4rem] border border-border/60 bg-background/82 p-4">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  建议动作
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <Button
                    className="rounded-xl"
                    onClick={() =>
                      onSampleDisposition(activeAuditDocument.id, 'approved')
                    }
                  >
                    确认可入库
                  </Button>
                  <Button
                    variant="outline"
                    className="rounded-xl"
                    onClick={() =>
                      onSampleDisposition(activeAuditDocument.id, 'manual')
                    }
                  >
                    需人工处理
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    )
  }

  return (
    <IngestionDetailDialog
      open={Boolean(activeDetailId)}
      onOpenChange={(open) => !open && onCloseActiveDetail()}
      documentId={activeDetailId}
    />
  )
}
