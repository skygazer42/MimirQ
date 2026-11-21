'use client'

import { Fragment, useId, useMemo, useState } from 'react'
import { skipToken, useQuery } from '@tanstack/react-query'
import { FileDown, SearchCode } from '@/components/icons'

import { Button } from '@/components/ui/button'
import { WorkspaceNotice, WorkspaceTableScroll } from '@/components/ui/operational-workspace'
import { evaluationApi } from '@/lib/api/evaluation'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { downloadBlob } from '@/lib/download'
import { formatRegressionMetric, formatRegressionValue } from '@/lib/regression-result-model'
import { queryKeys } from '@/lib/query-keys'
import { toast } from 'sonner'
import type { RagasRegressionRunDiffResponse, RegressionRunCaseDiff } from '@/types'

function meanCaseScore(metrics: RegressionRunCaseDiff['metric_diffs'], side: 'before' | 'after'): number | null {
  if (metrics.length === 0) return null
  return metrics.reduce((sum, metric) => sum + metric[side], 0) / metrics.length
}

function csvEscape(value: string | number | null): string {
  if (value === null) return '""'
  return `"${String(value).replaceAll('"', '""')}"`
}

export function AblationCaseDrilldown({
  diff,
}: Readonly<{
  diff: RagasRegressionRunDiffResponse | null
}>) {
  const detailsId = useId()
  const [expandedCaseId, setExpandedCaseId] = useState<string>()
  const detailsQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionCaseComparison(diff?.base_run_id, diff?.target_run_id),
    enabled: false,
    retry: false,
    queryFn:
      diff === null
        ? skipToken
        : ({ signal }) =>
            Promise.all([
              evaluationApi.getRegressionRun(
                diff.base_run_id,
                { include_items: true, include_contexts: false },
                { signal },
              ),
              evaluationApi.getRegressionRun(
                diff.target_run_id,
                { include_items: true, include_contexts: false },
                { signal },
              ),
            ]),
  })
  const loading = detailsQuery.isFetching

  const rows = useMemo(() => {
    if (diff === null) return []
    const baseByCase = new Map(detailsQuery.data?.[0].items.map((item) => [item.case_id, item]))
    const targetByCase = new Map(detailsQuery.data?.[1].items.map((item) => [item.case_id, item]))
    return diff.case_diffs.map((item) => ({
      case_id: item.case_id,
      question: item.question,
      base_score: meanCaseScore(item.metric_diffs, 'before'),
      target_score: meanCaseScore(item.metric_diffs, 'after'),
      delta: item.mean_delta,
      label: item.label,
      base_response: baseByCase.get(item.case_id)?.response,
      target_response: targetByCase.get(item.case_id)?.response,
      metric_diffs: item.metric_diffs,
    }))
  }, [diff, detailsQuery.data])
  const pairedCount = diff?.significance_summary.paired_cases
  let missingAnswer = '本次明细未返回该样本。'
  if (detailsQuery.data === undefined) {
    if (loading) {
      missingAnswer = '正在读取回答…'
    } else if (detailsQuery.isError) {
      missingAnswer = '回答读取失败，请重试。'
    } else {
      missingAnswer = '尚未读取回答。'
    }
  }

  function exportCasesCsv() {
    try {
      const headers = ['case_id', 'question', 'base_score', 'target_score', 'delta', 'label'] as const
      const lines = [headers.join(',')]
      for (const row of rows) lines.push(headers.map((key) => csvEscape(row[key])).join(','))
      downloadBlob('ablation-case-drilldown.csv', new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }))
      toast.success('样本比较 CSV 已开始下载')
    } catch (error) {
      reportClientError('Failed to export case comparison', error)
      toast.error(formatApiError(error, '样本比较导出失败'))
    }
  }

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <SearchCode className="size-4 text-destructive" />
            逐样本比较
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            使用本次运行对比返回的配对样本和结论，按需读取完整回答。
          </p>
          {diff !== null ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {pairedCount === undefined
                ? `本次返回 ${rows.length} 个配对样本。`
                : `共 ${pairedCount} 个配对样本，本次返回 ${rows.length} 个。`}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={loading || diff === null || rows.length === 0}
            onClick={() => void detailsQuery.refetch({ cancelRefetch: false })}
            className="rounded-xl"
          >
            {loading ? '正在读取…' : detailsQuery.data === undefined ? '加载回答' : '重新读取回答'}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={rows.length === 0}
            onClick={exportCasesCsv}
            className="gap-2 rounded-xl"
          >
            <FileDown className="size-4" />
            导出 CSV
          </Button>
        </div>
      </div>

      {detailsQuery.error !== null ? (
        <WorkspaceNotice
          retry={() => void detailsQuery.refetch({ cancelRefetch: false })}
          retryLabel="重新读取样本明细"
          pending={loading}
        >
          {detailsQuery.data === undefined ? null : '更新失败，保留上次同一组运行的明细。'}
          {formatApiError(detailsQuery.error, '样本比较明细读取失败')}
        </WorkspaceNotice>
      ) : null}
      {rows.length > 0 ? (
        <div className="mt-3 overflow-hidden rounded-xl border border-border">
          <WorkspaceTableScroll label="配对样本结果及回答">
            <table className="w-full min-w-[640px] text-xs">
              <caption className="sr-only">
                本次运行对比已返回的配对样本、两侧均分、服务端差值和结论；展开样本查看完整回答。
              </caption>
              <thead className="bg-muted/50 text-[11px] text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left">
                    样本与问题
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    基线均分
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    候选均分
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    变化
                  </th>
                  <th scope="col" className="px-3 py-2 text-right">
                    服务端结论
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const expanded = expandedCaseId === row.case_id
                  const rowDetailsId = `${detailsId}-${row.case_id}`
                  return (
                    <Fragment key={row.case_id}>
                      <tr className="border-t border-border/50">
                        <th scope="row" className="px-3 py-2 text-left align-top font-normal">
                          <Button
                            type="button"
                            variant="ghost"
                            className="h-auto max-w-full flex-col items-start whitespace-normal text-left font-normal"
                            aria-expanded={expanded}
                            aria-controls={expanded ? rowDetailsId : undefined}
                            onClick={() => setExpandedCaseId(expanded ? undefined : row.case_id)}
                          >
                            <span
                              className="block max-w-[360px] truncate font-mono text-[11px] text-muted-foreground"
                              title={row.case_id}
                            >
                              {row.case_id}
                            </span>
                            <span className="max-w-[360px] break-words text-foreground">{row.question}</span>
                            <span className="text-[11px] text-muted-foreground">
                              {expanded ? '收起详情' : '展开详情'}
                            </span>
                          </Button>
                        </th>
                        <td className="px-3 py-2 text-right align-top font-mono text-muted-foreground">
                          {formatRegressionMetric(row.base_score)}
                        </td>
                        <td className="px-3 py-2 text-right align-top font-mono text-muted-foreground">
                          {formatRegressionMetric(row.target_score)}
                        </td>
                        <td
                          className={cn(
                            'px-3 py-2 text-right align-top font-mono text-muted-foreground',
                            row.delta !== null && row.delta > 0 && 'text-success',
                            row.delta !== null && row.delta < 0 && 'text-destructive',
                          )}
                        >
                          {row.delta === null ? '未提供' : `${row.delta > 0 ? '+' : ''}${row.delta.toFixed(3)}`}
                        </td>
                        <td className="px-3 py-2 text-right align-top text-foreground/85">{row.label}</td>
                      </tr>
                      {expanded ? (
                        <tr>
                          <td colSpan={5} className="border-t border-border/50 bg-muted/50 px-3 py-3">
                            <div id={rowDetailsId} className="grid gap-2 md:grid-cols-2">
                              <div>
                                <h4 className="mb-1 font-medium text-foreground/85">基线回答</h4>
                                <div className="whitespace-pre-wrap break-words rounded-lg bg-background p-2 text-muted-foreground">
                                  {row.base_response ?? missingAnswer}
                                </div>
                              </div>
                              <div>
                                <h4 className="mb-1 font-medium text-foreground/85">候选回答</h4>
                                <div className="whitespace-pre-wrap break-words rounded-lg bg-background p-2 text-muted-foreground">
                                  {row.target_response ?? missingAnswer}
                                </div>
                              </div>
                              {row.metric_diffs.length > 0 ? (
                                <div className="md:col-span-2">
                                  <h4 className="mb-1 font-medium text-foreground/85">逐指标差异</h4>
                                  <div className="rounded-lg bg-background p-2 text-muted-foreground">
                                    {row.metric_diffs.map((item) => (
                                      <p key={item.key}>
                                        {item.key}: {formatRegressionValue(item.before)} →{' '}
                                        {formatRegressionValue(item.after)}
                                      </p>
                                    ))}
                                  </div>
                                </div>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </WorkspaceTableScroll>
        </div>
      ) : (
        <p className="mt-3 px-3 py-8 text-center text-xs text-muted-foreground">
          {diff === null ? '请先在上方生成运行对比，再查看配对样本。' : '本次对比没有返回配对样本。'}
        </p>
      )}
    </section>
  )
}
