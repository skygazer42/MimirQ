/**
 * 对话历史页面
 */
'use client'

import { useState, useEffect, useLayoutEffect, useRef, Suspense, useCallback, useDeferredValue, useMemo } from 'react'
import Image from 'next/image'
import { useLocale, useTranslations } from 'next-intl'
import { useSearchParams } from 'next/navigation'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
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
const RECENT_CONVERSATION_WINDOW_MS = 7 * 24 * 60 * 60 * 1000

type ConversationPagesCache = {
  pages?: Array<{
    items?: Conversation[]
    total?: number
    returned?: number
  }>
  pageParams?: unknown[]
}

export async function deleteConversationFromHistory(
  conversationId: string,
  queryClient: QueryClient
) {
  await chatApi.deleteConversation(conversationId)
  queryClient.setQueriesData<ConversationPagesCache>(
    { queryKey: queryKeys.chat.conversationPagesAll },
    (current: ConversationPagesCache | undefined) =>
      current
        ? {
            ...current,
            pages: (current.pages || []).map((page) => {
              const items = (page.items || []).filter(
                (conversation) => conversation.id !== conversationId
              )
              const removed = (page.items || []).length - items.length
              return {
                ...page,
                items,
                returned: Math.max(
                  0,
                  Number(page.returned ?? page.items?.length ?? 0) - removed
                ),
                total: Math.max(0, Number(page.total || 0) - removed),
              }
            }),
          }
        : current
  )
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.chat.conversationPagesAll }),
    queryClient.invalidateQueries({ queryKey: queryKeys.chat.conversationsAll }),
  ])
}

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
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(initialSelectedConversation)
  const [searchQuery, setSearchQuery] = useState('')
  const [historyView, setHistoryView] = useState<'all' | 'recent'>('all')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
  const [isTraceOpen, setIsTraceOpen] = useState(false)
  const [recentConversationCutoff, setRecentConversationCutoff] = useState<number | null>(null)

  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const conversationLoadMoreRef = useRef<HTMLDivElement>(null)
  const pendingPrependScrollRef = useRef<{ top: number; height: number } | null>(null)
  const shouldScrollToEndRef = useRef(false)
  const deferredSearchQuery = useDeferredValue(searchQuery)
  const conversationSearchTerm = deferredSearchQuery.trim()
  const conversationListParams = useMemo(
    () => ({
      limit: CONVERSATION_PAGE_SIZE,
      ...(conversationSearchTerm ? { q: conversationSearchTerm } : {}),
    }),
    [conversationSearchTerm]
  )
  const conversationsQuery = useInfiniteQuery({
    queryKey: queryKeys.chat.conversationPages(conversationListParams),
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const result = await chatApi.listConversations({
        skip: Number(pageParam) || 0,
        ...conversationListParams,
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
    initialData: initialConversationsLoaded && !conversationSearchTerm
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
  const selectedConversationId = selectedConversation?.id || conversationId || null
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
  const displayConversation = useMemo<Conversation | null>(() => {
    if (selectedConversation) return selectedConversation
    if (!selectedConversationId || messagesQuery.isError) return null
    const firstMessage = messages[0]
    const lastMessage = messages[messages.length - 1]
    const createdAt =
      firstMessage?.created_at
      || lastMessage?.created_at
      || new Date().toISOString()
    const updatedAt = lastMessage?.created_at || createdAt
    return {
      id: selectedConversationId,
      title: '',
      last_message: lastMessage?.content,
      last_message_at: lastMessage?.created_at,
      message_count: messages.length,
      created_at: createdAt,
      updated_at: updatedAt,
    }
  }, [messages, messagesQuery.isError, selectedConversation, selectedConversationId])
  const hasMoreMessages = messagesQuery.hasPreviousPage
  const isLoadingOlder = messagesQuery.isFetchingPreviousPage
  const isLoadingMessages = Boolean(selectedConversationId) && messagesQuery.isLoading

  const handleSelectConversation = useCallback(async (conversation: Conversation) => {
    if (selectedConversation?.id === conversation.id) return

    shouldScrollToEndRef.current = true
    setSelectedConversation(conversation)
    if (globalThis.window.matchMedia('(max-width: 767px)').matches) {
      setIsSidebarCollapsed(true)
    }

    // 更新 URL
    router.push(`/history?id=${conversation.id}`, { scroll: false })
  }, [router, selectedConversation?.id])

  useEffect(() => {
    if (conversationId && globalThis.window.matchMedia('(max-width: 767px)').matches) {
      setIsSidebarCollapsed(true)
    }
  }, [conversationId])

  useEffect(() => {
    if (!conversationsQuery.error) return
    reportClientError('Failed to load conversations', conversationsQuery.error)
    toast.error(formatApiError(conversationsQuery.error, t('loadConversationListFailed')))
  }, [conversationsQuery.error, t])

  useEffect(() => {
    if (historyView !== 'recent') return
    const timer = globalThis.window.setInterval(() => {
      setRecentConversationCutoff(Date.now() - RECENT_CONVERSATION_WINDOW_MS)
    }, 60_000)
    return () => globalThis.window.clearInterval(timer)
  }, [historyView])

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
    if (!conversationId) return
    const conv = conversations.find((c) => c.id === conversationId)
    if (conv) {
      if (selectedConversation?.id !== conv.id) {
        shouldScrollToEndRef.current = true
        setSelectedConversation(conv)
      }
      return
    }
    if (conversationSearchTerm) return
    if (selectedConversation) {
      shouldScrollToEndRef.current = true
      setSelectedConversation(null)
    }
  }, [conversationId, conversations, conversationSearchTerm, selectedConversation, selectedConversation?.id])

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
      await deleteConversationFromHistory(conversationId, queryClient)
      if (displayConversation?.id === conversationId) {
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
    if (displayConversation) {
      router.push(`/?conversation=${displayConversation.id}`)
    }
  }

  const handleEvaluateConversation = () => {
    if (displayConversation) {
      router.push(`/evaluations?conversation_id=${displayConversation.id}`, { scroll: false })
    }
  }

  // 最近视图仍是本地时间筛选；文本搜索由服务端覆盖完整历史。
  const filteredConversations = useMemo(() => {
    let base = conversations
    if (!conversationSearchTerm && historyView === 'recent' && recentConversationCutoff !== null) {
      base = base.filter((c) => {
        const activityDate = c.last_message_at || c.updated_at || c.created_at
        const ts = new Date(activityDate).getTime()
        return Number.isFinite(ts) && ts >= recentConversationCutoff
      })
    }
    return base
  }, [conversationSearchTerm, conversations, historyView, recentConversationCutoff])

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
  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding mainClassName="overflow-hidden">
      <PageScaffold
        title={t('pageTitle')}
        icon={History}
        showHeader={false}
        size="full"
        bodyClassName="p-0 overflow-hidden"
        bodyGutter="none"
        bodyContainerClassName="h-full max-w-none"
      >
        <div className="h-full overflow-hidden">
          <section data-history-shell="ruled" className="relative flex h-full min-h-0 overflow-hidden bg-background">

            {/* 侧边栏 - 对话列表 */}
            <motion.aside 
              data-history-sidebar="true"
              initial={false}
              animate={{ 
                opacity: isSidebarCollapsed ? 0 : 1,
                borderRightWidth: isSidebarCollapsed ? 0 : 1
              }}
              transition={{ type: 'spring', stiffness: 300, damping: 30, mass: 0.8 }}
              className={cn(
                "relative z-10 flex shrink-0 flex-col overflow-hidden border-r border-foreground/15 bg-background transition-[width] duration-200",
                isSidebarCollapsed ? "w-0" : "w-full md:w-[19.5rem] xl:w-[20.75rem]"
              )}
            >
              {/* 头部 - 已扁平化 */}
              <div className="sticky top-0 z-20 min-w-0 space-y-1 border-b border-foreground/15 bg-background px-2 pb-2 pt-2 md:min-w-[19.5rem]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-md border border-foreground/10 bg-background text-foreground">
                      <PageTitleIcon name="qa-history" className="size-7" />
                    </div>
                    <h2 className="text-sm font-medium text-foreground  uppercase">历史记录</h2>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8 rounded-md border border-transparent text-muted-foreground hover:bg-muted hover:text-foreground"
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
                    maxLength={500}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('searchPlaceholder')}
                    className="h-9 w-full rounded-md border border-foreground/10 bg-background pl-8 pr-3 text-xs font-medium outline-none transition-all focus:border-primary/30 focus:bg-background focus:ring-1 focus:ring-primary/30"
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
                      onClick={() => {
                        setHistoryView(value)
                        setRecentConversationCutoff(
                          value === 'recent' ? Date.now() - RECENT_CONVERSATION_WINDOW_MS : null
                        )
                      }}
                      className={cn(
                        'rounded-md border border-transparent px-3 py-1 text-[11px] font-medium transition-colors',
                        historyView === value
                          ? 'border-foreground/10 bg-background text-foreground'
                          : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
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
                    className="h-8 rounded-md px-3 text-[11px] font-medium text-muted-foreground hover:bg-muted/40 hover:text-foreground"
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
                "relative min-w-0 flex-1 flex-col transition-colors duration-500",
                isSidebarCollapsed ? "flex bg-background/40" : "hidden bg-background/65 md:flex"
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
                      className="size-10 rounded-md border border-foreground/10 bg-background text-muted-foreground transition-all hover:bg-muted hover:text-foreground active:scale-95"
                      onClick={() => setIsSidebarCollapsed(false)}
                      aria-label="展开侧边栏"
                      title="展开侧边栏"
                    >
                      <PanelLeftOpen className="size-5" />
                    </Button>
                  </motion.div>
                )}
              </AnimatePresence>

              {displayConversation ? (
                <>
                  {/* 对话头部 - 极简重构版 */}
                  <div data-history-detail-header="true" className="sticky top-0 z-20 border-b border-foreground/15 bg-background">
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
                              <div className="flex size-10 shrink-0 items-center justify-center rounded-md border border-foreground/10 bg-background text-foreground">
                                <MessageSquare className="size-5" />
                              </div>
                              <div className="mx-1 hidden h-6 w-px bg-foreground/10 md:block" />
                            </>
                          )}
                          
                          {/* 如果收起，留出悬浮按钮的位移空间 */}
                          <div className={cn(
                            "min-w-0 flex flex-col justify-center transition-all duration-500",
                            isSidebarCollapsed ? "ml-12" : "ml-0"
                          )}>
                            <h2 className="truncate text-base font-medium text-foreground/92  leading-tight md:text-lg">
                              {displayConversation.title || t("untitledConversation")}
                            </h2>
                            <div className="flex items-center gap-1 mt-0.5 tabular-nums">
                              <span className="inline-flex items-center rounded-md border border-foreground/10 bg-background/70 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                                {t("messageCount", { count: displayConversation.message_count })}
                              </span>
                              <span className="text-muted-foreground/20 text-[11px] leading-none px-0.5">•</span>
                              <span suppressHydrationWarning className="inline-flex items-center gap-1 rounded-md border border-foreground/10 bg-background/70 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                                {formatDate(displayConversation.created_at, locale)}
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
                            className="h-8 gap-1.5 rounded-md px-3.5 text-[11px] font-medium"
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
                    className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-background px-4 pb-6 pt-0 md:px-6 md:pb-8 xl:px-8"
                  >
                    {(() => {
    if (isLoadingMessages) {
        return (<div className="flex h-full items-center justify-center">
                          <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                        </div>);
    }
    else if (messages.length === 0) {
            return (<div className="flex h-full items-center justify-center">
                          <div className="rounded-lg border border-dashed border-foreground/10 bg-background px-8 py-12 text-center text-muted-foreground">
                            <MessageSquare className="mx-auto mb-4 h-12 w-12 opacity-10"/>
                            <p>{t('noMessageRecords')}</p>
                          </div>
                        </div>);
        }
                        else {
            return (<AnimatePresence mode="wait">
                        <motion.div 
                          layout
                          key={displayConversation.id}
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
                          <ConversationOpsPanel conversationId={displayConversation.id} />
                          {hasMoreMessages ? (<div className="flex justify-center mb-4">
                              <Button variant="ghost" size="sm" onClick={loadOlderMessages} disabled={isLoadingOlder} className="rounded-md text-[11px] font-bold uppercase text-muted-foreground/60 hover:bg-muted/40 hover:text-foreground">
                                {isLoadingOlder ? t('loading') : t('loadOlderMessages')}
                              </Button>
                            </div>) : null}
                          {groupedMessages.map((group) => (<div key={group.key} className="space-y-6">
                              <div className="flex items-center gap-6 py-1">
                                <div className="h-px flex-1 bg-foreground/10" />
                                <div suppressHydrationWarning className="whitespace-nowrap text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground/60">
                                  {group.label}
                                </div>
                                <div className="h-px flex-1 bg-foreground/10" />
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
                <HistoryMainEmptyState hasConversations={conversations.length > 0} />
              )}
            </motion.div>
          </section>
        </div>
        <RagTraceDialog
          open={isTraceOpen}
          onOpenChange={setIsTraceOpen}
          conversationId={displayConversation?.id || null}
          title={displayConversation?.title || null}
        />
      </PageScaffold>
    </AppFrame>
  )
}

function HistoryMainEmptyState({
  hasConversations,
}: Readonly<{
  hasConversations: boolean
}>) {
  const t = useTranslations('History')
  const title = hasConversations ? t('noConversationSelected') : t('startFirstConversation')
  const description = hasConversations
    ? t('noConversationSelectedDescription').replace('\n', ' ')
    : t('startFirstConversationDescription')

  return (
    <div className="flex-1 bg-muted/[0.1] p-2 md:p-3">
      <section
        data-history-main-empty="true"
        className="relative flex min-h-full items-center justify-center rounded-lg border border-foreground/15 bg-background px-6 py-10 text-center"
      >
        <div className="relative mx-auto flex max-w-md -translate-y-3 flex-col items-center">
          <Image
            src="/brand/mimirq-history-archive.png"
            alt=""
            aria-hidden="true"
            width={96}
            height={96}
            loading="eager"
            className="mb-1.5 size-24 object-contain"
          />
          <p className="text-[10px] font-semibold tracking-[0.2em] text-info/72">
            {t('historyEmptyKicker')}
          </p>
          <h2 className="mt-2.5 text-lg font-semibold tracking-[-0.035em] text-foreground">
            {title}
          </h2>
          <p className="mt-2 max-w-sm text-[13px] leading-6 text-muted-foreground/75">
            {description}
          </p>

          <div className="mt-5 flex items-center justify-center">
            <Button asChild className="h-9 rounded-md bg-foreground px-4 text-[12px] font-semibold text-background hover:bg-foreground/92">
              <Link href="/">
                <Plus className="size-3.5" />
                {t('startNewConversation')}
              </Link>
            </Button>
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
      <div className="mx-2 mt-3 rounded-lg border border-dashed border-foreground/10 bg-background px-5 py-8 text-center text-sm text-muted-foreground">
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
      className="mx-2 mt-5 px-4 text-center"
    >
      <Image
        src="/brand/mimirq-history-archive.png"
        alt=""
        aria-hidden="true"
        width={64}
        height={64}
        loading="eager"
        className="mx-auto mb-1 size-16 object-contain"
      />
      <h3 className="text-sm font-semibold tracking-[-0.025em] text-foreground">
        {t('noConversationRecords')}
      </h3>
      <p className="mx-auto mt-1.5 max-w-[13rem] text-[11px] leading-[1.125rem] text-muted-foreground/70">
        {t('historyEmptyDescription')}
      </p>
    </div>
  )
}

// 对话列表项
export function ConversationItem({
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
          'relative flex w-full flex-col gap-0.5 overflow-hidden rounded-md border border-transparent px-3 py-1.5 text-left transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
          isSelected 
            ? 'border-primary/20 bg-primary/[0.08] text-foreground'
            : 'bg-transparent text-foreground/80 hover:bg-muted/40 hover:text-foreground'
        )}
      >
        {/* 选中时的左侧指示条 */}
        {isSelected && (
          <motion.div 
            layoutId="active-indicator"
            className="absolute bottom-3 left-0 top-3 w-px bg-primary/50"
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
              className="size-8 rounded-md border border-transparent text-destructive transition-all hover:border-destructive/10 hover:bg-destructive/10 active:bg-destructive/20"
              onClick={(e) => { e.stopPropagation(); onConfirmDelete() }}
            >
              <Trash2 className="size-4" />
            </IconButton>
            <IconButton
              label={t('cancelDelete')}
              variant="ghost"
              className="size-8 rounded-md text-muted-foreground/40 transition-all hover:bg-muted hover:text-foreground active:bg-muted"
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
              className="size-8 rounded-md text-muted-foreground/30 transition-all hover:bg-destructive/10 hover:text-destructive active:bg-destructive/20"
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
        'inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-[11px] font-semibold',
        isUser
          ? 'border-primary/15 bg-primary/10 text-primary'
          : 'border-foreground/10 bg-background text-foreground/80'
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-sm', isUser ? 'bg-primary' : 'bg-info')} />
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
      chipClass: 'border-foreground/10 bg-background text-foreground/80',
      countClass: 'border border-foreground/10 bg-background text-muted-foreground',
      lineClass: 'bg-foreground/10',
    }
  }

  if (group === labels.yesterday) {
    return {
      chipClass: 'border-foreground/10 bg-background text-foreground/80',
      countClass: 'border border-foreground/10 bg-background text-muted-foreground',
      lineClass: 'bg-foreground/10',
    }
  }

  if (group === labels.last7Days) {
    return {
      chipClass: 'border-foreground/10 bg-background text-foreground/80',
      countClass: 'border border-foreground/10 bg-background text-muted-foreground',
      lineClass: 'bg-foreground/10',
    }
  }

  if (group === labels.last30Days) {
    return {
      chipClass: 'border-foreground/10 bg-background text-foreground/80',
      countClass: 'border border-foreground/10 bg-background text-muted-foreground',
      lineClass: 'bg-foreground/10',
    }
  }

  return {
    chipClass: 'border-foreground/10 bg-background text-muted-foreground',
    countClass: 'border border-foreground/10 bg-background text-muted-foreground',
    lineClass: 'bg-foreground/10',
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
