'use client'

/**
 * 文档解析页面：集中上传 / 解析 / 切片预览
 */
import { useRef } from 'react'
import { Upload, Loader2, CheckCircle, XCircle, Clock } from 'lucide-react'

import { Navbar } from '@/components/navbar'
import { ManualUploadDialog } from '@/components/manual-upload-dialog'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, formatDate, getFileIcon } from '@/lib/utils'
import type { Document } from '@/types'

export default function ParsingPage() {
  const { documents, isLoading, uploadDocument, deleteDocument } = useDocuments()
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file)
      } catch (error) {
        console.error('Upload failed:', error)
      }
    }

    e.target.value = ''
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'processing':
      case 'pending':
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
      default:
        return <Clock className="h-4 w-4 text-gray-400" />
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar />
      <main className="flex-1 overflow-y-auto p-8">
        <div className="max-w-7xl mx-auto space-y-8">
          <header className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">文档解析</h1>
              <p className="text-gray-600">上传 / 解析 / 切片预览，一站完成</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                <Upload className="h-4 w-4" />
                上传文档（自动解析）
              </button>
              <ManualUploadDialog onUploaded={() => undefined} />
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.txt,.md"
                className="hidden"
                onChange={handleFileUpload}
              />
            </div>
          </header>

          {/* 文档列表 & 状态 */}
          <section className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900">最近上传</h2>
              {isLoading && (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  加载中...
                </div>
              )}
            </div>

            {documents.length === 0 ? (
              <div className="text-sm text-gray-500">暂无文档，先上传一个吧。</div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                {documents.map((doc) => (
                  <DocCard
                    key={doc.id}
                    document={doc}
                    onDelete={() => deleteDocument(doc.id)}
                    getStatusIcon={getStatusIcon}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  )
}

function DocCard({
  document,
  onDelete,
  getStatusIcon,
}: {
  document: Document
  onDelete: () => void
  getStatusIcon: (s: string) => React.ReactNode
}) {
  return (
    <div className="border rounded-lg p-4 bg-gray-50 hover:bg-gray-100 transition">
      <div className="flex items-start gap-3">
        <div className="text-2xl mt-0.5">{getFileIcon(document.file_type)}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900 truncate">{document.filename}</h3>
            {getStatusIcon(document.status)}
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {formatFileSize(document.file_size)} · {formatDate(document.created_at)}
          </p>

          {document.status === 'processing' || document.status === 'pending' ? (
            <div className="mt-2">
              <div className="w-full bg-gray-200 rounded-full h-1.5">
                <div
                  className="bg-blue-500 h-1.5 rounded-full transition-all"
                  style={{ width: `${document.processing_progress}%` }}
                />
              </div>
              <p className="text-xs text-gray-500 mt-1">
                {document.current_stage || '处理中'} · {document.processing_progress}%
              </p>
            </div>
          ) : null}

          {document.status === 'completed' && (
            <p className="text-xs text-gray-600 mt-1">
              {document.chunk_count} 个块 · {document.total_characters} 字
            </p>
          )}

          {document.status === 'failed' && (
            <p className="text-xs text-red-500 mt-1">处理失败：{document.error_message}</p>
          )}
        </div>

        <div className="flex flex-col items-end gap-2">
          <DocumentDetailDialog document={document} />
          {document.status !== 'processing' && (
            <button
              onClick={onDelete}
              className="text-xs text-red-500 hover:text-red-600"
            >
              删除
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
