'use client'

import { Layers, Route } from '@/components/icons'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { Button } from '@/components/ui/button'
import { Link } from '@/i18n/navigation'
import { buildChunkPreviewDocumentHref } from '@/lib/chunk-preview-links'
import { getUserTagsFromDocument } from '@/lib/document-user-tags'
import { formatDate, formatFileSize } from '@/lib/utils'
import type { Document } from '@/types/documents'

import styles from './knowledge-page.module.css'

type KnowledgeInspectorProps = {
  document: Document | null
  datasetLabel?: string
}

const STATUS_LABELS: Record<Document['status'], string> = {
  completed: '已就绪',
  pending: '等待处理',
  processing: '处理中',
  failed: '失败',
  quarantined: '已隔离',
  cancelled: '已取消',
  deleting: '删除中',
}

export function KnowledgeInspector({ document: selected, datasetLabel }: Readonly<KnowledgeInspectorProps>) {
  if (selected === null) return <div className={styles.inspector}>选择一份文档以查看详情。</div>

  const fileType = getFileTypeMeta(selected)
  const TypeIcon = fileType.icon
  const rawSourcePath = selected.metadata?.source_path
  const sourcePath = typeof rawSourcePath === 'string' ? rawSourcePath.trim() : undefined
  const parserBackend = selected.metadata?.parser_backend
  const parserId = typeof parserBackend === 'string' ? parserBackend.trim() : undefined
  const parser = parserId === undefined || parserId.length === 0 ? '未提供' : parserId === 'auto' ? '自动' : parserId
  const userTags = getUserTagsFromDocument(selected)
  const details = [
    ['处理状态', STATUS_LABELS[selected.status]],
    ['生命周期', selected.archived_at ? '已归档' : selected.disabled_at ? '已禁用' : '启用中'],
    ['所属数据集', datasetLabel ?? selected.dataset_id ?? '未分类'],
    ['文件大小', formatFileSize(selected.file_size)],
    ['分块数', String(selected.chunk_count)],
    ['上传时间', formatDate(selected.created_at)],
    ['更新时间', formatDate(selected.updated_at)],
    ['解析器', parser],
    ...(userTags.length > 0 ? [['标签', userTags.join('、')]] : []),
    ['文档 ID', selected.id],
  ]

  return (
    <div className={styles.inspector}>
      <div className={styles.inspectorIdentity}>
        <TypeIcon appearance="color" aria-hidden="true" />
        <div>
          <h3>{selected.filename}</h3>
          <p>{fileType.label}</p>
        </div>
      </div>
      {selected.error_message ? (
        <div className={styles.inspectorError}>
          <h4>{selected.status === 'quarantined' ? '隔离原因' : '处理记录'}</h4>
          <p>{selected.error_message}</p>
        </div>
      ) : null}
      <dl>
        {details.map(([label, value]) => (
          <div key={label} className="contents">
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {sourcePath !== undefined && sourcePath.length > 0 ? (
        <div className={styles.inspectorSource}>
          <h4>来源路径</h4>
          <p>{sourcePath}</p>
        </div>
      ) : null}
      <div className={styles.inspectorActions}>
        <Button asChild variant="outline" size="sm">
          <Link href={buildChunkPreviewDocumentHref(selected.id)} target="_blank" rel="noopener noreferrer">
            <Layers className="size-4" aria-hidden="true" />
            切片管理
          </Link>
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link href={`/knowledge/${selected.id}/health`}>
            <Route className="size-4" aria-hidden="true" />
            健康卡片
          </Link>
        </Button>
      </div>
    </div>
  )
}
