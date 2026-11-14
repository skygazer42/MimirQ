'use client'

import * as React from 'react'
import { useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { FileUp, UploadCloud } from '@/components/icons'
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
import { datasetApi } from '@/lib/api/datasets'
import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionRevision } from '@/lib/auth-storage'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { detachPromise } from '@/lib/utils'
import type { Dataset } from '@/types'

export type DropZoneHandle = {
  triggerFilePicker: (options?: { precheckOnly?: boolean }) => void
  uploadFiles: (files: File[]) => Promise<void>
}

const PARSER_STORAGE_KEY = 'mimirq.ingestion.dropParserBackend'

function readStoredParserBackend() {
  if (globalThis.window === undefined) return 'auto'
  return readClientStorage(PARSER_STORAGE_KEY) || 'auto'
}

function persistParserBackend(value: string) {
  if (globalThis.window === undefined) return
  writeClientStorage(PARSER_STORAGE_KEY, value)
}

type DropZoneProps = {
  datasetId: string | null
  precheckOnly?: boolean
  onUploadComplete: () => void
}

type PendingDropUpload = {
  confirmation: object
  authRevision: number
  datasetId: string | undefined
  parserBackend: string
  precheckOnly: boolean
  files: File[]
}

export const DropZone = React.forwardRef<DropZoneHandle, DropZoneProps>(
  ({ datasetId, precheckOnly: defaultPrecheckOnly = false, onUploadComplete }, ref) => {
    const inputRef = useRef<HTMLInputElement | null>(null)
    const dragCounterRef = useRef(0)
    const uploadModeRef = useRef(defaultPrecheckOnly)
    const confirmationRef = useRef<object>({})
    const uploadsRef = useRef(new Map<PendingDropUpload, Promise<boolean>>())
    const mountedRef = useRef(false)
    const [overlayVisible, setOverlayVisible] = useState(false)
    const [invalidDrop, setInvalidDrop] = useState(false)
    const [dropConfirmOpen, setDropConfirmOpen] = useState(false)
    const [pendingDropFiles, setPendingDropFiles] = useState<File[] | null>(null)
    const [selectedDatasetId, setSelectedDatasetId] = useState<string>('')
    const [parserBackend, setParserBackend] = useState(readStoredParserBackend)
    const [dialogPrecheckOnly, setDialogPrecheckOnly] = useState(defaultPrecheckOnly)
    const [uploading, setUploading] = useState(false)
    const fileCount = pendingDropFiles?.length ?? 0

    const { data: datasetsResponse } = useQuery({
      queryKey: ['drop-zone-datasets'],
      queryFn: () => datasetApi.listAll(),
      enabled: dropConfirmOpen && !datasetId,
      staleTime: 60_000,
    })

    const datasets = useMemo(() => datasetsResponse ?? [], [datasetsResponse])

    React.useEffect(() => {
      mountedRef.current = true
      setUploading(false)
      return () => {
        mountedRef.current = false
        confirmationRef.current = {}
      }
    }, [datasetId])

    const changeConfirmationOpen = (open: boolean) => {
      if (!open) {
        confirmationRef.current = {}
        setUploading(false)
      }
      setDropConfirmOpen(open)
    }

    React.useEffect(() => {
      uploadModeRef.current = defaultPrecheckOnly
      setDialogPrecheckOnly(defaultPrecheckOnly)
    }, [defaultPrecheckOnly])

    const uploadFiles = React.useCallback(
      async (files: File[], options?: { precheckOnly?: boolean }) => {
        if (!files.length) return false
        const precheckOnly = options?.precheckOnly ?? uploadModeRef.current
        const targetDatasetId = datasetId || selectedDatasetId || undefined
        const confirmation = confirmationRef.current
        const authRevision = getAuthSessionRevision()
        for (const [pending, completion] of uploadsRef.current) {
          if (
            pending.confirmation === confirmation &&
            pending.authRevision === authRevision &&
            pending.datasetId === targetDatasetId &&
            pending.parserBackend === parserBackend &&
            pending.precheckOnly === precheckOnly &&
            pending.files.length === files.length &&
            pending.files.every((file, index) => file === files[index])
          )
            return completion
        }
        const upload: PendingDropUpload = {
          confirmation,
          authRevision,
          datasetId: targetDatasetId,
          parserBackend,
          precheckOnly,
          files: [...files],
        }
        const ownsUpload = () =>
          mountedRef.current && confirmationRef.current === confirmation && authRevision === getAuthSessionRevision()
        setUploading(true)
        const completion = (async () => {
          try {
            const response = await documentApi.uploadBatch(upload.files, {
              dataset_id: upload.datasetId,
              parser_backend: upload.parserBackend,
              chunk_strategy: 'langchain_recursive',
              precheck_only: upload.precheckOnly,
              max_concurrent: 4,
            })
            if (authRevision === getAuthSessionRevision()) onUploadComplete()
            if (!ownsUpload()) return true
            persistParserBackend(parserBackend)
            if (response.failed_count > 0) {
              response.failed?.forEach((item) => toast.error(`${item.filename}: ${item.error || '上传失败'}`))
            }
            const successLabel = precheckOnly ? '评估完成' : '上传完成'
            toast.success(`${successLabel}：成功 ${response.successful_count} / 失败 ${response.failed_count}`)
            return true
          } catch (error) {
            if (ownsUpload()) toast.error(formatApiError(error, '上传失败'))
            throw error
          } finally {
            uploadsRef.current.delete(upload)
            if (mountedRef.current && confirmationRef.current === confirmation) {
              setUploading(
                Array.from(uploadsRef.current.keys()).some(
                  (pending) =>
                    pending.confirmation === confirmation && pending.authRevision === getAuthSessionRevision(),
                ),
              )
            }
          }
        })()
        uploadsRef.current.set(upload, completion)
        return completion
      },
      [datasetId, onUploadComplete, parserBackend, selectedDatasetId],
    )

    React.useImperativeHandle(
      ref,
      () => ({
        triggerFilePicker: (options?: { precheckOnly?: boolean }) => {
          uploadModeRef.current = options?.precheckOnly ?? defaultPrecheckOnly
          setDialogPrecheckOnly(uploadModeRef.current)
          inputRef.current?.click()
        },
        uploadFiles: async (files: File[]) => {
          await uploadFiles(files)
        },
      }),
      [defaultPrecheckOnly, uploadFiles],
    )

    React.useEffect(() => {
      const handleDragEnter = (event: DragEvent) => {
        dragCounterRef.current += 1
        setOverlayVisible(true)
        setInvalidDrop(!event.dataTransfer?.types.includes('Files'))
      }

      const handleDragOver = (event: DragEvent) => {
        event.preventDefault()
        setOverlayVisible(true)
        setInvalidDrop(!event.dataTransfer?.types.includes('Files'))
      }

      const handleDragLeave = () => {
        dragCounterRef.current = Math.max(0, dragCounterRef.current - 1)
        if (dragCounterRef.current === 0) {
          setOverlayVisible(false)
          setInvalidDrop(false)
        }
      }

      const handleDrop = (event: DragEvent) => {
        event.preventDefault()
        dragCounterRef.current = 0
        setOverlayVisible(false)
        const droppedFiles = Array.from(event.dataTransfer?.files ?? [])
        if (!droppedFiles.length) {
          setInvalidDrop(true)
          return
        }
        uploadModeRef.current = defaultPrecheckOnly
        setDialogPrecheckOnly(defaultPrecheckOnly)
        if (datasetId) {
          detachPromise(uploadFiles(droppedFiles))
          return
        }
        confirmationRef.current = {}
        setUploading(false)
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
    }, [datasetId, defaultPrecheckOnly, uploadFiles])

    return (
      <>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="sr-only"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? [])
            if (!files.length) return
            if (datasetId) detachPromise(uploadFiles(files))
            else {
              confirmationRef.current = {}
              setUploading(false)
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
              className="rounded-3xl border border-dashed border-border/50 bg-background/95 px-10 py-12 text-center shadow-strong"
            >
              <UploadCloud className="mx-auto h-10 w-10 text-info" />
              <p className="mt-4 text-base font-semibold text-foreground">
                {invalidDrop ? '仅支持文件' : defaultPrecheckOnly ? '拖入文件以开始评估' : '拖入文件以上传'}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {invalidDrop
                  ? '请放下本地文件，而不是链接或其它拖拽内容。'
                  : `拖入 ${fileCount || '若干'} 个文件后即可开始上传。`}
              </p>
            </div>
          </div>
        )}

        <Dialog open={dropConfirmOpen} onOpenChange={changeConfirmationOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{dialogPrecheckOnly ? '上传样本评估' : '正式入库'}</DialogTitle>
              <DialogDescription>
                {dialogPrecheckOnly
                  ? '选择目标数据集和候选解析策略，只生成入库前摸底和文件布局难度分析，不会写入正式知识库。'
                  : '选择目标数据集和解析策略，文件会写入知识库并启动解析、治理、切块处理。'}
              </DialogDescription>
            </DialogHeader>

            {datasets.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border/60 bg-muted/20 p-4 text-sm">
                <p className="font-medium text-foreground">尚无数据集,请先前往新建</p>
                <Button asChild className="mt-3" variant="outline">
                  <Link href="/datasets">前往新建</Link>
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
                  <div className="text-sm font-medium">解析策略</div>
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
                    {dialogPrecheckOnly ? '待评估' : '待入库'} {pendingDropFiles?.length ?? 0} 个文件
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
              <Button variant="ghost" onClick={() => changeConfirmationOpen(false)}>
                取消
              </Button>
              <Button
                disabled={uploading || !datasets.length || !selectedDatasetId || !pendingDropFiles?.length}
                onClick={() => {
                  if (!pendingDropFiles?.length) return
                  const confirmation = confirmationRef.current
                  const authRevision = getAuthSessionRevision()
                  detachPromise(
                    uploadFiles(pendingDropFiles, { precheckOnly: dialogPrecheckOnly }).then((accepted) => {
                      if (
                        !accepted ||
                        !mountedRef.current ||
                        confirmationRef.current !== confirmation ||
                        authRevision !== getAuthSessionRevision()
                      )
                        return
                      setPendingDropFiles(null)
                      changeConfirmationOpen(false)
                    }),
                  )
                }}
              >
                {dialogPrecheckOnly ? '开始评估' : '开始入库'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </>
    )
  },
)

DropZone.displayName = 'DropZone'
