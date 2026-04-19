'use client'

import type { ReactNode } from 'react'
import { Copy, Loader2, RefreshCw } from 'lucide-react'

import type { EvidenceHardcaseDiscovery } from '@/types'
import { cn } from '@/lib/utils'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TagInput } from '@/components/ui/tag-input'

type HardcaseCandidatesDialogProps = {
  open: boolean
  selectedSuiteId: string
  loading: boolean
  error: string | null
  hardcaseRes: EvidenceHardcaseDiscovery | null
  maxRating: number
  includeExisting: boolean
  maxCandidates: number
  tags: string[]
  convertingFeedbackId: string
  onOpenChange: (open: boolean) => void
  onMaxRatingChange: (value: number) => void
  onIncludeExistingChange: (value: boolean) => void
  onMaxCandidatesChange: (value: number) => void
  onTagsChange: (value: string[]) => void
  onRefresh: () => void
  onCopyText: (label: string, text: string) => void
  onConvertFeedback: (feedbackId: string, questionHash?: string) => void
}

type ErrBadgeEntry = [string, number]

function compareErrBadgeEntry(a: ErrBadgeEntry, b: ErrBadgeEntry): number {
  return Number(b[1]) - Number(a[1]) || String(a[0]).localeCompare(String(b[0]))
}

function buildErrBadges(errKinds: Record<string, number>): ErrBadgeEntry[] {
  const entries: ErrBadgeEntry[] = []
  for (const [keyRaw, valueRaw] of Object.entries(errKinds || {})) {
    const key = String(keyRaw || '').trim()
    const value = Number(valueRaw) || 0
    if (!key || value <= 0) continue
    entries.push([key, value])
  }
  entries.sort(compareErrBadgeEntry)
  return entries.slice(0, 4)
}

