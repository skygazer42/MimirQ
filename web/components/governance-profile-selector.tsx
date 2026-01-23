'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, FileUp, RefreshCw, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { pipelineApi } from '@/lib/api-client'
import type { DocumentPipelineOptions, GovernanceProfileOut, GovernanceProfileSummary } from '@/types'
import { toast } from 'sonner'

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

export function GovernanceProfileSelector({ className, compact, onApplyPatch }: Props) {
  const [loading, setLoading] = useState(false)
  const [profiles, setProfiles] = useState<GovernanceProfileSummary[]>([])
  const [selectedRef, setSelectedRef] = useState<string>(SELECT_NONE)
  const [selectedDetail, setSelectedDetail] = useState<GovernanceProfileOut | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const loadProfiles = useCallback(async () => {
    setLoading(true)
    try {
      const res = await pipelineApi.listGovernanceProfiles({ include_builtin: true, limit: 200 })
      setProfiles(res.items || [])
    } catch (e) {
      console.error('Failed to load governance profiles', e)
      setProfiles([])
      toast.error('加载治理预设失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadProfiles()
  }, [loadProfiles])

  const selectedSummary = useMemo(() => {
    if (!selectedRef || selectedRef === SELECT_NONE) return null
    return profiles.find((p) => p.key === selectedRef || p.id === selectedRef) || null
  }, [profiles, selectedRef])

  useEffect(() => {
    let cancelled = false
    const loadDetail = async () => {
      if (!selectedRef || selectedRef === SELECT_NONE) {
        setSelectedDetail(null)
        return
      }
      try {
        const res = await pipelineApi.getGovernanceProfile(selectedRef)
        if (cancelled) return
        setSelectedDetail(res)
      } catch (e) {
        if (cancelled) return
        console.error('Failed to load governance profile detail', e)
        setSelectedDetail(null)
      }
    }
    loadDetail()
    return () => {
      cancelled = true
    }
  }, [selectedRef])

  const handleApply = useCallback(() => {
    const profile = selectedDetail
    if (!profile) {
      toast.error('请先选择一个治理预设')
      return
    }

    const patch: Partial<DocumentPipelineOptions> = {
      ...(profile.payload?.pipeline_patch || {}),
      governance_regex_rules: Array.isArray(profile.payload?.regex_rules) ? profile.payload.regex_rules : [],
      governance_enabled: true,
    }
    onApplyPatch(patch)
    toast.success(`已应用预设：${profile.name}`)
  }, [selectedDetail, onApplyPatch])

  const handleImportClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleImportFile = useCallback(async (file: File | null) => {
    if (!file) return
    try {
      const res = await pipelineApi.importGovernanceProfiles(file, true /* overwrite */)
      toast.success(`导入成功：新增 ${res.created} / 更新 ${res.updated}`)
      await loadProfiles()
    } catch (e) {
      console.error('Failed to import governance profiles', e)
      toast.error('导入失败（请检查脚本格式/正则是否安全）')
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [loadProfiles])

  const handleExport = useCallback(async () => {
    if (!selectedRef || selectedRef === SELECT_NONE) {
      toast.error('请先选择一个治理预设')
      return
    }
    try {
      const blob = await pipelineApi.exportGovernanceProfile(selectedRef)
      const safe = (selectedSummary?.name || selectedRef).replace(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.governance-profile.json`)
    } catch (e) {
      console.error('Failed to export governance profile', e)
      toast.error('导出失败')
    }
  }, [selectedRef, selectedSummary])

  const triggerCls = compact ? 'h-8 text-xs' : 'h-9 text-sm'

  return (
    <div className={cn('space-y-2', className)}>
      <div className="flex items-center gap-2">
        <div className="flex-1 min-w-0">
          <Select value={selectedRef} onValueChange={setSelectedRef} disabled={loading}>
            <SelectTrigger className={cn('w-full', triggerCls)}>
              <SelectValue placeholder={loading ? '加载治理预设…' : '选择治理预设（Profiles/脚本）'} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={SELECT_NONE}>不使用预设</SelectItem>
              {profiles.map((p) => (
                <SelectItem key={p.key || p.id || p.name} value={p.key || (p.id as any)}>
                  {p.is_system ? '内置' : '自定义'} · {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button variant="outline" size={compact ? 'sm' : 'default'} onClick={loadProfiles} disabled={loading}>
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {selectedSummary?.description && (
        <div className={cn('text-muted-foreground', compact ? 'text-[11px]' : 'text-xs')}>
          {selectedSummary.description}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button
          onClick={handleApply}
          size={compact ? 'sm' : 'default'}
          className="gap-2"
          disabled={!selectedDetail}
        >
          <Sparkles className="w-4 h-4" />
          应用到当前配置
        </Button>
        <Button
          variant="outline"
          onClick={handleImportClick}
          size={compact ? 'sm' : 'default'}
          className="gap-2"
        >
          <FileUp className="w-4 h-4" />
          导入脚本
        </Button>
        <Button
          variant="outline"
          onClick={handleExport}
          size={compact ? 'sm' : 'default'}
          className="gap-2"
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

