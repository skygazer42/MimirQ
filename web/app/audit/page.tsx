'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ShieldCheck, RefreshCw, Search, Copy, FilterX, ScrollText } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SystemDataStrip } from '@/components/ui/system-data-strip'
import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { AuditLogItem, AuditLogListResponse } from '@/types'
import { cn, detachPromise } from '@/lib/utils'
import { EmptyState } from '@/components/ui/empty-state'
import { systemDenseControls, systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'

const DENSE_OUTLINE_BUTTON = systemDenseControls.outlineButton
const DENSE_INPUT = systemDenseControls.input
const DENSE_PANEL = systemWorkbenchTokens.panel
const DENSE_INLINE_ACTION = systemDenseControls.inlineAction

function fmtTs(ts: string) {
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

async function copyText(text: string, okMsg: string, errMsg: string) {
  const value = (text || '').trim()
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    toast.success(okMsg)
  } catch {
    toast.error(errMsg)
  }
}

export default function AuditLogsPage() {
  const [loading, setLoading] = useState(false)
  const [resp, setResp] = useState<AuditLogListResponse | null>(null)
  const [skip, setSkip] = useState(0)
  const limit = 50

  const t = useTranslations('AuditPage')

  const [filters, setFilters] = useState({
    actor_id: '',
    action: '',
    resource_type: '',
    resource_id: '',
    request_id: '',
    since: '',
    until: '',
  })

  const [expandedId, setExpandedId] = useState<string | null>(null)

  const presets = useMemo(
    () => [
      { label: t('presets.accessReviewDaily'), action: 'compliance.access_review.daily' },
      { label: t('presets.indexAuditDaily'), action: 'observability.index_audit.daily' },
      { label: t('presets.evidenceDriftDaily'), action: 'evidence.drift_audit.daily' },
      { label: t('presets.accessGraphExport'), action: 'compliance.access_graph.export' },
    ],
    [t]
  )

  const params = useMemo(() => {
    const p: Record<string, any> = { skip, limit }
    for (const [k, v] of Object.entries(filters)) {
      const vv = String(v || '').trim()
      if (!vv) continue
      p[k] = vv
    }
    return p
  }, [filters, skip])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await auditApi.listLogs(params)
      setResp(data)
    } catch (err: any) {
      setResp(null)
      toast.error(formatApiError(err, t('errors.loadLogs')))
    } finally {
      setLoading(false)
    }
  }, [params, t])

  useEffect(() => {
    detachPromise(load())
  }, [load])

  const items: AuditLogItem[] = resp?.items || []
  const total = resp?.total || 0
  const page = Math.floor(skip / limit) + 1
  const totalPages = Math.max(1, Math.ceil(total / limit))
  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((value) => String(value || '').trim().length > 0).length,
    [filters]
  )

  const stripItems = useMemo(
    () => [
      { label: '总事件', value: total, mono: true },
      { label: '当前页', value: `${page}/${totalPages}`, mono: true },
      { label: '筛选条件', value: activeFilterCount, mono: true },
      {
        label: '列表状态',
        value: loading ? '加载中' : items.length ? '已就绪' : '空结果',
        tone: loading ? 'warning' : items.length ? 'success' : 'default',
      },
    ],
    [total, page, totalPages, activeFilterCount, loading, items.length]
  )

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title={t('title')}
          description={t('description')}
          icon={ShieldCheck}
          iconColor="text-success"
          size="full"
          density="system-dense"
          top={<SystemDataStrip items={stripItems} minColumnWidth={152} />}
          actions={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className={DENSE_OUTLINE_BUTTON}
                onClick={() => detachPromise(load())}
                disabled={loading}
              >
                <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
                {t('actions.refresh')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className={DENSE_OUTLINE_BUTTON}
                onClick={() => {
                  setSkip(0)
                  setExpandedId(null)
                  setFilters({
                    actor_id: '',
                    action: '',
                    resource_type: '',
                    resource_id: '',
                    request_id: '',
                    since: '',
                    until: '',
                  })
                }}
                >
                  <FilterX className="w-4 h-4" />
                  {t('actions.reset')}
                </Button>
            </div>
          }
        >
          <Panel padding="md" className={cn('mt-3', DENSE_PANEL)}>
            <div className="flex flex-wrap items-center gap-2">
            <div className={cn(systemPageTokens.tableHead, 'tracking-[0.08em]')}>{t('labels.quickPresets')}</div>
              {presets.map((p) => (
                <Button
                  key={p.action}
                  size="sm"
                  variant="outline"
                  className="h-7 rounded-lg border-border/70 bg-background px-2.5 text-[11px] font-semibold"
                  onClick={() => {
                    setSkip(0)
                    setExpandedId(null)
                    setFilters({
                      actor_id: '',
                      action: p.action,
                      resource_type: '',
                      resource_id: '',
                      request_id: '',
                      since: '',
                      until: '',
                    })
                  }}
                >
                  {p.label}
                </Button>
              ))}
            </div>

            <div className="mt-3 space-y-2.5">
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
                <div className="space-y-1">
                  <Label htmlFor="audit-action" className={systemPageTokens.microLabel}>动作</Label>
                  <Input id="audit-action" className={DENSE_INPUT} placeholder="例如：chat.ask / doc.upload（动作键）" value={filters.action} onChange={(e) => setFilters((p) => ({ ...p, action: e.target.value }))} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="audit-actor" className={systemPageTokens.microLabel}>操作者 ID（actor_id）</Label>
                  <Input id="audit-actor" className={DENSE_INPUT} placeholder="输入 actor_id" value={filters.actor_id} onChange={(e) => setFilters((p) => ({ ...p, actor_id: e.target.value }))} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="audit-request" className={systemPageTokens.microLabel}>请求 ID（request_id）</Label>
                  <Input id="audit-request" className={DENSE_INPUT} placeholder="输入 request_id" value={filters.request_id} onChange={(e) => setFilters((p) => ({ ...p, request_id: e.target.value }))} />
                </div>
              </div>

              <div className="hidden grid-cols-1 gap-2.5 xl:grid xl:grid-cols-4">
                <div className="space-y-1">
                  <Label htmlFor="audit-resource-type" className={systemPageTokens.microLabel}>资源类型（resource_type）</Label>
                  <Input id="audit-resource-type" className={DENSE_INPUT} placeholder="输入 resource_type" value={filters.resource_type} onChange={(e) => setFilters((p) => ({ ...p, resource_type: e.target.value }))} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="audit-resource-id" className={systemPageTokens.microLabel}>资源 ID（resource_id）</Label>
                  <Input id="audit-resource-id" className={DENSE_INPUT} placeholder="输入 resource_id" value={filters.resource_id} onChange={(e) => setFilters((p) => ({ ...p, resource_id: e.target.value }))} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="audit-since" className={systemPageTokens.microLabel}>开始时间</Label>
                  <Input
                    id="audit-since"
                    className={DENSE_INPUT}
                    type="datetime-local"
                    value={filters.since}
                    onChange={(e) => setFilters((p) => ({ ...p, since: e.target.value }))}
                    title="开始时间"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="audit-until" className={systemPageTokens.microLabel}>结束时间</Label>
                  <Input
                    id="audit-until"
                    className={DENSE_INPUT}
                    type="datetime-local"
                    value={filters.until}
                    onChange={(e) => setFilters((p) => ({ ...p, until: e.target.value }))}
                    title="结束时间"
                  />
                </div>
              </div>

              <details className="rounded-lg border border-border/60 bg-muted/10 p-2.5 xl:hidden">
                <summary className={cn(systemPageTokens.microLabel, 'list-none cursor-pointer select-none')}>
                  更多筛选
                </summary>
                <div className="mt-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label htmlFor="audit-resource-type-mobile" className={systemPageTokens.microLabel}>资源类型（resource_type）</Label>
                    <Input id="audit-resource-type-mobile" className={DENSE_INPUT} placeholder="输入 resource_type" value={filters.resource_type} onChange={(e) => setFilters((p) => ({ ...p, resource_type: e.target.value }))} />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="audit-resource-id-mobile" className={systemPageTokens.microLabel}>资源 ID（resource_id）</Label>
                    <Input id="audit-resource-id-mobile" className={DENSE_INPUT} placeholder="输入 resource_id" value={filters.resource_id} onChange={(e) => setFilters((p) => ({ ...p, resource_id: e.target.value }))} />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="audit-since-mobile" className={systemPageTokens.microLabel}>开始时间</Label>
                    <Input
                      id="audit-since-mobile"
                      className={DENSE_INPUT}
                      type="datetime-local"
                      value={filters.since}
                      onChange={(e) => setFilters((p) => ({ ...p, since: e.target.value }))}
                      title="开始时间"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="audit-until-mobile" className={systemPageTokens.microLabel}>结束时间</Label>
                    <Input
                      id="audit-until-mobile"
                      className={DENSE_INPUT}
                      type="datetime-local"
                      value={filters.until}
                      onChange={(e) => setFilters((p) => ({ ...p, until: e.target.value }))}
                      title="结束时间"
                    />
                  </div>
                </div>
              </details>
            </div>
            <div className={cn('mt-3 flex flex-col gap-2 text-xs sm:flex-row sm:items-center sm:justify-between', systemPageTokens.body)}>
              <div>{t('pagination.status', { total, page, totalPages })}</div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className={DENSE_OUTLINE_BUTTON}
                  onClick={() => setSkip((v) => Math.max(0, v - limit))}
                  disabled={skip <= 0}
                >
                  {t('pagination.previous')}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className={DENSE_OUTLINE_BUTTON}
                  onClick={() => setSkip((v) => (v + limit < total ? v + limit : v))}
                  disabled={skip + limit >= total}
                >
                  {t('pagination.next')}
                </Button>
              </div>
            </div>
          </Panel>

          <Panel padding="md" className={cn('mt-3', DENSE_PANEL)}>
            {(() => {
    if (resp) {
        if (items.length === 0) {
            return (<EmptyState
                      icon={ScrollText}
                      title={t('emptyState.title')}
                      description={t('emptyState.description')}
                    />);
        }
        else {
            return (<div className="space-y-2">
                {items.map((it) => {
                    const expanded = expandedId === it.id;
                    const resource = [it.resource_type, it.resource_id].filter(Boolean).join(': ');
                    return (<div key={it.id} className={cn('rounded-lg border border-border/70 bg-background transition-colors hover:bg-muted/15', expanded && 'border-primary/40')}>
                      <div className="flex items-start justify-between gap-2.5 px-3 py-1.5">
                        <button type="button" className="flex-1 text-left min-w-0" onClick={() => setExpandedId(expanded ? null : it.id)}>
                          <div className={cn('flex items-center gap-2', systemPageTokens.monoMeta)}>
                            <span className="font-mono">{fmtTs(it.created_at)}</span>
                            {it.actor_id ? <span className="font-mono">操作者: {it.actor_id}</span> : null}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-2">
                            <span className="text-[13px] font-semibold text-foreground">{it.action}</span>
                            {resource ? (<span className={cn(systemPageTokens.monoMeta, 'text-[11px]')}>{resource}</span>) : null}
                            {it.request_id ? (<span className={cn(systemPageTokens.monoMeta, 'text-[11px]')}>请求: {shorten(it.request_id)}</span>) : null}
                          </div>
                        </button>
                        <div className="flex items-center gap-1.5">
                          {it.request_id ? (<Button variant="outline" size="sm" className={DENSE_INLINE_ACTION} onClick={() => {
                                setSkip(0);
                                setFilters((p) => ({ ...p, request_id: it.request_id || '' }));
                            }} title={t('actions.requestFilterTitle')}>
                              <Search className="w-4 h-4"/>
                              请求
                            </Button>) : null}
                          <Button variant="outline" size="sm" className={DENSE_INLINE_ACTION} onClick={() => detachPromise(copyText(JSON.stringify(it.details || {}, null, 2), t('toasts.copySuccess'), t('toasts.copyFailure')))}>
                            <Copy className="w-4 h-4"/>
                            JSON
                          </Button>
                        </div>
                      </div>

                      {expanded ? (<div className="px-3 pb-3">
                          <pre className="max-h-[280px] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border/60 bg-muted/20 p-3 text-[11px]">
                            {JSON.stringify(it.details || {}, null, 2)}
                          </pre>
                        </div>) : null}
                    </div>);
                })}
              </div>);
        }
    }
    else {
        return (<div className={systemPageTokens.body}>
                {t('alerts.unableToLoad')}
              </div>);
    }
})()}
          </Panel>
        </PageScaffold>
      </div>
    </AppFrame>
  )
}

function shorten(id: string) {
  const v = (id || '').trim()
  if (!v) return ''
  return v.length > 16 ? `${v.slice(0, 8)}…${v.slice(-6)}` : v
}
