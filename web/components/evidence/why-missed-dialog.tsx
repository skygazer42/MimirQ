'use client'

import { z } from 'zod'
import { Download, RefreshCw, Search } from '@/components/icons'
import type { EvidenceItem } from '@/types'
import { formatEvidenceScore, type EvidenceCitation } from '@/lib/evidence-citations'
import type { WhyMissedReport } from '@/lib/evidence-why-missed'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { LoadingButton } from '@/components/ui/loading-button'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { RETRIEVAL_PROFILE_VALUES, type RetrievalProfile } from './evidence-suite-workbench-utils'

const retrievalProfileSchema = z.enum(RETRIEVAL_PROFILE_VALUES)
const REFERENCE_STATUS_LABELS = {
  retrieved: '已召回',
  missing: '未召回',
  drifted: '引用已变化',
  unknown: '待确认',
} as const
const REFERENCE_STATUS_VARIANTS = {
  retrieved: 'soft',
  missing: 'destructive',
  drifted: 'secondary',
  unknown: 'outline',
} as const

type WhyMissedDialogProps = {
  open: boolean
  datasetId: string | null
  selectedSuiteId: string
  selectedItem: EvidenceItem | null
  whyMissedProfile: RetrievalProfile
  whyMissedRetrieving: boolean
  whyMissedDriftLoading: boolean
  whyMissedReport: WhyMissedReport | null
  whyMissedError: string | null
  whyMissedDriftError: string | null
  whyMissedRanRetrieve: boolean
  whyMissedCitations: readonly EvidenceCitation[]
  whyMissedRefDocIds: ReadonlySet<string>
  whyMissedRefChunkIds: ReadonlySet<string>
  onOpenChange: (open: boolean) => void
  onCloseAutoFocus: (event: Event) => void
  onWhyMissedProfileChange: (value: RetrievalProfile) => void
  onRunRetrieve: () => void
  onLoadDrift: () => void
  onExportReport: () => void
}

function ReferenceDiagnostic({ reference }: { reference: WhyMissedReport['references'][number] }) {
  return (
    <article className="rounded-lg border border-border/60 p-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={REFERENCE_STATUS_VARIANTS[reference.status]} className="font-mono text-xs">
              {REFERENCE_STATUS_LABELS[reference.status]}
            </Badge>
            <h4 className="truncate text-xs font-mono text-foreground">
              {reference.document_id.slice(0, 8)}:{reference.chunk_id.slice(0, 8)}
            </h4>
          </div>
          {reference.label ? (
            <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{reference.label}</p>
          ) : null}
          {reference.drift !== undefined ? (
            <p className="mt-1 break-words text-xs text-muted-foreground">{reference.drift.reason}</p>
          ) : null}
          {reference.retrieval !== undefined ? (
            <p className="mt-1 text-xs text-muted-foreground font-mono tabular-nums">
              {reference.retrieval.hit_type} · rank {reference.retrieval.rank} · score{' '}
              {typeof reference.retrieval.score === 'number' ? reference.retrieval.score.toFixed(4) : '未提供'}
            </p>
          ) : null}
          {reference.hints?.document_hit_rank !== undefined || reference.hints?.chunk_index_hit_rank !== undefined ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {reference.hints.document_hit_rank !== undefined ? (
                <Badge variant="outline" className="font-mono text-xs">
                  doc@{reference.hints.document_hit_rank}
                </Badge>
              ) : null}
              {reference.hints.chunk_index_hit_rank !== undefined ? (
                <Badge variant="outline" className="font-mono text-xs">
                  idx@{reference.hints.chunk_index_hit_rank}
                </Badge>
              ) : null}
            </div>
          ) : null}
        </div>
        {reference.chunk_index !== undefined && reference.chunk_index !== null ? (
          <span className="shrink-0 text-xs text-muted-foreground font-mono tabular-nums">
            #{reference.chunk_index}
          </span>
        ) : null}
      </div>
    </article>
  )
}

