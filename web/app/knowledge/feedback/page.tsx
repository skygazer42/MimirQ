'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Star, RefreshCw, Search, ArrowUpRight, Copy, MessageSquare, Loader2, ThumbsUp, ThumbsDown, ArrowRight } from 'lucide-react'
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
type FeedbackType = 'thumbs_up' | 'thumbs_down'
type FeedbackTypeFilter = 'all' | FeedbackType

function classifyFeedback(rating: number): FeedbackType | 'neutral' {
  const v = Number(rating) || 0
  if (v >= 4) return 'thumbs_up'
  if (v > 0 && v <= 2) return 'thumbs_down'
  return 'neutral'
}

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
  const [filterType, setFilterType] = useState<FeedbackTypeFilter>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [detail, setDetail] = useState<MessageFeedbackEnriched | null>(null)

  const params = useMemo(() => {
    const p: any = {}
    if (ratingFilter !== 'all') {
      const v = Number(ratingFilter)
      p.min_rating = v
      p.max_rating = v
    }
    return p
  }, [ratingFilter])

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['feedback-enriched', params],
    queryFn: async () => feedbackApi.listEnriched({ limit: 100, ...params }),
    staleTime: 5_000,
  })

  const items = useMemo(() => data?.items || [], [data])

  const stats = useMemo(() => {
    const s = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, total: 0, upvotes: 0, downvotes: 0 }
    for (const it of items) {
      s.total++
      const r = Number(it.rating) || 0
      if (r >= 1 && r <= 5) (s as any)[r] += 1
      const kind = classifyFeedback(r)
      if (kind === 'thumbs_up') s.upvotes++
      if (kind === 'thumbs_down') s.downvotes++
    }
    return s
  }, [items])

  const filtered = useMemo(() => {
    let res = items
    const q = searchTerm.trim().toLowerCase()

    if (filterType !== 'all') {
      res = res.filter((i) => classifyFeedback(i.rating) === filterType)
    }

    if (q) {
      res = res.filter((it) => {
        const hay = [
          it.conversation_title,
          it.message_content,
          it.reason,
          (it.tags || []).join(' '),
          it.id,
          it.account_id
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        return hay.includes(q)
      })
    }
    return res
  }, [items, searchTerm, filterType])

  const copyDetail = async (it: MessageFeedbackEnriched) => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(it, null, 2))
      toast.success('已复制')
    } catch (err: any) {
      toast.error(formatApiError(err, '复制失败'))
    }
  }

  return (
    <div className="flex min-h-screen overflow-hidden bg-slate-50 dark:bg-slate-950 font-sans selection:bg-indigo-100 dark:selection:bg-indigo-900 selection:text-indigo-900 dark:selection:text-indigo-100">
      <Navbar />

      <main id="main-content" tabIndex={-1} className="relative z-10 flex-1 flex flex-col overflow-hidden transition-all duration-300">
        {/* Background Texture - Dark mode adjusted */}
        <div className="fixed inset-0 z-0 pointer-events-none opacity-60 dark:opacity-20 mix-blend-multiply dark:mix-blend-normal"
          style={{ backgroundImage: 'radial-gradient(#cbd5e1 1px, transparent 1px)', backgroundSize: '32px 32px' }} />

        <div className="fixed top-0 right-0 w-[600px] h-[600px] bg-indigo-200/20 dark:bg-indigo-900/10 rounded-full blur-[100px] pointer-events-none" />
        <div className="fixed bottom-0 left-0 w-[600px] h-[600px] bg-sky-200/20 dark:bg-sky-900/10 rounded-full blur-[100px] pointer-events-none" />

        <div className="sticky top-0 z-20 backdrop-blur-md bg-white/70 dark:bg-slate-950/70 border-b border-slate-200/50 dark:border-slate-800/50 transition-all duration-300">
          <PageHeader
            title="反馈分析中心"
            icon={MessageSquare}
            iconColor="text-indigo-500 dark:text-indigo-400"
            className="!pt-6 !pb-6"
            description={
              <span className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
                <span className="font-bold text-slate-700 dark:text-slate-200">TRIAGE_MODE</span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-500/20 uppercase tracking-wider">Active</span>
                <span className="text-slate-300 dark:text-slate-600">|</span>
                用户反馈实时监控与优化分析。
              </span>
            }
          >
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                className="gap-2 bg-white/50 dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 hover:bg-white dark:hover:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-700 text-slate-600 dark:text-slate-300 rounded-full transition-all duration-300 shadow-sm"
                onClick={() => refetch()}
              >
                <RefreshCw className={cn('h-3.5 w-3.5 transition-transform group-hover:rotate-180', isFetching ? 'animate-spin' : '')} />
                刷新数据
              </Button>
            </div>
          </PageHeader>
        </div>

        <div className="px-8 pb-4 grid grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
          {[
            { label: '总反馈量', value: stats.total, icon: MessageSquare, color: 'text-indigo-600 dark:text-indigo-400', bg: 'bg-indigo-50 dark:bg-indigo-500/10', border: 'hover:border-indigo-200 dark:hover:border-indigo-800' },
            { label: '点赞 (Like)', value: stats.upvotes, icon: ThumbsUp, color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-500/10', border: 'hover:border-emerald-200 dark:hover:border-emerald-800' },
            { label: '点踩 (Dislike)', value: stats.downvotes, icon: ThumbsDown, color: 'text-rose-600 dark:text-rose-400', bg: 'bg-rose-50 dark:bg-rose-500/10', border: 'hover:border-rose-200 dark:hover:border-rose-800' },
            { label: '平均响应', value: '~1.2s', icon: Loader2, color: 'text-sky-600 dark:text-sky-400', bg: 'bg-sky-50 dark:bg-sky-500/10', border: 'hover:border-sky-200 dark:hover:border-sky-800' },
          ].map((stat, idx) => (
            <div key={idx} className={cn(
              "group relative overflow-hidden rounded-2xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 shadow-[0_2px_20px_rgba(0,0,0,0.04)] dark:shadow-none hover:shadow-[0_8px_30px_rgba(0,0,0,0.08)] transition-all duration-300 hover:-translate-y-1",
              stat.border
            )}>
              <div className="p-5 flex flex-col justify-between h-full relative z-10">
                <div className="flex items-center justify-between mb-4">
                  <div className={cn("p-2 rounded-lg transition-colors", stat.bg)}>
                    <stat.icon className={cn("w-5 h-5", stat.color)} />
                  </div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">{stat.label}</div>
                </div>
                <div className="flex items-baseline gap-1">
                  <span className={cn("text-3xl font-black tracking-tight", stat.color)}>{stat.value}</span>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="px-8 pb-6 flex-shrink-0 z-10 sticky top-[88px] my-2">
          <div className="flex flex-col md:flex-row md:items-center gap-0 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl border border-slate-200 dark:border-slate-800 shadow-lg shadow-slate-200/50 dark:shadow-none rounded-full p-1.5 transition-all duration-300 max-w-4xl mx-auto md:mx-0">
            <div className="relative flex-1 group pl-2">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 dark:text-slate-500 group-hover:text-indigo-500 dark:group-hover:text-indigo-400 transition-colors" />
              <Input
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="搜索反馈内容..."
                className="pl-9 bg-transparent border-0 focus-visible:ring-0 text-slate-700 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 h-10 rounded-full"
              />
            </div>

            <div className="w-px h-6 bg-slate-200 dark:bg-slate-800 hidden md:block mx-2" />

            <Select value={filterType} onValueChange={(v) => setFilterType(v as FeedbackTypeFilter)}>
              <SelectTrigger className="w-full md:w-32 bg-transparent border-0 focus:ring-0 h-10 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 rounded-full hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                <SelectValue placeholder="类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部</SelectItem>
                <SelectItem value="thumbs_up">点赞</SelectItem>
                <SelectItem value="thumbs_down">点踩</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <section className="flex-1 overflow-y-auto px-8 pb-10 z-10 custom-scrollbar">
          <div className="space-y-3">
            {filtered.map((item) => {
              const kind = classifyFeedback(item.rating)
              const isUp = kind === 'thumbs_up'
              const isDown = kind === 'thumbs_down'
              return (
                <div
                  key={item.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setDetail(item)}
                  className={cn(
                    'group w-full text-left rounded-xl border transition-all duration-300 relative overflow-hidden',
                    'bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800 hover:border-indigo-200 dark:hover:border-indigo-800 hover:shadow-[0_8px_30px_rgba(0,0,0,0.04)] hover:-translate-y-0.5'
                  )}
                >
                  <div
                    className={cn(
                      "absolute left-0 top-0 bottom-0 w-1 transition-colors",
                      isUp
                        ? "bg-emerald-500 group-hover:bg-emerald-400"
                        : isDown
                          ? "bg-rose-500 group-hover:bg-rose-400"
                          : "bg-slate-300 group-hover:bg-slate-400 dark:bg-slate-700 dark:group-hover:bg-slate-600"
                    )}
                  />

                  <div className="flex items-start gap-4 p-5 pl-7">
                    <div
                      className={cn(
                        "w-10 h-10 rounded-full flex items-center justify-center shrink-0 border",
                        isUp
                          ? "bg-emerald-50 dark:bg-emerald-500/10 border-emerald-100 dark:border-emerald-500/20 text-emerald-600 dark:text-emerald-400"
                          : isDown
                            ? "bg-rose-50 dark:bg-rose-500/10 border-rose-100 dark:border-rose-500/20 text-rose-600 dark:text-rose-400"
                            : "bg-slate-50 dark:bg-slate-800/60 border-slate-100 dark:border-slate-800 text-slate-600 dark:text-slate-300"
                      )}
                    >
                      {isUp ? (
                        <ThumbsUp className="w-5 h-5" />
                      ) : isDown ? (
                        <ThumbsDown className="w-5 h-5" />
                      ) : (
                        <Star className="w-5 h-5" />
                      )}
                    </div>

                    <div className="flex-1 min-w-0 pt-0.5">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono text-slate-400 dark:text-slate-500">{item.id.slice(0, 8)}</span>
                          <span className="text-xs font-medium text-slate-300 dark:text-slate-600">·</span>
                        <span className="text-xs text-slate-500 dark:text-slate-400">{formatDate(item.created_at)}</span>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <span className="text-xs font-bold text-indigo-500 dark:text-indigo-400">查看详情</span>
                        <ArrowRight className="w-3 h-3 text-indigo-500 dark:text-indigo-400" />
                      </div>
                    </div>

	                    <h3 className="text-base font-bold text-slate-800 dark:text-slate-100 mb-2 truncate pr-4">{item.reason || "用户未填写原因"}</h3>
	                    <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 border border-slate-100 dark:border-slate-800/50">
	                      <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-2 font-medium leading-relaxed">
	                        {item.message_content || "（无消息内容）"}
	                      </p>
	                    </div>

                    {Array.isArray(item.tags) && item.tags.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {item.tags.slice(0, 5).map((t) => (
                          <span key={t} className="text-[10px] uppercase tracking-wider font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10 border border-indigo-100 dark:border-indigo-500/20 px-2 py-0.5 rounded-md">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  </div>
                </div>
              )
            })}

            {!filtered.length && (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-20 h-20 rounded-full bg-slate-50 dark:bg-slate-900 flex items-center justify-center mb-4">
                  <Search className="w-8 h-8 text-slate-300 dark:text-slate-600" />
                </div>
                <p className="text-slate-500 dark:text-slate-400 font-medium">没有找到相关的反馈记录</p>
              </div>
            )}
          </div>
        </section>

        <Dialog open={Boolean(detail)} onOpenChange={(o) => (!o ? setDetail(null) : null)}>
          <DialogContent className="max-w-3xl bg-[#fafafa] dark:bg-slate-950 border-slate-200 dark:border-slate-800 shadow-2xl sm:rounded-[2rem] p-0 overflow-hidden outline-none">
            {/* Paper Texture Overlay */}
            <div className="absolute inset-0 opacity-50 dark:opacity-10 pointer-events-none mix-blend-multiply dark:mix-blend-overlay" style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg width=\'100\' height=\'100\' viewBox=\'0 0 100 100\' xmlns=\'http://www.w3.org/200\'%3E%3Cfilter id=\'noise\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.8\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100\' height=\'100\' filter=\'url(%23noise)\' opacity=\'0.08\'/%3E%3C/svg%3E")', backgroundSize: '200px 200px' }} />

            <DialogHeader className="px-8 pt-8 pb-4 border-b border-slate-200/60 dark:border-slate-800/60 bg-white dark:bg-slate-900 relative z-10">
              <DialogTitle className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-lg font-bold tracking-tight text-slate-900 dark:text-slate-100">反馈详情报告</span>
                </div>
                {detail && (
                  <Button size="sm" variant="outline" className="border-slate-200 dark:border-slate-800 text-xs bg-white dark:bg-slate-900" onClick={() => copyDetail(detail)}>
                    <Copy className="h-3.5 w-3.5 mr-2" />
                    Copy JSON
                  </Button>
                )}
              </DialogTitle>
            </DialogHeader>

            {detail && (
              <div className="p-8 space-y-8 max-h-[70vh] overflow-y-auto custom-scrollbar relative z-10">

                {/* Meta Card */}
                <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
                  <div>
                    <div className="text-sm font-bold text-slate-900 dark:text-slate-100 mb-1">{detail.conversation_title || `对话 ${detail.conversation_id}`}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400 font-mono flex items-center gap-3">
                      <span>ID: {detail.id.slice(0, 8)}</span>
                      <span className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
                      <span>Msg: {detail.message_id.slice(0, 8)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10 px-3 py-1.5 rounded-full border border-indigo-100 dark:border-indigo-500/20 font-bold">
                      {formatDate(detail.updated_at)}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-8">
                  {detail.reason && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest pl-1">
                        <MessageSquare className="w-3.5 h-3.5" />
                        User Feedback
                      </div>
                      <div className="rounded-2xl border border-rose-100 dark:border-rose-900/30 bg-rose-50/50 dark:bg-rose-900/10 p-5 text-sm leading-relaxed text-rose-900 dark:text-rose-100 shadow-sm">
                        {detail.reason}
                      </div>
                    </div>
                  )}

                  {detail.expected_answer && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest pl-1">
                        <Star className="w-3.5 h-3.5" />
                        Expected Output
                      </div>
                      <div className="rounded-2xl border border-emerald-100 dark:border-emerald-900/30 bg-emerald-50/50 dark:bg-emerald-900/10 p-5 text-sm leading-relaxed text-emerald-900 dark:text-emerald-100 shadow-sm font-medium">
                        {detail.expected_answer}
                      </div>
                    </div>
                  )}

                  {detail.message_content && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest pl-1">
                        <Loader2 className="w-3.5 h-3.5" />
                        AI Response
                      </div>
                      <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 p-5 text-sm leading-relaxed text-slate-600 dark:text-slate-300 font-mono text-[13px] whitespace-pre-wrap max-h-80 overflow-y-auto custom-scrollbar shadow-inner">
                        {detail.message_content}
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-end gap-3 pt-6 border-t border-slate-200/60 dark:border-slate-800/60">
                  <Button
                    variant="outline"
                    onClick={() => router.push(`/history?id=${encodeURIComponent(detail.conversation_id)}`)}
                    className="rounded-full border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800 gap-2"
                  >
                    跳转至对话上下文
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </Button>
                  <Button onClick={() => setDetail(null)} className="rounded-full bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg shadow-indigo-200 dark:shadow-none">关闭面板</Button>
                </div>
              </div>
            )}
          </DialogContent>
        </Dialog>
      </main>
    </div>
  )
}
