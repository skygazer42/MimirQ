/**
 * 对话历史页面
 */
'use client'

import { useState, useEffect, useLayoutEffect, useRef, Suspense, useCallback, useDeferredValue, useMemo } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useSearchParams } from 'next/navigation'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  MessageSquare,
  Trash2,
  Send,
  Loader2,
  BarChart3,
  History,
  X,
  Plus,
  Route,
  Search,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react'
import { AppFrame } from '@/components/app-frame'
import { ChatMessageItem } from '@/components/chat/message-item'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { ConversationOpsPanel } from '@/components/history/conversation-ops-panel'
import { AnswerLineageAction } from '@/components/history/answer-lineage-action'
import { RagTraceDialog } from '@/components/rag-trace/rag-trace-dialog'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { PageLoading } from '@/components/ui/page-loading'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Link, useRouter } from '@/i18n/navigation'
import { chatApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { toast } from 'sonner'
import type { Conversation, Message } from '@/types'

type HistoryPageClientProps = {
  initialConversationId?: string | null
  initialConversations?: Conversation[]
  initialSelectedConversation?: Conversation | null
  initialMessages?: Message[]
  initialHasMoreMessages?: boolean
  initialHasMoreConversations?: boolean
  initialConversationNextSkip?: number | null
  initialConversationTotal?: number
  initialConversationsLoaded?: boolean
}

type HistoryPageContentProps = {
  initialConversationId: string | null
  initialConversations: Conversation[]
  initialSelectedConversation: Conversation | null
  initialMessages: Message[]
  initialHasMoreMessages: boolean
  initialHasMoreConversations: boolean
  initialConversationNextSkip: number | null
  initialConversationTotal: number
  initialConversationsLoaded: boolean
}

const EMPTY_CONVERSATIONS: Conversation[] = []
const EMPTY_MESSAGES: Message[] = []
const CONVERSATION_PAGE_SIZE = 100

export default function HistoryPageClient({
  initialConversationId = null,
  initialConversations = [],
  initialSelectedConversation = null,
  initialMessages = [],
  initialHasMoreMessages = false,
  initialHasMoreConversations = false,
  initialConversationNextSkip = null,
  initialConversationTotal = initialConversations.length,
  initialConversationsLoaded = false,
}: Readonly<HistoryPageClientProps>) {
  return (
    <Suspense fallback={<HistoryPageLoading />}>
      <HistoryPageContent
        initialConversationId={initialConversationId}
        initialConversations={initialConversations}
        initialSelectedConversation={initialSelectedConversation}
        initialMessages={initialMessages}
        initialHasMoreMessages={initialHasMoreMessages}
        initialHasMoreConversations={initialHasMoreConversations}
        initialConversationNextSkip={initialConversationNextSkip}
        initialConversationTotal={initialConversationTotal}
        initialConversationsLoaded={initialConversationsLoaded}
      />
    </Suspense>
  )
}

const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40

function HistoryPageLoading() {
  const t = useTranslations('History')

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding>
      <PageLoading message={t('loadingPage')} srMessage={t('loadingPageSr')} />
    </AppFrame>
  )
}

