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
import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { AuditLogItem, AuditLogListResponse } from '@/types'
import { cn, detachPromise } from '@/lib/utils'
import { EmptyState } from '@/components/ui/empty-state'

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

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title={t('title')}
          description={t('description')}
          icon={ShieldCheck}
          iconColor="text-success"
          size="7xl"
          actions={
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="gap-2 rounded-xl"
                onClick={() => detachPromise(load())}
                disabled={loading}
              >
                <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
                {t('actions.refresh')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="gap-2 rounded-xl"
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
          <Panel padding="lg" className="mt-4">
            <div className="flex flex-wrap items-center gap-2">
            <div className="text-xs text-muted-foreground">{t('labels.quickPresets')}</div>
              {presets.map((p) => (
                <Button
                  key={p.action}
                  size="sm"
                  variant="outline"
                  className="h-8 rounded-xl"
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

            <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label htmlFor="audit-action" className="text-xs text-muted-foreground">Action</Label>
                <Input id="audit-action" placeholder="e.g. chat.ask" value={filters.action} onChange={(e) => setFilters((p) => ({ ...p, action: e.target.value }))} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="audit-actor" className="text-xs text-muted-foreground">Actor ID</Label>
                <Input id="audit-actor" placeholder="actor_id" value={filters.actor_id} onChange={(e) => setFilters((p) => ({ ...p, actor_id: e.target.value }))} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="audit-request" className="text-xs text-muted-foreground">Request ID</Label>
                <Input id="audit-request" placeholder="request_id" value={filters.request_id} onChange={(e) => setFilters((p) => ({ ...p, request_id: e.target.value }))} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="audit-resource-type" className="text-xs text-muted-foreground">Resource Type</Label>
                <Input id="audit-resource-type" placeholder="resource_type" value={filters.resource_type} onChange={(e) => setFilters((p) => ({ ...p, resource_type: e.target.value }))} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="audit-resource-id" className="text-xs text-muted-foreground">Resource ID</Label>
                <Input id="audit-resource-id" placeholder="resource_id" value={filters.resource_id} onChange={(e) => setFilters((p) => ({ ...p, resource_id: e.target.value }))} />
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="datetime-local"
                  value={filters.since}
                  onChange={(e) => setFilters((p) => ({ ...p, since: e.target.value }))}
                  title="since"
                />
                <Input
                  type="datetime-local"
                  value={filters.until}
                  onChange={(e) => setFilters((p) => ({ ...p, until: e.target.value }))}
                  title="until"
                />
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
              <div>{t('pagination.status', { total, page, totalPages })}</div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 gap-2"
                  onClick={() => setSkip((v) => Math.max(0, v - limit))}
                  disabled={skip <= 0}
                >
                  {t('pagination.previous')}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 gap-2"
                  onClick={() => setSkip((v) => (v + limit < total ? v + limit : v))}
                  disabled={skip + limit >= total}
                >
                  {t('pagination.next')}
                </Button>
              </div>
            </div>
          </Panel>

          <Panel padding="lg" className="mt-4">
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
                    return (<div key={it.id} className={cn('rounded-xl border border-border/60 bg-background hover:bg-muted/10 transition-colors', expanded && 'border-primary/30')}>
                      <div className="p-3 flex items-start justify-between gap-3">
                        <button type="button" className="flex-1 text-left min-w-0" onClick={() => setExpandedId(expanded ? null : it.id)}>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span className="font-mono">{fmtTs(it.created_at)}</span>
                            {it.actor_id ? <span className="font-mono">actor: {it.actor_id}</span> : null}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold text-foreground">{it.action}</span>
                            {resource ? (<span className="text-xs text-muted-foreground font-mono">{resource}</span>) : null}
                            {it.request_id ? (<span className="text-xs text-muted-foreground font-mono">req: {shorten(it.request_id)}</span>) : null}
                          </div>
                        </button>
                        <div className="flex items-center gap-2">
                          {it.request_id ? (<Button variant="outline" size="sm" className="h-8 gap-2" onClick={() => {
                                setSkip(0);
                                setFilters((p) => ({ ...p, request_id: it.request_id || '' }));
                            }} title={t('actions.requestFilterTitle')}>
                              <Search className="w-4 h-4"/>
                              req
                            </Button>) : null}
                          <Button variant="outline" size="sm" className="h-8 gap-2" onClick={() => detachPromise(copyText(JSON.stringify(it.details || {}, null, 2), t('toasts.copySuccess'), t('toasts.copyFailure')))}>
                            <Copy className="w-4 h-4"/>
                            JSON
                          </Button>
                        </div>
                      </div>

                      {expanded ? (<div className="px-3 pb-3">
                          <pre className="text-xs whitespace-pre-wrap break-words rounded-lg border border-border/60 bg-muted/20 p-3 max-h-[320px] overflow-auto">
                            {JSON.stringify(it.details || {}, null, 2)}
                          </pre>
                        </div>) : null}
                    </div>);
                })}
              </div>);
        }
    }
    else {
        return (<div className="text-sm text-muted-foreground">
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
