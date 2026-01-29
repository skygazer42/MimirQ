'use client'

import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'

import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EmptyState } from '@/components/ui/empty-state'
import { pipelineApi } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import type { GovernanceProfileListResponse, GovernanceProfileSummary } from '@/types'

export function GovernanceProfilesPage() {
  const [loading, setLoading] = useState(false)
  const [resp, setResp] = useState<GovernanceProfileListResponse | null>(null)
  const [query, setQuery] = useState('')
  const [includeBuiltin, setIncludeBuiltin] = useState(true)

  const params = useMemo(() => {
    const q = query.trim()
    return {
      q: q || undefined,
      include_builtin: includeBuiltin,
      limit: 200,
    }
  }, [query, includeBuiltin])

  const load = async () => {
    setLoading(true)
    try {
      const data = await pipelineApi.listGovernanceProfiles(params)
      setResp(data)
    } catch (err: any) {
      setResp(null)
      toast.error(err?.response?.data?.detail || err?.message || '加载治理 Profiles 失败')
    } finally {
      setLoading(false)
    }
  }

  // Keep it simple: fetch on param change.
  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  const items: GovernanceProfileSummary[] = resp?.items || []

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <PageScaffold
        title="治理 Profiles"
        description="创建/管理治理配置（清洗规则与 pipeline_patch），用于入库前的数据治理阶段。"
        icon={ShieldCheck}
        iconColor="text-emerald-600 dark:text-emerald-400"
        size="7xl"
        actions={
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="gap-2 rounded-xl"
              disabled={loading}
              onClick={() => void load()}
            >
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
          </div>
        }
      >
        <Panel className="mt-4" padding="lg">
          <div className="flex flex-col md:flex-row md:items-center gap-3">
            <Input
              placeholder="搜索 name/description/key"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button
              type="button"
              variant={includeBuiltin ? 'default' : 'outline'}
              className="rounded-xl"
              onClick={() => setIncludeBuiltin((v) => !v)}
            >
              {includeBuiltin ? '包含内置' : '仅自定义'}
            </Button>
          </div>
        </Panel>

        {items.length ? (
          <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {items.map((p) => (
              <Panel key={p.key} padding="lg" className="rounded-2xl">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="font-semibold text-foreground truncate">{p.name}</div>
                      {p.is_system ? (
                        <span className="px-2 py-0.5 rounded-full text-[11px] border border-border bg-muted/40 text-muted-foreground">
                          built-in
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[11px] border border-border bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                          custom
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-[12px] text-muted-foreground font-mono break-all">{p.key}</div>
                    {p.description ? (
                      <div className="mt-2 text-sm text-muted-foreground line-clamp-3">{p.description}</div>
                    ) : null}
                  </div>
                </div>
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            className="mt-6"
            title={loading ? '正在加载…' : '暂无 Profiles'}
            description={
              loading ? '请稍候' : '你可以创建一个自定义 Profile，或切换“包含内置”查看内置预设。'
            }
            icon={ShieldCheck}
          />
        )}
      </PageScaffold>
    </div>
  )
}