export function HardcaseCandidatesDialog({
  open,
  selectedSuiteId,
  loading,
  error,
  hardcaseRes,
  maxRating,
  includeExisting,
  maxCandidates,
  tags,
  convertingFeedbackId,
  onOpenChange,
  onMaxRatingChange,
  onIncludeExistingChange,
  onMaxCandidatesChange,
  onTagsChange,
  onRefresh,
  onCopyText,
  onConvertFeedback,
}: Readonly<HardcaseCandidatesDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl overflow-hidden">
        <DialogHeader>
          <DialogTitle>Hardcase Candidates</DialogTitle>
          <DialogDescription className="text-pretty">
            从低分反馈 + rag_trace 聚类得到的候选（PII-safe）。选择一个 <span className="font-mono">feedback_id</span> 转为 draft EvidenceItem。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">max rating</span>
              <Select value={String(maxRating)} onValueChange={(value) => onMaxRatingChange(Number(value) || 2)}>
                <SelectTrigger className="h-8 w-24">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">{'<= 1'}</SelectItem>
                  <SelectItem value="2">{'<= 2'}</SelectItem>
                  <SelectItem value="3">{'<= 3'}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="inline-flex items-center gap-2 select-none text-xs text-muted-foreground">
              <Checkbox
                checked={includeExisting}
                onCheckedChange={(value) => onIncludeExistingChange(Boolean(value))}
                aria-label="Include existing items"
              />
              include existing
            </div>

            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">max candidates</span>
              <Input
                value={String(maxCandidates)}
                onChange={(event) => {
                  const next = Number(event.target.value || 0) || 0
                  onMaxCandidatesChange(Math.max(0, Math.min(200, Math.floor(next))))
                }}
                className="h-8 w-24 font-mono tabular-nums"
                inputMode="numeric"
              />
            </div>
          </div>

          <div className="flex items-center gap-2 sm:ml-auto">
            {hardcaseRes ? (
              <div className="text-xs text-muted-foreground font-mono tabular-nums">
                scanned {hardcaseRes.feedback_scanned} · candidates {hardcaseRes.candidates?.length ?? 0}
                {hardcaseRes.truncated ? ' · truncated' : ''}
              </div>
            ) : null}

            <Button variant="outline" size="sm" className="gap-2" onClick={onRefresh} disabled={!selectedSuiteId || loading}>
              <RefreshCw className={cn('size-4', loading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
              refresh
            </Button>
          </div>
        </div>

        <div className="space-y-1">
          <Label>Convert tags</Label>
          <TagInput value={tags} onValueChange={onTagsChange} placeholder="回车添加 tag…" />
        </div>

        {error ? <div className="text-xs text-destructive text-pretty">{error}</div> : null}

        <ScrollArea className="max-h-[70vh] pr-3">
          {loading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              loading…
            </div>
          ) : hardcaseRes ? (
            <div className="space-y-3 py-1">
              {hardcaseRes.enabled ? (
                (hardcaseRes.candidates || []).length ? (
                  (hardcaseRes.candidates || []).map((candidate) => {
                    const questionHash = String(candidate.question_hash || '').trim()
                    const feedbackIds = Array.isArray(candidate.feedback_ids) ? candidate.feedback_ids : []
                    const requestIds = Array.isArray(candidate.request_ids) ? candidate.request_ids : []
                    const errKinds = (candidate.retrieval_error_kinds || {}) as Record<string, number>
                    const errBadges = buildErrBadges(errKinds)
                    const template = candidate.rag_config_template ?? null
                    const templateKey = template ? String(template.template_key || '').trim() : ''
                    const templateVersion = template && Number.isFinite(Number(template.version)) ? Number(template.version) : null
                    const templatePatch = template ? String(template.patch_hash || '').trim() : ''
                    const templateLabel = templateKey ? `${templateKey}${templateVersion === null ? '' : `@${templateVersion}`}` : ''

                    const errBadgeNodes: ReactNode[] = []
                    for (const [key, value] of errBadges) {
                      errBadgeNodes.push(
                        <Badge key={key} variant="outline" className="font-mono">
                          {key}:{value}
                        </Badge>,
                      )
                    }

                    const feedbackIdNodes: ReactNode[] = []
                    if (feedbackIds.length) {
                      for (const feedbackIdRaw of feedbackIds.slice(0, 8)) {
                        const feedbackId = String(feedbackIdRaw)
                        feedbackIdNodes.push(
                          <div key={feedbackId} className="inline-flex items-center gap-1.5">
                            <Badge variant="outline" className="font-mono text-[11px]">
                              {feedbackId.slice(0, 8)}
                            </Badge>
                            <Button
                              variant="outline"
                              size="icon"
                              className="size-7"
                              aria-label="复制 feedback_id"
                              onClick={() => onCopyText('feedback_id', feedbackId)}
                            >
                              <Copy className="size-3.5" aria-hidden="true" />
                            </Button>
                            <Button
                              size="sm"
                              className="h-7 px-2 text-xs"
                              onClick={() => onConvertFeedback(feedbackId, questionHash)}
                              disabled={!selectedSuiteId || Boolean(convertingFeedbackId)}
                            >
                              {convertingFeedbackId === feedbackId ? (
                                <Loader2 className="mr-1.5 size-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                              ) : null}
                              转为 draft
                            </Button>
                          </div>,
                        )
                      }
                    }

                    const requestIdNodes: ReactNode[] = []
                    if (requestIds.length) {
                      for (const requestIdRaw of requestIds.slice(0, 6)) {
                        const requestId = String(requestIdRaw)
                        requestIdNodes.push(
                          <div key={requestId} className="inline-flex items-center gap-1.5">
                            <Badge variant="secondary" className="font-mono text-[11px]">
                              {requestId.slice(0, 10)}
                            </Badge>
                            <Button
                              variant="outline"
                              size="icon"
                              className="size-7"
                              aria-label="复制 request_id"
                              onClick={() => onCopyText('request_id', requestId)}
                            >
                              <Copy className="size-3.5" aria-hidden="true" />
                            </Button>
                          </div>,
                        )
                      }
                    }

                    return (
                      <Panel key={questionHash || JSON.stringify(candidate)} className="p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-[11px] text-muted-foreground">question_hash</div>
                            <div className="mt-0.5 font-mono text-sm break-all">{questionHash || '(missing)'}</div>
                          </div>
                          <div className="flex flex-shrink-0 items-center gap-2">
                            <Badge variant="outline" className="font-mono tabular-nums">
                              cluster {candidate.cluster_size ?? 0}
                            </Badge>
                            <Button
                              variant="outline"
                              size="icon"
                              className="size-8"
                              aria-label="复制 question_hash"
                              onClick={() => onCopyText('question_hash', questionHash)}
                              disabled={!questionHash}
                            >
                              <Copy className="size-4" aria-hidden="true" />
                            </Button>
                          </div>
                        </div>

                        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground font-mono tabular-nums">
                          {candidate.retrieval_config_hash ? (
                            <Badge variant="secondary" className="font-mono">
                              cfg {String(candidate.retrieval_config_hash).slice(0, 16)}
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="font-mono">
                              cfg -
                            </Badge>
                          )}

                          {typeof candidate.citations_count === 'number' ? (
                            <Badge variant="outline" className="font-mono">
                              cites {candidate.citations_count}
                            </Badge>
                          ) : null}

                          {errBadges.length ? (
                            errBadgeNodes
                          ) : (
                            <Badge variant="outline" className="font-mono">
                              errors 0
                            </Badge>
                          )}

                          {templateLabel ? (
                            <Badge variant="outline" className="font-mono">
                              tmpl {templateLabel}
                            </Badge>
                          ) : null}
                          {templatePatch ? (
                            <Badge variant="outline" className="font-mono">
                              patch {templatePatch.slice(0, 10)}
                            </Badge>
                          ) : null}

                          {hardcaseRes.truncated ? (
                            <Badge variant="destructive" className="font-mono">
                              truncated
                            </Badge>
                          ) : null}
                        </div>

                        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                          <div>
                            <div className="mb-1 text-[11px] text-muted-foreground">feedback_ids (sample)</div>
                            <div className="flex flex-wrap gap-2">
                              {feedbackIds.length ? feedbackIdNodes : <div className="text-xs text-muted-foreground">-</div>}
                            </div>
                          </div>

                          <div>
                            <div className="mb-1 text-[11px] text-muted-foreground">request_ids (sample)</div>
                            <div className="flex flex-wrap gap-2">
                              {requestIds.length ? requestIdNodes : <div className="text-xs text-muted-foreground">-</div>}
                            </div>
                          </div>
                        </div>
                      </Panel>
                    )
                  })
                ) : (
                  <Panel className="p-3">
                    <div className="text-sm font-medium text-foreground">暂无候选</div>
                    <div className="mt-1 text-xs text-muted-foreground text-pretty">
                      你可以尝试提高 <span className="font-mono">max rating</span> 或增大窗口（后端默认 7 天）。
                    </div>
                  </Panel>
                )
              ) : (
                <Panel className="p-3">
                  <div className="text-sm font-medium text-foreground">Metrics log disabled</div>
                  <div className="mt-1 text-xs text-muted-foreground text-pretty">
                    需要开启 <span className="font-mono">ENABLE_METRICS_LOG=true</span> 才能从 traces 中发现 hardcases。
                  </div>
                </Panel>
              )}

              <div className="text-[11px] text-muted-foreground font-mono tabular-nums">
                window {hardcaseRes.window_minutes}m · max_bytes {hardcaseRes.max_bytes} · trace_index {hardcaseRes.trace_index_size}
              </div>
            </div>
          ) : (
            <div className="py-4 text-sm text-muted-foreground">点击 refresh 加载候选。</div>
          )}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
