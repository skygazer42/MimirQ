'use client'

import { useEffect, useId, useState } from 'react'
import { Copy, RefreshCw } from '@/components/icons'
import type { HardcaseDiscovery, HardcaseSnapshot } from '@/lib/evidence-hardcases'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingButton } from '@/components/ui/loading-button'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { TagInput } from '@/components/ui/tag-input'
import { WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'

type HardcaseCandidatesDialogProps = {
  open: boolean
  selectedSuiteId: string
  loading: boolean
  error: string | null
  snapshot: HardcaseSnapshot | null
  maxRating: number
  includeExisting: boolean
  maxCandidates: number
  tags: string[]
  convertingFeedbackIds: ReadonlySet<string>
  feedbackErrors: ReadonlyMap<string, string>
  onOpenChange: (open: boolean) => void
  onMaxRatingChange: (value: number) => void
  onIncludeExistingChange: (value: boolean) => void
  onMaxCandidatesChange: (value: number) => void
  onTagsChange: (value: string[]) => void
  onRefresh: () => void
  onCopyText: (label: string, text: string) => void
  onConvertFeedback: (feedbackId: string, questionHash?: string) => void
}

function topRetrievalErrors(counts: Record<string, number>): [string, number][] {
  return Object.entries(counts)
    .filter((entry) => entry[1] > 0)
    .sort((left, right) => {
      const difference = right[1] - left[1]
      return difference === 0 ? left[0].localeCompare(right[0]) : difference
    })
    .slice(0, 4)
}

function HardcaseCandidate({
  candidate,
  selectedSuiteId,
  convertingFeedbackIds,
  feedbackErrors,
  onCopyText,
  conversionFormId,
}: Pick<
  HardcaseCandidatesDialogProps,
  'selectedSuiteId' | 'convertingFeedbackIds' | 'feedbackErrors' | 'onCopyText'
> & {
  candidate: HardcaseDiscovery['candidates'][number]
  conversionFormId: string
}) {
  const errors = topRetrievalErrors(candidate.retrieval_error_kinds)
  const template = candidate.rag_config_template
  return (
    <Panel className="p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-xs text-muted-foreground">问题校验值</h3>
          <div className="mt-0.5 font-mono text-sm break-all">{candidate.question_hash}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant="outline" className="font-mono tabular-nums">
            同组反馈 {candidate.cluster_size}
          </Badge>
          <Button
            variant="outline"
            size="icon"
            className="size-8"
            aria-label="复制问题校验值"
            onClick={() => onCopyText('问题校验值', candidate.question_hash)}
          >
            <Copy className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs font-mono tabular-nums text-muted-foreground">
        {candidate.retrieval_config_hash ? (
          <Badge variant="secondary">检索配置 {candidate.retrieval_config_hash.slice(0, 16)}</Badge>
        ) : null}
        {candidate.citations_count !== undefined && candidate.citations_count !== null ? (
          <Badge variant="outline">引用 {candidate.citations_count}</Badge>
        ) : null}
        {errors.map(([kind, count]) => (
          <Badge key={kind} variant="outline">
            {kind}:{count}
          </Badge>
        ))}
        {errors.length === 0 ? <span>未记录检索错误</span> : null}
        {template?.template_key ? (
          <Badge variant="outline" className="max-w-full break-all whitespace-normal">
            模板 {template.template_key}
          </Badge>
        ) : null}
        {template?.version !== undefined && template.version !== null ? (
          <Badge variant="outline">版本 {template.version}</Badge>
        ) : null}
        {template?.patch_hash ? <Badge variant="outline">配置补丁 {template.patch_hash.slice(0, 10)}</Badge> : null}
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <h4 className="mb-1 text-xs text-muted-foreground">反馈标识（样本）</h4>
          <div className="flex flex-wrap gap-2">
            {candidate.feedback_ids.length === 0 ? (
              <span className={ws.muted}>未提供反馈标识。</span>
            ) : (
              candidate.feedback_ids.slice(0, 8).map((feedbackId) => {
                const conversionError = feedbackErrors.get(feedbackId)
                return (
                  <div key={feedbackId} className="min-w-0 max-w-full space-y-1">
                    <div className="inline-flex items-center gap-1.5">
                      <Badge variant="outline" className="font-mono text-xs">
                        {feedbackId.slice(0, 8)}
                      </Badge>
                      <Button
                        variant="outline"
                        size="icon"
                        className="size-7"
                        aria-label="复制反馈标识"
                        onClick={() => onCopyText('反馈标识', feedbackId)}
                      >
                        <Copy className="size-3.5" aria-hidden="true" />
                      </Button>
                      <LoadingButton
                        loading={convertingFeedbackIds.has(feedbackId)}
                        size="sm"
                        className="h-7 px-2 text-xs"
                        type="submit"
                        form={conversionFormId}
                        name={candidate.question_hash}
                        value={feedbackId}
                        disabled={!selectedSuiteId}
                      >
                        转为草稿
                      </LoadingButton>
                    </div>
                    {conversionError !== undefined ? (
                      <p role="alert" className="break-words text-sm text-destructive">
                        {conversionError}
                      </p>
                    ) : null}
                  </div>
                )
              })
            )}
          </div>
        </div>
        <div>
          <h4 className="mb-1 text-xs text-muted-foreground">请求标识（样本）</h4>
          <div className="flex flex-wrap gap-2">
            {candidate.request_ids.length === 0 ? (
              <span className={ws.muted}>未提供请求标识。</span>
            ) : (
              candidate.request_ids.slice(0, 6).map((requestId) => (
                <div key={requestId} className="inline-flex items-center gap-1.5">
                  <Badge variant="secondary" className="font-mono text-xs">
                    {requestId.slice(0, 10)}
                  </Badge>
                  <Button
                    variant="outline"
                    size="icon"
                    className="size-7"
                    aria-label="复制请求标识"
                    onClick={() => onCopyText('请求标识', requestId)}
                  >
                    <Copy className="size-3.5" aria-hidden="true" />
                  </Button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </Panel>
  )
}

export function HardcaseCandidatesDialog({
  open,
  selectedSuiteId,
  loading,
  error,
  snapshot,
  maxRating,
  includeExisting,
  maxCandidates,
  tags,
  convertingFeedbackIds,
  feedbackErrors,
  onOpenChange,
  onMaxRatingChange,
  onIncludeExistingChange,
  onMaxCandidatesChange,
  onTagsChange,
  onRefresh,
  onCopyText,
  onConvertFeedback,
}: Readonly<HardcaseCandidatesDialogProps>) {
  const conversionFormId = useId()
  const [candidateLimit, setCandidateLimit] = useState(String(maxCandidates))
  useEffect(() => {
    setCandidateLimit(String(maxCandidates))
  }, [maxCandidates, open])
  const limit = Number(candidateLimit)
  const limitError =
    candidateLimit.trim().length === 0 || !Number.isInteger(limit) || limit < 0 || limit > 200
      ? '请输入 0 到 200 的整数。'
      : null
  const discovery = snapshot?.data

  function refreshCandidates() {
    if (limitError !== null) return
    if (limit !== maxCandidates) onMaxCandidatesChange(limit)
    else onRefresh()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${ws.dialog} ${ws.wideDialog}`}>
        <DialogHeader className={ws.dialogHeader}>
          <DialogTitle>难例候选</DialogTitle>
          <DialogDescription>从低评分反馈中发现候选，选择反馈转为草稿证据条目。</DialogDescription>
        </DialogHeader>
        <div className={ws.dialogBody}>
          <form
            className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault()
              refreshCandidates()
            }}
          >
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-1 text-xs">
                <Label htmlFor="evidence-hardcase-rating">最高评分</Label>
                <Select value={String(maxRating)} onValueChange={(value) => onMaxRatingChange(Number(value))}>
                  <SelectTrigger id="evidence-hardcase-rating" className="h-8 w-24">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">{'<= 1'}</SelectItem>
                    <SelectItem value="2">{'<= 2'}</SelectItem>
                    <SelectItem value="3">{'<= 3'}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                <Checkbox
                  checked={includeExisting}
                  onCheckedChange={(value) => onIncludeExistingChange(value === true)}
                  aria-label="包含已有条目"
                />
                包含已有条目
              </label>
              <div className="space-y-1 text-xs">
                <Label htmlFor="evidence-hardcase-limit">候选数量</Label>
                <Input
                  id="evidence-hardcase-limit"
                  type="number"
                  min={0}
                  max={200}
                  step={1}
                  value={candidateLimit}
                  onChange={(event) => setCandidateLimit(event.target.value)}
                  aria-invalid={limitError !== null}
                  aria-describedby={
                    limitError === null
                      ? 'evidence-hardcase-limit-help'
                      : 'evidence-hardcase-limit-error evidence-hardcase-limit-help'
                  }
                  className="h-8 w-24 font-mono tabular-nums"
                />
              </div>
            </div>
            <LoadingButton
              type="submit"
              loading={loading}
              variant="outline"
              size="sm"
              className="sm:ml-auto"
              disabled={!selectedSuiteId || limitError !== null}
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              刷新候选
            </LoadingButton>
          </form>
          <p id="evidence-hardcase-limit-help" className="mb-3 text-xs text-muted-foreground">
            候选数量修改后点击“刷新候选”或按 Enter 应用。
          </p>
          {limitError !== null ? (
            <p id="evidence-hardcase-limit-error" role="alert" className="mb-3 text-sm text-destructive">
              {limitError}
            </p>
          ) : null}
          <form
            id={conversionFormId}
            className="mb-4 space-y-1"
            onSubmit={(event) => {
              event.preventDefault()
              const submitter = (event.nativeEvent as SubmitEvent).submitter
              if (!(submitter instanceof HTMLButtonElement)) return
              const feedbackId = submitter.value
              const questionHash = submitter.name
              onConvertFeedback(feedbackId, questionHash)
            }}
          >
            <Label htmlFor="evidence-hardcase-tags">导入标签</Label>
            <TagInput
              inputId="evidence-hardcase-tags"
              value={tags}
              onValueChange={onTagsChange}
              placeholder="回车添加标签…"
            />
          </form>
          {error !== null ? (
            <WorkspaceNotice retry={limitError === null ? refreshCandidates : undefined} pending={loading}>
              {error}
            </WorkspaceNotice>
          ) : null}
          {snapshot !== null ? (
            <div className="mb-3 space-y-1 text-xs text-muted-foreground">
              <p>
                当前结果：评分 ≤ {snapshot.maxRating} · {snapshot.includeExisting ? '包含已有条目' : '排除已有条目'} ·
                最多 {snapshot.maxCandidates} 条
              </p>
              <p className="font-mono tabular-nums">
                scanned {snapshot.data.feedback_scanned} · candidates {snapshot.data.candidates.length}
              </p>
              {snapshot.data.truncated ? <p className={ws.warning}>本次仅扫描了部分检索记录。</p> : null}
            </div>
          ) : null}
          <div className="space-y-3" aria-busy={loading}>
            {loading && snapshot === null ? (
              <Skeleton className="h-32 w-full" role="status" aria-label="正在读取候选" />
            ) : null}
            {discovery === undefined ? (
              !loading && error === null ? (
                <p className={ws.muted}>点击 refresh 加载候选。</p>
              ) : null
            ) : !discovery.enabled ? (
              <p className={ws.muted}>当前未启用检索记录，无法从历史反馈发现难例。</p>
            ) : discovery.candidates.length === 0 ? (
              <p className={ws.muted}>
                {snapshot?.maxCandidates === 0
                  ? '本次候选数量设为 0。'
                  : '暂无候选，可调整评分上限、已有条目或候选数量后重试。'}
              </p>
            ) : (
              discovery.candidates.map((candidate) => (
                <HardcaseCandidate
                  key={candidate.question_hash}
                  candidate={candidate}
                  selectedSuiteId={selectedSuiteId}
                  convertingFeedbackIds={convertingFeedbackIds}
                  feedbackErrors={feedbackErrors}
                  onCopyText={onCopyText}
                  conversionFormId={conversionFormId}
                />
              ))
            )}
            {discovery !== undefined ? (
              <div className="space-y-1 text-xs font-mono tabular-nums text-muted-foreground">
                <p>generated {discovery.generated_at}</p>
                <p>
                  window {discovery.window_minutes}m · max_bytes {discovery.max_bytes} · trace_index{' '}
                  {discovery.trace_index_size}
                </p>
              </div>
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
