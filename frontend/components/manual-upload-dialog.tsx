/**
 * 手动切片上传对话框
 */
'use client'

import { useState, ChangeEvent } from 'react'
import { Upload, Loader2 } from 'lucide-react'

import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import { formatFileSize } from '@/lib/utils'
import type { DocumentPreview, ManualChunk } from '@/types'

interface ManualUploadDialogProps {
  onUploaded?: () => void
}

type ChunkMode = 'page' | 'length' | 'delimiter'

export function ManualUploadDialog({ onUploaded }: ManualUploadDialogProps) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [isParsing, setIsParsing] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [mode, setMode] = useState<ChunkMode>('page')
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(200)
  const [delimiter, setDelimiter] = useState('## ')

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const selected = files[0]
    setFile(selected)
    setPreview(null)
    setError(null)
    setIsParsing(true)

    try {
      const result = await documentApi.preview(selected)
      setPreview(result)
    } catch (err: any) {
      console.error('Preview parse failed:', err)
      setError(err.message || '文档解析失败')
    } finally {
      setIsParsing(false)
      // 清空 input，方便下次选择相同文件
      e.target.value = ''
    }
  }

  const buildChunks = (): ManualChunk[] => {
    if (!preview) return []

    const segments = preview.segments || []

    if (mode === 'page') {
      // 每个解析片段直接作为一个 chunk
      return segments.map((seg) => ({
        content: seg.content,
        page_number: seg.page_number,
        start_char: 0,
        end_char: seg.content.length,
        metadata: seg.metadata || {},
      }))
    }

    if (mode === 'length') {
      // 按长度切片（在每个 segment 内部按字符数分段）
      const chunks: ManualChunk[] = []

      segments.forEach((seg) => {
        const content = seg.content || ''
        const len = content.length

        if (len === 0) {
          return
        }

        let start = 0

        while (start < len) {
          const end = Math.min(start + chunkSize, len)
          const piece = content.slice(start, end)

          chunks.push({
            content: piece,
            page_number: seg.page_number,
            start_char: start,
            end_char: end,
            metadata: seg.metadata || {},
          })

          if (end >= len) break

          const nextStart = end - chunkOverlap
          start = nextStart > start ? nextStart : end
        }
      })

      return chunks
    }

    if (mode === 'delimiter') {
      const chunks: ManualChunk[] = []
      const fullText = segments.map((s) => s.content).join('\n')

      if (!delimiter || !fullText) {
        if (fullText) {
          chunks.push({
            content: fullText,
            page_number: segments[0]?.page_number,
            metadata: segments[0]?.metadata || {},
          })
        }
        return chunks
      }

      const parts = fullText.split(delimiter)

      parts.forEach((part, index) => {
        const trimmed = part.trim()
        if (!trimmed) return

        const content =
          index === 0 && !fullText.startsWith(delimiter)
            ? trimmed
            : `${delimiter}${trimmed}`

        chunks.push({
          content,
          page_number: segments[0]?.page_number,
          metadata: segments[0]?.metadata || {},
        })
      })

      return chunks
    }

    return []
  }

  const handleSubmit = async () => {
    if (!preview) return

    const chunks = buildChunks()
    if (!chunks.length) {
      setError('没有可用的切片，请检查切片设置')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      await documentApi.createFromChunks({
        filename: preview.filename,
        file_type: preview.file_type,
        file_size: preview.file_size,
        chunks,
        metadata: {},
      })

      setOpen(false)
      setPreview(null)
      setFile(null)

      if (onUploaded) {
        onUploaded()
      }
    } catch (err: any) {
      console.error('Manual upload failed:', err)
      setError(err.message || '手动切片上传失败')
    } finally {
      setIsSubmitting(false)
    }
  }

  const resetState = () => {
    setFile(null)
    setPreview(null)
    setError(null)
    setIsParsing(false)
    setIsSubmitting(false)
    setMode('page')
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) resetState()
      }}
    >
      <DialogTrigger asChild>
        <Button
          variant="outline"
          className="w-full mt-3 justify-center gap-2"
        >
          <Upload className="h-4 w-4" />
          <span className="text-sm">高级切片上传</span>
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>手动切片上传文档</DialogTitle>
          <DialogDescription>
            先解析文档查看原始内容，再根据需要自定义切片方式（按页面、按长度或按自定义分隔符，例如 Markdown
            标题“## ”）。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 文件选择 */}
          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-700">选择文件</p>
            <input
              type="file"
              accept=".pdf,.txt,.md"
              onChange={handleFileChange}
            />
            {file && (
              <p className="text-xs text-gray-500">
                已选择：{file.name}（{formatFileSize(file.size)}）
              </p>
            )}
          </div>

          {/* 解析状态 / 预览 */}
          <div className="border rounded-md p-3 bg-gray-50 max-h-64 overflow-y-auto">
            {isParsing && (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在解析文档...
              </div>
            )}

            {!isParsing && !preview && (
              <p className="text-sm text-gray-500">
                请选择一个文档，系统会先解析出基础片段（按页或整篇文本）。
              </p>
            )}

            {preview && (
              <div className="space-y-2">
                <p className="text-sm text-gray-700">
                  解析结果：{preview.segments.length} 个基础片段
                </p>
                {preview.segments.map((seg) => (
                  <div
                    key={seg.index}
                    className="border rounded p-2 bg-white text-xs text-gray-700"
                  >
                    <div className="flex justify-between mb-1">
                      <span className="font-medium">
                        片段 #{seg.index + 1}
                      </span>
                      {seg.page_number && (
                        <span className="text-gray-500">
                          页码：{seg.page_number}
                        </span>
                      )}
                    </div>
                    <div className="max-h-24 overflow-y-auto whitespace-pre-wrap">
                      {seg.content.slice(0, 400)}
                      {seg.content.length > 400 && '...'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 切片设置 */}
          <div className="space-y-3">
            <p className="text-sm font-medium text-gray-700">切片方式</p>
            <div className="flex flex-wrap gap-3 text-sm">
              <button
                type="button"
                className={`px-3 py-1.5 rounded-full border ${
                  mode === 'page'
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300'
                }`}
                onClick={() => setMode('page')}
              >
                按解析片段（如页面）切
              </button>
              <button
                type="button"
                className={`px-3 py-1.5 rounded-full border ${
                  mode === 'length'
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300'
                }`}
                onClick={() => setMode('length')}
              >
                按长度切片
              </button>
              <button
                type="button"
                className={`px-3 py-1.5 rounded-full border ${
                  mode === 'delimiter'
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300'
                }`}
                onClick={() => setMode('delimiter')}
              >
                按自定义分隔符切
              </button>
            </div>

            {mode === 'length' && (
              <div className="grid grid-cols-2 gap-3 text-sm">
                <label className="space-y-1">
                  <span className="text-gray-700">单块最大长度（字符）</span>
                  <input
                    type="number"
                    min={100}
                    max={5000}
                    value={chunkSize}
                    onChange={(e) =>
                      setChunkSize(
                        Number.isNaN(parseInt(e.target.value, 10))
                          ? 1000
                          : parseInt(e.target.value, 10)
                      )
                    }
                    className="w-full border rounded px-2 py-1 text-sm"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-gray-700">重叠长度（字符）</span>
                  <input
                    type="number"
                    min={0}
                    max={chunkSize - 1}
                    value={chunkOverlap}
                    onChange={(e) =>
                      setChunkOverlap(
                        Number.isNaN(parseInt(e.target.value, 10))
                          ? 0
                          : parseInt(e.target.value, 10)
                      )
                    }
                    className="w-full border rounded px-2 py-1 text-sm"
                  />
                </label>
              </div>
            )}

            {mode === 'delimiter' && (
              <div className="space-y-1 text-sm">
                <span className="text-gray-700">
                  分隔符（例如 Markdown 标题：<code>## </code>）
                </span>
                <input
                  type="text"
                  value={delimiter}
                  onChange={(e) => setDelimiter(e.target.value)}
                  className="w-full border rounded px-2 py-1 text-sm"
                  placeholder="输入用来分段的特殊符号，如 '## '"
                />
              </div>
            )}
          </div>

          {error && (
            <p className="text-xs text-red-500 whitespace-pre-line">{error}</p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={isSubmitting}
          >
            取消
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!preview || isSubmitting}
          >
            {isSubmitting && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            确认切片并创建文档
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

