'use client'

import { useCallback, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileUp, RefreshCw, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { pipelineApi } from '@/lib/api'
import type { DocumentPipelineOptions } from '@/types'
import { toast } from 'sonner'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'

type Props = {
  className?: string
  compact?: boolean
  onApplyPatch: (patch: Partial<DocumentPipelineOptions>) => void
}

const SELECT_NONE = '__none__'

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function GovernanceProfileSelector({ className, compact, onApplyPatch }: Readonly<Props>) {
  const queryClient = useQueryClient()
  const [selectedRef, setSelectedRef] = useState<string>(SELECT_NONE)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const profilesQuery = useQuery({
    queryKey: queryKeys.governance.profiles({ include_builtin: true, limit: 200 }),
    queryFn: async () => {
      try {
        const res = await pipelineApi.listGovernanceProfiles({ include_builtin: true, limit: 200 })
        return res.items || []
      } catch (e) {
        console.error('Failed to load governance profiles', e)
        toast.error(formatApiError(e, '加载治理预设失败'))
        return []
      }
    },
  })

  const selectedResolvedQuery = useQuery({
    queryKey: queryKeys.governance.profileResolved(selectedRef),
    queryFn: async () => {
      if (!selectedRef || selectedRef === SELECT_NONE) return null
      try {
        return await pipelineApi.getGovernanceProfileResolved(selectedRef)
      } catch (e) {
        console.error('Failed to load governance profile detail', e)
        toast.error(formatApiError(e, '加载治理预设详情失败'))
        return null
      }
    },
    enabled: Boolean(selectedRef && selectedRef !== SELECT_NONE),
  })

  const profiles = useMemo(() => profilesQuery.data || [], [profilesQuery.data])
  const selectedResolved = selectedResolvedQuery.data || null
  const loading = profilesQuery.isFetching

  const selectedSummary = useMemo(() => {
    if (!selectedRef || selectedRef === SELECT_NONE) return null
    return profiles.find((p) => p.key === selectedRef || p.id === selectedRef) || null
  }, [profiles, selectedRef])

  const handleApply = useCallback(() => {
    const resolved = selectedResolved
    const profile = resolved?.profile
    const effective = resolved?.effective
    if (!profile || !effective) {
      toast.error('请先选择一个治理预设')
      return
    }

    const normalizedRegexRules = Array.isArray(effective.regex_rules)
      ? effective.regex_rules
          .map((r) => ({
            pattern: String(r?.pattern || '').trim(),
            repl: String(r?.repl ?? ''),
            flags: Number(r?.flags ?? 0),
          }))
          .filter((r) => r.pattern.length > 0)
      : []

    const patch: Partial<DocumentPipelineOptions> = {
      ...effective.pipeline_patch,
      governance_regex_rules: normalizedRegexRules,
      governance_enabled: true,
    }
    onApplyPatch(patch)
    toast.success(`已应用预设：${profile.name}`)
  }, [selectedResolved, onApplyPatch])

  const handleImportClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleImportFile = useCallback(async (file: File | null) => {
    if (!file) return
    try {
      const res = await pipelineApi.importGovernanceProfiles(file, true /* overwrite */)
      toast.success(`导入成功：新增 ${res.created} / 更新 ${res.updated}`)
      await queryClient.invalidateQueries({
        queryKey: queryKeys.governance.profiles({ include_builtin: true, limit: 200 }),
      })
    } catch (e) {
      console.error('Failed to import governance profiles', e)
      toast.error(formatApiError(e, '导入失败（请检查脚本格式/正则是否安全）'))
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [queryClient])

  const handleExport = useCallback(async () => {
    if (!selectedRef || selectedRef === SELECT_NONE) {
      toast.error('请先选择一个治理预设')
      return
    }
    try {
      const blob = await pipelineApi.exportGovernanceProfile(selectedRef)
      const safe = (selectedSummary?.name || selectedRef).replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.governance-profile.json`)
    } catch (e) {
      console.error('Failed to export governance profile', e)
      toast.error(formatApiError(e, '导出失败'))
    }
  }, [selectedRef, selectedSummary])

  const triggerCls = compact
    ? 'h-8 rounded-lg border-border/50 bg-card/85 text-[11px] font-medium text-foreground/80 shadow-none'
    : 'h-9 rounded-lg border-border/50 bg-card/85 text-sm font-medium text-foreground/80 shadow-none'
  const primaryActionClass =
    'h-8 gap-2 rounded-lg border-primary/25 bg-primary/10 text-primary shadow-none hover:border-primary/35 hover:bg-primary/20 hover:text-primary'
  const secondaryActionClass =
    'h-8 gap-2 rounded-lg border-border/50 bg-background/60 text-foreground/70 shadow-none hover:bg-muted/45 hover:text-foreground'

  const inheritanceText = useMemo(() => {
    const chain = selectedResolved?.chain || []
    if (!chain.length) return ''
    return chain.map((c) => c.name || c.key).join(' → ')
  }, [selectedResolved?.chain])

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <Select value={selectedRef} onValueChange={setSelectedRef} disabled={loading}>
            <SelectTrigger className={cn('w-full', triggerCls)}>
              <SelectValue placeholder={loading ? '加载治理预设…' : '选择治理预设（Profiles/脚本）'} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={SELECT_NONE}>不使用预设</SelectItem>
              {profiles.map((p) => (
                <SelectItem key={p.key || p.id || p.name} value={p.key || p.id || p.name}>
                  {p.is_system ? '内置' : '自定义'} · {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant="outline"
          size={compact ? 'sm' : 'default'}
          onClick={() => profilesQuery.refetch()}
          disabled={loading}
          aria-label="刷新治理预设"
          title="刷新治理预设"
          className="h-8 rounded-lg border-border/50 bg-background/70 px-2.5 text-muted-foreground shadow-none hover:text-foreground"
        >
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {selectedSummary?.description && (
        <div className={cn('text-muted-foreground/80', compact ? 'text-[10.5px]' : 'text-xs')}>
          {selectedSummary.description}
        </div>
      )}

      {inheritanceText ? (
        <div className={cn('text-muted-foreground/75', compact ? 'text-[10.5px]' : 'text-xs')}>
          继承链：{inheritanceText}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-border/35 bg-background/45 p-1.5">
        <Button
          onClick={handleApply}
          size={compact ? 'sm' : 'default'}
          variant="outline"
          className={primaryActionClass}
          disabled={!selectedResolved}
        >
          <Sparkles className="w-4 h-4" />
          应用到当前配置
        </Button>
        <Button
          variant="outline"
          onClick={handleImportClick}
          size={compact ? 'sm' : 'default'}
          className={secondaryActionClass}
        >
          <FileUp className="w-4 h-4" />
          导入脚本
        </Button>
        <Button
          variant="outline"
          onClick={handleExport}
          size={compact ? 'sm' : 'default'}
          className={secondaryActionClass}
          disabled={!selectedRef || selectedRef === SELECT_NONE}
        >
          <Download className="w-4 h-4" />
          导出
        </Button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(e) => handleImportFile(e.target.files?.[0] || null)}
      />
    </div>
  )
}
