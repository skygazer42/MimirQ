'use client'

import { Layers, Route } from '@/components/icons'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { Button } from '@/components/ui/button'
import { Link } from '@/i18n/navigation'
import { buildChunkPreviewDocumentHref } from '@/lib/chunk-preview-links'
import { getUserTagsFromDocument } from '@/lib/document-user-tags'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type { Document } from '@/types'

import styles from './knowledge-page.module.css'

type KnowledgeInspectorProps = {
  selectedDocs: Document[]
  datasetLabel?: string
  children?: React.ReactNode
  className?: string
  embedded?: boolean
}

const STATUS_LABELS: Record<string, string> = {
  completed: '已就绪', pending: '等待处理', processing: '处理中',
  failed: '失败', quarantined: '已隔离', cancelled: '已取消', deleting: '删除中',
}

export function KnowledgeInspector({ selectedDocs, datasetLabel, children, className }: Readonly<KnowledgeInspectorProps>) {
  const selected = selectedDocs.length === 1 ? selectedDocs[0] : null
  if (!selected) return <div className={cn(styles.inspector, className)}>选择一份文档以查看详情。</div>

  const fileType = getFileTypeMeta(selected)
  const TypeIcon = fileType.icon
  const sourcePath = toTrimmedPrimitiveString(selected.metadata?.source_path)
  const parserId = toTrimmedPrimitiveString(selected.metadata?.parser_backend)
  const parser = !parserId || parserId === 'auto' ? '自动' : parserId
  const userTags = getUserTagsFromDocument(selected)
  const details = [
    ['处理状态', STATUS_LABELS[selected.status] || selected.status],
    ['生命周期', selected.archived_at ? '已归档' : selected.disabled_at ? '已禁用' : '启用中'],
    ['所属数据集', datasetLabel || selected.dataset_id || '未分类'],
    ['文件大小', formatFileSize(Number(selected.file_size || 0))],
    ['分块数', String(selected.chunk_count ?? 0)],
    ['上传时间', formatDate(selected.created_at)],
    ['更新时间', formatDate(selected.updated_at || selected.created_at)],
    ['解析器', parser],
    ...(userTags.length ? [['标签', userTags.join('、')]] : []),
    ['文档 ID', selected.id],
  ]

  return (
    <div className={cn(styles.inspector, className)}>
      <div className={styles.inspectorIdentity}>
        <TypeIcon appearance="color" aria-hidden="true" />
        <div><h3>{selected.filename}</h3><p>{fileType.label}</p></div>
      </div>
      {selected.error_message ? (
        <div className={styles.inspectorError}>
          <h4>{selected.status === 'quarantined' ? '隔离原因' : '处理记录'}</h4>
          <p>{selected.error_message}</p>
        </div>
      ) : null}
      <dl>{details.map(([label, value]) => <div key={label} className="contents"><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      {sourcePath ? <div className={styles.inspectorSource}><h4>来源路径</h4><p>{sourcePath}</p></div> : null}
      <div className={styles.inspectorActions}>
        <Button asChild variant="outline" size="sm"><Link href={buildChunkPreviewDocumentHref(selected.id)} target="_blank" rel="noopener noreferrer"><Layers className="size-4" />切片管理</Link></Button>
        <Button asChild variant="ghost" size="sm"><Link href={'/knowledge/' + selected.id + '/health'}><Route className="size-4" />健康卡片</Link></Button>
      </div>
      {children}
    </div>
  )
}