function HistoryPageContent({
  initialConversationId,
  initialConversations,
  initialSelectedConversation,
  initialMessages,
  initialHasMoreMessages,
  initialHasMoreConversations,
  initialConversationNextSkip,
  initialConversationTotal,
  initialConversationsLoaded,
}: Readonly<HistoryPageContentProps>) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const locale = useLocale()
  const t = useTranslations('History')
  const conversationId = searchParams.get('id') || initialConversationId || null

  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isWideHistoryViewport, setIsWideHistoryViewport] = useState(false)
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(initialSelectedConversation)
  const [searchQuery, setSearchQuery] = useState('')
  const [historyView, setHistoryView] = useState<'all' | 'recent'>('all')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
  const [isTraceOpen, setIsTraceOpen] = useState(false)

  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const conversationLoadMoreRef = useRef<HTMLDivElement>(null)
  const pendingPrependScrollRef = useRef<{ top: number; height: number } | null>(null)
  const shouldScrollToEndRef = useRef(false)
  const deferredSearchQuery = useDeferredValue(searchQuery)
  const conversationsQuery = useInfiniteQuery({
    queryKey: queryKeys.chat.conversationPages({ limit: CONVERSATION_PAGE_SIZE }),
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const result = await chatApi.listConversations({
        skip: Number(pageParam) || 0,
        limit: CONVERSATION_PAGE_SIZE,
      })
      return {
        items: result.items || [],
        total: Number(result.total || 0),
        returned: Number(result.returned ?? result.items?.length ?? 0),
        has_more: Boolean(result.has_more),
        next_skip: typeof result.next_skip === 'number' ? result.next_skip : null,
      }
    },
    getNextPageParam: (lastPage, allPages) => {
      if (!lastPage.has_more) return undefined
      if (typeof lastPage.next_skip === 'number') return lastPage.next_skip
      return allPages.reduce((sum, page) => sum + Number(page.returned ?? page.items?.length ?? 0), 0)
    },
    initialData: initialConversationsLoaded
      ? {
          pages: [
            {
              items: initialConversations,
              total: initialConversationTotal,
              returned: initialConversations.length,
              has_more: initialHasMoreConversations,
              next_skip: initialConversationNextSkip,
            },
          ],
          pageParams: [0],
        }
      : undefined,
  })
  const conversations = useMemo(() => {
    const seen = new Set<string>()
    const merged: Conversation[] = []
    for (const page of conversationsQuery.data?.pages || []) {
      for (const conversation of page.items || []) {
        if (seen.has(conversation.id)) continue
        seen.add(conversation.id)
        merged.push(conversation)
      }
    }
    return merged.length ? merged : EMPTY_CONVERSATIONS
  }, [conversationsQuery.data])
  const isLoadingList = conversationsQuery.isLoading
  const hasMoreConversations = conversationsQuery.hasNextPage
  const isLoadingMoreConversations = conversationsQuery.isFetchingNextPage
  const selectedConversationId = selectedConversation?.id || null
  const messagesQuery = useInfiniteQuery({
    queryKey: queryKeys.chat.messages(selectedConversationId || ''),
    enabled: Boolean(selectedConversationId),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const result = await chatApi.getMessages(selectedConversationId || '', {
        limit: pageParam ? LOAD_MORE_STEP : DEFAULT_VISIBLE_MESSAGES,
        before: pageParam,
      })
      return {
        conversation_id: result.conversation_id,
        messages: result.messages || [],
        returned: Number(result.returned ?? result.messages?.length ?? 0),
        has_more: Boolean(result.has_more),
      }
    },
    getPreviousPageParam: (firstPage) =>
      firstPage.has_more ? firstPage.messages?.[0]?.id || undefined : undefined,
    getNextPageParam: () => undefined,
    initialData:
      initialSelectedConversation?.id && initialSelectedConversation.id === selectedConversationId
        ? {
            pages: [
              {
                conversation_id: initialSelectedConversation.id,
                messages: initialMessages,
                returned: initialMessages.length,
                has_more: initialHasMoreMessages,
              },
            ],
            pageParams: [undefined],
          }
        : undefined,
  })
  const messages = useMemo(
    () => messagesQuery.data?.pages.flatMap((page) => page.messages || []) ?? EMPTY_MESSAGES,
    [messagesQuery.data]
  )
  const hasMoreMessages = messagesQuery.hasPreviousPage
  const isLoadingOlder = messagesQuery.isFetchingPreviousPage
  const isLoadingMessages = Boolean(selectedConversationId) && messagesQuery.isLoading

  useEffect(() => {
    const media = globalThis.window.matchMedia('(min-width: 1280px)')
    const updateViewportWidth = () => setIsWideHistoryViewport(media.matches)

    updateViewportWidth()
    media.addEventListener('change', updateViewportWidth)
    return () => media.removeEventListener('change', updateViewportWidth)
  }, [])

  const handleSelectConversation = useCallback(async (conversation: Conversation) => {
    if (selectedConversation?.id === conversation.id) return

    shouldScrollToEndRef.current = true
    setSelectedConversation(conversation)

    // 更新 URL
    router.push(`/history?id=${conversation.id}`, { scroll: false })
  }, [router, selectedConversation?.id])

  useEffect(() => {
    if (!conversationsQuery.error) return
    reportClientError('Failed to load conversations', conversationsQuery.error)
    toast.error(formatApiError(conversationsQuery.error, t('loadConversationListFailed')))
  }, [conversationsQuery.error, t])

  const loadMoreConversations = useCallback(async () => {
    if (!hasMoreConversations || isLoadingMoreConversations) return
    try {
      await conversationsQuery.fetchNextPage()
    } catch (error) {
      reportClientError('Failed to load older conversations', error)
      toast.error(formatApiError(error, t('loadConversationListFailed')))
    }
  }, [conversationsQuery, hasMoreConversations, isLoadingMoreConversations, t])

  useEffect(() => {
    const node = conversationLoadMoreRef.current
    if (!node || !hasMoreConversations) return

    const root = node.closest('[data-history-sidebar-scroll]')
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        void loadMoreConversations()
      },
      {
        root,
        rootMargin: '240px 0px',
      }
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasMoreConversations, loadMoreConversations])

  // 当 URL 中有 id 参数时，自动选中对话
  useEffect(() => {
    if (conversationId && conversations.length > 0) {
      const conv = conversations.find((c) => c.id === conversationId)
      if (conv && selectedConversation?.id !== conv.id) {
        shouldScrollToEndRef.current = true
        setSelectedConversation(conv)
      }
    }
  }, [conversationId, conversations, selectedConversation?.id])

  useEffect(() => {
    if (!selectedConversationId) return
    if (messagesQuery.error) {
      reportClientError('Failed to load conversation messages', messagesQuery.error)
      toast.error(formatApiError(messagesQuery.error, t('loadConversationMessagesFailed')))
      return
    }
    if (!messagesQuery.isSuccess) return
    if (!shouldScrollToEndRef.current) return
    shouldScrollToEndRef.current = false
    globalThis.window.requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' })
    })
  }, [messagesQuery.error, messagesQuery.isSuccess, selectedConversationId, t])

  // Preserve scroll position when prepending older messages.
  useLayoutEffect(() => {
    const pending = pendingPrependScrollRef.current
    if (!pending) return
    const el = messagesContainerRef.current
    if (!el) {
      pendingPrependScrollRef.current = null
      return
    }
    const nextHeight = el.scrollHeight
    el.scrollTop = pending.top + (nextHeight - pending.height)
    pendingPrependScrollRef.current = null
  }, [messages])

  const handleDeleteConversation = async (conversationId: string) => {
    try {
      await chatApi.deleteConversation(conversationId)
      queryClient.setQueryData(
        queryKeys.chat.conversationPages({ limit: CONVERSATION_PAGE_SIZE }),
        (
          current:
            | {
                pages?: Array<{
                  items?: Conversation[]
                  total?: number
                  returned?: number
                }>
                pageParams?: unknown[]
              }
            | undefined
        ) =>
          current
            ? {
                ...current,
                pages: (current.pages || []).map((page) => {
                  const items = (page.items || []).filter((conversation) => conversation.id !== conversationId)
                  const removed = (page.items || []).length - items.length
                  return {
                    ...page,
                    items,
                    returned: Math.max(0, Number(page.returned ?? page.items?.length ?? 0) - removed),
                    total: Math.max(0, Number(page.total || 0) - removed),
                  }
                }),
              }
            : current
      )
      if (selectedConversation?.id === conversationId) {
        setSelectedConversation(null)
        router.push('/history', { scroll: false })
      }
    } catch (error) {
      reportClientError('Failed to delete conversation', error)
    } finally {
      setShowDeleteConfirm(null)
    }
  }

  const handleContinueChat = () => {
    if (selectedConversation) {
      router.push(`/?conversation=${selectedConversation.id}`)
    }
  }

  const handleEvaluateConversation = () => {
    if (selectedConversation) {
      router.push(`/evaluations?conversation_id=${selectedConversation.id}`, { scroll: false })
    }
  }

  // 过滤对话
  const filteredConversations = useMemo(() => {
    let base = conversations
    if (historyView === 'recent') {
      const now = Date.now()
      base = base.filter((c) => {
        const activityDate = c.last_message_at || c.updated_at || c.created_at
        const ts = new Date(activityDate).getTime()
        return Number.isFinite(ts) && now - ts <= 7 * 24 * 60 * 60 * 1000
      })
    }
    const term = deferredSearchQuery.trim().toLowerCase()
    if (!term) return base
    return base.filter(
      (c) =>
        (c.title || '').toLowerCase().includes(term) ||
        (c.last_message || '').toLowerCase().includes(term)
    )
  }, [conversations, deferredSearchQuery, historyView])

  const groupLabels = useMemo(
    () => ({
      today: t('groupToday'),
      yesterday: t('groupYesterday'),
      last7Days: t('groupLast7Days'),
      last30Days: t('groupLast30Days'),
      earlier: t('groupEarlier'),
    }),
    [t]
  )

  // 按日期分组
  const groupedConversations = useMemo(
    () => groupConversationsByDate(filteredConversations, groupLabels),
    [filteredConversations, groupLabels]
  )
  const groupOrder = [
    groupLabels.today,
    groupLabels.last7Days,
    groupLabels.last30Days,
    groupLabels.earlier,
  ]
  const oldestMessageId = messages[0]?.id
  const groupedMessages = useMemo(
    () =>
      groupMessagesByDay(messages, locale, {
        today: groupLabels.today,
        yesterday: groupLabels.yesterday,
      }),
    [groupLabels.today, groupLabels.yesterday, locale, messages]
  )

  const loadOlderMessages = useCallback(async () => {
    if (!selectedConversation) return
    if (!hasMoreMessages) return
    if (isLoadingMessages || isLoadingOlder) return
    if (!oldestMessageId) return

    const el = messagesContainerRef.current
    if (el) {
      pendingPrependScrollRef.current = { top: el.scrollTop, height: el.scrollHeight }
    }

    try {
      await messagesQuery.fetchPreviousPage()
    } catch (error) {
      reportClientError('Failed to load older messages', error)
      toast.error(formatApiError(error, t('loadOlderMessagesFailed')))
    }
  }, [selectedConversation, hasMoreMessages, isLoadingMessages, isLoadingOlder, oldestMessageId, messagesQuery, t])
  const sidebarExpandedWidth = isWideHistoryViewport ? '20.75rem' : '19.5rem'

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding mainClassName="overflow-hidden">
      <PageScaffold
        title={t('pageTitle')}
        icon={History}
        showHeader={false}
        size="full"
        bodyClassName="p-0 overflow-hidden"
        bodyContainerClassName="h-full max-w-none"
      >
        <div className="h-full overflow-hidden">
          <section className="relative flex h-full min-h-0 overflow-hidden bg-background">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-primary/[0.04]"
            />

            {/* 侧边栏 - 对话列表 */}
            <motion.aside 
              initial={false}
              animate={{ 
                width: isSidebarCollapsed ? 0 : sidebarExpandedWidth,
                opacity: isSidebarCollapsed ? 0 : 1,
                borderRightWidth: isSidebarCollapsed ? 0 : 1
              }}
              transition={{ type: 'spring', stiffness: 300, damping: 30, mass: 0.8 }}
              className={cn(
                "relative z-10 flex shrink-0 flex-col border-r border-border/60 bg-muted/30 overflow-hidden"
              )}
            >
              {/* 头部 - 已扁平化 */}
              <div className="sticky top-0 z-20 border-b border-border/50 px-2 pt-2 pb-1.5 space-y-1 min-w-[19.5rem] backdrop-blur-md bg-background/80">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-2xl border border-sky-200/70 bg-[radial-gradient(circle_at_34%_24%,rgba(255,255,255,0.98),rgba(226,243,255,0.86)_48%,rgba(219,234,254,0.66)_100%)] text-primary shadow-[0_8px_18px_rgba(37,99,235,0.12)] ring-1 ring-white/80">
                      <PageTitleIcon name="qa-history" className="size-7" />
                    </div>
                    <h2 className="text-sm font-medium text-foreground  uppercase">历史记录</h2>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8 rounded-full hover:bg-muted text-muted-foreground"
                      onClick={() => setIsSidebarCollapsed(true)}
                      aria-label="收起侧边栏"
                      title="收起侧边栏"
                    >
                      <PanelLeftClose className="size-4" />
                    </Button>
                  </div>
                </div>
                
                <div className="relative group">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground/50 group-focus-within:text-primary transition-colors" />
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('searchPlaceholder')}
                    className="w-full h-9 pl-8 pr-3 rounded-xl border border-border/60 bg-background/60 backdrop-blur-sm text-xs font-medium outline-none focus:ring-1 focus:ring-primary/30 focus:border-primary/40 focus:bg-background transition-all"
                  />
                </div>

                <div className="flex items-center gap-1 px-0.5 pb-0.5">
                  {([
                    ['all', '全部'],
                    ['recent', '最近'],
                  ] as const).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setHistoryView(value)}
                      className={cn(
                        'rounded-full px-3 py-1 text-[11px] font-medium transition-colors',
                        historyView === value
                          ? 'border border-primary/15 bg-primary/10 text-primary shadow-sm'
                          : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 对话列表 */}
              <div
                data-history-sidebar-scroll
                className="flex-1 overflow-y-auto overscroll-contain no-scrollbar px-0 py-0.5"
              >
                {(() => {
    if (isLoadingList) {
        return (<div className="flex items-center justify-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                    </div>);
    }
    else if (filteredConversations.length === 0) {
            return <HistorySidebarEmptyState isSearching={Boolean(searchQuery.trim())} />;
        }
        else {
            return (<>
              {groupOrder.map((group) => {
                const convs = groupedConversations[group];
                if (!convs || convs.length === 0)
                    return null;
                const groupTone = getConversationGroupTone(group, groupLabels);
                return (<div key={group} className="pb-0.5 last:pb-0">
                          <div className="sticky top-0 z-10 px-0 pb-0 pt-0 bg-transparent">
                            <div className="flex items-center gap-2">
                              <div className={cn("h-px flex-1", groupTone.lineClass)} />
                              <div className={cn("inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] shadow-sm", groupTone.chipClass)}>
                                <span suppressHydrationWarning>{group}</span>
                                <span className={cn("rounded-full px-1.5 py-0.5 text-[11px] font-semibold", groupTone.countClass)}>
                                  {convs.length}
                                </span>
                              </div>
                              <div className={cn("h-px flex-1", groupTone.lineClass)} />
                            </div>
                          </div>
                          <div className="space-y-0 px-0 pb-0">
                            {convs.map((conversation) => (<ConversationItem key={conversation.id} conversation={conversation} isSelected={selectedConversation?.id === conversation.id} onSelect={() => handleSelectConversation(conversation)} onDelete={() => setShowDeleteConfirm(conversation.id)} showDeleteConfirm={showDeleteConfirm === conversation.id} onConfirmDelete={() => handleDeleteConversation(conversation.id)} onCancelDelete={() => setShowDeleteConfirm(null)}/>))}
                          </div>
                        </div>);
              })}
              <div ref={conversationLoadMoreRef} className="px-3 py-3 text-center">
                {hasMoreConversations ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={loadMoreConversations}
                    disabled={isLoadingMoreConversations}
                    className="h-8 rounded-full px-3 text-[11px] font-medium text-muted-foreground hover:text-foreground"
                  >
                    {isLoadingMoreConversations ? (
                      <>
                        <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
                        加载中
                      </>
                    ) : (
                      '加载更早记录'
                    )}
                  </Button>
                ) : (
                  <span className="text-[11px] text-muted-foreground/45">已显示全部历史</span>
                )}
              </div>
            </>);
        }
        })()}
        </div>
        </motion.aside>
            {/* 主区域 - 对话详情 */}
            <motion.div 
              layout
              className={cn(
                "relative flex min-w-0 flex-1 flex-col transition-colors duration-500",
                isSidebarCollapsed ? "bg-background/40" : "bg-background/65"
              )}
            >
              {/* 悬浮侧边栏展开按钮 - 仅在收起时显示，且固定在边缘 */}
              <AnimatePresence>
                {isSidebarCollapsed && (
                  <motion.div
                    initial={{ x: -20, opacity: 0 }}
                    animate={{ x: 0, opacity: 1 }}
                    exit={{ x: -20, opacity: 0 }}
                    transition={{ type: 'spring', stiffness: 300, damping: 30 }}
                    className="absolute left-4 top-3.5 z-30"
                  >
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-10 rounded-2xl bg-background/80 backdrop-blur-md border border-border/40 hover:bg-muted text-muted-foreground shadow-soft transition-all active:scale-95"
                      onClick={() => setIsSidebarCollapsed(false)}
                      aria-label="展开侧边栏"
                      title="展开侧边栏"
                    >
                      <PanelLeftOpen className="size-5" />
                    </Button>
                  </motion.div>
                )}
              </AnimatePresence>

              {selectedConversation ? (
                <>
                  {/* 对话头部 - 极简重构版 */}
                  <div className="border-b border-border/40 bg-background/80 backdrop-blur sticky top-0 z-20 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
                    <motion.div 
                      layout
                      className={cn(
                        "mx-auto px-4 py-3 md:px-6 xl:px-8 transition-all duration-500",
                        isSidebarCollapsed ? "max-w-6xl" : "max-w-5xl"
                      )}
                    >
                      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                        <div className="min-w-0 flex items-center gap-3">
                          {!isSidebarCollapsed && (
                            <>
                              <div className="size-10 shrink-0 rounded-2xl bg-primary/5 border border-primary/10 flex items-center justify-center text-primary shadow-[0_2px_8px_-3px_rgba(var(--primary),0.08)]">
                                <MessageSquare className="size-5" />
                              </div>
                              <div className="w-px h-6 bg-border/40 mx-1 hidden md:block" />
                            </>
                          )}
                          
                          {/* 如果收起，留出悬浮按钮的位移空间 */}
                          <div className={cn(
                            "min-w-0 flex flex-col justify-center transition-all duration-500",
                            isSidebarCollapsed ? "ml-12" : "ml-0"
                          )}>
                            <h2 className="truncate text-base font-medium text-foreground/92  leading-tight md:text-lg">
                              {selectedConversation.title || t("untitledConversation")}
                            </h2>
                            <div className="flex items-center gap-1 mt-0.5 tabular-nums">
                              <span className="inline-flex items-center rounded-md bg-muted/30 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground/50 border border-border/10">
                                {t("messageCount", { count: selectedConversation.message_count })}
                              </span>
                              <span className="text-muted-foreground/20 text-[11px] leading-none px-0.5">•</span>
                              <span suppressHydrationWarning className="inline-flex items-center gap-1 rounded-md bg-muted/30 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground/50 border border-border/10">
                                {formatDate(selectedConversation.created_at, locale)}
                              </span>
                            </div>
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={handleEvaluateConversation}
                            aria-label="进行对话分析评测"
                            className="h-8 gap-1.5 rounded-lg text-[11px] font-medium text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-all"
                          >
                            <BarChart3 className="size-3.5" />
                            分析评测
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setIsTraceOpen(true)}
                            aria-label="查看数据追踪"
                            className="h-8 gap-1.5 rounded-lg text-[11px] font-medium text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-all"
                          >
                            <Route className="size-3.5" />
                            数据追踪
                          </Button>
                          <div className="w-px h-3 bg-border/60 mx-1 hidden sm:block" />
                          <Button
                            variant="default"
                            size="sm"
                            onClick={handleContinueChat}
                            aria-label="继续当前对话"
                            className="h-8 gap-1.5 rounded-lg px-3.5 text-[11px] font-medium shadow-sm"
                          >
                            <Send className="size-3.5" />
                            继续对话
                          </Button>
                        </div>
                      </div>
                    </motion.div>
                  </div>

                  {/* 消息列表 */}
                  <div
                    ref={messagesContainerRef}
                    className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-muted/[0.12] px-4 pt-0 pb-6 md:px-6 md:pb-8 xl:px-8"
                  >
                    {(() => {
    if (isLoadingMessages) {
        return (<div className="flex h-full items-center justify-center">
                          <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                        </div>);
    }
    else if (messages.length === 0) {
            return (<div className="flex h-full items-center justify-center">
                          <div className="rounded-3xl border border-dashed border-border/70 bg-background/80 px-8 py-12 text-center text-muted-foreground shadow-sm">
                            <MessageSquare className="mx-auto mb-4 h-12 w-12 opacity-10"/>
                            <p>{t('noMessageRecords')}</p>
                          </div>
                        </div>);
        }
                        else {
            return (<AnimatePresence mode="wait">
                        <motion.div 
                          layout
                          key={selectedConversation.id}
                          initial="hidden"
                          animate="visible"
                          variants={{
                            hidden: { opacity: 0 },
                            visible: { 
                              opacity: 1,
                              transition: {
                                staggerChildren: 0.05
                              }
                            }
                          }}
                          className={cn(
                            "mx-auto w-full space-y-6 pt-4 transition-all duration-500",
                            isSidebarCollapsed ? "max-w-6xl" : "max-w-5xl"
                          )}
                        >
                          <ConversationOpsPanel conversationId={selectedConversation.id} />
                          {hasMoreMessages ? (<div className="flex justify-center mb-4">
                              <Button variant="ghost" size="sm" onClick={loadOlderMessages} disabled={isLoadingOlder} className="rounded-full text-[11px] font-bold uppercase  text-muted-foreground/60 hover:text-foreground">
                                {isLoadingOlder ? t('loading') : t('loadOlderMessages')}
                              </Button>
                            </div>) : null}
                          {groupedMessages.map((group) => (<div key={group.key} className="space-y-6">
                              <div className="flex items-center gap-6 py-1">
                                <div className="h-px flex-1 bg-border/30" />
                                <div suppressHydrationWarning className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground/28 whitespace-nowrap">
                                  {group.label}
                                </div>
                                <div className="h-px flex-1 bg-border/30" />
                              </div>
                              <div className="space-y-6">
                                {group.messages.map((message) => (<HistoryMessageEntry key={message.id} message={message} locale={locale} />))}
                              </div>
                            </div>))}
                          <div ref={messagesEndRef} className="h-4"/>
                        </motion.div>
                      </AnimatePresence>);
        }
})()}
                  </div>
                </>
              ) : (
                <HistoryMainEmptyState />
              )}
            </motion.div>
          </section>
        </div>
        <RagTraceDialog
          open={isTraceOpen}
          onOpenChange={setIsTraceOpen}
          conversationId={selectedConversation?.id || null}
          title={selectedConversation?.title || null}
        />
      </PageScaffold>
    </AppFrame>
  )
}

