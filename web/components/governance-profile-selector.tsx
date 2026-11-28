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

  const inheritanceText = selectedResolved?.chain.map((profile) => profile.name).join(' → ')

  return (
    <div className={cn(compact ? 'space-y-2' : 'space-y-3', className)}>
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <Select value={selectedRef} onValueChange={setSelectedRef} disabled={profilesQuery.isLoading}>
            <SelectTrigger
              aria-label="治理预设"
              className="h-9 w-full rounded-md border-border bg-card text-[13px] font-normal text-foreground shadow-none"
            >
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
          size="icon"
          onClick={refreshProfiles}
          disabled={profilesQuery.isFetching || selectedResolvedQuery.isFetching || isImporting}
          aria-label="刷新治理预设"
          title="刷新治理预设"
          className="h-9 w-9 shrink-0 rounded-md border-border bg-card text-muted-foreground shadow-none hover:text-foreground"
        >
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Button
          onClick={handleApply}
          size="sm"
          variant="outline"
          className="h-8 gap-1.5 rounded-md border-border bg-card px-3 text-xs font-medium shadow-none sm:h-8"
          disabled={!canApply}
        >
          <Sparkles className="w-4 h-4" />
          应用到当前配置
        </Button>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <LoadingButton
            variant="ghost"
            loading={isImporting}
            onClick={() => fileInputRef.current?.click()}
            size="sm"
            className="h-8 gap-1.5 rounded-md px-2.5 text-xs text-muted-foreground hover:text-foreground sm:h-8"
          >
            <FileUp className="w-4 h-4" />
            导入脚本
          </LoadingButton>
          <Button
            variant="ghost"
            onClick={handleExport}
            size="sm"
            className="h-8 gap-1.5 rounded-md px-2.5 text-xs text-muted-foreground hover:text-foreground sm:h-8"
            disabled={selectedRef === SELECT_NONE}
          >
            <Download className="w-4 h-4" />
            导出
          </Button>
        </div>
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
        <p role="status" className="text-xs leading-5 text-muted-foreground">
          网络恢复后将重新读取治理预设详情。
        </p>
      )}

      {selectedSummary?.description && (
        <div className="text-xs leading-5 text-muted-foreground">{selectedSummary.description}</div>
      )}

      {inheritanceText ? (
        <div className="text-xs leading-5 text-muted-foreground">继承链：{inheritanceText}</div>
      ) : null}

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
