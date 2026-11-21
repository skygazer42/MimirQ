'use client'

import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { createTwoFilesPatch } from 'diff'
import { Copy, GitCompare, FileText } from '@/components/icons'
import { toast } from 'sonner'

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { LoadingButton } from '@/components/ui/loading-button'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { formatApiError } from '@/lib/api-errors'
import { diffParsingElements, type ParsingElementDiffSummary } from '@/lib/parsing-element-diff'
import { cn } from '@/lib/utils'
import type { ParseRun } from './parsing-types'

type ParseCompareDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  runs: readonly ParseRun[]
  defaultBaseRunId: string | null
  onUseRun: (runId: string) => void
}

type ParseComparisonProps = Pick<ParseCompareDialogProps, 'runs' | 'onUseRun'> & {
  initialBaseId: string
  initialCompareId: string
}

type CompareMode = 'cleaned' | 'raw'

type TextComparison =
  | { status: 'unavailable' }
  | { status: 'too-large' }
  | { status: 'timed-out' }
  | { status: 'equal' }
  | { status: 'changed'; patch: string }

const elementKinds: ReadonlyArray<{ kind: keyof ParsingElementDiffSummary['addedByKind']; label: string }> = [
  { kind: 'heading', label: '标题' },
  { kind: 'paragraph', label: '段落' },
  { kind: 'list', label: '列表' },
  { kind: 'table', label: '表格' },
  { kind: 'image', label: '图片' },
  { kind: 'equation', label: '公式' },
  { kind: 'seal', label: '印章' },
  { kind: 'unknown', label: '未分类元素' },
]

function formatRunLabel(run: ParseRun): string {
  return `${run.parserLabel} · ${new Date(run.createdAt).toLocaleTimeString()}`
}

function compareRunText(base: ParseRun | undefined, compare: ParseRun | undefined, mode: CompareMode): TextComparison {
  if (base === undefined || compare === undefined) return { status: 'unavailable' }

  const baseText = mode === 'raw' ? base.rawMarkdown : base.cleanedMarkdown
  const compareText = mode === 'raw' ? compare.rawMarkdown : compare.cleanedMarkdown
  if (baseText === compareText) return { status: 'equal' }
  if (baseText.length > 300_000 || compareText.length > 300_000) return { status: 'too-large' }

  const patch = createTwoFilesPatch(
    formatRunLabel(base),
    formatRunLabel(compare),
    baseText,
    compareText,
    undefined,
    undefined,
    { context: 3, timeout: 100 },
  )
  if (patch === undefined) return { status: 'timed-out' }
  return { status: 'changed', patch }
}

