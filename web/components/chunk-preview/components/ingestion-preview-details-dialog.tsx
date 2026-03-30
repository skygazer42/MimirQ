/**
 * IngestionPreviewDetailsDialog
 *
 * Shows ingestion policy match + preprocess / governance preview details.
 * Used by /chunk-preview to quickly audit "what will happen on ingest" before confirming.
 */
'use client'

import { useMemo } from 'react'
import { Download, FileText, Settings2 } from 'lucide-react'
import { toast } from 'sonner'

import { useRouter } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { isJsonObject } from '@/components/chunk-preview/utils/metadata'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { cn, formatFileSize } from '@/lib/utils'
import type { DocumentPipelineOptions, GovernanceIssue, IngestionPreviewResponse, JsonObject, PreprocessStepLog } from '@/types'

function toShortNote(note: unknown, maxChars: number = 180): string {
  const s = toTrimmedPrimitiveString(note)
  if (!s) return ''
  if (s.length <= maxChars) return s
  return `${s.slice(0, Math.max(0, maxChars - 3))}...`
}

function downloadJsonObject(obj: unknown, filename: string) {
  const safe = String(filename || 'export.json')
    .trim()
    .replaceAll(/[\\/:*?"<>|]+/g, '_')
    .slice(0, 128)
  const blob = new Blob([JSON.stringify(obj ?? {}, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = safe.endsWith('.json') ? safe : `${safe}.json`
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function countTotalHits(entries: Record<string, number> | null | undefined): number {
  if (!entries) return 0
  return Object.values(entries).reduce((acc, value) => acc + (Number(value) || 0), 0)
}

export function IngestionPreviewDetailsDialog({
  open,
  onOpenChange,
  preview,
  datasetId,
  onApplyPipelinePatch,
}: Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  preview: IngestionPreviewResponse | null
  datasetId?: string
  onApplyPipelinePatch?: (patch: DocumentPipelineOptions) => void
}>) {
  const router = useRouter()
  const ruleTitle = useMemo(() => {
    if (!preview) return ''
    if (!preview.rule?.matched) return '未命中策略规则（使用默认配置）'
    return preview.rule?.rule_name || preview.rule?.rule_id || '已命中规则'
  }, [preview])

  const preprocessSummary = useMemo(() => {
    if (!preview?.preprocess) return null
    const p = preview.preprocess
    const sizeBefore = Number(p.size_before || 0)
    const sizeAfter = Number(p.size_after || 0)
    const changed = Boolean(p.changed)
    const warnings = Array.isArray(p.warnings) ? p.warnings.filter(Boolean).map(String) : []
    const steps = Array.isArray(p.steps) ? p.steps : []
    return { changed, sizeBefore, sizeAfter, warnings, steps }
  }, [preview])

  const cleanSummary = useMemo(() => {
    const c = preview?.clean
    if (!c) return null
    const piiHits = c.pii_hits ?? null
    const secretsHits = c.secrets_hits ?? null
    const piiTotal = countTotalHits(piiHits)
    const secretsTotal = countTotalHits(secretsHits)
    return {
      changed: Boolean(c.changed),
      dropped: Boolean(c.dropped),
      dropReason: (c.drop_reason || '').trim() || null,
      appliedRules: Number(c.applied_rules || 0),
      inputChars: Number(c.input_chars || 0),
      outputChars: Number(c.output_chars || 0),
      inputLines: Number(c.input_lines || 0),
      outputLines: Number(c.output_lines || 0),
      added: Number(c.added_lines || 0),
      removed: Number(c.removed_lines || 0),
      changedLines: Number(c.changed_lines || 0),
      urlsChanged: Number(c.urls_changed || 0),
      paragraphsDropped: Number(c.paragraphs_dropped || 0),
      referencesRemovedLines: Number(c.references_removed_lines || 0),
      piiTotal,
      secretsTotal,
      piiHits,
      secretsHits,
      diffTruncated: Boolean(c.diff_truncated),
    }
  }, [preview?.clean])

  const hasPreview = Boolean(preview)
  const issues = useMemo(() => {
    const list = preview?.clean?.issues ?? []
    return Array.isArray(list) ? list : []
  }, [preview?.clean?.issues])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2">
              <Settings2 className="w-5 h-5 text-primary" />
              入库策略预览
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 px-3 text-[11px]"
              onClick={() => {
                const params = new URLSearchParams()
                params.set('from', 'chunk-preview')
                params.set('tab', 'clean')
                const ds = String(datasetId || '').trim()
                if (ds) params.set('dataset_id', ds)
                const ref = String(preview?.rule?.governance_profile_ref || '').trim()
                if (ref) params.set('governance_profile_ref', ref)
                router.push(`/data-governance?${params.toString()}`)
                onOpenChange(false)
              }}
              disabled={!preview}
	            >
	              去数据治理
	            </Button>
	          </DialogTitle>
	          <DialogDescription className="space-y-1">
            <div className="text-xs text-foreground/90">
              {ruleTitle || '—'}
              {preview?.rule?.parser_backend ? (
                <span className="text-muted-foreground"> · parser: {preview.rule.parser_backend}</span>
              ) : null}
              {preview?.rule?.chunk_strategy ? (
                <span className="text-muted-foreground"> · strategy: {preview.rule.chunk_strategy}</span>
              ) : null}
            </div>
            {preview?.rule?.governance_profile_ref ? (
              <div className="text-[11px] text-muted-foreground">
                governance profile: <span className="font-mono">{preview.rule.governance_profile_ref}</span>
              </div>
            ) : null}
            <div className="text-[11px] text-muted-foreground">
              该预览来自 <span className="font-mono">/pipeline/ingestion-preview</span>（不会入库）。
            </div>
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="preprocess" className="w-full">
          <TabsList className="grid w-full grid-cols-5">
            <TabsTrigger value="preprocess" disabled={!hasPreview}>
              Preprocess
            </TabsTrigger>
            <TabsTrigger value="clean" disabled={!hasPreview}>
              Governance
            </TabsTrigger>
            <TabsTrigger value="diff" disabled={!hasPreview}>
              Diff
            </TabsTrigger>
            <TabsTrigger value="issues" disabled={!hasPreview}>
              Issues{issues.length ? ` (${issues.length})` : ''}
            </TabsTrigger>
            <TabsTrigger value="explain" disabled={!hasPreview}>
              Explain
            </TabsTrigger>
          </TabsList>

          <TabsContent value="preprocess" className="mt-4">
            {preprocessSummary ? (
              <div className="space-y-3">
                <div className="rounded-xl border border-border/60 bg-card p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium text-foreground">预处理（Preprocess）</div>
                    <span
                      className={cn(
                        'text-[11px] px-2 py-0.5 rounded-full border',
                        preprocessSummary.changed
                          ? 'bg-warning/10 text-warning border-warning/25'
                          : 'bg-success/10 text-success border-success/25'
                      )}
                    >
                      {preprocessSummary.changed ? 'changed' : 'no change'}
                    </span>
                  </div>
                  <div className="mt-2 text-[11px] text-muted-foreground">
                    size: <span className="font-mono">{formatFileSize(preprocessSummary.sizeBefore)}</span> →{' '}
                    <span className="font-mono">{formatFileSize(preprocessSummary.sizeAfter)}</span>
                  </div>
                  {preprocessSummary.warnings.length ? (
                    <div className="mt-2 text-[11px] text-warning">
                      warnings: <span className="font-mono">{preprocessSummary.warnings.length}</span>
                    </div>
                  ) : null}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl border border-border/60 bg-card p-3">
                    <div className="text-[11px] font-medium text-muted-foreground">步骤（Steps）</div>
                    <ScrollArea className="h-[240px] mt-2 pr-2">
                      {preprocessSummary.steps.length ? (
                        <div className="space-y-1">
                          {preprocessSummary.steps.map((step: PreprocessStepLog, idx: number) => {
                            const id = String(step.id || '').trim() || `step_${idx + 1}`
                            const applied = Boolean(step.applied)
                            const changed = Boolean(step.changed)
                            return (
                            <div key={id} className="rounded-lg border border-border/60 bg-background p-2">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="text-[11px] font-mono text-foreground/90">{id}</div>
                                  <div className="flex items-center gap-1.5">
                                    <span
                                      className={cn(
                                        'text-[10px] px-1.5 py-0.5 rounded border',
                                        applied ? 'bg-success/10 text-success border-success/25' : 'bg-muted text-muted-foreground border-border/60'
                                      )}
                                    >
                                      {applied ? 'applied' : 'skip'}
                                    </span>
                                    <span
                                      className={cn(
                                        'text-[10px] px-1.5 py-0.5 rounded border',
                                        changed ? 'bg-warning/10 text-warning border-warning/25' : 'bg-muted text-muted-foreground border-border/60'
                                      )}
                                    >
                                      {changed ? 'changed' : 'same'}
                                    </span>
                                  </div>
                                </div>
                                {step.note ? (
                                  <div className="mt-1 text-[10px] text-muted-foreground">{toShortNote(step.note)}</div>
                                ) : null}
                              </div>
                            )
                          })}
                        </div>
                      ) : (
                        <div className="text-[11px] text-muted-foreground">无 preprocess steps</div>
                      )}
                    </ScrollArea>
                  </div>

                  <div className="rounded-xl border border-border/60 bg-card p-3">
                    <div className="text-[11px] font-medium text-muted-foreground">Warnings</div>
                    <ScrollArea className="h-[240px] mt-2 pr-2">
                      {preprocessSummary.warnings.length ? (
                        <div className="space-y-1">
                          {preprocessSummary.warnings.map((w) => (
                            <div key={w} className="rounded-lg border border-warning/25 bg-warning/10 px-2 py-1 text-[11px] text-warning">
                              {w}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-[11px] text-muted-foreground">无 warnings</div>
                      )}
                    </ScrollArea>
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">暂无预览数据</div>
            )}
          </TabsContent>

          <TabsContent value="clean" className="mt-4">
            {cleanSummary ? (
              <div className="space-y-3">
                <div className="rounded-xl border border-border/60 bg-card p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-medium text-foreground">治理清洗（Governance）</div>
                    <span
                      className={cn(
                        'text-[11px] px-2 py-0.5 rounded-full border',
                        (() => {
    if (cleanSummary.dropped) {
        return 'bg-destructive/10 text-destructive border-destructive/25';
    }
    else if (cleanSummary.changed) {
            return 'bg-warning/10 text-warning border-warning/25';
        }
        else {
            return 'bg-success/10 text-success border-success/25';
        }
})()
                      )}
                    >
                      {(() => {
    if (cleanSummary.dropped) {
        return 'dropped';
    }
    else if (cleanSummary.changed) {
            return 'changed';
        }
        else {
            return 'no change';
        }
})()}
                    </span>
                  </div>
                  {cleanSummary.dropReason ? (
                    <div className="mt-2 text-[11px] text-destructive">
                      drop_reason: <span className="font-mono">{cleanSummary.dropReason}</span>
                    </div>
                  ) : null}
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                    <div>
                      chars: <span className="font-mono">{cleanSummary.inputChars}</span> →{' '}
                      <span className="font-mono">{cleanSummary.outputChars}</span>
                    </div>
                    <div>
                      lines: <span className="font-mono">{cleanSummary.inputLines}</span> →{' '}
                      <span className="font-mono">{cleanSummary.outputLines}</span>
                    </div>
                    <div>
                      rules: <span className="font-mono">{cleanSummary.appliedRules}</span> · urls:{' '}
                      <span className="font-mono">{cleanSummary.urlsChanged}</span>
                    </div>
                    <div>
                      dropped: <span className="font-mono">{cleanSummary.paragraphsDropped}</span> · refs:{' '}
                      <span className="font-mono">{cleanSummary.referencesRemovedLines}</span>
                    </div>
                    <div>
                      +<span className="font-mono">{cleanSummary.added}</span> -<span className="font-mono">{cleanSummary.removed}</span> ~
                      <span className="font-mono">{cleanSummary.changedLines}</span>
                    </div>
                    <div>
                      diff: <span className="font-mono">{cleanSummary.diffTruncated ? 'truncated' : 'full'}</span>
                    </div>
                  </div>

                  {(cleanSummary.piiTotal > 0 || cleanSummary.secretsTotal > 0) && (
                    <div className="mt-2 rounded-lg border border-warning/25 bg-warning/10 px-2 py-1 text-[11px] text-warning">
                      {cleanSummary.piiTotal > 0 ? (
                        <div>
                          pii_hits: <span className="font-mono">{cleanSummary.piiTotal}</span>
                        </div>
                      ) : null}
                      {cleanSummary.secretsTotal > 0 ? (
                        <div>
                          secrets_hits: <span className="font-mono">{cleanSummary.secretsTotal}</span>
                        </div>
                      ) : null}
                      <div className="text-[10px] text-muted-foreground mt-1">
                        提示：如果你不希望脱敏，关闭对应治理开关；如果你希望强制脱敏，确保启用并设置 mask/token 策略。
                      </div>
                    </div>
                  )}
                </div>

                {preview?.clean?.suggested_pipeline_patch && Object.keys(preview.clean.suggested_pipeline_patch || {}).length ? (
                  <div className="rounded-xl border border-border/60 bg-card p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[11px] font-medium text-muted-foreground">Suggested patch</div>
                      <Button
                        type="button"
                        size="sm"
                        className="h-8 px-3 text-[11px]"
                        onClick={() => {
                          const patch = preview?.clean?.suggested_pipeline_patch || {}
                          if (!onApplyPipelinePatch) {
                            toast.message('未提供 patch 应用函数')
                            return
                          }
                          onApplyPipelinePatch(patch)
                          toast.success('已应用 suggested pipeline patch')
                        }}
                        disabled={!onApplyPipelinePatch}
                      >
                        应用
                      </Button>
                    </div>
                    <pre className="mt-2 max-h-[160px] overflow-auto rounded-lg border border-border/60 bg-background p-2 text-[11px] text-muted-foreground">
                      {JSON.stringify(preview.clean.suggested_pipeline_patch, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">暂无预览数据</div>
            )}
          </TabsContent>

          <TabsContent value="diff" className="mt-4">
            <div className="rounded-xl border border-border/60 bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-primary" />
                  <div className="text-sm font-medium text-foreground">Unified Diff</div>
                </div>
                {preview?.clean?.diff_unified ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 px-3 text-[11px]"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(String(preview?.clean?.diff_unified || ''))
                        toast.success('已复制 diff')
                      } catch {
                        toast.error('复制失败（请检查浏览器权限）')
                      }
                    }}
                  >
                    复制
                  </Button>
                ) : null}
              </div>
              <div className="mt-2 text-[11px] text-muted-foreground">
                {preview?.clean?.diff_unified ? (
                  <span>
                    {preview.clean.diff_truncated ? (
                      <span className="text-warning">diff_truncated=true（仅返回部分 diff）</span>
                    ) : (
                      <span className="text-muted-foreground">diff_truncated=false</span>
                    )}
                  </span>
                ) : (
                  <span>本次未生成 diff（可能 changed=false 或 include_diff=false）</span>
                )}
              </div>
              {preview?.clean?.diff_unified ? (
                <pre className="mt-2 max-h-[420px] overflow-auto rounded-lg border border-border/60 bg-background p-3 text-[11px] font-mono text-foreground/80">
                  {String(preview.clean.diff_unified)}
                </pre>
              ) : null}
            </div>
          </TabsContent>

	          <TabsContent value="issues" className="mt-4">
	            <div className="rounded-xl border border-border/60 bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium text-foreground">治理问题（Issues）</div>
                {preview?.clean?.suggested_pipeline_patch && Object.keys(preview.clean.suggested_pipeline_patch || {}).length ? (
                  <Button
                    type="button"
                    size="sm"
                    className="h-8 px-3 text-[11px]"
                    onClick={() => {
                      const patch = preview?.clean?.suggested_pipeline_patch || {}
                      if (!onApplyPipelinePatch) {
                        toast.message('未提供 patch 应用函数')
                        return
                      }
                      onApplyPipelinePatch(patch)
                      toast.success('已应用 suggested pipeline patch')
                    }}
                    disabled={!onApplyPipelinePatch}
                  >
                    应用全部建议
                  </Button>
                ) : null}
              </div>

              {issues.length ? (
                <ScrollArea className="h-[520px] mt-3 pr-2">
                  <div className="space-y-2">
                    {issues.map((issue: GovernanceIssue, idx: number) => {
                      const code = String(issue.code || '').trim() || `issue_${idx + 1}`
                      const severity = String(issue.severity || 'info')
                      const count = Number(issue.count || 0)
                      const message = String(issue.message || '').trim() || code
                      const samples = Array.isArray(issue.samples) ? issue.samples.filter(Boolean).map(String) : []
                      const patch = issue.suggested_pipeline_patch ?? null
                      const patchKeys = patch ? Object.keys(patch || {}) : []
                      const badgeCls =
                        (() => {
    if (severity === 'error') {
        return 'bg-destructive/10 text-destructive border-destructive/25';
    }
    else if (severity === 'warning') {
            return 'bg-warning/10 text-warning border-warning/25';
        }
        else {
            return 'bg-muted text-muted-foreground border-border/60';
        }
})()
                      return (
                        <div key={`${code}-${message}`} className="rounded-xl border border-border/60 bg-background p-3">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <span className={cn('text-[10px] px-2 py-0.5 rounded-full border font-medium', badgeCls)}>
                                  {severity}
                                </span>
                                <span className="text-[11px] font-mono text-muted-foreground">{code}</span>
                                <span className="text-[11px] text-muted-foreground">
                                  count: <span className="font-mono">{count}</span>
                                </span>
                              </div>
                              <div className="mt-1 text-[12px] text-foreground/90">{message}</div>
                            </div>

                            {patch && patchKeys.length ? (
                              <Button
                                type="button"
                                size="sm"
                                className="h-8 px-3 text-[11px]"
                                onClick={() => {
                                  if (!onApplyPipelinePatch) {
                                    toast.message('未提供 patch 应用函数')
                                    return
                                  }
                                  onApplyPipelinePatch(patch)
                                  toast.success(`已应用建议：${code}`)
                                }}
                                disabled={!onApplyPipelinePatch}
                              >
                                应用建议
                              </Button>
                            ) : null}
                          </div>

                          {samples.length ? (
                            <div className="mt-2">
                              <div className="text-[10px] text-muted-foreground">samples</div>
                              <div className="mt-1 space-y-1">
                                {samples.slice(0, 4).map((s: string) => (
                                  <div
                                    key={s}
                                    className="rounded-lg border border-border/60 bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground"
                                  >
                                    {toShortNote(s, 240)}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}

                          {patch && patchKeys.length ? (
                            <details className="mt-2">
                              <summary className="cursor-pointer select-none text-[11px] text-muted-foreground hover:text-foreground">
                                查看 suggested patch（{patchKeys.length}）
                              </summary>
                              <pre className="mt-2 max-h-[180px] overflow-auto rounded-lg border border-border/60 bg-muted/30 p-2 text-[11px] text-muted-foreground">
                                {JSON.stringify(patch, null, 2)}
                              </pre>
                            </details>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                </ScrollArea>
              ) : (
                <div className="mt-3 text-[12px] text-muted-foreground">暂无 issues（治理侧未发现明显问题）</div>
              )}
	            </div>
	          </TabsContent>

          <TabsContent value="explain" className="mt-4">
            <div className="rounded-xl border border-border/60 bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium text-foreground">Explain（可追溯/可导出）</div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 px-3 text-[11px] gap-2"
                  onClick={() => {
                    const exp = preview?.explain
                    if (!exp) {
                      toast.error('后端未返回 explain 字段')
                      return
                    }
                    const snapshotValue = isJsonObject(exp) && 'snapshot' in exp ? exp.snapshot ?? exp : exp
                    const snapshotRecord = isJsonObject(snapshotValue) ? snapshotValue : null
                    const rawName = String(snapshotRecord?.filename || 'ingestion-preview')
                      .trim()
                      .replaceAll(/[^a-zA-Z0-9_.-]+/g, '_')
                      .slice(0, 64)
                    downloadJsonObject(snapshotValue, `${rawName}.ingestion-preview.explain.json`)
                    toast.success('已导出 explain 快照')
                  }}
                  disabled={!preview?.explain}
                >
                  <Download className="w-4 h-4" />
                  导出 JSON
                </Button>
              </div>

              <div className="mt-2 text-[11px] text-muted-foreground">
                包含：命中规则、最终生效配置、pipeline_patch 与（可选）fallback 线索。建议作为入库前审计快照留存。
              </div>

              <div className="mt-3 rounded-lg border border-border/60 bg-background">
                <div className="px-3 py-2 text-[11px] font-medium text-muted-foreground border-b border-border/60">
                  payload.explain
                </div>
                <ScrollArea className="h-[420px]">
                  <pre className="p-3 text-xs font-mono whitespace-pre-wrap break-words text-foreground/80">
                    {JSON.stringify(preview?.explain ?? null, null, 2)}
                  </pre>
                </ScrollArea>
              </div>
            </div>
          </TabsContent>
	        </Tabs>
	      </DialogContent>
	    </Dialog>
	  )
}
