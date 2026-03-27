'use client'

import type { Dataset } from '@/types'
import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { Button } from '@/components/ui/button'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { formatApiError } from '@/lib/api-errors'

type KnowledgeUrlImportDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void

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

  useEffect(() => {
    if (!open) return
    setDatasetId(selectedDatasetId || datasetDefaultValue)
    setUrlError(null)
  }, [open, selectedDatasetId, datasetDefaultValue])

  const handleImport = useCallback(async () => {
    const nextUrl = url.trim()
    if (!nextUrl) {
      setUrlError('请输入 URL')
      return
    }

    let normalizedUrl: string
    try {
      // Keep this permissive (any valid absolute URL) and let the backend enforce policy.
      // This is primarily an inline UX guard so users don't submit empty/garbled text.
      normalizedUrl = new URL(nextUrl).toString()
    } catch {
      setUrlError('请输入完整 URL（例如 https://example.com/doc.pdf）')
      return
    }

    setSubmitting(true)
    try {
      await uploadDocumentFromUrl({
        url: normalizedUrl,
        filename: filename.trim() ? filename.trim() : undefined,
        dataset_id: datasetId === datasetDefaultValue ? undefined : datasetId,
      })

      toast.success('已提交 URL 导入任务（后台拉取并入库）')
      onOpenChange(false)
      setUrl('')
      setUrlError(null)
      setFilename('')
      Promise.resolve(onAfterImport?.()).catch(() => {
        // Best-effort refresh.
      })
    } catch (err: any) {
      toast.error(formatApiError(err, 'URL 导入失败'))
    } finally {
      setSubmitting(false)
    }
  }, [datasetDefaultValue, datasetId, filename, onAfterImport, onOpenChange, uploadDocumentFromUrl, url])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>通过 URL 导入文档</DialogTitle>
          <DialogDescription>
            后端拉取 URL 内容并按当前管线配置入库（需要后端开启 URL_INGEST_ENABLED）。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">URL</div>
              <Input
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value)
                  if (urlError) setUrlError(null)
                }}
                placeholder="https://example.com/doc.pdf / https://example.com/page.html"
                className="font-mono"
                aria-invalid={Boolean(urlError)}
                aria-describedby={urlError ? 'knowledge-url-import-url-error' : undefined}
              />
              {urlError ? (
                <div id="knowledge-url-import-url-error" className="text-xs text-destructive text-pretty">
                  {urlError}
                </div>
              ) : null}
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">文件名（可选）</div>
              <Input value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="例如：产品手册.pdf" />
            </div>
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
            <Button onClick={handleImport} disabled={submitting || !url.trim()} className="gap-2">
              {submitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
              开始导入
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
