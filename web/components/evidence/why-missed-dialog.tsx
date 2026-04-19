'use client'

import { Download, Loader2, RefreshCw, Search } from 'lucide-react'

import type { Citation, EvidenceItem } from '@/types'
import type { WhyMissedReport } from '@/lib/evidence-why-missed'
import { coerceOneOf } from '@/lib/one-of'
import { cn } from '@/lib/utils'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const RETRIEVAL_PROFILE_VALUES = ['recall50', 'coverage80', 'recall20'] as const

type RetrievalProfile = (typeof RETRIEVAL_PROFILE_VALUES)[number]

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
  whyMissedCitations: Citation[]
  whyMissedRefDocIds: Set<string>
  whyMissedRefChunkIds: Set<string>
  onOpenChange: (open: boolean) => void
  onWhyMissedProfileChange: (value: RetrievalProfile) => void
  onRunRetrieve: () => void
  onLoadDrift: () => void
  onExportReport: () => void
}

function statusLabel(reportRow: WhyMissedReport['references'][number]): string {
  if (reportRow.status === 'retrieved') return `hit #${reportRow.retrieval?.rank ?? '?'}`
  if (reportRow.status === 'drifted') return `drift:${String(reportRow.drift?.reason || 'unknown')}`
  if (reportRow.status === 'missing') return 'missed'
  return 'unknown'
}

