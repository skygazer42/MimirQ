'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Star, RefreshCw, Search, ArrowUpRight, Copy } from 'lucide-react'
import { toast } from 'sonner'

import { Navbar } from '@/components/navbar'
import { PageHeader } from '@/components/ui/page-header'
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

  const items = useMemo(() => data?.items || [], [data])

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
    <div className="flex min-h-screen overflow-hidden bg-background font-sans selection:bg-primary/20 selection:text-primary">
      {/* Ambient Background */}
      <div className="fixed inset-0 z-0 pointer-events-none">
        <div className="absolute top-[-20%] left-[-10%] w-[800px] h-[800px] bg-primary/5 rounded-full blur-[120px] animate-pulse-subtle" />
        <div className="absolute bottom-[-10%] right-[-20%] w-[600px] h-[600px] bg-purple-500/5 rounded-full blur-[120px] animate-pulse-subtle" style={{ animationDelay: '3s' }} />
        <div className="absolute top-[30%] left-[30%] w-[400px] h-[400px] bg-blue-500/5 rounded-full blur-[100px] animate-pulse-subtle" style={{ animationDelay: '1.5s' }} />
      </div>

      <Navbar />

      <main className="relative z-10 flex-1 flex flex-col overflow-hidden">

        <PageHeader
          title="反馈质检"
          icon={Star}
          iconColor="text-primary"
          description={
            <span>
              QUALITY_CONTROL: <span className="text-primary">ACTIVE</span> <span className="opacity-50 mx-2">{'//'}</span> 汇总用户评分与反馈，驱动模型迭代与知识库优化。
            </span>
          }
        >
          <Button
            variant="outline"
            className="gap-2 border-primary/20 hover:bg-primary/10 hover:text-primary transition-all duration-300 group rounded-full"
            onClick={() => refetch()}
          >
            <RefreshCw className={cn('h-4 w-4 transition-transform group-hover:rotate-180', isFetching ? 'animate-spin' : '')} />
            刷新数据
          </Button>
        </PageHeader>

        <div className="px-8 pb-4 grid grid-cols-2 md:grid-cols-5 gap-4">
          {[5, 4, 3, 2, 1].map((r) => (
            <div key={r} className="group relative overflow-hidden rounded-2xl border bg-white/5 border-white/10 hover:border-primary/30 p-4 transition-all duration-300 hover:shadow-lg backdrop-blur-sm">
              <div className="absolute inset-0 bg-gradient-to-br from-white/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />

              <div className="relative z-10 flex items-center justify-between">
                <div className="flex items-center gap-1">
                  <Star className={cn("w-4 h-4", r >= 4 ? "text-yellow-400 fill-yellow-400" : "text-muted-foreground")} />
                  <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">{r} 星</span>
                </div>
                <div className={cn("text-2xl font-black tracking-tight transition-transform group-hover:scale-110", r >= 4 ? "text-primary" : "text-muted-foreground")}>
                  {stats[r] || 0}
                </div>
              </div>
              {/* Progress bar visual */}
              <div className="mt-3 h-1 w-full bg-white/10 rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all duration-1000", r >= 4 ? "bg-gradient-to-r from-yellow-400 to-orange-400" : "bg-muted-foreground/30")}
                  style={{ width: `${Math.min(100, (stats[r] || 0) * 5)}%` }} // Rough viz
                />
              </div>
            </div>
          ))}
        </div>

        <div className="px-8 pb-6 flex-shrink-0 z-10">
          <div className="flex flex-col md:flex-row md:items-center gap-4 bg-white/5 backdrop-blur-md border border-white/10 p-2 rounded-2xl">
            <div className="relative flex-1 group">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索反馈内容、原因、标签或ID..."
                className="pl-11 bg-transparent border-0 focus-visible:ring-0 text-foreground placeholder:text-muted-foreground/50 h-11"
              />
            </div>
            <div className="w-px h-8 bg-white/10 hidden md:block" />
            <Select value={ratingFilter} onValueChange={(v) => setRatingFilter(v as RatingFilter)}>
              <SelectTrigger className="w-full md:w-48 bg-transparent border-0 focus:ring-0 h-11 text-muted-foreground hover:text-foreground">
                <SelectValue placeholder="筛选评分" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部评分</SelectItem>
                <SelectItem value="5">5 星 - 极好</SelectItem>
                <SelectItem value="4">4 星 - 满意</SelectItem>
                <SelectItem value="3">3 星 - 一般</SelectItem>
                <SelectItem value="2">2 星 - 较差</SelectItem>
                <SelectItem value="1">1 星 - 极差</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <section className="flex-1 overflow-y-auto px-8 pb-10 z-10 custom-scrollbar">
          <div className="space-y-4">
            {filtered.map((it) => (
              <div
                key={it.id}
                className={cn(
                  'group w-full rounded-2xl border transition-all duration-300 relative overflow-hidden',
                  'bg-white/5 border-white/10 hover:bg-white/10 hover:border-primary/30 hover:shadow-[0_0_30px_-10px_rgba(var(--primary),0.2)]',
                  'p-5 backdrop-blur-sm'
                )}
              >
                {/* Decorative Accent */}
                <div className={cn("absolute left-0 top-0 bottom-0 w-1 transition-colors", Number(it.rating) >= 4 ? "bg-primary" : "bg-muted-foreground/20")} />

                <div className="flex items-start justify-between gap-4 pl-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <div className="flex items-center gap-1 bg-black/20 rounded-full px-2 py-0.5 border border-white/5">
                        <Stars rating={it.rating} />
                      </div>
                      <h3 className="font-semibold text-lg text-foreground truncate group-hover:text-primary transition-colors">
                        {it.conversation_title || `Conversation ${it.conversation_id.slice(0, 8)}`}
                      </h3>
                    </div>

                    <div className="mt-2 text-xs text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 font-mono items-center">
                      <span className="flex items-center gap-1.5">
                        <div className="w-1.5 h-1.5 rounded-full bg-slate-500/50" />
                        {formatDate(it.updated_at)}
                      </span>
                      <span className="bg-white/5 px-1.5 py-0.5 rounded text-xs select-all">MSG_ID: {it.message_id.slice(0, 8)}</span>
                      <span className="bg-white/5 px-1.5 py-0.5 rounded text-xs select-all">USER: {it.account_id}</span>
                    </div>

                    {it.reason && (
                      <div className="mt-4 flex gap-3 text-sm">
                        <span className="text-muted-foreground/60 font-medium whitespace-nowrap pt-1">FEEDBACK</span>
                        <div className="text-foreground/80 leading-relaxed bg-white/5 p-2 rounded-lg border border-white/5 w-full">
                          {it.reason}
                        </div>
                      </div>
                    )}

                    {it.message_content && !it.reason && (
                      <div className="mt-4 text-sm text-muted-foreground/60 bg-black/20 p-2 rounded-lg border border-white/5 line-clamp-2 font-serif italic">
                        &quot;{it.message_content}&quot;
                      </div>
                    )}
                  </div>

                  <div className="flex flex-col gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setDetail(it)}
                      className="text-primary hover:text-primary hover:bg-primary/10"
                    >
                      查看详情
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-muted-foreground hover:text-foreground hover:bg-white/10"
                      onClick={() => router.push(`/history?id=${encodeURIComponent(it.conversation_id)}`)}
                    >
                      <ArrowUpRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                {Array.isArray(it.tags) && it.tags.length > 0 && (
                  <div className="mt-4 pl-3 flex flex-wrap gap-2">
                    {it.tags.slice(0, 12).map((t) => (
                      <span key={t} className="text-[10px] uppercase tracking-wider font-bold text-primary/80 bg-primary/10 border border-primary/20 px-2 py-1 rounded-md">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {!filtered.length && (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-20 h-20 rounded-full bg-white/5 flex items-center justify-center mb-4 animate-pulse">
                  <Search className="w-8 h-8 text-muted-foreground/30" />
                </div>
                <p className="text-muted-foreground">没有找到相关的反馈记录</p>
                <p className="text-xs text-muted-foreground/50 mt-1">系统将持续监控新的用户反馈...</p>
              </div>
            )}
          </div>
        </section>

        <Dialog open={Boolean(detail)} onOpenChange={(o) => (!o ? setDetail(null) : null)}>
          <DialogContent className="max-w-3xl border-primary/20 bg-slate-950/95 backdrop-blur-xl shadow-[0_0_50px_-10px_rgba(var(--primary),0.2)] sm:rounded-[2rem] p-0 overflow-hidden">
            {/* Decorative HUD Elements */}
            <div className="absolute top-0 right-0 w-32 h-32 bg-primary/10 blur-[60px] pointer-events-none" />
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-primary/50 to-transparent" />

            <DialogHeader className="px-8 pt-8 pb-4 border-b border-white/10 bg-white/5 relative z-10">
              <DialogTitle className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <Stars rating={detail?.rating || 0} />
                  <span className="text-lg font-bold tracking-wide">反馈详情报告</span>
                </div>
                {detail && (
                  <Button size="sm" variant="outline" className="border-white/10 hover:border-primary/50 text-xs" onClick={() => copyDetail(detail)}>
                    <Copy className="h-3.5 w-3.5 mr-2" />
                    Copy Payload
                  </Button>
                )}
              </DialogTitle>
            </DialogHeader>

            {detail && (
              <div className="p-8 space-y-6 max-h-[70vh] overflow-y-auto custom-scrollbar relative z-10">

                {/* Meta Card */}
                <div className="rounded-xl border border-white/10 bg-white/5 p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div>
                    <div className="text-sm font-bold text-foreground">{detail.conversation_title || `对话 ${detail.conversation_id}`}</div>
                    <div className="mt-1 text-xs text-muted-foreground font-mono flex items-center gap-3">
                      <span>ID: {detail.id}</span>
                      <span className="w-1 h-1 rounded-full bg-white/20" />
                      <span>MSG: {detail.message_id}</span>
                    </div>
                  </div>
                  <div className="text-xs font-mono text-primary/80 bg-primary/10 px-3 py-1.5 rounded-full border border-primary/20">
                    {formatDate(detail.updated_at)}
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-6">
                  {detail.reason && (
                    <div className="space-y-2">
                      <div className="text-xs font-bold text-muted-foreground uppercase tracking-widest pl-1">User Feedback</div>
                      <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 text-sm leading-relaxed text-foreground/90">
                        {detail.reason}
                      </div>
                    </div>
                  )}

                  {detail.expected_answer && (
                    <div className="space-y-2">
                      <div className="text-xs font-bold text-primary/80 uppercase tracking-widest pl-1">Expected Output</div>
                      <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm leading-relaxed text-foreground/90 font-medium">
                        {detail.expected_answer}
                      </div>
                    </div>
                  )}

                  {detail.message_content && (
                    <div className="space-y-2">
                      <div className="text-xs font-bold text-muted-foreground uppercase tracking-widest pl-1">AI Response Content</div>
                      <div className="rounded-xl border border-white/10 bg-black/20 p-4 text-sm leading-relaxed text-muted-foreground font-mono text-[13px] whitespace-pre-wrap max-h-60 overflow-y-auto custom-scrollbar">
                        {detail.message_content}
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/10">
                  <Button
                    variant="outline"
                    onClick={() => router.push(`/history?id=${encodeURIComponent(detail.conversation_id)}`)}
                    className="gap-2 border-white/10 hover:bg-white/5"
                  >
                    跳转至对话上下文
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </Button>
                  <Button onClick={() => setDetail(null)} className="bg-primary text-primary-foreground hover:bg-primary/90">关闭面板</Button>
                </div>
              </div>
            )}
          </DialogContent>
        </Dialog>
      </main>
    </div>
  )
}

