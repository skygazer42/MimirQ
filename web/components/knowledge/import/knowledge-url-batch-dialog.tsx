'use client'

import type { ConnectorRunOut, Dataset, DocumentAccessMode } from '@/types'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GroupChipsInput } from '@/components/groups/group-chips-input'
import { Button } from '@/components/ui/button'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { formatApiError } from '@/lib/api-errors'
import { connectorApi } from '@/lib/api'
import { detachPromise } from '@/lib/utils'


function parseUrlBatchUrls(raw: string): string[] {
  const parts = (raw || '')
    .split(/[\n,;]+/g)
    .map((s) => s.trim())
    .filter(Boolean)
  const out: string[] = []
  const seen = new Set<string>()

  for (const p of parts) {
    if (!/^https?:\/\//i.test(p)) continue
    if (seen.has(p)) continue
    seen.add(p)
    out.push(p)
    if (out.length >= 50) break
  }

  return out
}

function parseAccessMembers(raw: string): string[] {
  const parts = (raw || '')
    .split(/[\n,;]+/g)
    .map((s) => s.trim())
    .filter(Boolean)
  const out: string[] = []
  const seen = new Set<string>()

  for (const p of parts) {
    if (seen.has(p)) continue
    seen.add(p)
    out.push(p)
    if (out.length >= 200) break
  }

  return out
}

type KnowledgeUrlBatchDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void

  datasets: Dataset[]
  datasetsLoading: boolean
  selectedDatasetId?: string
  datasetDefaultValue: string

  loadDocuments: () => void | Promise<void>
  loadConnectorRuns: (params?: { datasetId?: string }) => void | Promise<void>
  onRunCreated?: (run: ConnectorRunOut) => void
}

export function KnowledgeUrlBatchDialog({
  open,
  onOpenChange,
  datasets,
  datasetsLoading,
  selectedDatasetId,
  datasetDefaultValue,
  loadDocuments,
  loadConnectorRuns,
  onRunCreated,
}: Readonly<KnowledgeUrlBatchDialogProps>) {
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()

  const [urls, setUrls] = useState('')
  const [filename, setFilename] = useState('')
  const [datasetId, setDatasetId] = useState<string>(datasetDefaultValue)
  const [accessMode, setAccessMode] = useState<DocumentAccessMode>('inherit')
  const [accessMembers, setAccessMembers] = useState('')
  const [accessGroupIds, setAccessGroupIds] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setDatasetId(selectedDatasetId || datasetDefaultValue)
  }, [datasetDefaultValue, open, selectedDatasetId])

  const parsedUrls = useMemo(() => parseUrlBatchUrls(urls), [urls])

  const handleSubmit = useCallback(async () => {
    if (!parsedUrls.length) {
      toast.error('请输入至少 1 个 http(s) URL（每行一个）')
      return
    }

    setSubmitting(true)
    try {
      const access =
        accessMode === 'inherit'
          ? null
          : {
              mode: accessMode,
              partial_member_list: accessMode === 'partial_members' ? parseAccessMembers(accessMembers) : null,
              partial_group_list: accessMode === 'partial_members' ? accessGroupIds : null,
            }

      const run = await connectorApi.createRun({
        connector_id: 'url_batch',
        dataset_id: datasetId === datasetDefaultValue ? undefined : datasetId,
        config: {
          urls: parsedUrls,
          filename: filename.trim() ? filename.trim() : undefined,
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
          access,
        },
      })

      toast.success(`已创建批量导入任务：${run.id.slice(0, 8)}`, {
        action: onRunCreated
          ? {
              label: '查看任务',
              onClick: () => onRunCreated(run),
            }
          : undefined,
      })
      onOpenChange(false)
      setUrls('')
      setFilename('')
      setAccessMode('inherit')
      setAccessMembers('')
      setAccessGroupIds([])
      detachPromise(loadConnectorRuns({ datasetId: selectedDatasetId }))
      detachPromise(loadDocuments())
    } catch (err: any) {
      toast.error(formatApiError(err, '创建 URL 批量导入失败'))
    } finally {
      setSubmitting(false)
    }
  }, [
    accessMembers,
    accessGroupIds,
    accessMode,
    chunkStrategy,
    datasetDefaultValue,
    datasetId,
    filename,
    loadConnectorRuns,
    loadDocuments,
    onOpenChange,
    parsedUrls,
    parserBackend,
    pipelineOptions,
    pipelineOverridesEnabled,
    selectedDatasetId,
    onRunCreated,
  ])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>URL 批量导入（Connector）</DialogTitle>
          <DialogDescription>一次导入多个 URL，并生成导入运行记录（需要后端开启 URL_INGEST_ENABLED）。</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">URLs（每行一个，最多 50）</div>
            <Textarea
              value={urls}
              onChange={(e) => setUrls(e.target.value)}
              placeholder={'https://example.com/doc1.pdf\nhttps://example.com/doc2.html'}
              className="font-mono min-h-[140px]"
            />
            <div className="text-xs text-muted-foreground">已识别 {parsedUrls.length} 个 URL（仅统计 http/https）。</div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">文件名（可选）</div>
              <Input value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="例如：产品手册.pdf" />
              <div className="text-xs text-muted-foreground">用于显示名/扩展名推断（对所有 URL 生效）。</div>
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">目标数据集</div>
              <Select value={datasetId} onValueChange={setDatasetId}>
                <SelectTrigger className="h-10 bg-background">
                  <SelectValue placeholder="选择数据集" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={datasetDefaultValue}>默认（自动选择可写数据集）</SelectItem>
                  {datasets.map((ds) => (
                    <SelectItem key={ds.id} value={ds.id}>
                      {ds.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {datasetsLoading ? <div className="text-xs text-muted-foreground">正在加载数据集...</div> : null}
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">文档访问控制（可选）</div>
            <Select value={accessMode} onValueChange={(v) => setAccessMode(v as DocumentAccessMode)}>
              <SelectTrigger className="h-10 bg-background">
                <SelectValue placeholder="选择访问模式" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="inherit">继承数据集</SelectItem>
                <SelectItem value="only_me">仅我可见</SelectItem>
                <SelectItem value="partial_members">指定成员/组</SelectItem>
                <SelectItem value="all_team_members">团队成员</SelectItem>
              </SelectContent>
            </Select>
            {accessMode === 'partial_members' ? (
              <div className="space-y-4 pt-2">
                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground/80">允许组（可选）</div>
                  <GroupChipsInput
                    value={accessGroupIds}
                    onChange={setAccessGroupIds}
                    placeholder="选择组（组内成员将自动获得访问权限）"
                  />
                  <div className="text-xs text-muted-foreground">最多 200 个；仅支持当前租户已存在的组。</div>
                </div>

                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground/80">允许成员（每行一个 user_id）</div>
                  <Textarea
                    value={accessMembers}
                    onChange={(e) => setAccessMembers(e.target.value)}
                    placeholder={'alice\nbob\ncharlie'}
                    className="font-mono min-h-[110px]"
                  />
                  <div className="text-xs text-muted-foreground">最多 200 个；仅支持当前租户已存在的成员。</div>
                </div>
              </div>
            ) : null}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">解析方式</div>
              <ParserDropdown value={parserBackend} onChange={setParserBackend} />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">切块策略</div>
              <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
            </div>
          </div>

          <PipelineOptionsPanel />

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              取消
            </Button>
            <Button onClick={handleSubmit} disabled={submitting} className="gap-2">
              {submitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
              开始导入
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
