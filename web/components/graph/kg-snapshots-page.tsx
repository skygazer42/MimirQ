'use client'

import { useMemo, useState } from 'react'
import { Copy, Download, GitCompare, RefreshCcw } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Textarea } from '@/components/ui/textarea'
import { formatApiError } from '@/lib/api-errors'
import { kgApi } from '@/lib/api-client'
import { detachPromise } from '@/lib/utils'

type SnapshotPayload = Record<string, unknown>

type SnapshotDiffEntityRow = {
  type?: string
  delta?: number | null
  [key: string]: unknown
}

type SnapshotDiffPayload = {
  delta?: SnapshotPayload | null
  entity_types_delta?: SnapshotDiffEntityRow[] | null
  [key: string]: unknown
}


function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function sanitizeFilename(name: string): string {
  const trimmed = String(name || '').trim()
  const base = trimmed || 'kg-snapshots'
  return base.replaceAll(/[\\/:*?"<>|]+/g, '_')
}

function downloadJson(value: unknown, filename: string): void {
  const content = JSON.stringify(value ?? {}, null, 2)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function copyToClipboard(text: string, label: string): Promise<void> {
  const v = String(text || '')
  if (!v.trim()) {
    toast.error('无可复制内容')
    return
  }
  try {
    await navigator.clipboard.writeText(v)
    toast.success(`已复制 ${label}`)
  } catch (err) {
    console.error('clipboard.writeText failed:', err)
    toast.error('复制失败（浏览器权限限制）')
  }
}

function parseDocumentIds(raw: string): string[] {
  const input = String(raw || '').trim()
  if (!input) return []
  return input
    .split(/[,\n]/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function KGSnapshotsPage() {
  const [pipelineHashA, setPipelineHashA] = useState('')
  const [pipelineHashB, setPipelineHashB] = useState('')
  const [documentIdsRaw, setDocumentIdsRaw] = useState('')

  const [snapA, setSnapA] = useState<SnapshotPayload | null>(null)
  const [snapB, setSnapB] = useState<SnapshotPayload | null>(null)
  const [diff, setDiff] = useState<SnapshotDiffPayload | null>(null)
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const documentIds = useMemo(() => parseDocumentIds(documentIdsRaw), [documentIdsRaw])

  const snapAJson = useMemo(() => prettyJson(snapA ?? { hint: '点击“导出 A 快照”生成快照' }), [snapA])
  const snapBJson = useMemo(() => prettyJson(snapB ?? { hint: '点击“导出 B 快照”生成快照' }), [snapB])
  const diffJson = useMemo(() => prettyJson(diff ?? { hint: '点击“对比”生成 diff（mimirq.kg_snapshot_diff.v1）' }), [diff])

  const diffDelta = useMemo(() => {
    const d = diff
    const delta = d?.delta && typeof d.delta === 'object' ? d.delta : null
    const entityTypesDelta = Array.isArray(d?.entity_types_delta) ? d.entity_types_delta : []
    return { delta, entityTypesDelta }
  }, [diff])

  async function runExport(which: 'a' | 'b'): Promise<void> {
    const pipelineHash = (which === 'a' ? pipelineHashA : pipelineHashB).trim()
    if (!pipelineHash) {
      toast.error(which === 'a' ? '请输入 pipeline_hash A' : '请输入 pipeline_hash B')
      return
    }

    setIsRunning(true)
    try {
      const snapshot = await kgApi.exportSnapshot({
        pipeline_hash: pipelineHash,
        document_ids: documentIds.length ? documentIds : undefined,
      })
      if (which === 'a') setSnapA(snapshot)
      else setSnapB(snapshot)
      toast.success(`已导出 ${which.toUpperCase()} 快照`)
    } catch (err) {
      toast.error(formatApiError(err, '导出 KG snapshot 失败'))
    } finally {
      setIsRunning(false)
    }
  }

  async function runCompare(): Promise<void> {
    const a = pipelineHashA.trim()
    const b = pipelineHashB.trim()
    if (!a || !b) {
      toast.error('请输入 pipeline_hash A / B')
      return
    }
    if (a === b) {
      toast.error('A / B pipeline_hash 不能相同')
      return
    }

    setIsRunning(true)
    setLatencyMs(null)
    try {
      const start = Date.now()
      const [snapshotA, snapshotB] = await Promise.all([
        kgApi.exportSnapshot({
          pipeline_hash: a,
          document_ids: documentIds.length ? documentIds : undefined,
        }),
        kgApi.exportSnapshot({
          pipeline_hash: b,
          document_ids: documentIds.length ? documentIds : undefined,
        }),
      ])
      const result = await kgApi.diffSnapshots({ snapshot_a: snapshotA, snapshot_b: snapshotB })
      setLatencyMs(Math.max(0, Date.now() - start))
      setSnapA(snapshotA)
      setSnapB(snapshotB)
      setDiff(result)
      toast.success('已生成 diff')
    } catch (err) {
      toast.error(formatApiError(err, 'KG snapshot compare 失败'))
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <AppFrame>
      <PageScaffold
        title="KG Snapshots"
        description="导出/对比 KG 轻量快照（PII-safe），用于诊断 pipeline_hash 导致的抽取/规模漂移。"
        icon={GitCompare}
        iconColor="text-info"
        size="6xl"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => {
                setSnapA(null)
                setSnapB(null)
                setDiff(null)
                setLatencyMs(null)
                toast.message('已清空')
              }}
            >
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              清空
            </Button>
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">对比参数</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-2">
                <Label htmlFor="pipeline-hash-a">pipeline_hash A</Label>
                <Input
                  id="pipeline-hash-a"
                  placeholder="ph_a..."
                  value={pipelineHashA}
                  onChange={(e) => setPipelineHashA(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="pipeline-hash-b">pipeline_hash B</Label>
                <Input
                  id="pipeline-hash-b"
                  placeholder="ph_b..."
                  value={pipelineHashB}
                  onChange={(e) => setPipelineHashB(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="document-ids">document_ids（可选，逗号或换行分隔）</Label>
                <Textarea
                  id="document-ids"
                  placeholder="7b6e... , 1c2d... (留空表示使用可访问文档集合的默认上限)"
                  value={documentIdsRaw}
                  onChange={(e) => setDocumentIdsRaw(e.target.value)}
                  rows={4}
                />
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  className="gap-2"
                  onClick={() => detachPromise(runExport('a'))}
                  disabled={isRunning}
                >
                  导出 A 快照
                </Button>
                <Button
                  variant="secondary"
                  className="gap-2"
                  onClick={() => detachPromise(runExport('b'))}
                  disabled={isRunning}
                >
                  导出 B 快照
                </Button>
                <Button className="gap-2" onClick={() => detachPromise(runCompare())} disabled={isRunning}>
                  <GitCompare className="h-4 w-4" aria-hidden="true" />
                  对比
                </Button>
                {typeof latencyMs === 'number' ? (
                  <div className="text-xs text-muted-foreground">latency: {latencyMs} ms</div>
                ) : null}
              </div>

              <div className="text-xs text-muted-foreground">
                提示：快照是“计数 + 类型直方图”的轻量 payload；详情级别的 drift 需要结合 KG diagnostics / traces。
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Diff（A → B）</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {diffDelta.delta ? (
                <div className="grid gap-3 md:grid-cols-5">
                  {(['docs', 'events', 'entities', 'links', 'relations']).map((key) => {
                    const a0 = Number((snapA)?.[key] ?? 0)
                    const b0 = Number((snapB)?.[key] ?? 0)
                    const d0 = Number((diffDelta.delta)?.[key] ?? b0 - a0)
                    const sign = d0 > 0 ? '+' : ''
                    const tone = (() => {
    if (d0 > 0) {
        return 'text-emerald-600';
    }
    else if (d0 < 0) {
            return 'text-rose-600';
        }
        else {
            return 'text-muted-foreground';
        }
})()
                    return (
                      <Card key={key} className="border-muted/60">
                        <CardHeader className="pb-2">
                          <CardTitle className="text-xs font-medium text-muted-foreground uppercase">{key}</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-1">
                          <div className="text-sm">
                            <span className="text-muted-foreground">A</span> {Number.isFinite(a0) ? a0 : 0}
                          </div>
                          <div className="text-sm">
                            <span className="text-muted-foreground">B</span> {Number.isFinite(b0) ? b0 : 0}
                          </div>
                          <div className={`text-sm font-semibold ${tone}`}>{sign + (Number.isFinite(d0) ? d0 : 0)}</div>
                        </CardContent>
                      </Card>
                    )
                  })}
                </div>
              ) : null}

              {diffDelta.entityTypesDelta.length ? (
                <div className="rounded-md border bg-muted/20 p-3">
                  <div className="text-xs font-medium text-muted-foreground mb-2">entity_types_delta (top)</div>
                  <div className="grid gap-1 md:grid-cols-2">
                    {diffDelta.entityTypesDelta.slice(0, 12).map((row) => {
                      const typ = String(row?.type || 'unknown')
                      const delta = Number(row?.delta ?? 0)
                      const sign = delta > 0 ? '+' : ''
                      const tone = (() => {
    if (delta > 0) {
        return 'text-emerald-600';
    }
    else if (delta < 0) {
            return 'text-rose-600';
        }
        else {
            return 'text-muted-foreground';
        }
})()
                      return (
                        <div key={`${typ}:${delta}`} className="flex items-center justify-between gap-2 text-xs">
                          <div className="truncate">{typ}</div>
                          <div className={`shrink-0 tabular-nums ${tone}`}>{sign + (Number.isFinite(delta) ? delta : 0)}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => detachPromise(copyToClipboard(diffJson, 'diff JSON'))}
                >
                  <Copy className="h-4 w-4" aria-hidden="true" />
                  复制
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => {
                    const base = sanitizeFilename(`kg_snapshot_${pipelineHashA.trim()}_vs_${pipelineHashB.trim()}`) || 'kg_snapshot'
                    downloadJson(diff ?? {}, `${base}.diff.json`)
                    toast.success('已导出 diff.json')
                  }}
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  导出
                </Button>
              </div>
              <Textarea value={diffJson} readOnly rows={14} className="font-mono text-xs" />
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 md:grid-cols-2 mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Snapshot A</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex items-center justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => detachPromise(copyToClipboard(snapAJson, 'snapshot A JSON'))}
                >
                  <Copy className="h-4 w-4" aria-hidden="true" />
                  复制
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => {
                    const base = sanitizeFilename(`kg_snapshot_${pipelineHashA.trim() || 'A'}`) || 'kg_snapshot_A'
                    downloadJson(snapA ?? {}, `${base}.json`)
                    toast.success('已导出 snapshot A')
                  }}
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  导出
                </Button>
              </div>
              <Textarea value={snapAJson} readOnly rows={12} className="font-mono text-xs" />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Snapshot B</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex items-center justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => detachPromise(copyToClipboard(snapBJson, 'snapshot B JSON'))}
                >
                  <Copy className="h-4 w-4" aria-hidden="true" />
                  复制
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2"
                  onClick={() => {
                    const base = sanitizeFilename(`kg_snapshot_${pipelineHashB.trim() || 'B'}`) || 'kg_snapshot_B'
                    downloadJson(snapB ?? {}, `${base}.json`)
                    toast.success('已导出 snapshot B')
                  }}
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  导出
                </Button>
              </div>
              <Textarea value={snapBJson} readOnly rows={12} className="font-mono text-xs" />
            </CardContent>
          </Card>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
