/**
 * 对话历史页面
 */
'use client'

import { useState, useEffect, useLayoutEffect, useRef, Suspense, useCallback, useDeferredValue, useMemo } from 'react'
import { ConversationHistory } from '@/components/icons'
import { useLocale, useTranslations } from 'next-intl'
import { useSearchParams } from 'next/navigation'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import {
  Trash2,
  ArrowUpRight,
  Download,
  MessageSquare,
  MoreHorizontal,
  Loader2,
  BarChart3,
  History,
  X,
  Plus,
  Route,
  Search,
  ArrowLeft,
  PanelLeftClose,
  PanelLeftOpen,
} from '@/components/icons'
import { AppFrame } from '@/components/app-frame'
import { ChatMessageItem } from '@/components/chat/message-item'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { ConversationOpsPanel } from '@/components/history/conversation-ops-panel'
import { AnswerLineageAction } from '@/components/history/answer-lineage-action'
import { RagTraceDialog } from '@/components/rag-trace/rag-trace-dialog'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { PageLoading } from '@/components/ui/page-loading'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Link, useRouter } from '@/i18n/navigation'
import { chatApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { toast } from 'sonner'
import type { Conversation, Message } from '@/types'
import styles from './history.module.css'

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
  const reduceMotion = useReducedMotion()

  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(initialSelectedConversation)
  const [searchQuery, setSearchQuery] = useState('')
  const [historyView, setHistoryView] = useState<'all' | 'recent'>('all')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
  const [isTraceOpen, setIsTraceOpen] = useState(false)
  const [isOpsOpen, setIsOpsOpen] = useState(false)
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
    if (globalThis.window.matchMedia('(max-width: 767px)').matches) {
      setIsSidebarCollapsed(true)
    }
    if (selectedConversation?.id === conversation.id) return

    shouldScrollToEndRef.current = true
    setSelectedConversation(conversation)

    // 更新 URL
    router.push(`/history?id=${conversation.id}`, { scroll: false })
  }, [router, selectedConversation?.id])

  useEffect(() => {
    const media = globalThis.window.matchMedia('(max-width: 767px)')
    const showSelectedConversation = () => {
      if (conversationId && media.matches) setIsSidebarCollapsed(true)
    }
    showSelectedConversation()
    media.addEventListener?.('change', showSelectedConversation)
    return () => media.removeEventListener?.('change', showSelectedConversation)
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
    groupLabels.yesterday,
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
          <section data-history-shell="ruled" data-history-design="fog-ink" className={styles.shell}>
            <header className={styles.pageHeader}>
              <div className={styles.pageHeading}>
                <span><History className="size-[21px]" aria-hidden="true" /></span>
                <h1>{t('pageTitle')}</h1>
              </div>
              {isSidebarCollapsed && (
                <IconButton
                  label={t('expandHistory')}
                  variant="ghost"
                  className="size-11 text-muted-foreground md:size-9"
                  onClick={() => setIsSidebarCollapsed(false)}
                  aria-controls="history-conversations"
                  aria-expanded={false}
                >
                  <ArrowLeft className="size-5 md:hidden" />
                  <PanelLeftOpen className="hidden size-[18px] md:block" />
                </IconButton>
              )}
            </header>
            <div className={styles.workspace}>

            {/* 侧边栏 - 对话列表 */}
            <motion.aside 
              data-history-sidebar="true"
              id="history-conversations"
              inert={isSidebarCollapsed}
              initial={false}
              animate={{ 
                opacity: isSidebarCollapsed ? 0 : 1,
              }}
              transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 300, damping: 30, mass: 0.8 }}
              className={cn(
                styles.queue,
                "relative z-10 flex shrink-0 flex-col overflow-hidden border-border transition-[width] duration-200 motion-reduce:transition-none",
                isSidebarCollapsed ? "w-0" : "w-full md:w-[284px] md:border-r"
              )}
            >
              <div className={styles.queueTools}>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    maxLength={500}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('searchPlaceholder')}
                    aria-label={t('searchPlaceholder')}
                    className={cn(styles.searchInput, 'pl-9 pr-10 placeholder:text-muted-foreground')}
                  />
                  {searchQuery && (
                    <IconButton
                      label={t('clearSearch')}
                      variant="ghost"
                      className="absolute right-1 top-1/2 size-9 -translate-y-1/2 text-muted-foreground sm:size-8"
                      onClick={() => setSearchQuery('')}
                    >
                      <X className="size-4" />
                    </IconButton>
                  )}
                </div>

                <div role="group" aria-label={t('filterConversations')} className={styles.filters}>
                  {([
                    ['all', t('allConversations')],
                    ['recent', t('recentConversations')],
                  ] as const).map(([value, label]) => (
                    <Button
                      key={value}
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-pressed={historyView === value}
                      onClick={() => {
                        setHistoryView(value)
                        setRecentConversationCutoff(
                          value === 'recent' ? Date.now() - RECENT_CONVERSATION_WINDOW_MS : null
                        )
                      }}
                      className={styles.filter}
                    >
                      {label}
                    </Button>
                  ))}
                  <IconButton
                    label={t('collapseHistory')}
                    variant="ghost"
                    className={cn(styles.queueToggle, 'hidden size-8 text-muted-foreground md:inline-flex')}
                    onClick={() => setIsSidebarCollapsed(true)}
                    aria-controls="history-conversations"
                    aria-expanded={!isSidebarCollapsed}
                  >
                    <PanelLeftClose className="size-[15px]" />
                  </IconButton>
                </div>
              </div>

              {/* 对话列表 */}
              <div
                data-history-sidebar-scroll
                className={cn(styles.queueScroll, 'no-scrollbar')}
              >
                {(() => {
    if (isLoadingList) {
        return (<div role="status" aria-label={t('loading')} className="flex items-center justify-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                    </div>);
    }
    else if (conversationsQuery.isError) {
        return <div role="alert" className={styles.status}><p>{t('loadConversationListFailed')}</p><Button variant="ghost" size="sm" className="mt-3" onClick={() => void conversationsQuery.refetch()}>重试</Button></div>;
    }
    else if (filteredConversations.length === 0) {
            return <HistorySidebarEmptyState isSearching={Boolean(searchQuery.trim())} isRecent={historyView === 'recent'} />;
        }
        else {
            return (<>
              {groupOrder.map((group) => {
                const convs = groupedConversations[group];
                if (!convs || convs.length === 0)
                    return null;
                return (<div key={group} className={styles.dateGroup}>
                          <div className={styles.groupHeading}>
                            <span suppressHydrationWarning>{group}</span>
                          </div>
                          <div className="space-y-1">
                            {convs.map((conversation) => (<ConversationItem key={conversation.id} conversation={conversation} isSelected={selectedConversationId === conversation.id} onSelect={() => handleSelectConversation(conversation)} onDelete={() => setShowDeleteConfirm(conversation.id)} showDeleteConfirm={showDeleteConfirm === conversation.id} onConfirmDelete={() => handleDeleteConversation(conversation.id)} onCancelDelete={() => setShowDeleteConfirm(null)}/>))}
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
                    className="text-xs text-muted-foreground"
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
                  <span className="text-[11px] text-muted-foreground">已显示全部历史</span>
                )}
              </div>
            </>);
        }
        })()}
        </div>
        </motion.aside>
            {/* 主区域 - 对话详情 */}
            <motion.div 
              layout={!reduceMotion}
              className={cn(
                styles.reading,
                isSidebarCollapsed ? "flex" : "hidden md:flex"
              )}
            >
              {displayConversation ? (
                <>
                  <div data-history-detail-header="true" className={styles.detailHeader}>
                    <motion.div 
                      layout={!reduceMotion}
                      className={styles.detailHeaderInner}
                    >
                      <div className="contents">
                        <div className={styles.detailHeading}>
                          <div className="min-w-0">
                            <h2
                              title={displayConversation.title || t("untitledConversation")}
                              className={styles.detailTitle}
                            >
                              {displayConversation.title || t("untitledConversation")}
                            </h2>
                            <div className={cn(styles.detailMeta, 'tabular-nums')}>
                              <span>
                                {t("messageCount", { count: displayConversation.message_count })}
                              </span>
                              <span suppressHydrationWarning>
                                {formatDate(displayConversation.created_at, locale)}
                              </span>
                            </div>
                          </div>
                        </div>
                        <div className={styles.detailActions}>
                          <Button
                            variant="default"
                            size="sm"
                            onClick={handleContinueChat}
                            aria-label="继续当前对话"
                            className={styles.continueButton}
                          >
                            继续对话
                            <ArrowUpRight className="size-4" />
                          </Button>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <IconButton label="更多对话操作" variant="ghost" className="size-11 text-muted-foreground md:size-9">
                                <MoreHorizontal className="size-[18px]" />
                              </IconButton>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className={styles.menu}>
                              <DropdownMenuItem onSelect={handleEvaluateConversation} aria-label="进行对话分析评测"><BarChart3 className="size-4" />分析评测</DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => setIsTraceOpen(true)} aria-label="查看数据追踪"><Route className="size-4" />数据追踪</DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem onSelect={() => setIsOpsOpen(true)}><Download className="size-4" />导出与检查点</DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </div>
                    </motion.div>
                  </div>

                  {/* 消息列表 */}
                  <div
                    ref={messagesContainerRef}
                    data-history-messages-scroll
                    className={cn(styles.messagesViewport, 'no-scrollbar')}
                  >
                    {(() => {
    if (isLoadingMessages) {
        return (<div role="status" aria-label={t('loading')} className="flex h-full items-center justify-center">
                          <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                        </div>);
    }
    else if (messagesQuery.isError) {
            return <div role="alert" className={styles.readingStatus}><p>{t('loadConversationMessagesFailed')}</p><Button variant="outline" onClick={() => void messagesQuery.refetch()}>重试</Button></div>;
        }
    else if (messages.length === 0) {
            return (<div className="flex h-full items-center justify-center">
                          <div className="px-6 py-10 text-center text-sm text-muted-foreground">
                            <ConversationHistory className="mx-auto mb-4 size-10" />
                            <p>{t('noMessageRecords')}</p>
                          </div>
                        </div>);
        }
                        else {
            return (<AnimatePresence mode="wait">
                        <motion.div 
                          layout={!reduceMotion}
                          key={displayConversation.id}
                          initial={reduceMotion ? false : { opacity: 0 }}
                          animate={{ opacity: 1 }}
                          transition={{ duration: reduceMotion ? 0 : 0.16 }}
                          className={styles.messages}
                        >
                          {hasMoreMessages ? (<div className="flex justify-center mb-4">
                              <Button variant="ghost" size="sm" onClick={loadOlderMessages} disabled={isLoadingOlder} className="text-xs text-muted-foreground">
                                {isLoadingOlder ? t('loading') : t('loadOlderMessages')}
                              </Button>
                            </div>) : null}
                          {groupedMessages.map((group) => (<div key={group.key} className={styles.messageGroup}>
                              {groupedMessages.length > 1 && <div className={styles.messageDate}>
                                <div suppressHydrationWarning>
                                  {group.label}
                                </div>
                              </div>}
                              <div>
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
            </div>
          </section>
        </div>
        <Dialog open={isOpsOpen} onOpenChange={setIsOpsOpen}>
          <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
            <DialogHeader>
              <DialogTitle>对话操作</DialogTitle>
              <DialogDescription>{displayConversation?.title || t('untitledConversation')}</DialogDescription>
            </DialogHeader>
            <ConversationOpsPanel conversationId={displayConversation?.id} initiallyExpanded />
          </DialogContent>
        </Dialog>
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
    <section
      data-history-main-empty="true"
      className="flex min-h-0 flex-1 items-center justify-center px-6 py-12 text-center"
    >
        <div className="mx-auto flex max-w-sm -translate-y-6 flex-col items-center">
          <ConversationHistory className="mb-5 size-10 text-muted-foreground" />
          <h2 className="text-xl font-medium leading-7 text-foreground">
            {title}
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {description}
          </p>

          <div className="mt-6">
            <Button asChild>
              <Link href="/">
                <Plus className="size-4" />
                {t('startNewConversation')}
              </Link>
            </Button>
          </div>
        </div>
    </section>
  )
}

function HistorySidebarEmptyState({
  isSearching,
  isRecent,
}: Readonly<{
  isSearching: boolean
  isRecent: boolean
}>) {
  const t = useTranslations('History')

  if (isSearching) {
    return (
      <div aria-live="polite" className="px-3 py-6 text-sm leading-6 text-muted-foreground">
        {t('noMatchedConversation')}
      </div>
    )
  }

  return (
    <div
      data-history-empty-archive="true"
      data-history-empty-inline="true"
      aria-live="polite"
      className={cn('px-3 py-6', !isRecent && 'md:hidden')}
    >
      <p className="text-sm leading-6 text-muted-foreground">
        {t(isRecent ? 'noRecentConversations' : 'noConversationRecords')}
      </p>
      <div className="mt-2 md:hidden">
        <p className="text-sm leading-6 text-muted-foreground">{t('historyEmptyDescription')}</p>
        <Button asChild className="mt-5 h-11">
          <Link href="/">
            <Plus className="size-4" />
            {t('startNewConversation')}
          </Link>
        </Button>
      </div>
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
    <div className="group relative">
      <motion.button
        type="button"
        onClick={onSelect}
        aria-pressed={isSelected}
        className={cn(styles.conversationButton, 'text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset', showDeleteConfirm && 'pr-24')}
      >
          <span title={conversation.title || t('untitledConversation')} className={styles.conversationTitle}>
            {conversation.title || t('untitledConversation')}
          </span>
          {isSelected && <p className={styles.conversationPreview}>
            {conversation.last_message || t('noMessage')}
          </p>}
        <div className={styles.conversationMeta}>
          <time
            suppressHydrationWarning
            dateTime={conversation.last_message_at || conversation.updated_at || conversation.created_at}
            className="shrink-0"
          >
            {formatRelativeTime(conversation.last_message_at || conversation.updated_at, locale, t('justNow'))}
          </time>
          <span className={styles.conversationCount}><MessageSquare className="size-3" />{t('messageCount', { count: conversation.message_count })}</span>
        </div>
      </motion.button>

      <div className={cn(
        styles.rowActions,
        'transition-opacity motion-reduce:transition-none',
        showDeleteConfirm ? "opacity-100" : "opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
      )}>
        {showDeleteConfirm ? (
          <div className="flex items-center gap-1">
            <IconButton
              label={t('confirmDeleteConversation')}
              variant="ghost"
              className="size-11 text-destructive hover:bg-destructive/10 hover:text-destructive md:size-8"
              onClick={(e) => { e.stopPropagation(); onConfirmDelete() }}
            >
              <Trash2 className="size-4" />
            </IconButton>
            <IconButton
              label={t('cancelDelete')}
              variant="ghost"
              className="size-11 text-muted-foreground md:size-8"
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
              className="size-11 text-muted-foreground hover:bg-destructive/10 hover:text-destructive md:size-8"
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
  const reduceMotion = useReducedMotion()
  const requestId = isUser ? '' : extractMessageRequestId(message)
  const showAnswerLineage = Boolean(requestId && hasAnswerLineageEvidence(message))

  return (
    <motion.div 
      initial={false}
      animate={{ opacity: 1 }}
      transition={{ duration: reduceMotion ? 0 : 0.16 }}
      data-history-message-role={message.role}
      className={cn(styles.messageEntry, 'mx-auto w-full min-w-0')}
    >
      <ChatMessageItem message={message} variant="history" />
      {showAnswerLineage ? <div className="mt-1"><AnswerLineageAction requestId={requestId} /></div> : null}
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
    } else if (convDate === today - 24 * 60 * 60 * 1000) {
      group = labels.yesterday
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