function RetrievedCitation({
  citation,
  rank,
  isReferenceDocument,
  isReferenceChunk,
}: {
  citation: EvidenceCitation
  rank: number
  isReferenceDocument: boolean
  isReferenceChunk: boolean
}) {
  return (
    <article
      className={cn(
        'rounded-lg border p-2',
        isReferenceChunk
          ? 'border-primary/50 bg-primary/5'
          : isReferenceDocument
            ? 'border-border/60 bg-muted/20'
            : 'border-border/60',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="truncate text-xs font-mono text-foreground">
              #{rank} {citation.document_name ?? citation.document_id?.slice(0, 8) ?? '未提供文档名称'}
            </h4>
            {isReferenceChunk ? (
              <Badge variant="soft" className="font-mono text-xs">
                ref_chunk
              </Badge>
            ) : null}
            {isReferenceDocument && !isReferenceChunk ? (
              <Badge variant="outline" className="font-mono text-xs">
                ref_doc
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-muted-foreground font-mono tabular-nums">
            {citation.hit_type} · score {formatEvidenceScore(citation)}
            {citation.page_number !== undefined && citation.page_number !== null
              ? ` · P.${citation.page_number}`
              : null}
            {citation.chunk_index !== undefined && citation.chunk_index !== null ? ` · #${citation.chunk_index}` : null}
          </p>
        </div>
        {citation.chunk_id ? (
          <Badge variant="outline" className="font-mono text-xs">
            {citation.chunk_id.slice(0, 8)}
          </Badge>
        ) : null}
      </div>
      <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-xs text-muted-foreground">
        {citation.chunk_content === undefined || citation.chunk_content === null
          ? '未返回正文'
          : citation.chunk_content.length === 0
            ? '原文为空'
            : citation.chunk_content}
      </p>
    </article>
  )
}

export function WhyMissedDialog({
  open,
  datasetId,
  selectedSuiteId,
  selectedItem,
  whyMissedProfile,
  whyMissedRetrieving,
  whyMissedDriftLoading,
  whyMissedReport,
  whyMissedError,
  whyMissedDriftError,
  whyMissedRanRetrieve,
  whyMissedCitations,
  whyMissedRefDocIds,
  whyMissedRefChunkIds,
  onOpenChange,
  onCloseAutoFocus,
  onWhyMissedProfileChange,
  onRunRetrieve,
  onLoadDrift,
  onExportReport,
}: Readonly<WhyMissedDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${ws.dialog} ${ws.wideDialog}`} onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader className={ws.dialogHeader}>
          <DialogTitle>Why missed?</DialogTitle>
          <DialogDescription>对比标准引用与当前检索结果；漂移审计覆盖不足的引用标为待确认。</DialogDescription>
        </DialogHeader>
        <div className={ws.dialogBody}>
          <div className="space-y-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-end">
              <div className="w-full md:w-[220px]">
                <label htmlFor="evidence-why-profile" className="mb-1 block text-xs text-muted-foreground">
                  Retrieval Profile
                </label>
                <Select
                  value={whyMissedProfile}
                  onValueChange={(value) => onWhyMissedProfileChange(retrievalProfileSchema.parse(value))}
                >
                  <SelectTrigger id="evidence-why-profile" className="h-9">
                    <SelectValue placeholder="选择 profile" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="recall50">recall50 (默认)</SelectItem>
                    <SelectItem value="coverage80">coverage80</SelectItem>
                    <SelectItem value="recall20">recall20</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <LoadingButton
                loading={whyMissedRetrieving}
                onClick={onRunRetrieve}
                disabled={!datasetId || !selectedItem?.query}
              >
                <Search className="size-4" aria-hidden="true" />
                运行检索
              </LoadingButton>
              <LoadingButton
                loading={whyMissedDriftLoading}
                variant="outline"
                onClick={onLoadDrift}
                disabled={!selectedSuiteId || selectedItem === null}
              >
                <RefreshCw className="size-4" aria-hidden="true" />
                Drift Audit
              </LoadingButton>
              <Button variant="outline" onClick={onExportReport} disabled={whyMissedReport === null}>
                <Download className="size-4" aria-hidden="true" />
                导出 JSON
              </Button>
              <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">
                {selectedItem === null ? null : `item ${selectedItem.id.slice(0, 8)}`}
                {whyMissedRanRetrieve ? ` · citations ${whyMissedCitations.length}` : null}
              </div>
            </div>
            {whyMissedError !== null ? (
              <p role="alert" className="text-sm text-destructive break-words">
                {whyMissedError}
              </p>
            ) : null}
            {whyMissedDriftError !== null ? (
              <p role="alert" className="text-sm text-destructive break-words">
                {whyMissedDriftError}
              </p>
            ) : null}
            {whyMissedReport === null ? (
              <p className={ws.muted}>先运行检索，再查看引用对照。</p>
            ) : (
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="outline" className="font-mono tabular-nums">
                  refs {whyMissedReport.summary.total_references}
                </Badge>
                <Badge variant="soft" className="font-mono tabular-nums">
                  retrieved {whyMissedReport.summary.retrieved_references}
                </Badge>
                <Badge variant="destructive" className="font-mono tabular-nums">
                  missed {whyMissedReport.summary.missing_references}
                </Badge>
                <Badge variant="secondary" className="font-mono tabular-nums">
                  drifted {whyMissedReport.summary.drifted_references}
                </Badge>
                {whyMissedReport.summary.unknown_references > 0 ? (
                  <Badge variant="outline" className="font-mono tabular-nums">
                    待确认 {whyMissedReport.summary.unknown_references}
                  </Badge>
                ) : null}
              </div>
            )}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <Panel className="p-3">
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">Ground Truth（reference_sources）</h3>
                <ScrollArea className="h-[420px] pr-2">
                  <div className="space-y-2" aria-busy={whyMissedDriftLoading}>
                    {selectedItem === null ? (
                      <p className={ws.muted}>未选择条目。</p>
                    ) : whyMissedReport === null ? (
                      <p className={ws.muted}>运行检索后展示对照结果。</p>
                    ) : (
                      whyMissedReport.references.map((reference) => (
                        <ReferenceDiagnostic key={reference.sourceIndex} reference={reference} />
                      ))
                    )}
                  </div>
                </ScrollArea>
              </Panel>
              <Panel className="p-3">
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">Retrieved Citations（当前检索结果）</h3>
                <ScrollArea className="h-[420px] pr-2">
                  <div className="space-y-2" aria-busy={whyMissedRetrieving}>
                    {whyMissedRetrieving && !whyMissedRanRetrieve ? (
                      <Skeleton className="h-24 w-full" role="status" aria-label="正在检索引用" />
                    ) : !whyMissedRanRetrieve ? (
                      <p className={ws.muted}>先点击“运行检索”。</p>
                    ) : whyMissedCitations.length === 0 ? (
                      <p className={ws.muted}>本次未返回引用。</p>
                    ) : (
                      whyMissedCitations
                        .slice(0, 80)
                        .map((citation, index) => (
                          <RetrievedCitation
                            key={index}
                            citation={citation}
                            rank={index + 1}
                            isReferenceDocument={
                              typeof citation.document_id === 'string' && whyMissedRefDocIds.has(citation.document_id)
                            }
                            isReferenceChunk={
                              typeof citation.chunk_id === 'string' && whyMissedRefChunkIds.has(citation.chunk_id)
                            }
                          />
                        ))
                    )}
                  </div>
                </ScrollArea>
                {whyMissedRanRetrieve && whyMissedCitations.length > 80 ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    展示前 80 条，共 {whyMissedCitations.length} 条；导出包含全部结果。
                  </p>
                ) : null}
              </Panel>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