function ParseComparison({ runs, initialBaseId, initialCompareId, onUseRun }: Readonly<ParseComparisonProps>) {
  const baseSelectId = useId()
  const compareSelectId = useId()
  const [mode, setMode] = useState<CompareMode>('cleaned')
  const [baseId, setBaseId] = useState(initialBaseId)
  const [compareId, setCompareId] = useState(initialCompareId)
  const [isCopying, setIsCopying] = useState(false)
  const copyRequestRef = useRef<object | null>(null)

  const baseRun = runs.find((run) => run.id === baseId)
  const compareRun = runs.find((run) => run.id === compareId)
  const textComparison = useMemo(() => compareRunText(baseRun, compareRun, mode), [baseRun, compareRun, mode])
  const elementDiffSummary = useMemo(() => {
    if (baseRun?.elements === undefined || compareRun?.elements === undefined) return null
    return diffParsingElements(baseRun.elements, compareRun.elements)
  }, [baseRun, compareRun])
  const structureSummaryItems =
    elementDiffSummary === null
      ? []
      : elementKinds
          .flatMap(({ kind, label }) => [
            { label: `新增${label}`, value: elementDiffSummary.addedByKind[kind] },
            { label: `移除${label}`, value: elementDiffSummary.removedByKind[kind] },
          ])
          .filter((item) => item.value > 0)

  useEffect(() => {
    copyRequestRef.current = null
    setIsCopying(false)
    return () => {
      copyRequestRef.current = null
    }
  }, [textComparison])

  async function copyDiff() {
    if (textComparison.status !== 'changed' || copyRequestRef.current !== null) return
    const request = {}
    copyRequestRef.current = request
    const sessionKey = getAuthSessionKey()
    const isCurrent = () => copyRequestRef.current === request && getAuthSessionKey() === sessionKey
    setIsCopying(true)
    try {
      await navigator.clipboard.writeText(textComparison.patch)
      if (isCurrent()) toast.success('已复制正文差异')
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, '复制失败'))
    } finally {
      if (copyRequestRef.current === request) {
        copyRequestRef.current = null
        setIsCopying(false)
      }
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={baseSelectId}>基准版本</Label>
          <select
            id={baseSelectId}
            value={baseId}
            onChange={(event) => setBaseId(event.target.value)}
            className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground"
          >
            {baseRun === undefined ? (
              <option value={baseId} disabled>
                所选版本已不可用
              </option>
            ) : null}
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {formatRunLabel(run)}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor={compareSelectId}>对比版本</Label>
          <select
            id={compareSelectId}
            value={compareId}
            onChange={(event) => setCompareId(event.target.value)}
            className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground"
          >
            {compareRun === undefined ? (
              <option value={compareId} disabled>
                所选版本已不可用
              </option>
            ) : null}
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {formatRunLabel(run)}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div
          className="inline-flex items-center rounded-lg border border-border bg-muted/20 p-1"
          role="group"
          aria-label="比较正文"
        >
          <button
            type="button"
            aria-pressed={mode === 'cleaned'}
            onClick={() => setMode('cleaned')}
            className={cn(
              'flex items-center gap-1 rounded-md px-3 py-1.5 text-xs focus-ring transition-colors duration-200 motion-reduce:transition-none',
              mode === 'cleaned'
                ? 'bg-card text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground/80',
            )}
          >
            <FileText className="size-3.5" />
            处理后正文
          </button>
          <button
            type="button"
            aria-pressed={mode === 'raw'}
            onClick={() => setMode('raw')}
            className={cn(
              'flex items-center gap-1 rounded-md px-3 py-1.5 text-xs focus-ring transition-colors duration-200 motion-reduce:transition-none',
              mode === 'raw' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground/80',
            )}
          >
            <FileText className="size-3.5" />
            解析原文
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={baseRun === undefined}
            onClick={() => onUseRun(baseId)}
          >
            预览基准版本
          </Button>
          <Button type="button" size="sm" disabled={compareRun === undefined} onClick={() => onUseRun(compareId)}>
            预览对比版本
          </Button>
          <LoadingButton
            variant="outline"
            size="sm"
            loading={isCopying}
            disabled={textComparison.status !== 'changed'}
            onClick={() => void copyDiff()}
          >
            <Copy className="mr-1.5 size-4" />
            复制正文差异
          </LoadingButton>
        </div>
      </div>

      {elementDiffSummary === null ? (
        <p className="text-sm text-muted-foreground">所选版本未提供完整元素记录，无法比较结构差异。</p>
      ) : (
        <section className="space-y-2 rounded-xl border border-border bg-muted/15 p-3" aria-label="结构差异">
          <h3 className="text-sm font-medium">结构差异</h3>
          <p className="text-xs text-muted-foreground">
            基准版本 {elementDiffSummary.totalBase} 个元素 · 对比版本 {elementDiffSummary.totalCompare} 个元素
          </p>
          {structureSummaryItems.length === 0 ? (
            <p className="text-xs text-muted-foreground">未发现结构差异。</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {structureSummaryItems.map((item) => (
                <li
                  key={item.label}
                  className="rounded-full border border-border/60 bg-background px-2 py-1 text-xs text-muted-foreground"
                >
                  {item.label} <span className="font-mono font-semibold text-foreground">{item.value}</span>
                </li>
              ))}
            </ul>
          )}
          {elementDiffSummary.addedSealTexts.length > 0 ? (
            <p className="text-xs text-muted-foreground">新增印章：{elementDiffSummary.addedSealTexts.join(' · ')}</p>
          ) : null}
          {elementDiffSummary.removedSealTexts.length > 0 ? (
            <p className="text-xs text-muted-foreground">移除印章：{elementDiffSummary.removedSealTexts.join(' · ')}</p>
          ) : null}
          {elementDiffSummary.addedImageVisualKinds.length > 0 ? (
            <p className="text-xs text-muted-foreground">
              新增图片类型：{elementDiffSummary.addedImageVisualKinds.join(' · ')}
            </p>
          ) : null}
          {elementDiffSummary.removedImageVisualKinds.length > 0 ? (
            <p className="text-xs text-muted-foreground">
              移除图片类型：{elementDiffSummary.removedImageVisualKinds.join(' · ')}
            </p>
          ) : null}
        </section>
      )}

      {textComparison.status === 'unavailable' ? (
        <p role="status" className="text-sm text-muted-foreground">
          所选版本已不可用，请选择现有版本。
        </p>
      ) : textComparison.status === 'too-large' ? (
        <p role="status" className="text-sm text-muted-foreground">
          单份正文超过 300,000 字符，暂不生成逐行差异。仍可选择版本查看正文。
        </p>
      ) : textComparison.status === 'equal' ? (
        <p role="status" className="text-sm text-muted-foreground">
          两份正文相同。
        </p>
      ) : textComparison.status === 'timed-out' ? (
        <p role="status" className="text-sm text-muted-foreground">
          逐行对比超时，已停止计算。仍可分别预览版本。
        </p>
      ) : (
        <pre
          tabIndex={0}
          aria-label="正文差异"
          className="max-h-96 min-h-48 overflow-auto rounded-lg border border-border bg-muted/10 p-3 font-mono text-xs"
        >
          {textComparison.patch}
        </pre>
      )}
    </div>
  )
}

export function ParseCompareDialog({
  open,
  onOpenChange,
  runs,
  defaultBaseRunId,
  onUseRun,
}: Readonly<ParseCompareDialogProps>) {
  const firstRun = runs[0]
  const initialBaseId = defaultBaseRunId ?? firstRun?.id
  const initialCompareId = runs.find((run) => run.id !== initialBaseId)?.id ?? firstRun?.id

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitCompare className="size-5" />
            解析版本对比
          </DialogTitle>
          <DialogDescription>比较两次解析的正文与结构，选择版本后可切回工作台核对。</DialogDescription>
        </DialogHeader>
        {open && initialBaseId !== undefined && initialCompareId !== undefined ? (
          <ParseComparison
            runs={runs}
            initialBaseId={initialBaseId}
            initialCompareId={initialCompareId}
            onUseRun={onUseRun}
          />
        ) : open ? (
          <p role="status" className="text-sm text-muted-foreground">
            暂无可对比的解析版本。
          </p>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