function HistoryMainEmptyState() {
  const t = useTranslations('History')
  const descriptionLines = t('noConversationSelectedDescription').split('\n')

  return (
    <div className="flex-1 bg-muted/[0.12] p-4 md:p-6">
      <section
        data-history-main-empty="true"
        className="relative isolate flex min-h-full items-center justify-center overflow-hidden rounded-[32px] border border-sky-100/80 bg-[linear-gradient(135deg,rgba(14,165,233,0.08),transparent_42%),radial-gradient(circle_at_50%_105%,rgba(59,130,246,0.10),transparent_45%)] px-8 py-12 text-center shadow-soft"
      >
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-[linear-gradient(to_right,rgba(14,165,233,0.08)_1px,transparent_1px),linear-gradient(to_bottom,rgba(14,165,233,0.07)_1px,transparent_1px)] bg-[size:44px_44px] opacity-35"
        />
        <div
          aria-hidden="true"
          className="absolute left-1/2 top-1/2 size-[420px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-sky-200/20 blur-3xl"
        />

        <div className="relative mx-auto flex max-w-xl flex-col items-center">
          <div className="mb-5 grid size-[72px] place-items-center rounded-[26px] border border-sky-200/80 bg-[linear-gradient(145deg,rgba(255,255,255,0.96),rgba(224,244,255,0.84))] text-primary shadow-[0_18px_38px_rgba(14,165,233,0.16)]">
            <History className="size-8" />
          </div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.32em] text-sky-500/80">
            {t('historyEmptyKicker')}
          </p>
          <h2 className="mt-3 text-xl font-semibold tracking-[-0.04em] text-foreground">
            {t('noConversationSelected')}
          </h2>
          <p className="mt-3 max-w-md text-sm leading-7 text-muted-foreground/78">
            {descriptionLines[0]}<br />
            {descriptionLines[1]}
          </p>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            <Button asChild className="h-10 rounded-full bg-info px-5 text-[13px] font-semibold text-primary-foreground shadow-[0_14px_28px_hsl(var(--info)/0.24)] hover:bg-info/90">
              <Link href="/">
                <Plus className="h-4 w-4" />
                {t('startNewConversation')}
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              size="sm"
              className="h-10 rounded-full border-warning/20 bg-warning/10 px-4 text-xs font-semibold text-warning shadow-sm hover:bg-warning/15 hover:text-warning"
            >
              <Link href="/evaluations">
                <BarChart3 className="h-3.5 w-3.5" />
                {t('evaluateConversation')}
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              size="sm"
              className="h-10 rounded-full border-info/20 bg-info/10 px-4 text-xs font-semibold text-info shadow-sm hover:bg-info/15 hover:text-info"
            >
              <Link href="/observability">
                <Route className="h-3.5 w-3.5" />
                {t('ragTrace')}
              </Link>
            </Button>
          </div>

          <div className="mt-7 grid w-full max-w-lg gap-2 text-left sm:grid-cols-3">
            {[
              ['答案留存', '保存对话结论'],
              ['证据回看', '追溯引用来源'],
              ['评测追踪', '连接质量诊断'],
            ].map(([title, desc]) => (
              <div
                key={title}
                className="rounded-2xl border border-border/80 bg-background/72 px-3.5 py-3 shadow-[0_10px_24px_rgba(15,23,42,0.05)] backdrop-blur"
              >
                <div className="flex items-center gap-2 text-[12px] font-semibold text-foreground/82">
                  <span className="size-1.5 rounded-full bg-sky-400" />
                  {title}
                </div>
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground/70">
                  {desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}

function HistorySidebarEmptyState({
  isSearching,
}: Readonly<{
  isSearching: boolean
}>) {
  const t = useTranslations('History')

  if (isSearching) {
    return (
      <div className="mx-2 mt-3 rounded-[22px] border border-dashed border-border/70 bg-background/75 px-5 py-8 text-center text-sm text-muted-foreground shadow-sm">
        <Search className="mx-auto mb-3 size-7 text-muted-foreground/35" />
        <p className="font-medium text-foreground/70">{t('noMatchedConversation')}</p>
      </div>
    )
  }

  return (
    <div
      data-history-empty-archive="true"
      data-history-empty-inline="true"
      aria-live="polite"
      className="mx-2 mt-8 px-4 text-center"
    >
      <div className="relative mx-auto mb-4 grid size-14 place-items-center rounded-[22px] bg-sky-50/75 text-primary">
        <History className="size-6" />
        <span className="absolute -right-1 top-2 size-2 rounded-full bg-sky-300" />
        <span className="absolute -left-1.5 bottom-4 size-1.5 rounded-full bg-blue-200" />
      </div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-sky-500/75">
        {t('historyEmptyKicker')}
      </p>
      <h3 className="mt-2 text-[15px] font-semibold tracking-[-0.03em] text-foreground">
        {t('noConversationRecords')}
      </h3>
      <p className="mx-auto mt-2 max-w-[14rem] text-[12px] leading-5 text-muted-foreground/75">
        {t('historyEmptyDescription')}
      </p>

      <Button
        asChild
        size="sm"
        className="mt-5 h-9 rounded-full bg-info px-4 text-[12px] font-semibold text-primary-foreground shadow-[0_10px_20px_hsl(var(--info)/0.20)] hover:bg-info/90"
      >
        <Link href="/">
          <Plus className="size-3.5" />
          {t('startNewConversation')}
        </Link>
      </Button>
    </div>
  )
}

// 对话列表项
function ConversationItem({
  conversation,
  isSelected,
  onSelect,
  onDelete,
  showDeleteConfirm,
  onConfirmDelete,
  onCancelDelete,
}: Readonly<{
  conversation: Conversation
  isSelected: boolean
  onSelect: () => void
  onDelete: () => void
  showDeleteConfirm: boolean
  onConfirmDelete: () => void
  onCancelDelete: () => void
}>) {
  const locale = useLocale()
  const t = useTranslations('History')

  return (
    <div className="relative group px-0">
      <motion.button
        type="button"
        onClick={onSelect}
        whileHover={{ scale: 1.01, y: -0.5 }}
        whileTap={{ scale: 0.99 }}
        className={cn(
          'w-full flex flex-col gap-0.5 px-3 py-1.5 text-left transition-all duration-200 rounded-xl relative overflow-hidden border border-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
          isSelected 
            ? 'bg-primary/10 text-primary border-primary/10 shadow-[0_2px_12px_-3px_rgba(var(--primary),0.1)]' 
            : 'bg-transparent text-foreground/80 hover:bg-muted/60 hover:text-foreground'
        )}
      >
        {/* 选中时的左侧指示条 */}
        {isSelected && (
          <motion.div 
            layoutId="active-indicator"
            className="absolute left-0 top-3 bottom-3 w-1 bg-primary rounded-r-full shadow-[0_0_8px_rgba(var(--primary),0.3)]" 
          />
        )}

        <div className="flex items-start justify-between gap-3">
          <span className={cn(
            'flex-1 truncate text-[13.5px] font-normal leading-snug ',
            isSelected ? 'text-primary' : 'text-foreground/88'
          )}>
            {conversation.title || t('untitledConversation')}
          </span>
          <time
            suppressHydrationWarning
            dateTime={conversation.last_message_at || conversation.updated_at || conversation.created_at}
            className="text-[9px] font-medium uppercase  text-muted-foreground/30 pt-1.5 tabular-nums group-hover:text-muted-foreground/50 transition-colors shrink-0"
          >
            {formatRelativeTime(conversation.last_message_at || conversation.updated_at, locale, t('justNow'))}
          </time>
        </div>
        <div className="flex items-center gap-2 text-[11px] font-normal text-muted-foreground/40 tabular-nums">
          <span className="shrink-0">{t('messageCount', { count: conversation.message_count })}</span>
          <span className="text-muted-foreground/20">/</span>
          <p className="truncate flex-1 font-normal  text-muted-foreground/50 lowercase">
            {conversation.last_message || t('noMessage')}
          </p>
        </div>
      </motion.button>

      <div className={cn(
        "absolute right-3 top-1/2 -translate-y-1/2 transition-all duration-200 flex items-center",
        showDeleteConfirm ? "opacity-100" : "opacity-0 group-hover:opacity-100"
      )}>
        {showDeleteConfirm ? (
          <div className="flex items-center gap-1.5 animate-fade-in-up">
            <IconButton
              label={t('confirmDeleteConversation')}
              variant="ghost"
              className="size-8 text-destructive hover:bg-destructive/10 active:bg-destructive/20 rounded-full transition-all border border-transparent hover:border-destructive/10"
              onClick={(e) => { e.stopPropagation(); onConfirmDelete() }}
            >
              <Trash2 className="size-4" />
            </IconButton>
            <IconButton
              label={t('cancelDelete')}
              variant="ghost"
              className="size-8 text-muted-foreground/40 hover:text-foreground hover:bg-muted/80 active:bg-muted rounded-full transition-all"
              onClick={(e) => { e.stopPropagation(); onCancelDelete() }}
            >
              <X className="size-4" />
            </IconButton>
          </div>
        ) : (
          <div className="flex items-center gap-1">
            <IconButton
              label={t('deleteConversation')}
              variant="ghost"
              className="size-8 text-muted-foreground/30 hover:text-destructive hover:bg-destructive/10 active:bg-destructive/20 rounded-full transition-all"
              onClick={(e) => { e.stopPropagation(); onDelete() }}
            >
              <Trash2 className="size-4" />
            </IconButton>
          </div>
        )}
      </div>
    </div>
  )
}

function HistoryMessageEntry({
  message,
  locale,
}: Readonly<{
  message: Message
  locale: string
}>) {
  const isUser = message.role === 'user'
  const requestId = isUser ? '' : extractMessageRequestId(message)
  const showAnswerLineage = Boolean(requestId && hasAnswerLineageEvidence(message))

  return (
    <motion.div 
      initial={{ opacity: 0, y: 15 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-20px" }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "w-full py-4 transition-all duration-300",
        isUser ? "flex justify-end" : "flex justify-start"
      )}
    >
      <div className={cn(
        "w-full max-w-4xl",
        isUser ? "flex justify-end" : "flex justify-start"
      )}>
        <div className={cn('flex min-w-0 flex-col gap-1', isUser ? 'items-end' : 'items-start')}>
          <ChatMessageItem message={message} variant="minimal" />
          {showAnswerLineage ? <AnswerLineageAction requestId={requestId} /> : null}
        </div>
      </div>
    </motion.div>
  )
}

function extractMessageRequestId(message: Message): string {
  const metadata = message.message_metadata
  if (!metadata || typeof metadata !== 'object') return ''

  const direct = metadata.request_id
  if (typeof direct === 'string' && direct.trim()) return direct.trim()

  const metrics = metadata.metrics
  if (metrics && typeof metrics === 'object' && !Array.isArray(metrics)) {
    const metricRequestId = (metrics as Record<string, unknown>).request_id
    if (typeof metricRequestId === 'string' && metricRequestId.trim()) return metricRequestId.trim()
  }

  return ''
}

function hasEvidenceArray(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0
}

function hasClaimEvidence(value: unknown): boolean {
  if (!Array.isArray(value)) return false
  return value.some((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return false
    return hasEvidenceArray((item as Record<string, unknown>).evidence)
  })
}

function hasAnswerLineageEvidence(message: Message): boolean {
  if (hasEvidenceArray(message.citations)) return true

  const metadata = message.message_metadata
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return false

  if (hasEvidenceArray(metadata.retrieved_docs)) return true
  if (hasClaimEvidence(metadata.claim_evidence)) return true
  if (hasClaimEvidence(metadata.sentence_citations)) return true

  const docsReturned = metadata.docs_returned
  return typeof docsReturned === 'number' && Number.isFinite(docsReturned) && docsReturned > 0
}

function HistoryMessageRoleBadge({
  role,
}: Readonly<{
  role: Message['role']
}>) {
  const t = useTranslations('History')
  const isUser = role === 'user'

  return (
    <div
      className={cn(
        'inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-semibold shadow-sm',
        isUser
          ? 'border-primary/15 bg-primary/10 text-primary'
          : 'border-border/60 bg-background/90 text-foreground/80'
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', isUser ? 'bg-primary' : 'bg-sky-500')} />
      <span>{isUser ? t('speakerQuestion') : t('speakerAnswer')}</span>
    </div>
  )
}

function getConversationGroupTone(
  group: string,
  labels: Readonly<{
    earlier: string
    last30Days: string
    last7Days: string
    today: string
    yesterday: string
  }>
) {
  if (group === labels.today) {
    return {
      chipClass: 'border-[#B6D7A8]/90 bg-[#F2F8ED] text-[#5E7E4D] dark:border-[#5E7E4D]/30 dark:bg-[#5E7E4D]/10 dark:text-[#A8C895]',
      countClass: 'bg-[#DDECCF] text-[#4F6B41] dark:bg-[#5E7E4D]/20 dark:text-[#A8C895]',
      lineClass: 'bg-[#B6D7A8]/75 dark:bg-[#5E7E4D]/20',
    }
  }

  if (group === labels.yesterday) {
    return {
      chipClass: 'border-[#B0D2EF]/90 bg-[#EEF6FC] text-[#4F7090] dark:border-[#4F7090]/30 dark:bg-[#4F7090]/10 dark:text-[#9FBDE0]',
      countClass: 'bg-[#D9EAF8] text-[#476786] dark:bg-[#4F7090]/20 dark:text-[#9FBDE0]',
      lineClass: 'bg-[#B0D2EF]/75 dark:bg-[#4F7090]/20',
    }
  }

  if (group === labels.last7Days) {
    return {
      chipClass: 'border-[#FFBEBA]/90 bg-[#FFF1F0] text-[#A86762] dark:border-[#A86762]/30 dark:bg-[#A86762]/10 dark:text-[#E0A7A3]',
      countClass: 'bg-[#FFDCD8] text-[#955A56] dark:bg-[#A86762]/20 dark:text-[#E0A7A3]',
      lineClass: 'bg-[#FFBEBA]/75 dark:bg-[#A86762]/20',
    }
  }

  if (group === labels.last30Days) {
    return {
      chipClass: 'border-[#F4D8A6]/90 bg-[#FFF7E9] text-[#8A6A31] dark:border-[#8A6A31]/30 dark:bg-[#8A6A31]/10 dark:text-[#D4B581]',
      countClass: 'bg-[#FCE9C3] text-[#785B28] dark:bg-[#8A6A31]/20 dark:text-[#D4B581]',
      lineClass: 'bg-[#F4D8A6]/75 dark:bg-[#8A6A31]/20',
    }
  }

  return {
    chipClass: 'border-border/60 bg-muted/60 text-muted-foreground dark:bg-muted/10 dark:border-border/20',
    countClass: 'bg-muted text-muted-foreground dark:bg-muted/20',
    lineClass: 'bg-border dark:bg-border/20',
  }
}

function utcDayKey(dateLike: Date | string) {
  const date = typeof dateLike === 'string' ? new Date(dateLike) : dateLike
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, '0'),
    String(date.getUTCDate()).padStart(2, '0'),
  ].join('-')
}

function utcDayStartMs(dateLike: Date | string) {
  const date = typeof dateLike === 'string' ? new Date(dateLike) : dateLike
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())
}

// 辅助函数：按日期分组
function groupConversationsByDate(
  conversations: Conversation[],
  labels: Readonly<{
    earlier: string
    last30Days: string
    last7Days: string
    today: string
    yesterday: string
  }>
) {
  const groups: Record<string, Conversation[]> = {}
  const now = new Date()
  const today = utcDayStartMs(now)
  const lastWeek = new Date(today)
  lastWeek.setUTCDate(lastWeek.getUTCDate() - 7)
  const lastMonth = new Date(today)
  lastMonth.setUTCDate(lastMonth.getUTCDate() - 30)

  conversations.forEach((conv) => {
    const activityDate = conv.last_message_at || conv.created_at || conv.updated_at
    const convDate = utcDayStartMs(activityDate)

    let group: string
    if (convDate === today) {
      group = labels.today
    } else if (convDate >= lastWeek.getTime()) {
      group = labels.last7Days
    } else if (convDate >= lastMonth.getTime()) {
      group = labels.last30Days
    } else {
      group = labels.earlier
    }

    if (!groups[group]) {
      groups[group] = []
    }
    groups[group].push(conv)
  })

  return groups
}

function groupMessagesByDay(
  messages: Message[],
  locale: string,
  labels: Readonly<{
    today: string
    yesterday: string
  }>
) {
  const groups = new Map<string, { key: string; label: string; messages: Message[] }>()

  messages.forEach((message) => {
    const date = new Date(message.created_at)
    const key = utcDayKey(date)

    if (!groups.has(key)) {
      groups.set(key, {
        key,
        label: formatMessageGroupLabel(date, locale, labels),
        messages: [],
      })
    }
    groups.get(key)?.messages.push(message)
  })

  return Array.from(groups.values())
}

// 辅助函数：格式化相对时间
function formatRelativeTime(dateString: string, locale: string, justNowLabel: string) {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / (1000 * 60))
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  const relative = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })

  if (diffMins < 1) return justNowLabel
  if (diffMins < 60) return relative.format(-diffMins, 'minute')
  if (diffHours < 24) return relative.format(-diffHours, 'hour')
  if (diffDays < 7) return relative.format(-diffDays, 'day')

  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
  }).format(date)
}

function formatMessageGroupLabel(
  date: Date,
  locale: string,
  labels: Readonly<{
    today: string
    yesterday: string
  }>
) {
  const now = new Date()
  const today = utcDayKey(now)
  const yesterdayDate = new Date(utcDayStartMs(now))
  yesterdayDate.setUTCDate(yesterdayDate.getUTCDate() - 1)
  const yesterday = utcDayKey(yesterdayDate)
  const target = utcDayKey(date)

  if (target === today) return labels.today
  if (target === yesterday) return labels.yesterday

  return new Intl.DateTimeFormat(locale, {
    year: date.getUTCFullYear() === now.getUTCFullYear() ? undefined : 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(date)
}

function formatMessageTime(dateString: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(dateString))
}

// 辅助函数：格式化日期
function formatDate(dateString: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(dateString))
}

function buildConversationPreview(content: string | null | undefined, maxChars = 100) {
  const text = String(content || '').trim()
  if (!text) return ''
  return text.length > maxChars ? `${text.slice(0, maxChars)}...` : text
}
