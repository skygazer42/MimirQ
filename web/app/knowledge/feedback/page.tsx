'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Star, RefreshCw, Search, ArrowUpRight, ArrowRight, Copy, MessageSquare, Loader2, ThumbsUp, ThumbsDown, TestTube2 } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useRouter } from '@/i18n/navigation'
import { feedbackApi } from '@/lib/api'
import { cn, formatDate, detachPromise } from '@/lib/utils'
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

export default function FeedbackTriagePage() {
  const router = useRouter()
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>('all')
  const [filterType, setFilterType] = useState<FeedbackTypeFilter>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [detail, setDetail] = useState<MessageFeedbackEnriched | null>(null)
  const [creatingCase, setCreatingCase] = useState(false)
  const [createdCaseId, setCreatedCaseId] = useState<string | null>(null)

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
    queryFn: ({ signal }) => feedbackApi.listEnriched({ limit: 100, ...params }, { signal }),
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

  // Reset per-detail UI state.
  useEffect(() => {
    setCreatedCaseId(null)
    setCreatingCase(false)
  }, [detail?.id])

  return (
    <AppFrame>
      <PageScaffold
        title="反馈分析中心"
        icon={MessageSquare}
        iconColor="text-indigo-500 dark:text-indigo-400"
        description={
          <span className="flex items-center gap-2 text-muted-foreground">
            <span className="font-semibold text-foreground">TRIAGE_MODE</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-500/20 uppercase ">
              Active
            </span>
            <span className="text-muted-foreground/50">|</span>
            <span>用户反馈实时监控与优化分析。</span>
          </span>
        }
	        actions={
	          <Button
	            variant="outline"
	            className="gap-2 bg-card/60 border-border hover:bg-card hover:border-border/80 text-muted-foreground hover:text-foreground rounded-full transition-colors duration-200 motion-reduce:transition-none shadow-sm"
	            onClick={() => refetch()}
	          >
		            <RefreshCw className={cn('h-3.5 w-3.5', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
		            刷新数据
		          </Button>
        }
        top={
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
            {[
              { label: '总反馈量', value: stats.total, icon: MessageSquare, color: 'text-indigo-600 dark:text-indigo-400', bg: 'bg-indigo-50 dark:bg-indigo-500/10', border: 'hover:border-indigo-200 dark:hover:border-indigo-800' },
              { label: '点赞 (Like)', value: stats.upvotes, icon: ThumbsUp, color: 'text-success', bg: 'bg-success/10', border: 'hover:border-success/20' },
              { label: '点踩 (Dislike)', value: stats.downvotes, icon: ThumbsDown, color: 'text-destructive', bg: 'bg-destructive/10', border: 'hover:border-destructive/20' },
              { label: '中立反馈', value: stats.total - stats.upvotes - stats.downvotes, icon: MessageSquare, color: 'text-sky-600 dark:text-sky-400', bg: 'bg-sky-50 dark:bg-sky-500/10', border: 'hover:border-sky-200 dark:hover:border-sky-800' },
	            ].map((stat) => (
	              <div
	                key={stat.label}
	                className={cn(
	                  "group relative overflow-hidden rounded-2xl bg-card border border-border shadow-sm hover:shadow-md transition-shadow duration-200 motion-reduce:transition-none",
	                  stat.border
	                )}
	              >
                <div className="p-5 flex flex-col justify-between h-full relative z-10">
                  <div className="flex items-center justify-between mb-4">
                    <div className={cn("p-2 rounded-lg transition-colors", stat.bg)}>
                      <stat.icon className={cn("size-5", stat.color)} />
                    </div>
                    <div className="text-[10px] font-bold uppercase text-muted-foreground">{stat.label}</div>
                  </div>
                  <div className="flex items-baseline gap-1">
                    <span className={cn("text-3xl font-black ", stat.color)}>{stat.value}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
	        }
	        toolbar={
	          <div className="flex flex-col md:flex-row md:items-center gap-0 bg-card/80 border border-border shadow-soft rounded-full p-1.5 max-w-4xl mx-auto md:mx-0">
		            <div className="relative flex-1 group pl-2">
		              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground group-hover:text-indigo-500 dark:group-hover:text-indigo-400 transition-colors" />
		              <Input
	                value={searchTerm}
	                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="搜索反馈内容..."
                className="pl-9 bg-transparent border-0 text-foreground placeholder:text-muted-foreground h-10 rounded-full"
              />
            </div>

            <div className="w-px h-6 bg-border hidden md:block mx-2" />

            <Select value={filterType} onValueChange={(v) => setFilterType(v as FeedbackTypeFilter)}>
              <SelectTrigger className="w-full md:w-32 bg-transparent border-0 h-10 text-muted-foreground hover:text-foreground rounded-full hover:bg-accent transition-colors">
                <SelectValue placeholder="类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部</SelectItem>
                <SelectItem value="thumbs_up">点赞</SelectItem>
                <SelectItem value="thumbs_down">点踩</SelectItem>
              </SelectContent>
            </Select>

            <div className="w-px h-6 bg-border hidden md:block mx-2" />

            <Select value={ratingFilter} onValueChange={(v) => setRatingFilter(v as RatingFilter)}>
              <SelectTrigger className="w-full md:w-32 bg-transparent border-0 h-10 text-muted-foreground hover:text-foreground rounded-full hover:bg-accent transition-colors">
                <SelectValue placeholder="星级" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部星级</SelectItem>
                <SelectItem value="5">5 星</SelectItem>
                <SelectItem value="4">4 星</SelectItem>
                <SelectItem value="3">3 星</SelectItem>
                <SelectItem value="2">2 星</SelectItem>
                <SelectItem value="1">1 星</SelectItem>
              </SelectContent>
            </Select>
          </div>
        }
        bodyClassName="pb-10 z-10"
      >
        <div className="space-y-3">
            {filtered.map((item) => {
              const kind = classifyFeedback(item.rating)
              const isUp = kind === 'thumbs_up'
              const isDown = kind === 'thumbs_down'
	              return (
	                <button
	                  key={item.id}
	                  type="button"
	                  onClick={() => setDetail(item)}
	                  aria-label={`查看反馈详情：${item.reason || '用户未填写原因'}`}
	                  className={cn(
	                    'group w-full text-left rounded-xl border border-border bg-card shadow-sm hover:shadow-md hover:border-primary/20 transition-shadow duration-200 relative overflow-hidden cursor-pointer focus-ring motion-reduce:transition-none'
	                  )}
	                >
                  <div
                    className={cn(
                      "absolute left-0 top-0 bottom-0 w-1 transition-colors",
                      (() => {
    if (isUp) {
        return "bg-success group-hover:bg-success/80";
    }
    else if (isDown) {
            return "bg-destructive group-hover:bg-destructive/80";
        }
        else {
            return "bg-muted-foreground/30 group-hover:bg-muted-foreground/40";
        }
})()
                    )}
                  />

                  <div className="flex items-start gap-4 p-5 pl-7">
                    <div
                      className={cn(
                        "w-10 h-10 rounded-full flex items-center justify-center shrink-0 border",
                        (() => {
    if (isUp) {
        return "bg-success/10 border-success/20 text-success";
    }
    else if (isDown) {
            return "bg-destructive/10 border-destructive/20 text-destructive";
        }
        else {
            return "bg-muted border-border text-muted-foreground";
        }
})()
                      )}
                    >
                      {(() => {
    if (isUp) {
        return (<ThumbsUp className="size-5"/>);
    }
    else if (isDown) {
            return (<ThumbsDown className="size-5"/>);
        }
        else {
            return (<Star className="size-5"/>);
        }
})()}
                    </div>

                    <div className="flex-1 min-w-0 pt-0.5">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono text-muted-foreground">{item.id.slice(0, 8)}</span>
                          <span className="text-xs font-medium text-muted-foreground/40">·</span>
                        <span className="text-xs text-muted-foreground">{formatDate(item.created_at)}</span>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <span className="text-xs font-bold text-indigo-500 dark:text-indigo-400">查看详情</span>
                        <ArrowRight className="size-3 text-indigo-500 dark:text-indigo-400" />
                      </div>
                    </div>

	                    <h3 className="text-base font-bold text-foreground mb-2 truncate pr-4">{item.reason || "用户未填写原因"}</h3>
	                    <div className="bg-muted rounded-lg p-3 border border-border">
	                      <p className="text-sm text-muted-foreground line-clamp-2 font-medium leading-relaxed">
	                        {item.message_content || "（无消息内容）"}
	                      </p>
	                    </div>

                    {Array.isArray(item.tags) && item.tags.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {item.tags.slice(0, 5).map((t) => (
                          <span
                            key={t}
                            className="rounded-md border border-border bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  </div>
                </button>
              )
            })}

            {!filtered.length && (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="mb-4 flex size-20 items-center justify-center rounded-full bg-muted/50">
                  <Search className="size-8 text-muted-foreground/50" aria-hidden="true" />
                </div>
                <p className="font-medium text-muted-foreground">没有找到相关的反馈记录</p>
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-5"
                  onClick={() => {
                    if (searchTerm.trim().length > 0 || filterType !== 'all' || ratingFilter !== 'all') {
                      setSearchTerm('')
                      setFilterType('all')
                      setRatingFilter('all')
                      return
                    }
                    detachPromise(refetch())
                  }}
                >
                  {searchTerm.trim().length > 0 || filterType !== 'all' || ratingFilter !== 'all'
                    ? '清除筛选'
                    : '刷新'}
                </Button>
              </div>
            )}
          </div>
      </PageScaffold>

        <Dialog open={Boolean(detail)} onOpenChange={(o) => (o ? null : setDetail(null))}>
          <DialogContent className="max-w-3xl p-0 overflow-hidden sm:rounded-2xl">

	            <DialogHeader className="px-8 pt-8 pb-4 border-b border-border/60 bg-card relative z-10">
	              <DialogTitle className="flex items-center justify-between gap-3">
	                <div className="flex items-center gap-3">
	                  <span className="text-lg font-bold  text-foreground">反馈详情报告</span>
	                </div>
	                {detail && (
	                  <Button size="sm" variant="outline" className="border-border/80 text-xs bg-card" onClick={() => copyDetail(detail)}>
	                    <Copy className="h-3.5 w-3.5 mr-2" />
	                    Copy JSON
	                  </Button>
	                )}
	              </DialogTitle>
	            </DialogHeader>

            {detail && (
              <div className="p-8 space-y-8 max-h-[70vh] overflow-y-auto overscroll-contain no-scrollbar relative z-10">

                {/* Meta Card */}
	                <div className="rounded-2xl border border-border bg-card p-6 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
	                  <div>
	                    <div className="text-sm font-bold text-foreground mb-1">{detail.conversation_title || `对话 ${detail.conversation_id}`}</div>
	                    <div className="text-xs text-muted-foreground font-mono flex items-center gap-3">
                      <span>ID: {detail.id.slice(0, 8)}</span>
                      <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
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
                      <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground uppercase  pl-1">
                        <MessageSquare className="w-3.5 h-3.5" />
                        User Feedback
                      </div>
                      <div className="rounded-2xl border border-destructive/20 bg-destructive/10 p-5 text-sm leading-relaxed text-destructive shadow-sm">
                        {detail.reason}
                      </div>
                    </div>
                  )}

                  {detail.expected_answer && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground uppercase  pl-1">
                        <Star className="w-3.5 h-3.5" />
                        Expected Output
                      </div>
                      <div className="rounded-2xl border border-success/20 bg-success/10 p-5 text-sm leading-relaxed text-success shadow-sm font-medium">
                        {detail.expected_answer}
                      </div>
                    </div>
                  )}

                  {detail.message_content && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground uppercase  pl-1">
                        <Loader2 className="w-3.5 h-3.5" />
                        AI Response
                      </div>
                      <div className="rounded-2xl border border-border bg-muted p-5 text-sm leading-relaxed text-muted-foreground font-mono text-[13px] whitespace-pre-wrap max-h-80 overflow-y-auto overscroll-contain no-scrollbar shadow-inner">
                        {detail.message_content}
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-end gap-3 pt-6 border-t border-border/60">
                  <Button
                    variant="outline"
                    disabled={!detail?.id || creatingCase}
                    onClick={async () => {
                      if (!detail?.id) return
                      setCreatingCase(true)
                      try {
                        const rc = await feedbackApi.toRegressionCase(detail.id, { include_document_scope: true })
                        setCreatedCaseId(rc.id)
                        toast.success('已创建回归用例')
                      } catch (err: any) {
                        toast.error(formatApiError(err, '创建回归用例失败'))
                      } finally {
                        setCreatingCase(false)
                      }
                    }}
                    className="rounded-full border-border hover:bg-muted gap-2"
                  >
                    {creatingCase ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <TestTube2 className="h-3.5 w-3.5" />
                    )}
                    生成回归用例
                  </Button>

                  {createdCaseId ? (
                    <Button
                      variant="outline"
                      onClick={() => router.push(`/evaluations?tab=regression`)}
                      className="rounded-full border-border hover:bg-muted gap-2"
                      title={`case_id=${createdCaseId}`}
                    >
                      前往回归测试
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </Button>
                  ) : null}

                  <Button
                    variant="outline"
                    onClick={() => router.push(`/history?id=${encodeURIComponent(detail.conversation_id)}`)}
                    className="rounded-full border-border hover:bg-muted gap-2"
                  >
                    跳转至对话上下文
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </Button>
	                  <Button onClick={() => setDetail(null)} className="rounded-full">关闭面板</Button>
	                </div>
	              </div>
	            )}
          </DialogContent>
        </Dialog>
    </AppFrame>
  )
}
