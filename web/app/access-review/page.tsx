'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Download, RefreshCw, ShieldCheck } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

import { auditApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { cn } from '@/lib/utils'

type AccessGraphSummary = {
  schema?: string
  tenant_id?: string
  generated_at?: string
  group_count?: number
  group_member_count?: number
  dataset_count?: number
  dataset_permission_counts?: Record<string, number>
  dataset_member_allowlist_count?: number
  dataset_group_allowlist_count?: number
  document_count?: number
  document_access_mode_counts?: Record<string, number>
  document_member_allowlist_count?: number
  document_group_allowlist_count?: number
}

function safeInt(v: unknown) {
  const n = Number(v ?? 0)
  return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0
}

function safeTs() {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function AccessReviewPage() {
  const [summary, setSummary] = useState<AccessGraphSummary | null>(null)
  const [loadingSummary, setLoadingSummary] = useState(false)

  const [exportFormat, setExportFormat] = useState<'ndjson' | 'json'>('ndjson')
  const [includeSensitive, setIncludeSensitive] = useState(false)
  const [gzip, setGzip] = useState(true)
  const [limit, setLimit] = useState(10_000)

  const [exporting, setExporting] = useState(false)
  const [exportPages, setExportPages] = useState(0)
  const [exportBytes, setExportBytes] = useState(0)

  const permissionCounts = useMemo(() => {
    const m = summary?.dataset_permission_counts || {}
    return {
      all_team_members: safeInt(m.all_team_members),
      partial_members: safeInt(m.partial_members),
      only_me: safeInt(m.only_me),
    }
  }, [summary?.dataset_permission_counts])

  const accessModeCounts = useMemo(() => {
    const m = summary?.document_access_mode_counts || {}
    return {
      inherit: safeInt(m.inherit),
      partial_members: safeInt(m.partial_members),
      only_me: safeInt(m.only_me),
      all_team_members: safeInt(m.all_team_members),
      unknown: safeInt(m.unknown),
    }
  }, [summary?.document_access_mode_counts])

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true)
    try {
      const data = await auditApi.getAccessGraphSummary()
      setSummary(data || null)
    } catch (err: any) {
      setSummary(null)
      toast.error(formatApiError(err, '加载访问审查汇总失败'))
    } finally {
      setLoadingSummary(false)
    }
  }, [])

  useEffect(() => {
    void loadSummary()
  }, [loadSummary])

  const handleDownload = useCallback(async () => {
    const cap = Math.max(1, Math.min(10_000, safeInt(limit)))
    const maxPages = 50
    const maxTotalBytes = 150 * 1024 * 1024

    setExporting(true)
    setExportPages(0)
    setExportBytes(0)

    try {
      if (exportFormat === 'json') {
        const { blob } = await auditApi.exportAccessGraphPage({
          limit: cap,
          export_format: 'json',
          include_sensitive: includeSensitive,
          gzip,
        })
        downloadBlob(blob, `access-graph.${safeTs()}.json`)
        toast.success('已下载 access graph（JSON）')
        return
      }

      const blobs: Blob[] = []
      let cursor: { after_kind: string; after_created_at: string; after_id: string } | null = null
      let pages = 0
      let bytes = 0

      while (true) {
        pages += 1
        const res = await auditApi.exportAccessGraphPage({
          limit: cap,
          export_format: 'ndjson',
          include_sensitive: includeSensitive,
          gzip,
          after_kind: cursor?.after_kind,
          after_created_at: cursor?.after_created_at,
          after_id: cursor?.after_id,
        })
        blobs.push(res.blob)
        bytes += safeInt((res.blob as any)?.size)

        setExportPages(pages)
        setExportBytes(bytes)

        if (!res.nextCursor) break
        cursor = res.nextCursor

        if (pages >= maxPages) {
          toast.warning(`导出已达到最大分页上限（${maxPages}页）。建议用脚本/后端导出处理更大租户。`)
          break
        }
        if (bytes >= maxTotalBytes) {
          toast.warning('导出内容过大，已停止追加分页。建议用脚本/后端导出处理更大租户。')
          break
        }
      }

      const out = new Blob(blobs, { type: 'application/x-ndjson' })
      downloadBlob(out, `access-graph.${safeTs()}.ndjson`)
      toast.success(`已下载 access graph（${pages}页）`)
    } catch (err: any) {
      toast.error(formatApiError(err, '导出 access graph 失败'))
    } finally {
      setExporting(false)
    }
  }, [exportFormat, includeSensitive, gzip, limit])

  const summaryStats = useMemo(() => {
    return {
      group_count: safeInt(summary?.group_count),
      group_member_count: safeInt(summary?.group_member_count),
      dataset_count: safeInt(summary?.dataset_count),
      dataset_member_allowlist_count: safeInt(summary?.dataset_member_allowlist_count),
      dataset_group_allowlist_count: safeInt(summary?.dataset_group_allowlist_count),
      document_count: safeInt(summary?.document_count),
      document_member_allowlist_count: safeInt(summary?.document_member_allowlist_count),
      document_group_allowlist_count: safeInt(summary?.document_group_allowlist_count),
    }
  }, [summary])

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title="访问审查"
          description="权限图谱汇总与导出（admin-only，默认 PII-safe）"
          icon={ShieldCheck}
          iconColor="text-emerald-600 dark:text-emerald-400"
          size="7xl"
          actions={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="gap-2 rounded-xl"
                onClick={() => void loadSummary()}
                disabled={loadingSummary}
              >
                <RefreshCw className={cn('w-4 h-4', loadingSummary && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
              <Button
                size="sm"
                className="gap-2 rounded-xl"
                onClick={() => void handleDownload()}
                disabled={exporting}
              >
                <Download className="w-4 h-4" />
                下载导出
              </Button>
            </div>
          }
        >
          <Panel padding="lg" className="mt-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-foreground">汇总</div>
                <div className="mt-1 text-xs text-muted-foreground text-pretty">
                  用于日常 access review 与排查“为什么某个用户被拒绝”（目录/组/allowlist 维度），不包含文档内容。
                </div>
              </div>
              <div className="text-xs text-muted-foreground font-mono">
                {summary?.generated_at ? `generated_at: ${summary.generated_at}` : null}
              </div>
            </div>

            <div className="mt-4">
              {loadingSummary ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <Skeleton key={i} className="h-[68px] rounded-xl" />
                  ))}
                </div>
              ) : !summary ? (
                <div className="text-sm text-muted-foreground">
                  无法加载访问审查汇总。请确认你是 owner/admin，并且后端已更新到包含 `/api/v1/audit/access-graph/summary` 的版本。
                </div>
              ) : (
                <>
                  <StatsGrid className="mt-1">
                    <StatCard icon={ShieldCheck} label="Groups" value={summaryStats.group_count} color="cyan" />
                    <StatCard icon={ShieldCheck} label="Group Members" value={summaryStats.group_member_count} color="gray" />
                    <StatCard icon={ShieldCheck} label="Datasets" value={summaryStats.dataset_count} color="sky" />
                    <StatCard icon={ShieldCheck} label="Documents" value={summaryStats.document_count} color="sky" />
                    <StatCard
                      icon={ShieldCheck}
                      label="Dataset Member Allowlist"
                      value={summaryStats.dataset_member_allowlist_count}
                      color="gray"
                    />
                    <StatCard
                      icon={ShieldCheck}
                      label="Dataset Group Allowlist"
                      value={summaryStats.dataset_group_allowlist_count}
                      color="gray"
                    />
                    <StatCard
                      icon={ShieldCheck}
                      label="Document Member Allowlist"
                      value={summaryStats.document_member_allowlist_count}
                      color="gray"
                    />
                    <StatCard
                      icon={ShieldCheck}
                      label="Document Group Allowlist"
                      value={summaryStats.document_group_allowlist_count}
                      color="gray"
                    />
                  </StatsGrid>

                  <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="rounded-xl border border-border/60 bg-muted/10 p-3">
                      <div className="text-sm font-semibold">Dataset 权限分布</div>
                      <div className="mt-2 text-xs text-muted-foreground font-mono tabular-nums space-y-1">
                        <div className="flex items-center justify-between gap-2">
                          <span>all_team_members</span>
                          <span>{permissionCounts.all_team_members}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span>partial_members</span>
                          <span>{permissionCounts.partial_members}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span>only_me</span>
                          <span>{permissionCounts.only_me}</span>
                        </div>
                      </div>
                    </div>

                    <div className="rounded-xl border border-border/60 bg-muted/10 p-3">
                      <div className="text-sm font-semibold">Document 访问模式分布</div>
                      <div className="mt-2 text-xs text-muted-foreground font-mono tabular-nums space-y-1">
                        {Object.entries(accessModeCounts).map(([k, v]) => (
                          <div key={k} className="flex items-center justify-between gap-2">
                            <span>{k}</span>
                            <span>{v}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          </Panel>

          <Panel padding="lg" className="mt-4">
            <div className="text-sm font-semibold text-foreground">导出（Access Graph Export）</div>
            <div className="mt-1 text-xs text-muted-foreground text-pretty">
              建议优先使用 NDJSON（便于分页与流式处理）。浏览器下载会自动解压 gzip 编码，因此 “gzip” 主要用于网络传输节省带宽。
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label>格式</Label>
                <Select value={exportFormat} onValueChange={(v) => setExportFormat(v as any)}>
                  <SelectTrigger className="h-10 rounded-xl">
                    <SelectValue placeholder="选择格式" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ndjson">NDJSON（推荐）</SelectItem>
                    <SelectItem value="json">JSON（单页）</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <Label>每页条数（limit）</Label>
                <Input
                  type="number"
                  min={1}
                  max={10000}
                  value={String(limit)}
                  onChange={(e) => setLimit(safeInt(e.target.value))}
                />
              </div>

              <div className="flex items-end justify-between gap-3 rounded-xl border border-border/60 bg-muted/10 px-4 py-3">
                <div className="min-w-0">
                  <Label className="text-sm">gzip 传输</Label>
                  <div className="text-xs text-muted-foreground truncate">仅影响传输编码，不保证保存为 .gz</div>
                </div>
                <Switch checked={gzip} onCheckedChange={(v) => setGzip(Boolean(v))} />
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-muted/10 px-4 py-3">
              <div className="min-w-0">
                <Label className="text-sm">包含敏感字段（谨慎）</Label>
                <div className="text-xs text-muted-foreground text-pretty">
                  开启后可能包含 group name / external_id / user_id 等字段，仅建议用于审计导出与合规流程。
                </div>
              </div>
              <Switch checked={includeSensitive} onCheckedChange={(v) => setIncludeSensitive(Boolean(v))} />
            </div>

            {exporting ? (
              <div className="mt-3 text-xs text-muted-foreground font-mono tabular-nums">
                exporting… pages={exportPages} bytes={exportBytes}
              </div>
            ) : null}
          </Panel>
        </PageScaffold>
      </div>
    </AppFrame>
  )
}

