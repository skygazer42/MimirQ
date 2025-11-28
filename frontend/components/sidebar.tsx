/**
 * 左侧边栏组件 - 展示文档列表
 */
'use client'

import { useState } from 'react'
import {
  FileText,
  Upload,
  Loader2,
  Trash2,
  CheckCircle,
  XCircle,
  Clock,
} from 'lucide-react'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, formatDate, getFileIcon } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Document } from '@/types'

export function Sidebar() {
  const { documents, isLoading, uploadDocument, deleteDocument } = useDocuments()
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])

  // 处理文件上传
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

    // 清空 input
    e.target.value = ''
  }

  // 切换文档选择
  const toggleDocumentSelection = (docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : [...prev, docId]
    )
  }

  // 获取状态图标
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
    <div className="w-80 h-screen bg-gray-50 border-r border-gray-200 flex flex-col">
      {/* 头部 */}
      <div className="p-6 border-b border-gray-200 bg-white">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">知识库</h2>

        {/* 上传按钮 */}
        <label htmlFor="file-upload">
          <div className="flex items-center justify-center gap-2 w-full px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer transition-colors">
            <Upload className="h-4 w-4" />
            <span className="text-sm font-medium">上传文档</span>
          </div>
          <input
            id="file-upload"
            type="file"
            multiple
            accept=".pdf,.txt,.md"
            className="hidden"
            onChange={handleFileUpload}
          />
        </label>

        {selectedDocIds.length > 0 && (
          <p className="mt-3 text-xs text-gray-500 text-center">
            已选择 {selectedDocIds.length} 个文档
          </p>
        )}
      </div>

      {/* 文档列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {isLoading && documents.length === 0 ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-gray-400">
            <FileText className="h-12 w-12 mb-2" />
            <p className="text-sm">暂无文档</p>
          </div>
        ) : (
          documents.map((doc) => (
            <DocumentCard
              key={doc.id}
              document={doc}
              isSelected={selectedDocIds.includes(doc.id)}
              onSelect={() => toggleDocumentSelection(doc.id)}
              onDelete={() => deleteDocument(doc.id)}
              getStatusIcon={getStatusIcon}
            />
          ))
        )}
      </div>

      {/* 底部统计 */}
      <div className="p-4 border-t border-gray-200 bg-white">
        <p className="text-xs text-gray-500">
          共 {documents.length} 个文档
        </p>
      </div>
    </div>
  )
}

// 文档卡片组件
function DocumentCard({
  document,
  isSelected,
  onSelect,
  onDelete,
  getStatusIcon,
}: {
  document: Document
  isSelected: boolean
  onSelect: () => void
  onDelete: () => void
  getStatusIcon: (status: string) => React.ReactNode
}) {
  const [showDelete, setShowDelete] = useState(false)

  return (
    <div
      className={cn(
        'group relative p-3 rounded-lg border transition-all cursor-pointer',
        isSelected
          ? 'bg-blue-50 border-blue-200'
          : 'bg-white border-gray-200 hover:border-gray-300 hover:shadow-sm'
      )}
      onClick={onSelect}
      onMouseEnter={() => setShowDelete(true)}
      onMouseLeave={() => setShowDelete(false)}
    >
      <div className="flex items-start gap-3">
        {/* 文件图标 */}
        <div className="text-2xl mt-0.5">
          {getFileIcon(document.file_type)}
        </div>

        {/* 文档信息 */}
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-gray-900 truncate">
            {document.filename}
          </h3>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-gray-500">
              {formatFileSize(document.file_size)}
            </span>
            <span className="text-xs text-gray-400">·</span>
            <span className="text-xs text-gray-500">
              {formatDate(document.created_at)}
            </span>
          </div>

          {/* 处理进度 */}
          {(document.status === 'processing' || document.status === 'pending') && (
            <div className="mt-2">
              <div className="w-full bg-gray-200 rounded-full h-1.5">
                <div
                  className="bg-blue-500 h-1.5 rounded-full transition-all"
                  style={{ width: `${document.processing_progress}%` }}
                />
              </div>
              <p className="text-xs text-gray-500 mt-1">
                {document.current_stage || '处理中'}...{' '}
                {document.processing_progress}%
              </p>
            </div>
          )}

          {/* 完成状态 */}
          {document.status === 'completed' && (
            <p className="text-xs text-gray-500 mt-1">
              {document.chunk_count} 个片段
            </p>
          )}

          {/* 错误信息 */}
          {document.status === 'failed' && (
            <p className="text-xs text-red-500 mt-1">处理失败</p>
          )}
        </div>

        {/* 状态和操作 */}
        <div className="flex flex-col items-end gap-2">
          {getStatusIcon(document.status)}

          {showDelete && document.status !== 'processing' && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              className="p-1 hover:bg-red-50 rounded transition-colors"
            >
              <Trash2 className="h-4 w-4 text-red-500" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
