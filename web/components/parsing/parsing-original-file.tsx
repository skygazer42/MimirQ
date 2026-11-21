'use client'

import { useEffect, useState } from 'react'
import { Download, FileText } from '@/components/icons'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { Button } from '@/components/ui/button'
import { formatApiError } from '@/lib/api-errors'
import { downloadBlob } from '@/lib/download'
import styles from './parsing-compare.module.css'

const TEXT_PREVIEW_BYTE_LIMIT = 200_000

type OriginalPreviewProps = {
  file: File
  onRetry: () => void
}

type TextPreviewState = { file: File } & ({ status: 'ready'; text: string } | { status: 'failed'; error: unknown })

function OriginalPreviewError({ message, onRetry }: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <div className={styles.resourceBody} role="alert">
      <p className="p-4 text-sm text-destructive">{message}</p>
      <Button type="button" variant="outline" size="sm" className="mx-4 mb-4" onClick={onRetry}>
        重试预览
      </Button>
    </div>
  )
}

function TextFilePreview({ file, onRetry }: Readonly<OriginalPreviewProps>) {
  const [result, setResult] = useState<TextPreviewState | null>(null)

  useEffect(() => {
    let active = true
    async function readText() {
      try {
        const bytes = await file.slice(0, TEXT_PREVIEW_BYTE_LIMIT).arrayBuffer()
        const text = new TextDecoder().decode(bytes, { stream: file.size > TEXT_PREVIEW_BYTE_LIMIT })
        if (active) setResult({ file, status: 'ready', text })
      } catch (error) {
        if (active) setResult({ file, status: 'failed', error })
      }
    }

    void readText()
    return () => {
      active = false
    }
  }, [file])

  const current = result?.file === file ? result : null
  if (current === null) {
    return (
      <div className={styles.resourceBody} aria-busy="true">
        <p role="status" className="p-4 text-sm text-muted-foreground">
          正在读取原文
        </p>
      </div>
    )
  }
  if (current.status === 'failed') {
    return <OriginalPreviewError message={formatApiError(current.error, '读取原文失败')} onRetry={onRetry} />
  }

  return (
    <div className={styles.resourceBody}>
      {current.text.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">原文件没有可显示的文本。</p>
      ) : (
        <pre tabIndex={0} aria-label="原文件文本" className={styles.raw}>
          {current.text}
        </pre>
      )}
      {file.size > TEXT_PREVIEW_BYTE_LIMIT ? (
        <p className="p-4 text-xs text-muted-foreground">最多预览前 200 KB，下载可查看完整文件。</p>
      ) : null}
    </div>
  )
}

function ImageFilePreview({ file, onRetry }: Readonly<OriginalPreviewProps>) {
  const [source, setSource] = useState<{ file: File; url: string; failed: boolean } | null>(null)

  useEffect(() => {
    const url = URL.createObjectURL(file)
    setSource({ file, url, failed: false })
    return () => URL.revokeObjectURL(url)
  }, [file])

  const current = source?.file === file ? source : null
  if (current === null) {
    return (
      <div className={styles.resourceBody} aria-busy="true">
        <p role="status" className="p-4 text-sm text-muted-foreground">
          正在打开原图
        </p>
      </div>
    )
  }
  if (current.failed) {
    return <OriginalPreviewError message="图片无法预览，可下载原始文件对照。" onRetry={onRetry} />
  }

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-6">
      {/* A local Blob URL belongs to this preview, not Next image optimization. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        key={current.url}
        src={current.url}
        alt={file.name}
        className="max-h-full max-w-full object-contain"
        onError={() => setSource((source) => (source === current ? { ...current, failed: true } : source))}
      />
    </div>
  )
}

export function ParsingOriginalFile({ file }: Readonly<{ file: File }>) {
  const [retryCount, setRetryCount] = useState(0)
  const isText = /\.(txt|md|markdown|csv|tsv|json|xml|rst|adoc)$/i.test(file.name)
  const isImage = /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(file.name)
  const retryPreview = () => setRetryCount((count) => count + 1)

  return (
    <>
      <div className={styles.resultToolbar}>
        <FileText className="size-3.5 text-muted-foreground" />
        <span className="text-[13px]">原始文件</span>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="ml-auto size-8"
          onClick={() => downloadBlob(file.name, file)}
          aria-label="下载原始文件"
          title="下载原始文件"
        >
          <Download className="size-4" />
        </Button>
      </div>
      {isText ? (
        <TextFilePreview key={retryCount} file={file} onRetry={retryPreview} />
      ) : isImage ? (
        <ImageFilePreview key={retryCount} file={file} onRetry={retryPreview} />
      ) : (
        <div className={styles.empty}>
          <FileTypeIcon filename={file.name} className="size-10" />
          <h2>{file.name}</h2>
          <p>该格式暂不支持原文预览，可下载文件对照。</p>
        </div>
      )}
    </>
  )
}
