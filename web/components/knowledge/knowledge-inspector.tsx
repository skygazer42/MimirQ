'use client'

import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Activity,
  Calendar,
  ChevronRight,
  Copy,
  Dataset as DatasetIcon,
  Eye,
  FileText,
  HardDrive,
  Hash,
  Layers,
  Loader2,
  RefreshCw,
  Route,
  Tags,
} from '@/components/icons'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { readMetadataString } from '@/components/chunk-preview/utils/metadata'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Link } from '@/i18n/navigation'
import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { buildChunkPreviewDocumentHref } from '@/lib/chunk-preview-links'
import { getTagDomainTone, type DomainTone } from '@/lib/dataset-domain-tone'
import { getUserTagsFromDocument } from '@/lib/document-user-tags'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise, formatDate, formatFileSize } from '@/lib/utils'
import type { Document } from '@/types/documents'

import styles from './knowledge-page.module.css'

type KnowledgeInspectorProps = {
  document: Document | null
  datasetLabel?: string
  datasetTone?: DomainTone
  onOpenDocument: (id: string) => void
  onPeek: (id: string) => void
  onRefresh: () => Promise<void>
  onDelete: (document: Document) => void
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
const INSPECTOR_TABS = ['概览', '分块', '管理'] as const
type MaintenanceAction = 'reingest' | 'enable' | 'disable' | 'archive' | 'unarchive'
const ACTION_LABELS: Record<MaintenanceAction, string> = {
  reingest: '重新入库',
  enable: '启用',
  disable: '禁用',
  archive: '归档',
  unarchive: '取消归档',
}

export function KnowledgeInspector(props: Readonly<KnowledgeInspectorProps>) {
  if (props.document === null) return <div className={styles.inspector}>选择一份文档以查看详情。</div>
  return <SelectedInspector {...props} document={props.document} />
}

function SelectedInspector({
  document: selected,
  datasetLabel,
  datasetTone,
  onOpenDocument,
  onPeek,
  onRefresh,
  onDelete,
}: Readonly<KnowledgeInspectorProps & { document: Document }>) {
  const [tab, setTab] = useState<(typeof INSPECTOR_TABS)[number]>('概览')
  const sessionKey = getAuthSessionKey()
  const fileType = getFileTypeMeta(selected)
  const TypeIcon = fileType.icon
  const rawSourcePath = selected.metadata?.source_path
  const sourcePath = typeof rawSourcePath === 'string' ? rawSourcePath.trim() : undefined
  const parserBackend = selected.metadata?.parser_backend
  const parserId = typeof parserBackend === 'string' ? parserBackend.trim() : undefined
  const parser = parserId === undefined || parserId.length === 0 ? '未提供' : parserId === 'auto' ? '自动' : parserId
  const userTags = getUserTagsFromDocument(selected)
  const chunks = useQuery({
    queryKey: [...queryKeys.documents.chunks(selected.id), 'inspector', sessionKey],
    queryFn: ({ signal }) => documentApi.listChunks(selected.id, { limit: 8 }, { signal }),
    enabled: tab === '分块',
  })
  const maintenance = useMutation({
    mutationFn: async (action: MaintenanceAction) => {
      if (action === 'reingest') {
        const result = await documentApi.batchReingest({
          document_ids: [selected.id],
          replace: false,
          force: true,
          skip_if_unchanged: false,
        })
        if (result.queued === 0)
          throw new Error(
            result.skipped > 0 ? '文档未重新入库：处理已跳过。' : '文档未重新入库，请检查权限或处理状态。',
          )
      } else {
        const perform = {
          enable: documentApi.batchEnable,
          disable: documentApi.batchDisable,
          archive: documentApi.batchArchive,
          unarchive: documentApi.batchUnarchive,
        }[action]
        const result = await perform([selected.id])
        if (result.updated === 0) throw new Error('文档未更新，请检查权限或处理状态。')
      }
    },
    onSuccess: async (_, action) => {
      if (sessionKey !== getAuthSessionKey()) return
      toast.success(action === 'reingest' ? '已提交重新入库' : `文档已${ACTION_LABELS[action]}`)
      try {
        await onRefresh()
      } catch (error) {
        toast.error(formatApiError(error, '文档刷新失败'))
      }
    },
    onError: (error) => {
      if (sessionKey === getAuthSessionKey()) toast.error(formatApiError(error, '文档操作失败'))
    },
  })
  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(selected.id)
      toast.success('已复制文档 ID')
    } catch {
      toast.error('复制失败，请重试')
    }
  }

  return (
    <div className={styles.inspector} data-knowledge-inspector="true">
      <div className={styles.inspectorIdentity}>
        <span className={cn(styles.inspectorFileBadge, fileType.bg)}>
          <TypeIcon appearance="color" aria-hidden="true" />
        </span>
        <div className={styles.inspectorIdentityCopy}>
          <h3 title={selected.filename}>{selected.filename}</h3>
          <span className={cn(styles.status, styles.inspectorStatus)} data-state={selected.status}>
            <span className={styles.statusDot} aria-hidden="true" />
            {STATUS_LABELS[selected.status]}
          </span>
        </div>
      </div>
      <div className={styles.inspectorMetrics}>
        <div>
          <span>
            <Layers className="icon-ink-governance" />
            分块
          </span>
          <strong>{selected.chunk_count}</strong>
        </div>
        <div>
          <span>
            <HardDrive className="icon-ink-process" />
            大小
          </span>
          <strong>{formatFileSize(selected.file_size)}</strong>
        </div>
        <div>
          <span>
            <Activity className="icon-ink-analysis" />
            处理次数
          </span>
          <strong>{selected.processing_attempts ?? 1} 次</strong>
        </div>
      </div>
      <div className={styles.inspectorTabs} role="tablist" aria-label="文档详情视图">
        {INSPECTOR_TABS.map((item, index) => (
          <button
            key={item}
            type="button"
            role="tab"
            id={`inspector-tab-${index}`}
            aria-controls={`inspector-panel-${index}`}
            aria-selected={tab === item}
            tabIndex={tab === item ? 0 : -1}
            onClick={() => setTab(item)}
            onKeyDown={(event) => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
              event.preventDefault()
              const next =
                event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3
              setTab(INSPECTOR_TABS[next])
              event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button')[next].focus()
            }}
          >
            {item}
          </button>
        ))}
      </div>
      <div
        className={styles.inspectorTabBody}
        role="tabpanel"
        id={`inspector-panel-${INSPECTOR_TABS.indexOf(tab)}`}
        aria-labelledby={`inspector-tab-${INSPECTOR_TABS.indexOf(tab)}`}
      >
        {tab === '概览' ? (
          <>
            {selected.error_message ? (
              <div className={styles.inspectorError}>
                <h4>{selected.status === 'quarantined' ? '隔离原因' : '处理记录'}</h4>
                <p>{selected.error_message}</p>
              </div>
            ) : null}
            <dl className={styles.inspectorDetails}>
              <dt>
                <DatasetIcon />
                数据集
              </dt>
              <dd>
                <span className={styles.datasetPill} data-tone={datasetTone}>
                  {datasetLabel ?? selected.dataset_id ?? '未分类'}
                </span>
              </dd>
              <dt>
                <Calendar />
                上传时间
              </dt>
              <dd>{formatDate(selected.created_at)}</dd>
              <dt>
                <FileText />
                文件类型
              </dt>
              <dd>{fileType.label}</dd>
              <dt>
                <Activity />
                生命周期
              </dt>
              <dd>{selected.archived_at ? '已归档' : selected.disabled_at ? '已禁用' : '启用中'}</dd>
              <dt>
                <Route />
                解析器
              </dt>
              <dd>{parser}</dd>
              <dt>
                <Hash />
                文档 ID
              </dt>
              <dd className={styles.inspectorId}>
                <code title={selected.id}>{selected.id}</code>
                <IconButton label="复制文档 ID" variant="ghost" onClick={() => detachPromise(copyId())}>
                  <Copy className="size-3.5" />
                </IconButton>
              </dd>
              {sourcePath ? (
                <>
                  <dt>
                    <Route />
                    来源路径
                  </dt>
                  <dd>{sourcePath}</dd>
                </>
              ) : null}
              {userTags.length > 0 ? (
                <>
                  <dt>
                    <Tags />
                    标签
                  </dt>
                  <dd className={styles.tagList}>
                    {userTags.map((tag) => (
                      <span key={tag} className={styles.tagPill} data-tone={getTagDomainTone(tag)} title={tag}>
                        {tag}
                      </span>
                    ))}
                  </dd>
                </>
              ) : null}
            </dl>
            <h4 className={styles.quickActionsTitle}>快捷操作</h4>
            <div className={styles.quickActions}>
              <button type="button" data-tone="governance" onClick={() => onOpenDocument(selected.id)}>
                <Eye />
                <span>打开完整阅读器</span>
                <ChevronRight />
              </button>
              <button
                type="button"
                data-tone="process"
                disabled={maintenance.isPending}
                onClick={() => maintenance.mutate('reingest')}
              >
                {maintenance.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                <span>重新入库</span>
                <ChevronRight />
              </button>
              <Link data-tone="analysis" href={`/knowledge/${selected.id}/health`}>
                <Activity />
                <span>健康检查</span>
                <ChevronRight />
              </Link>
            </div>
          </>
        ) : tab === '分块' ? (
          <div className={styles.chunkPreview}>
            {chunks.isLoading ? (
              <p role="status">正在加载分块…</p>
            ) : chunks.error ? (
              <div role="alert">
                <p>{formatApiError(chunks.error, '分块加载失败')}</p>
                <Button variant="ghost" size="sm" onClick={() => detachPromise(chunks.refetch())}>
                  重试
                </Button>
              </div>
            ) : chunks.data?.items.length === 0 ? (
              <p>暂无分块。</p>
            ) : (
              chunks.data?.items.map((chunk) => {
                const headerPath = chunk.metadata?.header_path
                const header =
                  (Array.isArray(headerPath) && headerPath.every((part) => typeof part === 'string')
                    ? headerPath.join(' / ')
                    : readMetadataString(headerPath)) ??
                  readMetadataString(chunk.metadata?.outline_path_str) ??
                  readMetadataString(chunk.metadata?.header_context) ??
                  readMetadataString(chunk.metadata?.header)
                return (
                  <article key={chunk.id} className={styles.chunkExcerpt}>
                    <header>
                      <span>#{chunk.chunk_index + 1}</span>
                      {chunk.page_number != null ? <span>第 {chunk.page_number} 页</span> : null}
                      {header ? <span title={header}>{header}</span> : null}
                    </header>
                    <p>{chunk.content}</p>
                  </article>
                )
              })
            )}
            <Button variant="outline" size="sm" onClick={() => onPeek(selected.id)}>
              在阅读器查看全部分块
            </Button>
            <Link className={styles.inspectorTextLink} href={buildChunkPreviewDocumentHref(selected.id)}>
              切片管理
              <ChevronRight className="size-3.5" />
            </Link>
          </div>
        ) : (
          <div className={styles.managementActions}>
            <p>生命周期与维护</p>
            {(
              [selected.disabled_at ? 'enable' : 'disable', selected.archived_at ? 'unarchive' : 'archive'] as const
            ).map((action) => (
              <Button
                key={action}
                variant="outline"
                disabled={maintenance.isPending}
                onClick={() => maintenance.mutate(action)}
              >
                {maintenance.isPending && maintenance.variables === action ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : null}
                {ACTION_LABELS[action]}
              </Button>
            ))}
            <Button asChild variant="outline">
              <Link href={buildChunkPreviewDocumentHref(selected.id)}>
                <Layers className="size-3.5" />
                切片管理
              </Link>
            </Button>
            <Button variant="ghost" onClick={() => detachPromise(copyId())}>
              <Copy className="size-3.5" />
              复制文档 ID
            </Button>
            <Button
              variant="ghost"
              className="text-destructive"
              disabled={maintenance.isPending}
              onClick={() => onDelete(selected)}
            >
              删除文档
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
