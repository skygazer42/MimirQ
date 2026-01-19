'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Star, RefreshCw, Search, ArrowUpRight, Copy } from 'lucide-react'
import { toast } from 'sonner'

import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { feedbackApi } from '@/lib/api-client'
import { cn, formatDate } from '@/lib/utils'
import type { MessageFeedbackEnriched } from '@/types'
import { formatApiError } from '@/lib/api-errors'

type RatingFilter = 'all' | '1' | '2' | '3' | '4' | '5'

function Stars({ rating }: { rating: number }) {
  const v = Math.max(1, Math.min(5, Number(rating) || 0))
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => {
        const active = i <= v
        return (
          <Star
            key={i}
            className={cn('h-3.5 w-3.5', active ? 'text-yellow-500' : 'text-muted-foreground/40')}
            fill={active ? 'currentColor' : 'none'}
          />
        )
      })}
    </div>
  )
}

export default function FeedbackTriagePage() {
  const router = useRouter()
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>('all')
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState<MessageFeedbackEnriched | null>(null)

  const params = useMemo(() => {
    if (ratingFilter === 'all') return {}
    const v = Number(ratingFilter)
    return { min_rating: v, max_rating: v }
  }, [ratingFilter])

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['feedback-enriched', params],
    queryFn: async () => feedbackApi.listEnriched({ limit: 100, ...params }),
    staleTime: 5_000,
  })

  const items = data?.items || []

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter((it) => {
      const hay = [
        it.conversation_title,
        it.message_content,
        it.reason,
        (it.tags || []).join(' '),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return hay.includes(q)
    })
  }, [items, search])

  const stats = useMemo(() => {
    const byRating: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }
    for (const it of items) {
      const r = Number(it.rating) || 0
      if (r >= 1 && r <= 5) byRating[r] += 1
    }
    return byRating
  }, [items])

  const copyDetail = async (it: MessageFeedbackEnriched) => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(it, null, 2))
      toast.success('已复制')
    } catch (err: any) {
      toast.error(formatApiError(err, '复制失败'))
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50/50 dark:bg-slate-950 transition-colors duration-300">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden relative">
        <div className="absolute top-0 left-0 right-0 h-64 bg-gradient-to-b from-sky-50/60 dark:from-sky-900/10 to-transparent pointer-events-none" />

        <header className="px-8 pt-6 pb-4 flex-shrink-0 z-10">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">反馈质检</h1>
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                汇总用户对 assistant 回答的评分，用于回归、提示词与检索策略迭代
              </p>
            </div>

            <Button
              variant="outline"
              className="gap-2 bg-white/80 dark:bg-slate-900/60"
              onClick={() => refetch()}
            >
              <RefreshCw className={cn('h-4 w-4', isFetching ? 'animate-spin' : '')} />
              刷新
            </Button>
          </div>

          <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-3">
            {[5, 4, 3, 2, 1].map((r) => (
              <div key={r} className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 p-4">
                <div className="text-xs text-slate-500 dark:text-slate-400">{r} 星</div>
                <div className="text-xl font-bold text-slate-900 dark:text-white mt-1">{stats[r] || 0}</div>
              </div>
            ))}
          </div>
        </header>

        <div className="px-8 pb-4 flex-shrink-0 z-10">
          <div className="flex flex-col md:flex-row md:items-center gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索标题 / 内容 / tags / reason…"
                className="pl-9 bg-white/80 dark:bg-slate-900/60"
              />
            </div>
            <Select value={ratingFilter} onValueChange={(v) => setRatingFilter(v as RatingFilter)}>
              <SelectTrigger className="w-full md:w-56 bg-white/80 dark:bg-slate-900/60">
                <SelectValue placeholder="筛选评分" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部评分</SelectItem>
                <SelectItem value="5">5 星</SelectItem>
                <SelectItem value="4">4 星</SelectItem>
                <SelectItem value="3">3 星</SelectItem>
                <SelectItem value="2">2 星</SelectItem>
                <SelectItem value="1">1 星</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <section className="flex-1 overflow-y-auto px-8 pb-10 z-10">
          <div className="space-y-3">
            {filtered.map((it) => (
              <div
                key={it.id}
                className={cn(
                  'w-full rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 backdrop-blur-sm p-4',
                  'hover:shadow-md hover:shadow-sky-500/10 transition-all'
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-3">
                      <Stars rating={it.rating} />
                      <p className="font-semibold text-slate-900 dark:text-white truncate">
                        {it.conversation_title || `对话 ${it.conversation_id}`}
                      </p>
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400 flex flex-wrap gap-x-3 gap-y-1">
                      <span>更新 {formatDate(it.updated_at)}</span>
                      <span className="font-mono">msg {it.message_id}</span>
                      <span className="font-mono">by {it.account_id}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="bg-white/80 dark:bg-slate-900/60 gap-1"
                      onClick={() => router.push(`/history?id=${encodeURIComponent(it.conversation_id)}`)}
                    >
                      打开对话
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="sm" variant="outline" className="gap-1" onClick={() => copyDetail(it)}>
                      <Copy className="h-3.5 w-3.5" />
                      复制
                    </Button>
                    <Button size="sm" onClick={() => setDetail(it)}>
                      详情
                    </Button>
                  </div>
                </div>

                {it.reason && (
                  <div className="mt-3 text-xs text-slate-600 dark:text-slate-300">
                    <span className="text-slate-500 dark:text-slate-400">原因：</span>
                    {it.reason}
                  </div>
                )}

                {it.message_content && (
                  <div className="mt-3 rounded-xl border border-border/60 bg-background/60 p-3 text-sm text-foreground/90">
                    <div className="line-clamp-4 whitespace-pre-wrap">{it.message_content}</div>
                  </div>
                )}

                {Array.isArray(it.tags) && it.tags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {it.tags.slice(0, 12).map((t) => (
                      <span key={t} className="text-[10px] rounded-full border border-border bg-secondary/40 px-2 py-0.5 text-muted-foreground">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {!filtered.length && (
              <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/70 p-10 text-center text-sm text-slate-500 dark:text-slate-400">
                暂无匹配的反馈记录
              </div>
            )}
          </div>
        </section>

        <Dialog open={Boolean(detail)} onOpenChange={(o) => (!o ? setDetail(null) : null)}>
          <DialogContent className="max-w-3xl">
            <DialogHeader>
              <DialogTitle className="flex items-center justify-between gap-3">
                <span className="truncate">反馈详情</span>
                {detail && (
                  <Button size="sm" variant="outline" onClick={() => copyDetail(detail)}>
                    复制 JSON
                  </Button>
                )}
              </DialogTitle>
            </DialogHeader>

            {detail && (
              <div className="space-y-4">
                <div className="rounded-2xl border border-border bg-background/60 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <Stars rating={detail.rating} />
                    <div className="text-xs text-muted-foreground">{formatDate(detail.updated_at)}</div>
                  </div>
                  <div className="mt-2 text-sm font-semibold">
                    {detail.conversation_title || `对话 ${detail.conversation_id}`}
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground font-mono break-words">
                    feedback_id {detail.id} · message_id {detail.message_id}
                  </div>
                </div>

                {detail.reason && (
                  <div className="rounded-2xl border border-border bg-background/60 p-4">
                    <div className="text-sm font-medium">原因</div>
                    <div className="mt-2 text-sm whitespace-pre-wrap">{detail.reason}</div>
                  </div>
                )}

                {detail.expected_answer && (
                  <div className="rounded-2xl border border-border bg-background/60 p-4">
                    <div className="text-sm font-medium">期望回答</div>
                    <div className="mt-2 text-sm whitespace-pre-wrap">{detail.expected_answer}</div>
                  </div>
                )}

                {detail.message_content && (
                  <div className="rounded-2xl border border-border bg-background/60 p-4">
                    <div className="text-sm font-medium">assistant 内容（截断）</div>
                    <div className="mt-2 text-sm whitespace-pre-wrap">{detail.message_content}</div>
                  </div>
                )}

                <div className="flex items-center justify-end gap-2">
                  <Button
                    variant="outline"
                    onClick={() => router.push(`/history?id=${encodeURIComponent(detail.conversation_id)}`)}
                    className="gap-1"
                  >
                    打开对话
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </Button>
                  <Button onClick={() => setDetail(null)}>关闭</Button>
                </div>
              </div>
            )}
          </DialogContent>
        </Dialog>
      </main>
    </div>
  )
}

