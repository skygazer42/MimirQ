'use client'

import { useMemo, useState } from 'react'
import { Grid3X3, PlayCircle } from '@/components/icons'

import { LoadingButton } from '@/components/ui/loading-button'
import { Textarea } from '@/components/ui/textarea'
import { formatApiError } from '@/lib/api-errors'
import { ABLATION_GRID_KEYS, MAX_GRID_COMBINATIONS, parseAblationGrid } from '@/lib/regression-ablation-grid'
import { detachPromise } from '@/lib/utils'
import type { RegressionAblationBatchResponse, RegressionAblationGridValue } from '@/types'

const DEFAULT_GRID = `{
  "retrieval_mode": ["hybrid", "vector"],
  "top_k": [10, 20],
  "enable_reranker": [false, true]
}`

export function AblationGridPanel({
  disabled = false,
  disabledReason,
  onRunGrid,
}: Readonly<{
  disabled?: boolean
  disabledReason?: string
  onRunGrid: (
    grid: Record<string, RegressionAblationGridValue[]>,
    maxCombinations: number,
  ) => Promise<RegressionAblationBatchResponse>
}>) {
  const [gridText, setGridText] = useState(DEFAULT_GRID)
  const [running, setRunning] = useState(false)
  const [acceptedBatch, setAcceptedBatch] = useState<RegressionAblationBatchResponse | null>(null)
  const [batchError, setBatchError] = useState<string | null>(null)
  const preview = useMemo(() => parseAblationGrid(gridText), [gridText])
  const canRun = !disabled && !running && preview.status === 'ready'
  let combinationCount: number | string = '未计算'
  if (preview.status === 'ready') {
    combinationCount = preview.variants.length
  } else if (preview.status === 'overLimit') {
    combinationCount = `>${MAX_GRID_COMBINATIONS}`
  }

  async function runBatch() {
    if (!canRun) return
    setRunning(true)
    setBatchError(null)
    try {
      const batch = await onRunGrid(preview.grid, MAX_GRID_COMBINATIONS)
      setAcceptedBatch(batch)
    } catch (error) {
      setBatchError(formatApiError(error, '未取得有效批量回执，请先重新读取运行记录确认'))
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Grid3X3 className="size-4 text-info" />
            笛卡尔网格批量
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            按参数数组组合提交一个批次，由后端接受并调度运行；本次最多 {MAX_GRID_COMBINATIONS} 组。
          </p>
          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">支持字段：{ABLATION_GRID_KEYS.join(' / ')}</p>
        </div>
        <div className="rounded-xl border border-border bg-muted/50 px-3 py-2 text-right">
          <div className="text-[10px] text-muted-foreground">组合数</div>
          <div className="font-mono text-lg font-semibold text-foreground">{combinationCount}</div>
        </div>
      </div>
      <label className="mt-3 block text-xs font-medium text-muted-foreground">
        参数网格 JSON
        <Textarea
          value={gridText}
          onChange={(event) => setGridText(event.target.value)}
          disabled={running}
          spellCheck={false}
          className="mt-1 min-h-36 rounded-xl border-border bg-background font-mono text-xs text-foreground"
        />
      </label>
      {preview.status !== 'ready' ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {preview.message}
        </p>
      ) : null}
      {batchError !== null ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {batchError}
        </p>
      ) : null}
      {acceptedBatch !== null ? (
        <p role="status" className="mt-2 break-words text-xs text-muted-foreground">
          上次提交已接受 {acceptedBatch.total} 个运行；批次 {acceptedBatch.ablation_id}。运行结果请查看记录。
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 text-xs text-muted-foreground">
          {disabled && disabledReason !== undefined ? <p>{disabledReason}</p> : null}
          {preview.status === 'ready' ? (
            <p className="break-words">
              预览前 {Math.min(preview.variants.length, 3)} 组：
              {preview.variants
                .slice(0, 3)
                .map((variant) => JSON.stringify(variant))
                .join(' / ')}
            </p>
          ) : null}
        </div>
        <LoadingButton
          type="button"
          loading={running}
          disabled={!canRun}
          onClick={() => detachPromise(runBatch())}
          className="gap-2 rounded-xl"
        >
          <PlayCircle className="size-4" />
          提交网格
        </LoadingButton>
      </div>
    </section>
  )
}
