'use client'

import Link from 'next/link'
import {
  CalendarClock,
  Database,
  FileSearch,
  FolderTree,
  Hash,
  Layers,
  Route,
  type LucideIcon,
} from 'lucide-react'

import type { Document } from '@/types'

import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { buildChunkPreviewDocumentHref } from '@/lib/chunk-preview-links'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { cn, formatDate, formatFileSize } from '@/lib/utils'

type KnowledgeInspectorProps = {
  selectedDocs: Document[]
  children?: React.ReactNode
  className?: string
  embedded?: boolean
}

function formatShortId(value: string) {
  const text = String(value || '').trim()
  if (!text) return '—'
  return text.length > 18 ? `${text.slice(0, 8)}…${text.slice(-6)}` : text
}

function getStatusLabel(status: unknown) {
  const value = String(status || '').toLowerCase()
  if (value === 'completed' || value === 'ready') return '已就绪'
  if (value === 'processing' || value === 'pending') return '处理中'
  if (value === 'failed') return '失败'
  if (value === 'quarantined') return '隔离'
  return value || '未知'
}

function buildSourceTrail(sourcePath: string) {
  return sourcePath
    .split('/')
    .map((segment) => segment.trim())
    .filter(Boolean)
}

export function KnowledgeInspector({
  selectedDocs,
  children,
  className,
  embedded = false,
}: Readonly<KnowledgeInspectorProps>) {
  const selected = selectedDocs.length === 1 ? selectedDocs[0] : null
  const fileType = selected ? getFileTypeMeta(selected) : null
  const TypeIcon = fileType?.icon
  const metadata = selected?.metadata
  const sourcePath = selected ? toTrimmedPrimitiveString(metadata?.source_path) : ''
  const sourceTrail = buildSourceTrail(sourcePath)
  const folderPath = sourceTrail.length > 1 ? sourceTrail.slice(0, -1).join(' / ') : ''
  const parserLabel = selected
    ? toTrimmedPrimitiveString(metadata?.parser_backend) || '自动'
    : '—'

  const header = (
    <div
      className={cn(
        'flex items-center justify-between gap-3 border-b border-border/50',
        embedded
          ? 'bg-card/44 px-4 py-3 backdrop-blur-sm'
          : 'bg-card/58 px-4 py-3'
      )}
    >
      <div className="min-w-0">
        <div className="text-[13px] font-semibold leading-none tracking-[-0.01em] text-foreground">
          审查面板
        </div>
        <div className="mt-1 text-[11px] leading-none text-muted-foreground/72">
          单文档切片、来源和健康入口
        </div>
      </div>
      <div className="inline-flex h-7 items-center gap-1.5 rounded-full border border-border/50 bg-background/70 px-2.5 text-[11px] text-muted-foreground">
        <span className="size-1.5 rounded-full bg-info" />
        <span className="font-mono tabular-nums">{selectedDocs.length}</span>
      </div>
    </div>
  )

  const summary = (() => {
    if (selected) {
      return (
        <div className="space-y-3">
          <div className="relative overflow-hidden rounded-[18px] border border-border/50 bg-[linear-gradient(135deg,hsl(var(--card)/0.86),hsl(var(--surface-2)/0.50))] p-3.5 shadow-[0_14px_30px_-30px_hsl(var(--primary)/0.28)]">
            <div className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-[linear-gradient(90deg,hsl(var(--primary)/0.12),hsl(var(--info)/0.44),hsl(var(--primary)/0.10))]" />
            <div className="flex items-start gap-3">
              {fileType && TypeIcon ? (
                <div
                  className={cn(
                    'shrink-0 rounded-[14px] border p-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.72)]',
                    fileType.bg,
                    fileType.border,
                    fileType.color
                  )}
                >
                  <TypeIcon className="h-4 w-4" />
                </div>
              ) : null}

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-start gap-2">
                  <div className="min-w-0 flex-1 break-words text-[14px] font-semibold leading-5 text-foreground">
                    {selected.filename}
                  </div>
                  {fileType ? (
                    <span
                      className={cn(
                        'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold',
                        fileType.bg,
                        fileType.border,
                        fileType.color
                      )}
                      title={fileType.label}
                    >
                      {fileType.label}
                    </span>
                  ) : null}
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-border/45 bg-background/62 px-2 py-1 font-mono text-[10px] text-muted-foreground">
                    <Hash className="size-3 text-muted-foreground/55" />
                    {formatShortId(selected.id)}
                  </span>
                  <span className="inline-flex items-center rounded-full border border-border/45 bg-background/62 px-2 py-1 text-[10px] text-muted-foreground">
                    {getStatusLabel(selected.status)}
                  </span>
                  <span className="inline-flex items-center rounded-full border border-border/45 bg-background/62 px-2 py-1 text-[10px] text-muted-foreground">
                    解析器 {parserLabel}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
            <MetricTile
              icon={FileSearch}
              label="文件大小"
              value={formatFileSize(Number(selected.file_size || 0))}
            />
            <MetricTile
              icon={Layers}
              label="切片数"
              value={String(selected.chunk_count ?? 0)}
            />
            <MetricTile
              icon={CalendarClock}
              label="创建时间"
              value={formatDate(selected.created_at)}
            />
            <MetricTile
              icon={CalendarClock}
              label="更新时间"
              value={formatDate(selected.updated_at || selected.created_at)}
            />
          </div>

          {selected.dataset_id ? (
            <div className="rounded-[16px] border border-border/48 bg-card/62 px-3 py-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.74)]">
              <div className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold text-muted-foreground/76">
                <Database className="size-3.5 text-info" />
                所属知识库
              </div>
              <div className="break-all rounded-[10px] bg-background/60 px-2 py-1.5 font-mono text-[10px] leading-4 text-foreground/72">
                {selected.dataset_id}
              </div>
            </div>
          ) : null}

          {sourcePath ? (
            <div className="overflow-hidden rounded-[16px] border border-border/48 bg-card/62 shadow-[inset_0_1px_0_hsl(var(--card)/0.74)]">
              <div className="border-b border-border/45 px-3 py-2">
                <div className="flex items-center gap-2 text-[11px] font-semibold text-muted-foreground/76">
                  <FolderTree className="size-3.5 text-info" />
                  来源路径
                </div>
                {folderPath ? (
                  <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground/72" title={folderPath}>
                    {folderPath}
                  </div>
                ) : null}
              </div>
              <div className="space-y-2 px-3 py-2.5">
                <div className="flex flex-wrap gap-1.5">
                  {sourceTrail.slice(0, 5).map((segment, index) => (
                    <span
                      key={`${segment}-${index}`}
                      className="inline-flex max-w-full items-center rounded-full border border-border/45 bg-background/62 px-2 py-1 text-[10px] text-foreground/72"
                      title={segment}
                    >
                      <span className="max-w-[9rem] truncate">{segment}</span>
                    </span>
                  ))}
                  {sourceTrail.length > 5 ? (
                    <span className="inline-flex items-center rounded-full border border-border/45 bg-background/62 px-2 py-1 text-[10px] text-muted-foreground">
                      +{sourceTrail.length - 5}
                    </span>
                  ) : null}
                </div>
                <div className="break-all rounded-[10px] bg-background/58 px-2 py-1.5 font-mono text-[10px] leading-4 text-muted-foreground/82">
                  {sourcePath}
                </div>
              </div>
            </div>
          ) : null}

          <div className="grid grid-cols-2 gap-2">
            <Button
              asChild
              variant="outline"
              size="sm"
              className="h-8 rounded-xl border-info/18 bg-info/[0.06] px-2.5 text-[11px] font-medium text-info hover:bg-info/[0.10] dark:text-info"
            >
              <Link
                href={buildChunkPreviewDocumentHref(selected.id)}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Layers className="mr-1.5 size-3.5" />
                切片管理
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              size="sm"
              className="h-8 rounded-xl border-border/50 bg-background/72 px-2.5 text-[11px] font-medium text-foreground/78 hover:bg-card/92"
            >
              <Link href={`/knowledge/${selected.id}/health`}>
                <Route className="mr-1.5 size-3.5" />
                健康卡
              </Link>
            </Button>
          </div>
        </div>
      )
    }

    if (selectedDocs.length > 1) {
      return (
        <div className="rounded-xl border border-dashed border-border/60 bg-transparent px-3 py-3 text-xs text-muted-foreground">
          已选择 <span className="font-mono tabular-nums text-foreground">{selectedDocs.length}</span> 份文档。请收窄选择范围以查看单文档详情。
        </div>
      )
    }

    return (
      <div className="rounded-xl border border-dashed border-border/60 bg-transparent px-3 py-3 text-xs text-muted-foreground">
        选择一个文档以查看详情。
      </div>
    )
  })()

  if (embedded) {
    return (
      <div className={cn('flex flex-col border-0 bg-transparent', className)}>
        {header}
        <div className="space-y-3 overflow-y-auto p-3.5 lg:p-4">
          {summary}
          {children ? <div className="rounded-[16px] border border-border/50 bg-background/70 p-3">{children}</div> : null}
        </div>
      </div>
    )
  }

  return (
    <Panel
      padding="none"
      className={cn('min-h-0 overflow-hidden flex flex-col border-border/50 bg-card', className)}
    >
      {header}

      <div
        data-page-scroll-container="true"
        className="flex-1 min-h-0 overflow-y-auto overscroll-contain custom-scrollbar p-4 space-y-3"
      >
        {summary}
        {children ? <div className="border-t border-border/50 pt-3">{children}</div> : null}
      </div>
    </Panel>
  )
}

function MetricTile({
  icon: Icon,
  label,
  value,
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
}>) {
  return (
    <div className="rounded-[14px] border border-border/48 bg-card/62 px-2.5 py-2 shadow-[inset_0_1px_0_hsl(var(--card)/0.74)]">
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground/66">
        <Icon className="size-3 text-info/78" />
        {label}
      </div>
      <div className="mt-1 truncate font-mono text-[11px] font-semibold tabular-nums text-foreground/86" title={value}>
        {value}
      </div>
    </div>
  )
}
