'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCw,
  Search,
} from 'lucide-react'

import { Navbar } from '@/components/navbar'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { documentApi } from '@/lib/api-client'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type { Document } from '@/types'
import { useDocumentView } from '@/store/document-view'

type StatusFilter = 'all' | Document['status']

const STATUS_LABEL: Record<StatusFilter, string> = {
  all: '全部',
  pending: '等待',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

function StatusPill({ status }: { status: Document['status'] }) {
  const cfg = (() => {
    switch (status) {
      case 'completed':
        return { icon: CheckCircle2, cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' }
      case 'failed':
        return { icon: AlertCircle, cls: 'bg-red-500/10 text-red-600 border-red-500/20' }
      case 'cancelled':
        return { icon: AlertCircle, cls: 'bg-slate-500/10 text-slate-600 border-slate-500/20' }
      case 'pending':
        return { icon: Clock, cls: 'bg-sky-500/10 text-sky-600 border-sky-500/20' }
      case 'processing':
      default:
        return { icon: Loader2, cls: 'bg-sky-500/10 text-sky-600 border-sky-500/20' }
    }
  })()

  const Icon = cfg.icon
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium', cfg.cls)}>
      <Icon className={cn('h-3.5 w-3.5', status === 'processing' ? 'animate-spin' : '')} />
      {STATUS_LABEL[status]}
    </span>
  )
}

export default function IngestionMonitorPage() {
  const { isOpen, openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [status, setStatus] = useState<StatusFilter>('all')
  const [search, setSearch] = useState('')

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['ingestion-documents', status],
    queryFn: async () => {
      const res = await documentApi.list({
        limit: 200,
        status: status === 'all' ? undefined : status,
      })
      return res
    },
    staleTime: 3_000,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const documents = data?.items || []

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return documents
    return documents.filter((d) => (d.filename || '').toLowerCase().includes(q))
  }, [documents, search])

  const stats = useMemo(() => {
    let pending = 0
    let processing = 0
    let completed = 0
    let failed = 0
    let cancelled = 0
    let totalSize = 0

    for (const d of documents) {
      totalSize += d.file_size || 0
      if (d.status === 'pending') pending += 1
      else if (d.status === 'processing') processing += 1
      else if (d.status === 'completed') completed += 1
      else if (d.status === 'failed') failed += 1
      else if (d.status === 'cancelled') cancelled += 1
    }

    return { pending, processing, completed, failed, cancelled, totalSize }
  }, [documents])

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50/50 dark:bg-slate-950 transition-colors duration-300">
      <Navbar />

      <main
        className={cn(
          'flex-1 flex flex-col overflow-hidden transition-all duration-300 ease-in-out',
          isOpen ? 'mr-0 md:mr-[40vw] xl:mr-[40vw] lg:mr-[500px]' : 'mr-0'
        )}
      >
        <div className="absolute top-0 left-0 right-0 h-64 bg-gradient-to-b from-sky-50/60 dark:from-sky-900/10 to-transparent pointer-events-none" />

        <header className="px-8 pt-6 pb-4 flex-shrink-0 z-10">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">入库监控</h1>
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                追踪解析、切块、向量化与索引进度，快速定位失败原因
              </p>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                className="gap-2 bg-white/80 dark:bg-slate-900/60"
                onClick={() => refetch()}
              >
                <RefreshCw className={cn('h-4 w-4', isFetching ? 'animate-spin' : '')} />
                刷新
              </Button>
              <div className="flex items-center gap-2 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 px-3 py-2">
                <span className="text-xs text-slate-600 dark:text-slate-300">自动刷新</span>
                <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} />
              </div>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 p-4">
              <div className="text-xs text-slate-500 dark:text-slate-400">等待</div>
              <div className="text-xl font-bold text-slate-900 dark:text-white mt-1">{stats.pending}</div>
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 p-4">
              <div className="text-xs text-slate-500 dark:text-slate-400">处理中</div>
              <div className="text-xl font-bold text-slate-900 dark:text-white mt-1">{stats.processing}</div>
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 p-4">
              <div className="text-xs text-slate-500 dark:text-slate-400">已完成</div>
              <div className="text-xl font-bold text-slate-900 dark:text-white mt-1">{stats.completed}</div>
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 p-4">
              <div className="text-xs text-slate-500 dark:text-slate-400">失败</div>
              <div className="text-xl font-bold text-red-600 dark:text-red-400 mt-1">{stats.failed}</div>
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 p-4">
              <div className="text-xs text-slate-500 dark:text-slate-400">存储</div>
              <div className="text-xl font-bold text-slate-900 dark:text-white mt-1">{formatFileSize(stats.totalSize)}</div>
            </div>
          </div>
        </header>

        <div className="px-8 pb-4 flex-shrink-0 z-10">
          <div className="flex flex-col md:flex-row md:items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="按文件名搜索…"
                className="pl-9 bg-white/80 dark:bg-slate-900/60"
              />
            </div>
            <Select value={status} onValueChange={(v) => setStatus(v as StatusFilter)}>
              <SelectTrigger className="w-full md:w-56 bg-white/80 dark:bg-slate-900/60">
                <SelectValue placeholder="筛选状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部</SelectItem>
                <SelectItem value="pending">等待</SelectItem>
                <SelectItem value="processing">处理中</SelectItem>
                <SelectItem value="completed">已完成</SelectItem>
                <SelectItem value="failed">失败</SelectItem>
                <SelectItem value="cancelled">已取消</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <section className="flex-1 overflow-y-auto px-8 pb-10 z-10">
          <div className="space-y-3">
            {filtered.map((doc) => (
              <button
                key={doc.id}
                onClick={() => openDocument(doc.id)}
                className={cn(
                  'w-full text-left rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 backdrop-blur-sm p-4',
                  'hover:shadow-md hover:shadow-sky-500/10 transition-all'
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-semibold text-slate-900 dark:text-white truncate">{doc.filename}</p>
                      <StatusPill status={doc.status} />
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400 flex flex-wrap gap-x-3 gap-y-1">
                      <span>更新 {formatDate(doc.updated_at)}</span>
                      <span>大小 {formatFileSize(doc.file_size)}</span>
                      <span>切片 {doc.chunk_count ?? '-'}</span>
                      {doc.current_stage && <span>阶段 {doc.current_stage}</span>}
                    </div>
                  </div>

                  <div className="text-xs text-slate-500 dark:text-slate-400 tabular-nums">
                    {doc.status === 'processing' || doc.status === 'pending' ? `${doc.processing_progress}%` : ''}
                  </div>
                </div>

                {(doc.status === 'processing' || doc.status === 'pending') && (
                  <div className="mt-3">
                    <div className="h-2 w-full rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                      <div
                        className="h-full bg-sky-600 dark:bg-sky-500 transition-all duration-500"
                        style={{ width: `${Math.max(0, Math.min(100, doc.processing_progress || 0))}%` }}
                      />
                    </div>
                  </div>
                )}

                {doc.status === 'failed' && doc.error_message && (
                  <div className="mt-3 rounded-xl border border-red-500/20 bg-red-500/5 p-3 text-xs text-red-700 dark:text-red-300">
                    <span className="font-medium">错误：</span>
                    <span className="font-mono">{doc.error_message}</span>
                  </div>
                )}
              </button>
            ))}

            {!filtered.length && (
              <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 p-10 text-center text-sm text-slate-500 dark:text-slate-400">
                暂无匹配的入库任务
              </div>
            )}
          </div>
        </section>
      </main>

      <DocumentViewerPanel />
    </div>
  )
}

