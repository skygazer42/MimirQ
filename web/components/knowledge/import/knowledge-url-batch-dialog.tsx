'use client'

import type { DocumentAccessMode } from '@/types/common'
import type { ConnectorRunOut } from '@/types/connectors'
import type { Dataset } from '@/types/datasets'
import { useId, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Loader2 } from '@/components/icons'
import { toast } from 'sonner'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GroupChipsInput } from '@/components/groups/group-chips-input'
import { Button } from '@/components/ui/button'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionRevision } from '@/lib/auth-storage'
import { connectorApi } from '@/lib/api/connectors'
import { reportClientError } from '@/lib/client-logging'
import { documentAccessModeSchema } from '@/lib/document-access-schema'
import type { LoadConnectorRuns } from '@/hooks/use-connector-runs'
import { parseAccessMembers, parseHttpUrls } from './knowledge-import-parsers'

const URL_BATCH_LIMIT = 50

type KnowledgeUrlBatchDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void

  datasets: Dataset[]
  datasetsLoading: boolean
  selectedDatasetId?: string
  datasetDefaultValue: string

  loadDocuments: () => void | Promise<void>
  loadConnectorRuns: LoadConnectorRuns
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
  const submissionRef = useRef<{ authRevision: number } | null>(null)
  const formId = useId()
  const urlCountId = `${formId}-url-count`

  useLayoutEffect(() => {
    setSubmitting(false)
    if (open) setDatasetId(selectedDatasetId ?? datasetDefaultValue)
    return () => {
      submissionRef.current = null
    }
  }, [open, selectedDatasetId, datasetDefaultValue])

  const parsedUrls = useMemo(() => parseHttpUrls(urls, URL_BATCH_LIMIT + 1), [urls])
  const overLimit = parsedUrls.length > URL_BATCH_LIMIT

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!open || submissionRef.current || overLimit) return
    if (parsedUrls.length === 0) {
      toast.error('请输入至少 1 个 http(s) URL（每行一个）')
      return
    }

    const submission = { authRevision: getAuthSessionRevision() }
    submissionRef.current = submission
    const isSameSession = () => submission.authRevision === getAuthSessionRevision()
    const ownsSubmission = () => submissionRef.current === submission && isSameSession()
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

      const trimmedFilename = filename.trim()
      const run = await connectorApi.createRun({
        connector_id: 'url_batch',
        dataset_id: datasetId === datasetDefaultValue ? undefined : datasetId,
        config: {
          urls: parsedUrls,
          filename: trimmedFilename.length === 0 ? undefined : trimmedFilename,
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
          access,
        },
      })

      for (const refresh of [
        () => loadConnectorRuns({ datasetId: selectedDatasetId }, { selectScope: false }),
        loadDocuments,
      ]) {
        void Promise.resolve()
          .then(() => {
            if (isSameSession()) return refresh()
          })
          .catch((error) => reportClientError('Refresh after URL batch import failed', error))
      }
      if (!ownsSubmission()) return
      toast.success(`已创建批量导入任务：${run.id.slice(0, 8)}`, {
        action: onRunCreated
          ? {
              label: '查看任务',
              onClick: () => {
                if (isSameSession()) onRunCreated(run)
              },
            }
          : undefined,
      })
      onOpenChange(false)
      setUrls('')
      setFilename('')
      setAccessMode('inherit')
      setAccessMembers('')
      setAccessGroupIds([])
    } catch (err: unknown) {
      if (!ownsSubmission()) return
      toast.error(formatApiError(err, '创建 URL 批量导入失败'))
    } finally {
      if (submissionRef.current === submission) {
        submissionRef.current = null
        setSubmitting(false)
      }
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen || submissionRef.current === null) onOpenChange(nextOpen)
      }}
    >
      <DialogContent
        showCloseButton={!submitting}
        className="max-h-[calc(100dvh-2rem)] max-w-2xl overflow-y-auto overscroll-contain"
      >
        <DialogHeader>
          <DialogTitle>URL 批量导入（Connector）</DialogTitle>
          <DialogDescription>
            一次导入多个 URL，并生成导入运行记录（需要后端开启 URL_INGEST_ENABLED）。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <form id={formId} onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`${formId}-urls`} className="text-foreground/80">
                URLs（每行一个，最多 {URL_BATCH_LIMIT}）
              </Label>
              <Textarea
                id={`${formId}-urls`}
                value={urls}
                disabled={submitting}
                onChange={(e) => setUrls(e.target.value)}
                placeholder={'https://example.com/doc1.pdf\nhttps://example.com/doc2.html'}
                className="font-mono min-h-[140px]"
                aria-describedby={urlCountId}
                aria-invalid={overLimit}
              />
              {overLimit ? (
                <p id={urlCountId} role="alert" className="text-xs text-destructive">
                  每批最多导入 {URL_BATCH_LIMIT} 个 URL。
                </p>
              ) : (
                <p id={urlCountId} className="text-xs text-muted-foreground">
                  已识别 {parsedUrls.length} 个 URL（仅统计 http/https）。
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor={`${formId}-filename`} className="text-foreground/80">
                  文件名（可选）
                </Label>
                <Input
                  id={`${formId}-filename`}
                  value={filename}
                  disabled={submitting}
                  onChange={(e) => setFilename(e.target.value)}
                  placeholder="例如：产品手册.pdf"
                />
                <div className="text-xs text-muted-foreground">用于显示名/扩展名推断（对所有 URL 生效）。</div>
              </div>
              <div className="space-y-2">
                <Label htmlFor={`${formId}-dataset`} className="text-foreground/80">
                  目标数据集
                </Label>
                <Select value={datasetId} onValueChange={setDatasetId} disabled={submitting}>
                  <SelectTrigger id={`${formId}-dataset`} className="h-10 bg-background">
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
          </form>

          <div className="space-y-2">
            <Label htmlFor={`${formId}-access`} className="text-foreground/80">
              文档访问控制（可选）
            </Label>
            <Select
              value={accessMode}
              disabled={submitting}
              onValueChange={(value) => {
                const result = documentAccessModeSchema.safeParse(value)
                if (result.success) setAccessMode(result.data)
              }}
            >
              <SelectTrigger id={`${formId}-access`} className="h-10 bg-background">
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
                    disabled={submitting}
                    onChange={setAccessGroupIds}
                    placeholder="选择组（组内成员将自动获得访问权限）"
                  />
                  <div className="text-xs text-muted-foreground">最多 200 个；仅支持当前租户已存在的组。</div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor={`${formId}-members`} className="text-foreground/80">
                    允许成员（每行一个 user_id）
                  </Label>
                  <Textarea
                    id={`${formId}-members`}
                    value={accessMembers}
                    disabled={submitting}
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
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              取消
            </Button>
            <Button type="submit" form={formId} disabled={submitting || overLimit} className="gap-2">
              {submitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
              开始导入
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
