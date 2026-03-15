/**
 * ParseCompareDialog - A/B compare two parsing runs (best-effort).
 *
 * Keeps the diff computation fully client-side (no persistence).
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import { createTwoFilesPatch } from 'diff'
import { Copy, GitCompare, FileText } from 'lucide-react'
import { toast } from 'sonner'

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

export type ParseCompareRun = {
  id: string
  parserBackend?: string
  parserLabel?: string
  rawMarkdown: string
  cleanedMarkdown?: string
  createdAt?: number
}

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  runs: ParseCompareRun[]
  defaultBaseRunId?: string | null
  onUseRun?: (runId: string) => void
}

type CompareMode = 'cleaned' | 'raw'

function safeLabel(run: ParseCompareRun): string {
  return run.parserLabel || run.parserBackend || run.id
}

function safeTime(run: ParseCompareRun): string {
  if (!run.createdAt) return ''
  try {
    return new Date(run.createdAt).toLocaleTimeString()
  } catch {
    return ''
  }
}

export function ParseCompareDialog({ open, onOpenChange, runs, defaultBaseRunId, onUseRun }: Readonly<Props>) {
  const [mode, setMode] = useState<CompareMode>('cleaned')
  const [baseId, setBaseId] = useState<string>('')
  const [compareId, setCompareId] = useState<string>('')

  useEffect(() => {
    if (!open) return
    const ids = (runs || []).map((r) => r.id).filter(Boolean)
    const fallback = ids[0] || ''
    const base = defaultBaseRunId && ids.includes(defaultBaseRunId) ? defaultBaseRunId : fallback
    const other = ids.find((id) => id !== base) || base || fallback
    setMode('cleaned')
    setBaseId(base || '')
    setCompareId(other || '')
  }, [defaultBaseRunId, open, runs])

  const baseRun = useMemo(() => runs.find((r) => r.id === baseId) || null, [baseId, runs])
  const compareRun = useMemo(() => runs.find((r) => r.id === compareId) || null, [compareId, runs])

  const baseText = useMemo(() => {
    if (!baseRun) return ''
    return mode === 'raw' ? baseRun.rawMarkdown : baseRun.cleanedMarkdown || baseRun.rawMarkdown
  }, [baseRun, mode])
  const compareText = useMemo(() => {
    if (!compareRun) return ''
    return mode === 'raw' ? compareRun.rawMarkdown : compareRun.cleanedMarkdown || compareRun.rawMarkdown
  }, [compareRun, mode])

  const tooLarge = baseText.length > 300_000 || compareText.length > 300_000

  const diffText = useMemo(() => {
    if (!baseRun || !compareRun) return ''
    if (tooLarge) return ''
    const a = safeLabel(baseRun)
    const b = safeLabel(compareRun)
    const patch = createTwoFilesPatch(a, b, baseText || '', compareText || '', '', '', { context: 3 })
    return patch.trim() ? patch : '(no diff)'
  }, [baseRun, baseText, compareRun, compareText, tooLarge])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitCompare className="h-5 w-5" />
            解析对比（A/B）
          </DialogTitle>
          <DialogDescription>
            对比同一文件不同解析 run 的输出差异（best-effort）。选择右侧版本可一键切换为当前预览。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Base</div>
              <select
                value={baseId}
                onChange={(e) => setBaseId(e.target.value)}
                className="w-full text-sm border border-border rounded-lg px-3 py-2 bg-card text-foreground"
              >
                {(runs || []).map((run) => (
                  <option key={run.id} value={run.id}>
                    {safeLabel(run)} {safeTime(run) ? `· ${safeTime(run)}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Compare</div>
              <select
                value={compareId}
                onChange={(e) => setCompareId(e.target.value)}
                className="w-full text-sm border border-border rounded-lg px-3 py-2 bg-card text-foreground"
              >
                {(runs || []).map((run) => (
                  <option key={run.id} value={run.id}>
                    {safeLabel(run)} {safeTime(run) ? `· ${safeTime(run)}` : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="inline-flex items-center rounded-lg border border-border bg-muted/20 p-1">
	              <button
	                type="button"
	                onClick={() => setMode('cleaned')}
	                className={cn(
	                  'px-3 py-1.5 text-xs rounded-md flex items-center gap-1 focus-ring transition-colors duration-200 motion-reduce:transition-none',
	                  mode === 'cleaned'
	                    ? 'bg-card text-foreground shadow-sm'
	                    : 'text-muted-foreground hover:text-foreground/80'
	                )}
              >
                <FileText className="w-3.5 h-3.5" />
                Cleaned
              </button>
	              <button
	                type="button"
	                onClick={() => setMode('raw')}
	                className={cn(
	                  'px-3 py-1.5 text-xs rounded-md flex items-center gap-1 focus-ring transition-colors duration-200 motion-reduce:transition-none',
	                  mode === 'raw'
	                    ? 'bg-card text-foreground shadow-sm'
	                    : 'text-muted-foreground hover:text-foreground/80'
	                )}
              >
                <FileText className="w-3.5 h-3.5" />
                Raw
              </button>
            </div>

            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!baseRun || !onUseRun}
                onClick={() => baseRun && onUseRun?.(baseRun.id)}
              >
                使用 Base
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={!compareRun || !onUseRun}
                onClick={() => compareRun && onUseRun?.(compareRun.id)}
              >
                使用 Compare
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!diffText || diffText === '(no diff)'}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(diffText)
                    toast.success('已复制 diff')
                  } catch {
                    toast.error('复制失败')
                  }
                }}
              >
                <Copy className="w-4 h-4" />
              </Button>
            </div>
          </div>

          {tooLarge ? (
            <div className="rounded-xl border border-border bg-muted/20 p-4 text-sm text-muted-foreground">
              文本过大，已跳过 diff 计算（超过 300k chars）。你仍可分别切换 run 查看输出。
            </div>
          ) : (
            <Textarea value={diffText} readOnly className="font-mono min-h-[420px] text-xs" />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
