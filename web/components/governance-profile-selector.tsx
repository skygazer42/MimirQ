'use client'

import { useRef, useState } from 'react'
import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileUp, RefreshCw, Sparkles } from '@/components/icons'
import { profileRef } from '@/components/governance-profiles/profile-presentation'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { pipelineApi } from '@/lib/api/pipeline'
import type { DocumentPipelineOptions } from '@/types/processing'
import { toast } from 'sonner'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { downloadBlob } from '@/lib/download'
import { queryKeys } from '@/lib/query-keys'

type GovernanceProfileSelectorProps = {
  className?: string
  compact?: boolean
  onApplyPatch: (patch: Partial<DocumentPipelineOptions>) => void
}

const SELECT_NONE = '__none__'
const PROFILE_PARAMS = { include_builtin: true, limit: 200 }

export function GovernanceProfileSelector({
  className,
  compact,
  onApplyPatch,
}: Readonly<GovernanceProfileSelectorProps>) {
  const queryClient = useQueryClient()
  const [selectedRef, setSelectedRef] = useState<string>(SELECT_NONE)
  const [isImporting, setIsImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const profilesQuery = useQuery({
    queryKey: queryKeys.governance.profiles(PROFILE_PARAMS),
    queryFn: ({ signal }) => pipelineApi.listGovernanceProfiles(PROFILE_PARAMS, { signal }),
  })

  const selectedResolvedQuery = useQuery({
    queryKey: queryKeys.governance.profileResolved(selectedRef),
    queryFn:
      selectedRef === SELECT_NONE
        ? skipToken
        : ({ signal }) => pipelineApi.getGovernanceProfileResolved(selectedRef, { signal }),
  })

  const profiles = profilesQuery.data?.items
  const selectedResolved = selectedResolvedQuery.data
  const selectedSummary = profiles?.find((profile) => profileRef(profile) === selectedRef)
  const canApply =
    selectedResolved !== undefined &&
    !isImporting &&
    selectedResolvedQuery.fetchStatus === 'idle' &&
    !selectedResolvedQuery.isError

  function handleApply() {
    if (!canApply) return
    const { profile, effective } = selectedResolved
    const regexRules = effective.regex_rules
      .map((rule) => ({ ...rule, pattern: rule.pattern.trim() }))
      .filter((rule) => rule.pattern.length > 0)
    onApplyPatch({
      ...effective.pipeline_patch,
      governance_regex_rules: regexRules,
      governance_enabled: true,
    })
    toast.success(`已应用预设：${profile.name}`)
  }

  async function handleImportFile(file: File) {
    if (isImporting) return
    setIsImporting(true)
    try {
      const result = await pipelineApi.importGovernanceProfiles(file, true)
      await queryClient.invalidateQueries({ queryKey: queryKeys.governance.all })
      toast.success(`导入成功：新增 ${result.created} / 更新 ${result.updated}`)
    } catch (error) {
      reportClientError('Failed to import governance profiles', error)
      toast.error(formatApiError(error, '导入治理预设失败'))
    } finally {
      setIsImporting(false)
    }
  }

  function refreshProfiles() {
    void profilesQuery.refetch()
    if (selectedRef !== SELECT_NONE) void selectedResolvedQuery.refetch()
  }

  async function handleExport() {
    if (selectedRef === SELECT_NONE) return
    try {
      const blob = await pipelineApi.exportGovernanceProfile(selectedRef)
      const filename = (selectedSummary?.name ?? selectedRef).replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(`${filename}.governance-profile.json`, blob)
    } catch (error) {
      reportClientError('Failed to export governance profile', error)
      toast.error(formatApiError(error, '导出治理预设失败'))
    }
  }

  const triggerCls = compact
    ? 'h-8 rounded-[0.9rem] border-border/45 bg-card/74 text-[11px] font-medium text-foreground/80 shadow-none'
    : 'h-9 rounded-[0.95rem] border-border/45 bg-card/78 text-sm font-medium text-foreground/80 shadow-none'
  const primaryActionClass =
    'h-7 gap-1.5 rounded-full border-primary/24 bg-primary/[0.09] px-2.5 text-[11px] font-semibold text-primary shadow-none hover:border-primary/34 hover:bg-primary/[0.16] hover:text-primary'
  const secondaryActionClass =
    'h-7 gap-1.5 rounded-full border-border/38 bg-background/36 px-2.5 text-[11px] font-medium text-muted-foreground/78 shadow-none hover:border-border/50 hover:bg-background/58 hover:text-foreground'
  const actionRailClass =
    'flex flex-wrap items-center justify-end gap-1 rounded-[0.95rem] border border-border/28 bg-muted/[0.10] px-1.5 py-1'

  const inheritanceText = selectedResolved?.chain.map((profile) => profile.name).join(' → ')

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-center gap-1.5">
        <div className="min-w-0 flex-1">
          <Select value={selectedRef} onValueChange={setSelectedRef} disabled={profilesQuery.isLoading}>
            <SelectTrigger aria-label="治理预设" className={cn('w-full', triggerCls)}>
              <SelectValue placeholder="选择治理预设" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={SELECT_NONE}>不使用预设</SelectItem>
              {profiles?.map((profile) => {
                const ref = profileRef(profile)
                return (
                  <SelectItem key={ref} value={ref}>
                    {profile.is_system ? '内置' : '自定义'} · {profile.name}
                  </SelectItem>
                )
              })}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant="outline"
          size={compact ? 'sm' : 'default'}
          onClick={refreshProfiles}
          disabled={profilesQuery.isFetching || selectedResolvedQuery.isFetching || isImporting}
          aria-label="刷新治理预设"
          title="刷新治理预设"
          className="h-8 rounded-[0.9rem] border-border/42 bg-background/46 px-2.5 text-muted-foreground shadow-none hover:bg-background/68 hover:text-foreground"
        >
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {profilesQuery.isError && (
        <WorkspaceNotice>{formatApiError(profilesQuery.error, '加载治理预设失败')}</WorkspaceNotice>
      )}
      {selectedResolvedQuery.isError && (
        <WorkspaceNotice retry={() => void selectedResolvedQuery.refetch()} pending={selectedResolvedQuery.isFetching}>
          {formatApiError(selectedResolvedQuery.error, '加载治理预设详情失败')}
        </WorkspaceNotice>
      )}
      {selectedResolvedQuery.isPaused && (
        <p role="status" className="text-xs text-muted-foreground">
          网络恢复后将重新读取治理预设详情。
        </p>
      )}

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

      <div className={actionRailClass}>
        <Button
          onClick={handleApply}
          size={compact ? 'sm' : 'default'}
          variant="outline"
          className={primaryActionClass}
          disabled={!canApply}
        >
          <Sparkles className="w-4 h-4" />
          应用到当前配置
        </Button>
        <LoadingButton
          variant="outline"
          loading={isImporting}
          onClick={() => fileInputRef.current?.click()}
          size={compact ? 'sm' : 'default'}
          className={secondaryActionClass}
        >
          <FileUp className="w-4 h-4" />
          导入脚本
        </LoadingButton>
        <Button
          variant="outline"
          onClick={handleExport}
          size={compact ? 'sm' : 'default'}
          className={secondaryActionClass}
          disabled={selectedRef === SELECT_NONE}
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
        onChange={(event) => {
          const file = event.currentTarget.files?.item(0)
          event.currentTarget.value = ''
          if (file != null) void handleImportFile(file)
        }}
      />
    </div>
  )
}