function statusVariant(
  status: WhyMissedReport['references'][number]['status'],
): 'outline' | 'secondary' | 'soft' | 'destructive' {
  if (status === 'retrieved') return 'soft'
  if (status === 'missing') return 'destructive'
  if (status === 'drifted') return 'secondary'
  return 'outline'
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
  onWhyMissedProfileChange,
  onRunRetrieve,
  onLoadDrift,
  onExportReport,
}: Readonly<WhyMissedDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>Why missed?</DialogTitle>
          <DialogDescription className="text-pretty">
            对比 <span className="font-mono">reference_sources</span>（Ground Truth）与“当前检索结果”，并附带 Drift Audit（引用指针是否已漂移）。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-end">
            <div className="w-full md:w-[220px]">
              <div className="mb-1 text-xs text-muted-foreground">Retrieval Profile</div>
              <Select
                value={whyMissedProfile}
                onValueChange={(value) => onWhyMissedProfileChange(coerceOneOf(RETRIEVAL_PROFILE_VALUES, value, 'recall50'))}
              >
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="选择 profile" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="recall50">recall50 (默认)</SelectItem>
                  <SelectItem value="coverage80">coverage80</SelectItem>
                  <SelectItem value="recall20">recall20</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <Button className="gap-2" onClick={onRunRetrieve} disabled={whyMissedRetrieving || !datasetId || !selectedItem?.query}>
              {whyMissedRetrieving ? (
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <Search className="size-4" aria-hidden="true" />
              )}
              运行检索
            </Button>

            <Button
              variant="outline"
              className="gap-2"
              onClick={onLoadDrift}
              disabled={whyMissedDriftLoading || !selectedSuiteId || !selectedItem?.id}
              title="Load drift audit details for this suite and filter to the selected item"
            >
              {whyMissedDriftLoading ? (
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <RefreshCw className="size-4" aria-hidden="true" />
              )}
              Drift Audit
            </Button>

            <Button
              variant="outline"
              className="gap-2"
              onClick={onExportReport}
              disabled={!whyMissedReport}
              title="Export a JSON report (PII-minimized except for query text)."
            >
              <Download className="size-4" aria-hidden="true" />
              导出 JSON
            </Button>

            <div className="ml-auto text-xs text-muted-foreground font-mono tabular-nums">
              {selectedItem?.id ? `item ${String(selectedItem.id).slice(0, 8)}` : null}
              {whyMissedRanRetrieve ? ` · citations ${whyMissedCitations.length}` : null}
            </div>
          </div>

          {whyMissedError ? <div className="text-xs text-destructive text-pretty">{whyMissedError}</div> : null}
          {whyMissedDriftError ? <div className="text-xs text-destructive text-pretty">{whyMissedDriftError}</div> : null}

          {whyMissedReport ? (
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
            </div>
          ) : (
            <div className="text-xs text-muted-foreground text-pretty">先运行检索，再查看 “missed / drifted / retrieved” 解释。</div>
          )}

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Panel className="p-3">
              <div className="mb-2 text-xs font-medium text-muted-foreground">Ground Truth（reference_sources）</div>
              <ScrollArea className="h-[420px] pr-2">
                <div className="space-y-2">
                  {selectedItem ? (
                    whyMissedReport ? (
                      whyMissedReport.references.map((reference) => (
                        <div key={reference.chunk_id} className="rounded-lg border border-border/60 p-2">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant={statusVariant(reference.status)} className="font-mono text-[11px]">
                                  {statusLabel(reference)}
                                </Badge>
                                <div className="truncate text-xs font-mono text-foreground">
                                  {String(reference.document_id || '').slice(0, 8)}:{String(reference.chunk_id || '').slice(0, 8)}
                                </div>
                              </div>
                              {reference.label ? (
                                <div className="mt-1 line-clamp-1 text-xs text-muted-foreground text-pretty">{reference.label}</div>
                              ) : null}
                              {reference.retrieval ? (
                                <div className="mt-1 text-[11px] text-muted-foreground font-mono tabular-nums">
                                  {reference.retrieval.hit_type ? `${reference.retrieval.hit_type}` : 'hit'} · rank {reference.retrieval.rank}
                                  {typeof reference.retrieval.score === 'number' ? ` · score ${reference.retrieval.score.toFixed(4)}` : null}
                                </div>
                              ) : null}
                              {reference.hints?.document_hit_rank || reference.hints?.chunk_index_hit_rank ? (
                                <div className="mt-2 flex flex-wrap gap-1">
                                  {reference.hints?.document_hit_rank ? (
                                    <Badge variant="outline" className="font-mono text-[11px]">
                                      doc@{reference.hints.document_hit_rank}
                                    </Badge>
                                  ) : null}
                                  {reference.hints?.chunk_index_hit_rank ? (
                                    <Badge variant="outline" className="font-mono text-[11px]">
                                      idx@{reference.hints.chunk_index_hit_rank}
                                    </Badge>
                                  ) : null}
                                </div>
                              ) : null}
                            </div>
                            {typeof reference.chunk_index === 'number' ? (
                              <div className="flex-shrink-0 text-[11px] text-muted-foreground font-mono tabular-nums">#{reference.chunk_index}</div>
                            ) : null}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-sm text-muted-foreground text-pretty">运行检索后展示对照结果。</div>
                    )
                  ) : (
                    <div className="text-sm text-muted-foreground text-pretty">未选择 Item。</div>
                  )}
                </div>
              </ScrollArea>
            </Panel>

            <Panel className="p-3">
              <div className="mb-2 text-xs font-medium text-muted-foreground">Retrieved Citations（当前检索结果）</div>
              <ScrollArea className="h-[420px] pr-2">
                <div className="space-y-2">
                  {whyMissedRanRetrieve ? (
                    whyMissedCitations.length ? (
                      whyMissedCitations.slice(0, 80).map((citation, index) => {
                        const docId = String(citation.document_id || '').trim()
                        const chunkId = String(citation.chunk_id || '').trim()
                        const isRefDoc = !!docId && whyMissedRefDocIds.has(docId)
                        const isRefChunk = !!chunkId && whyMissedRefChunkIds.has(chunkId)
                        const score =
                          citation.retrieval_score ??
                          citation.rerank_score ??
                          citation.relevance_score ??
                          citation.vector_score ??
                          citation.bm25_score
                        return (
                          <div
                            key={chunkId || `${docId}:${index}`}
                            className={cn(
                              'rounded-lg border p-2',
                              isRefChunk ? 'border-primary/50 bg-primary/5' : isRefDoc ? 'border-border/60 bg-muted/20' : 'border-border/60',
                            )}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="truncate text-xs font-mono text-foreground">
                                    #{index + 1} {citation.document_name || docId.slice(0, 8)}
                                  </div>
                                  {isRefChunk ? (
                                    <Badge variant="soft" className="font-mono text-[11px]">
                                      ref_chunk
                                    </Badge>
                                  ) : null}
                                  {isRefDoc && !isRefChunk ? (
                                    <Badge variant="outline" className="font-mono text-[11px]">
                                      ref_doc
                                    </Badge>
                                  ) : null}
                                </div>
                                <div className="mt-1 text-[11px] text-muted-foreground font-mono tabular-nums">
                                  {String(citation.hit_type || 'hit')} · score {Number(score || 0).toFixed(4)}
                                  {typeof citation.page_number === 'number' ? ` · P.${citation.page_number}` : null}
                                  {typeof citation.chunk_index === 'number' ? ` · #${citation.chunk_index}` : null}
                                </div>
                              </div>
                              {chunkId ? (
                                <Badge variant="outline" className="font-mono text-[11px]">
                                  {chunkId.slice(0, 8)}
                                </Badge>
                              ) : null}
                            </div>
                            {citation.chunk_content ? (
                              <div className="mt-2 line-clamp-3 text-xs text-muted-foreground text-pretty">{citation.chunk_content}</div>
                            ) : null}
                          </div>
                        )
                      })
                    ) : (
                      <div className="text-sm text-muted-foreground text-pretty">无 citations。</div>
                    )
                  ) : (
                    <div className="text-sm text-muted-foreground text-pretty">先点击“运行检索”。</div>
                  )}
                </div>
              </ScrollArea>
              {whyMissedRanRetrieve && whyMissedCitations.length > 80 ? (
                <div className="mt-2 text-xs text-muted-foreground font-mono">showing first 80 of {whyMissedCitations.length}</div>
              ) : null}
            </Panel>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
