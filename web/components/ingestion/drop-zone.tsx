'use client'

import * as React from 'react'
import { useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { FileUp, UploadCloud } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { datasetApi, documentApi } from '@/lib/api'
import type { Dataset } from '@/types'

export type DropZoneHandle = {
  triggerFilePicker: () => void
  uploadFiles: (files: File[]) => Promise<void>
}

const PARSER_STORAGE_KEY = 'mimirq.ingestion.dropParserBackend'

function readStoredParserBackend() {
  if (typeof window === 'undefined') return 'auto'
  return window.localStorage.getItem(PARSER_STORAGE_KEY) || 'auto'
}

function persistParserBackend(value: string) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(PARSER_STORAGE_KEY, value)
}

export const DropZone = React.forwardRef<DropZoneHandle, {
  datasetId: string | null
  onUploadComplete: () => void
}>(({ datasetId, onUploadComplete }, ref) => {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const dragCounterRef = useRef(0)
  const [overlayVisible, setOverlayVisible] = useState(false)
  const [invalidDrop, setInvalidDrop] = useState(false)
  const [dropConfirmOpen, setDropConfirmOpen] = useState(false)
  const [pendingDropFiles, setPendingDropFiles] = useState<File[] | null>(null)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('')
  const [parserBackend, setParserBackend] = useState(readStoredParserBackend)
  const fileCount = pendingDropFiles?.length ?? 0

  const { data: datasetsResponse } = useQuery({
    queryKey: ['drop-zone-datasets'],
    queryFn: () => datasetApi.list({ limit: 200 }),
    enabled: dropConfirmOpen && !datasetId,
    staleTime: 60_000,
  })

  const datasets = useMemo(() => datasetsResponse?.items ?? [], [datasetsResponse?.items])

  const uploadFiles = React.useCallback(async (files: File[]) => {
    if (!files.length) return
    const response = await documentApi.uploadBatch(files, {
      dataset_id: datasetId || selectedDatasetId || undefined,
      parser_backend: parserBackend,
      chunk_strategy: 'langchain_recursive',
      max_concurrent: 4,
    })
    persistParserBackend(parserBackend)
    if (response.failed_count > 0) {
      response.failed?.forEach((item) => toast.error(`${item.filename}: ${item.error || '上传失败'}`))
    }
    toast.success(`上传完成：成功 ${response.successful_count} / 失败 ${response.failed_count}`)
    onUploadComplete()
  }, [datasetId, onUploadComplete, parserBackend, selectedDatasetId])

  React.useImperativeHandle(ref, () => ({
    triggerFilePicker: () => inputRef.current?.click(),
    uploadFiles: async (files: File[]) => uploadFiles(files),
  }), [uploadFiles])

  React.useEffect(() => {
    const handleDragEnter = (event: DragEvent) => {
      dragCounterRef.current += 1
      setOverlayVisible(true)
      setInvalidDrop(!(event.dataTransfer?.types.includes('Files')))
    }

    const handleDragOver = (event: DragEvent) => {
      event.preventDefault()
      setOverlayVisible(true)
      setInvalidDrop(!(event.dataTransfer?.types.includes('Files')))
    }

    const handleDragLeave = () => {
      dragCounterRef.current = Math.max(0, dragCounterRef.current - 1)
      if (dragCounterRef.current === 0) {
        setOverlayVisible(false)
        setInvalidDrop(false)
      }
    }

    const handleDrop = async (event: DragEvent) => {
      event.preventDefault()
      dragCounterRef.current = 0
      setOverlayVisible(false)
      const droppedFiles = Array.from(event.dataTransfer?.files ?? [])
      if (!droppedFiles.length) {
        setInvalidDrop(true)
        return
      }
      if (datasetId) {
        await uploadFiles(droppedFiles)
        return
      }
      setPendingDropFiles(droppedFiles)
      setDropConfirmOpen(true)
    }

    document.addEventListener('dragenter', handleDragEnter)
    document.addEventListener('dragover', handleDragOver)
    document.addEventListener('dragleave', handleDragLeave)
    document.addEventListener('drop', handleDrop)
    return () => {
      document.removeEventListener('dragenter', handleDragEnter)
      document.removeEventListener('dragover', handleDragOver)
      document.removeEventListener('dragleave', handleDragLeave)
      document.removeEventListener('drop', handleDrop)
    }
  }, [datasetId, uploadFiles])

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="sr-only"
        onChange={async (event) => {
          const files = Array.from(event.target.files ?? [])
          if (!files.length) return
          if (datasetId) await uploadFiles(files)
          else {
            setPendingDropFiles(files)
            setDropConfirmOpen(true)
          }
          event.target.value = ''
        }}
      />

      {overlayVisible && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
          <div
            aria-live="polite"
            className="rounded-3xl border border-dashed border-white/50 bg-background/95 px-10 py-12 text-center shadow-strong"
          >
            <UploadCloud className="mx-auto h-10 w-10 text-sky-500" />
            <p className="mt-4 text-base font-semibold text-foreground">
              {invalidDrop ? '仅支持文件' : '拖入文件以开始入库'}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {invalidDrop ? '请放下本地文件，而不是链接或其它拖拽内容。' : `拖入 ${fileCount || '若干'} 个文件后即可开始上传。`}
            </p>
          </div>
        </div>
      )}

      <Dialog open={dropConfirmOpen} onOpenChange={setDropConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>选择上传目标</DialogTitle>
            <DialogDescription>当前 URL 未指定 `dataset_id`，请先选择一个数据集和解析后端。</DialogDescription>
          </DialogHeader>

          {datasets.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border/60 bg-muted/20 p-4 text-sm">
              <p className="font-medium text-foreground">尚无数据集,请先前往新建</p>
              <Button asChild className="mt-3" variant="outline">
                <Link href="/knowledge/datasets">前往新建</Link>
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="text-sm font-medium">数据集</div>
                <Select value={selectedDatasetId} onValueChange={setSelectedDatasetId}>
                  <SelectTrigger>
                    <SelectValue placeholder="选择数据集" />
                  </SelectTrigger>
                  <SelectContent>
                    {datasets.map((dataset: Dataset) => (
                      <SelectItem key={dataset.id} value={dataset.id}>
                        {dataset.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <div className="text-sm font-medium">parser_backend</div>
                <Select value={parserBackend} onValueChange={setParserBackend}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {['auto', 'docling', 'markitdown', 'deepdoc', 'csv', 'json', 'markdown'].map((value) => (
                      <SelectItem key={value} value={value}>
                        {value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="rounded-xl border border-border/60 bg-muted/20 p-3 text-sm text-muted-foreground">
                <div className="flex items-center gap-2 font-medium text-foreground">
                  <FileUp className="h-4 w-4" />
                  待上传 {pendingDropFiles?.length ?? 0} 个文件
                </div>
                <div className="mt-2 space-y-1">
                  {pendingDropFiles?.map((file) => (
                    <div key={`${file.name}-${file.size}`}>{file.name}</div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="ghost" onClick={() => setDropConfirmOpen(false)}>
              取消
            </Button>
            <Button
              disabled={!datasets.length || !selectedDatasetId || !pendingDropFiles?.length}
              onClick={async () => {
                if (!pendingDropFiles?.length) return
                await uploadFiles(pendingDropFiles)
                setPendingDropFiles(null)
                setDropConfirmOpen(false)
              }}
            >
              开始上传
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
})

DropZone.displayName = 'DropZone'
