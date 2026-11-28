'use client'

import type { Dataset } from '@/types/datasets'
import { useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { Loader2 } from '@/components/icons'
import { toast } from 'sonner'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { Button } from '@/components/ui/button'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionRevision } from '@/lib/auth-storage'
import { reportClientError } from '@/lib/client-logging'

type KnowledgeUrlImportDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCloseAutoFocus?: (event: Event) => void

  datasets: Dataset[]
  datasetsLoading: boolean
  selectedDatasetId?: string
  datasetDefaultValue: string

  uploadDocumentFromUrl: (params: { url: string; filename?: string; dataset_id?: string }) => Promise<unknown>

  onAfterImport?: () => void | Promise<void>
}

export function KnowledgeUrlImportDialog({
  open,
  onOpenChange,
  onCloseAutoFocus,
  datasets,
  datasetsLoading,
  selectedDatasetId,
  datasetDefaultValue,
  uploadDocumentFromUrl,
  onAfterImport,
}: Readonly<KnowledgeUrlImportDialogProps>) {
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()

  const [url, setUrl] = useState('')
  const [urlError, setUrlError] = useState<string | null>(null)
  const [filename, setFilename] = useState('')
  const [datasetId, setDatasetId] = useState<string>(datasetDefaultValue)
  const [submitting, setSubmitting] = useState(false)
  const submissionRef = useRef<{ authRevision: number } | null>(null)
  const formId = useId()
  const urlErrorId = `${formId}-url-error`
  const trimmedUrl = url.trim()

  useLayoutEffect(() => {
    setSubmitting(false)
    if (open) {
      setDatasetId(selectedDatasetId ?? datasetDefaultValue)
      setUrlError(null)
    }
    return () => {
      submissionRef.current = null
    }
  }, [open, selectedDatasetId, datasetDefaultValue])

  async function handleImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!open || submissionRef.current) return
    if (trimmedUrl.length === 0) {
      setUrlError('请输入 URL')
      return
    }

    let parsedUrl: URL
    try {
      parsedUrl = new URL(trimmedUrl)
    } catch {
      setUrlError('请输入完整 URL（例如 https://example.com/doc.pdf）')
      return
    }
    if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
      setUrlError('文档地址须使用 HTTP 或 HTTPS')
      return
    }

    const trimmedFilename = filename.trim()
    const submission = { authRevision: getAuthSessionRevision() }
    submissionRef.current = submission
    const ownsSubmission = () =>
      submissionRef.current === submission && submission.authRevision === getAuthSessionRevision()
    setSubmitting(true)
    try {
      await uploadDocumentFromUrl({
        url: parsedUrl.toString(),
        filename: trimmedFilename.length === 0 ? undefined : trimmedFilename,
        dataset_id: datasetId === datasetDefaultValue ? undefined : datasetId,
      })

      if (onAfterImport !== undefined) {
        void Promise.resolve()
          .then(() => {
            if (submission.authRevision === getAuthSessionRevision()) return onAfterImport()
          })
          .catch((error) => reportClientError('Refresh after URL import failed', error))
      }
      if (!ownsSubmission()) return
      toast.success('已提交 URL 导入任务（后台拉取并入库）')
      onOpenChange(false)
      setUrl('')
      setUrlError(null)
      setFilename('')
    } catch (err: unknown) {
      if (!ownsSubmission()) return
      toast.error(formatApiError(err, 'URL 导入失败'))
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
        onCloseAutoFocus={onCloseAutoFocus}
        showCloseButton={!submitting}
        className="flex max-h-[min(88dvh,820px)] w-[calc(100%_-_2rem)] max-w-2xl flex-col gap-0 overflow-hidden rounded-xl p-0"
      >
        <DialogHeader className="shrink-0 border-b border-border/75 bg-popover px-6 pt-6 pb-4 text-left">
          <DialogTitle>通过 URL 导入文档</DialogTitle>
          <DialogDescription>
            输入要导入的网页地址。
          </DialogDescription>
        </DialogHeader>

        <div
          data-knowledge-dialog-body="true"
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain custom-scrollbar px-6 py-5"
        >
          <fieldset disabled={submitting} className="m-0 min-w-0 border-0 p-0 space-y-5">
            <legend className="sr-only">URL 导入配置</legend>
            <form id={formId} onSubmit={handleImport} className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor={`${formId}-url`} className="text-foreground/80">
                  URL
                </Label>
                <Input
                  id={`${formId}-url`}
                  inputMode="url"
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value)
                    if (urlError) setUrlError(null)
                  }}
                  placeholder="https://example.com/doc.pdf / https://example.com/page.html"
                  className="font-mono"
                  aria-invalid={urlError !== null}
                  aria-describedby={urlError === null ? undefined : urlErrorId}
                />
                {urlError !== null ? (
                  <div id={urlErrorId} role="alert" className="text-xs text-destructive text-pretty">
                    {urlError}
                  </div>
                ) : null}
              </div>
              <div className="space-y-2">
                <Label htmlFor={`${formId}-filename`} className="text-foreground/80">
                  文件名（可选）
                </Label>
                <Input
                  id={`${formId}-filename`}
                  value={filename}
                  onChange={(e) => setFilename(e.target.value)}
                  placeholder="例如：产品手册.pdf"
                />
              </div>
            </form>

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
          </fieldset>
        </div>
        <DialogFooter className="shrink-0 gap-2 border-t border-border/75 bg-popover px-6 py-4 sm:space-x-0">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" form={formId} disabled={submitting || trimmedUrl.length === 0} className="gap-2">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
            开始导入
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
