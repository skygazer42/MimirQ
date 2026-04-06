'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Star, RefreshCw, Search, ArrowUpRight, ArrowRight, Copy, MessageSquare, Loader2, ThumbsUp, ThumbsDown, TestTube2 } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useRouter } from '@/i18n/navigation'
import { feedbackApi } from '@/lib/api'
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

  const hasActiveFilters = searchTerm.trim().length > 0 || filterType !== 'all' || ratingFilter !== 'all'
  const listSummary = useMemo(() => {
    if (!items.length) return null
    if (hasActiveFilters) return `筛选 ${filtered.length} / ${items.length}`
    return `共 ${items.length} 条`
  }, [filtered.length, hasActiveFilters, items.length])

  return (
    <AppFrame>
      <PageScaffold
        title="反馈分析中心"
        icon={MessageSquare}
        iconColor="text-indigo-500 dark:text-indigo-400"
        size="full"
        topClassName="px-3 md:px-4 xl:px-5 pb-3"
        description={
          <div className="flex flex-wrap items-center gap-2 text-[12px] leading-5 text-muted-foreground">
            <span>汇总点赞、点踩与低分原因，快速定位需要回归验证的反馈。</span>
            <span className="inline-flex items-center rounded-md border border-border/60 bg-background/70 px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.04em] text-indigo-700/80 dark:text-indigo-300/80">
              实时分析
            </span>
            <span className="inline-flex items-center rounded-md border border-border/60 bg-background/70 px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.04em] text-sky-700/80 dark:text-sky-300/80">
              长文本优先
            </span>
            <span className="inline-flex items-center rounded-md border border-border/60 bg-background/70 px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.04em] text-emerald-700/80 dark:text-emerald-300/80">
              回归线索
            </span>
          </div>
        }
        actions={
          <Button
            variant="outline"
            className="gap-2 rounded-xl bg-card/60 text-muted-foreground shadow-sm transition-colors duration-200 hover:border-border/80 hover:bg-card hover:text-foreground motion-reduce:transition-none"
            onClick={() => refetch()}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
            刷新数据
          </Button>
        }
        top={
          <div className="pt-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { label: '总反馈量', value: stats.total, icon: MessageSquare, color: 'text-indigo-600 dark:text-indigo-400', bg: 'bg-indigo-50 dark:bg-indigo-500/10', border: 'border-indigo-100/70 dark:border-indigo-500/10' },
                { label: '点赞', value: stats.upvotes, icon: ThumbsUp, color: 'text-success', bg: 'bg-success/10', border: 'border-emerald-100/80 dark:border-emerald-500/10' },
                { label: '点踩', value: stats.downvotes, icon: ThumbsDown, color: 'text-destructive', bg: 'bg-destructive/10', border: 'border-rose-100/80 dark:border-rose-500/10' },
                { label: '中立反馈', value: stats.total - stats.upvotes - stats.downvotes, icon: Star, color: 'text-sky-600 dark:text-sky-400', bg: 'bg-sky-50 dark:bg-sky-500/10', border: 'border-sky-100/80 dark:border-sky-500/10' },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className={cn(
                    'rounded-xl border bg-card/90 px-4 py-3 shadow-soft',
                    stat.border
                  )}
                >
                  <div className="flex items-center gap-2">
                    <div className={cn('flex size-8 items-center justify-center rounded-lg', stat.bg)}>
                      <stat.icon className={cn('size-4', stat.color)} />
                    </div>
                    <div className="text-[11px] font-semibold tracking-[0.08em] text-muted-foreground">
                      {stat.label}
                    </div>
                  </div>
                  <div className={cn('mt-3 text-[1.85rem] font-black leading-none tracking-tight', stat.color)}>
                    {stat.value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        }
        bodyClassName="px-3 md:px-4 xl:px-5 pb-10 z-10"
      >
        <div className="overflow-hidden rounded-2xl border border-border/60 bg-card shadow-soft">
          <div className="border-b border-border/60 px-4 py-3.5">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="min-w-0">
                <div className="text-sm font-black text-foreground">反馈列表</div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>{items.length ? '长反馈与答复摘要优先' : '当前暂无反馈'}</span>
                  {listSummary ? (
                    <>
                      <span className="text-muted-foreground/35">·</span>
                      <span className="font-medium text-foreground/75">{listSummary}</span>
                    </>
                  ) : null}
                </div>
              </div>

              <div className="flex w-full flex-col gap-2 xl:w-auto xl:flex-row xl:items-center">
                <SearchInput
                  value={searchTerm}
                  onValueChange={setSearchTerm}
                  placeholder="搜索反馈 / 原因 / 标签 / 账号"
                  containerClassName="w-full xl:min-w-[20rem]"
                  inputClassName="h-9 rounded-xl border-border/60 bg-background/70 shadow-none"
                />

                <Select value={filterType} onValueChange={(v) => setFilterType(v as FeedbackTypeFilter)}>
                  <SelectTrigger
                    title={filterType === 'all' ? '按类型筛选（当前：全部）' : filterType === 'thumbs_up' ? '按类型筛选：点赞反馈' : '按类型筛选：点踩反馈'}
                    className="h-9 w-full rounded-lg border-border/55 bg-background px-3 shadow-none xl:w-[8.75rem] [&>svg]:text-muted-foreground/65"
                  >
                    <span className="truncate pr-2 text-sm font-medium text-foreground">
                      {filterType === 'all' ? '类型' : filterType === 'thumbs_up' ? '类型 · 点赞' : '类型 · 点踩'}
                    </span>
                  </SelectTrigger>
                  <SelectContent className="rounded-lg border-border/60 bg-popover/98 p-1 shadow-[0_18px_34px_-26px_hsl(var(--foreground)/0.18)]">
                    <SelectItem value="all">全部</SelectItem>
                    <SelectItem value="thumbs_up">点赞</SelectItem>
                    <SelectItem value="thumbs_down">点踩</SelectItem>
                  </SelectContent>
                </Select>

                <Select value={ratingFilter} onValueChange={(v) => setRatingFilter(v as RatingFilter)}>
                  <SelectTrigger
                    title={ratingFilter === 'all' ? '按星级筛选（当前：全部）' : `按星级筛选：${ratingFilter} 星反馈`}
                    className="h-9 w-full rounded-lg border-border/55 bg-background px-3 shadow-none xl:w-[8.75rem] [&>svg]:text-muted-foreground/65"
                  >
                    <span className="truncate pr-2 text-sm font-medium text-foreground">
                      {ratingFilter === 'all' ? '星级' : `星级 · ${ratingFilter} 星`}
                    </span>
                  </SelectTrigger>
                  <SelectContent className="rounded-lg border-border/60 bg-popover/98 p-1 shadow-[0_18px_34px_-26px_hsl(var(--foreground)/0.18)]">
                    <SelectItem value="all">全部</SelectItem>
                    <SelectItem value="5">5 星</SelectItem>
                    <SelectItem value="4">4 星</SelectItem>
                    <SelectItem value="3">3 星</SelectItem>
                    <SelectItem value="2">2 星</SelectItem>
                    <SelectItem value="1">1 星</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {filtered.length ? (
            <div className="space-y-3 p-3">
              {filtered.map((item) => {
                const kind = classifyFeedback(item.rating)
                const isUp = kind === 'thumbs_up'
                const isDown = kind === 'thumbs_down'
                const ratingValue = Number(item.rating) || 0
                const toneLabel = isUp ? '点赞' : isDown ? '点踩' : ratingValue > 0 ? `${ratingValue} 星` : '中立'
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setDetail(item)}
                    aria-label={`查看反馈详情：${item.reason || '用户未填写原因'}`}
                    className="group relative w-full cursor-pointer overflow-hidden rounded-xl border border-border/60 bg-background/70 text-left transition-colors duration-200 hover:border-primary/20 hover:bg-accent/30 focus-ring motion-reduce:transition-none"
                  >
                    <div
                      className={cn(
                        'absolute bottom-0 left-0 top-0 w-1 transition-colors',
                        isUp
                          ? 'bg-success group-hover:bg-success/80'
                          : isDown
                            ? 'bg-destructive group-hover:bg-destructive/80'
                            : 'bg-muted-foreground/30 group-hover:bg-muted-foreground/40'
                      )}
                    />

                    <div className="flex items-start gap-4 p-5 pl-7">
                      <div
                        className={cn(
                          'flex h-10 w-10 shrink-0 items-center justify-center rounded-full border',
                          isUp
                            ? 'border-success/20 bg-success/10 text-success'
                            : isDown
                              ? 'border-destructive/20 bg-destructive/10 text-destructive'
                              : 'border-border bg-muted text-muted-foreground'
                        )}
                      >
                        {isUp ? (
                          <ThumbsUp className="size-5" />
                        ) : isDown ? (
                          <ThumbsDown className="size-5" />
                        ) : (
                          <Star className="size-5" />
                        )}
                      </div>

                      <div className="min-w-0 flex-1 pt-0.5">
                        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={cn(
                                'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-[0.05em]',
                                isUp
                                  ? 'border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300'
                                  : isDown
                                    ? 'border-rose-200/80 bg-rose-50 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300'
                                    : 'border-border/60 bg-muted/60 text-muted-foreground'
                              )}
                            >
                              {toneLabel}
                            </span>
                            {ratingValue > 0 ? (
                              <span className="inline-flex items-center rounded-full border border-border/60 bg-background px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                                评分 {ratingValue}/5
                              </span>
                            ) : null}
                          </div>
                          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                            <span className="text-xs font-bold text-indigo-500 dark:text-indigo-400">查看详情</span>
                            <ArrowRight className="size-3 text-indigo-500 dark:text-indigo-400" />
                          </div>
                        </div>

                        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span className="truncate font-medium text-foreground/85">
                            {item.conversation_title || '未命名对话'}
                          </span>
                          <span className="text-muted-foreground/40">·</span>
                          <span className="font-mono">{item.id.slice(0, 8)}</span>
                          <span className="text-muted-foreground/40">·</span>
                          <span>{formatDate(item.created_at)}</span>
                        </div>

                        <div className="grid gap-3 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
                          <div className="rounded-lg border border-border bg-muted/45 p-3.5">
                            <div className="mb-2 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground">
                              用户反馈
                            </div>
                            <p className="line-clamp-4 text-sm leading-6 text-foreground/88">
                              {item.reason || '用户未填写原因'}
                            </p>
                          </div>

                          <div className="rounded-lg border border-border bg-muted/60 p-3.5">
                            <div className="mb-2 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground">
                              模型答复摘要
                            </div>
                            <p className="line-clamp-4 text-sm leading-6 text-muted-foreground">
                              {item.message_content || '（无消息内容）'}
                            </p>
                          </div>
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
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center px-6 py-20 text-center">
              <div className="mb-5 flex size-24 items-center justify-center rounded-full bg-muted/50">
                <Search className="size-9 text-muted-foreground/55" aria-hidden="true" />
              </div>
              <p className="text-[15px] font-semibold text-foreground">没有找到相关的反馈记录</p>
              <p className="mt-2 max-w-lg text-[13px] leading-6 text-muted-foreground/85">
                {hasActiveFilters ? '可以清除当前筛选条件，查看完整反馈流。' : '当前没有可分析的反馈数据，可使用右上角刷新获取最新结果。'}
              </p>
              {hasActiveFilters ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-5 rounded-xl"
                  onClick={() => {
                    setSearchTerm('')
                    setFilterType('all')
                    setRatingFilter('all')
                  }}
                >
                  清除筛选
                </Button>
              ) : null}
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
