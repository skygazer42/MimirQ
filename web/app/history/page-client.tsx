/**
 * 对话历史页面
 */
'use client'

import {
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
  Suspense,
  useCallback,
  useDeferredValue,
  useMemo,
  useTransition,
} from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useSearchParams } from 'next/navigation'
import { skipToken, useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import {
  ConversationHistory,
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
  Pencil,
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
import { Label } from '@/components/ui/label'
import { PageLoading } from '@/components/ui/page-loading'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { SplitEmptyStudio } from '@/components/ui/split-empty-studio'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Link, useRouter } from '@/i18n/navigation'
import { chatApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import { normalizeResourceId } from '@/lib/resource-id'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { reportClientError } from '@/lib/client-logging'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { toast } from 'sonner'
import type { Conversation, Message } from '@/types/chat'
import styles from './history.module.css'

type ConversationGroupLabels = {
  earlier: string
  last30Days: string
  last7Days: string
  today: string
  yesterday: string
}

const EMPTY_CONVERSATIONS: Conversation[] = []
const EMPTY_MESSAGES: Message[] = []
const CONVERSATION_PAGE_SIZE = 100
const RECENT_CONVERSATION_WINDOW_MS = 7 * 24 * 60 * 60 * 1000

export default function HistoryPageClient() {
  return (
    <Suspense fallback={<HistoryPageLoading />}>
      <HistoryPageContent />
    </Suspense>
  )
}

const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40

type MessagePageParams = { limit: number; before?: string }
const FIRST_MESSAGE_PAGE: MessagePageParams = { limit: DEFAULT_VISIBLE_MESSAGES }
type ConversationOperation = {
  owner: { active: boolean }
  authRevision: number
  authScope: string
}

function HistoryPageLoading() {
  const t = useTranslations('History')

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding>
      <PageLoading message={t('loadingPage')} srMessage={t('loadingPageSr')} />
    </AppFrame>
  )
}

function HistoryPageContent() {
  const router = useRouter()
  const [isNavigating, startNavigation] = useTransition()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const locale = useLocale()
  const t = useTranslations('History')
  const conversationId = searchParams.get('id')
  const requestedConversationId =
    conversationId === null || conversationId === '' ? null : normalizeResourceId(conversationId)
  const reduceMotion = useReducedMotion()

  const [showConversationDetail, setShowConversationDetail] = useState(requestedConversationId !== null)
  const [selectedConversationSnapshot, setSelectedConversationSnapshot] = useState<Conversation | null>(null)
  const selectedConversationId = requestedConversationId ?? selectedConversationSnapshot?.id ?? null
  const [searchQuery, setSearchQuery] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
  const [isTraceOpen, setIsTraceOpen] = useState(false)
  const [isOpsOpen, setIsOpsOpen] = useState(false)
  const [recentConversationCutoff, setRecentConversationCutoff] = useState<number | null>(null)
  const historyView = recentConversationCutoff === null ? 'all' : 'recent'
  const [deletingConversationIds, setDeletingConversationIds] = useState<ReadonlySet<string>>(new Set())
  const [removedConversationIds, setRemovedConversationIds] = useState<ReadonlySet<string>>(new Set())
  const [renameConversation, setRenameConversation] = useState<Pick<Conversation, 'id' | 'title'> | null>(null)
  const [renameTitle, setRenameTitle] = useState('')
  const [renameError, setRenameError] = useState<string | null>(null)
  const [isRenaming, setIsRenaming] = useState(false)

  const historyOwnerRef = useRef({ active: true })
  const deletionsRef = useRef(new Map<string, ConversationOperation>())
  const renameOperationRef = useRef<ConversationOperation | null>(null)
  const selectedConversationIdRef = useRef(selectedConversationId)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const conversationLoadMoreRef = useRef<HTMLDivElement>(null)
  const pendingPrependScrollRef = useRef<{ top: number; height: number } | null>(null)
  const shouldScrollToEndRef = useRef(false)
  const deferredSearchQuery = useDeferredValue(searchQuery)
  const conversationSearchTerm = deferredSearchQuery.trim()
  const searchTerm = searchQuery.trim()
  const isSearchPending = searchTerm !== conversationSearchTerm
  const conversationListParams = useMemo(
    () => ({
      limit: CONVERSATION_PAGE_SIZE,
      ...(conversationSearchTerm ? { q: conversationSearchTerm } : {}),
    }),
    [conversationSearchTerm],
  )
  const conversationsQuery = useInfiniteQuery({
    queryKey: queryKeys.chat.conversationPages(conversationListParams),
    initialPageParam: 0,
    staleTime: 0,
    queryFn: ({ pageParam, signal }) =>
      chatApi.listConversations({ skip: pageParam, ...conversationListParams }, { signal }),
    getNextPageParam: (lastPage) => lastPage.next_skip,
  })
  const [conversationListSnapshot, setConversationListSnapshot] = useState<{
    response: NonNullable<typeof conversationsQuery.data>
    searchTerm: string
  } | null>(null)
  useEffect(() => {
    if (conversationsQuery.isSuccess) {
      setConversationListSnapshot({ response: conversationsQuery.data, searchTerm: conversationSearchTerm })
    }
  }, [conversationsQuery.data, conversationsQuery.isSuccess, conversationSearchTerm])
  const displayedConversationData = conversationsQuery.data ?? conversationListSnapshot?.response
  const displayedSearchTerm =
    conversationsQuery.data === undefined && conversationListSnapshot !== null
      ? conversationListSnapshot.searchTerm
      : conversationSearchTerm
  const isSearchingHistory = searchTerm !== '' || displayedSearchTerm !== ''
  const showingPreviousSearch =
    displayedConversationData !== undefined && displayedSearchTerm !== conversationSearchTerm
  const conversations = useMemo(() => {
    if (displayedConversationData === undefined) return EMPTY_CONVERSATIONS

    const seen = new Set<string>()
    const merged: Conversation[] = []
    for (const page of displayedConversationData.pages) {
      for (const conversation of page.items) {
        if (seen.has(conversation.id) || removedConversationIds.has(conversation.id)) continue
        seen.add(conversation.id)
        merged.push(conversation)
      }
    }
    return merged
  }, [displayedConversationData, removedConversationIds])
  const isReadingConversations = conversationsQuery.fetchStatus !== 'idle'
  const isLoadingList = conversationsQuery.isLoading && displayedConversationData === undefined
  const hasMoreConversations = !showingPreviousSearch && conversationsQuery.hasNextPage
  const isLoadingMoreConversations = conversationsQuery.isFetchingNextPage
  const showEmptyHistory =
    !isSearchPending &&
    historyView === 'all' &&
    conversationSearchTerm.length === 0 &&
    conversationsQuery.isSuccess &&
    !isReadingConversations &&
    conversationsQuery.data.pages[0].total === 0
  const matchingConversation = conversations.find((conversation) => conversation.id === selectedConversationId)
  const selectedConversation =
    matchingConversation ??
    (selectedConversationSnapshot?.id === selectedConversationId ? selectedConversationSnapshot : null)
  const messagesQuery = useInfiniteQuery({
    queryKey: queryKeys.chat.messagePages(selectedConversationId),
    initialPageParam: FIRST_MESSAGE_PAGE,
    staleTime: 0,
    queryFn:
      selectedConversationId === null
        ? skipToken
        : ({ pageParam, signal }) => chatApi.getMessages(selectedConversationId, pageParam, { signal }),
    getNextPageParam: (lastPage): MessagePageParams | undefined =>
      lastPage.has_more ? { limit: LOAD_MORE_STEP, before: lastPage.messages[0].id } : undefined,
  })
  const messages = useMemo(
    () =>
      messagesQuery.data?.pages
        .slice()
        .reverse()
        .flatMap((page) => page.messages) ?? EMPTY_MESSAGES,
    [messagesQuery.data],
  )
  const selectedConversationTitle =
    selectedConversation === null ? selectedConversationId : (selectedConversation.title ?? t('untitledConversation'))
  const isDeletingSelected = selectedConversationId !== null && deletingConversationIds.has(selectedConversationId)
  const hasMoreMessages = messagesQuery.hasNextPage
  const isLoadingOlder = messagesQuery.isFetchingNextPage
  const isReadingMessages = messagesQuery.fetchStatus !== 'idle'

  const handleSelectConversation = useCallback(
    (conversation: Conversation) => {
      setShowConversationDetail(true)
      if (selectedConversationIdRef.current === conversation.id && requestedConversationId === conversation.id) return

      selectedConversationIdRef.current = conversation.id
      shouldScrollToEndRef.current = true
      setSelectedConversationSnapshot(conversation)

      // 更新 URL
      startNavigation(() => router.push(`/history?id=${encodeURIComponent(conversation.id)}`, { scroll: false }))
    },
    [requestedConversationId, router, startNavigation],
  )

  const handleConversationCreated = (conversation: Conversation) => {
    setIsOpsOpen(false)
    handleSelectConversation(conversation)
  }

  useLayoutEffect(() => {
    selectedConversationIdRef.current = selectedConversationId
    if (requestedConversationId !== null) setShowConversationDetail(true)
    shouldScrollToEndRef.current = selectedConversationId !== null
    pendingPrependScrollRef.current = null
    setIsTraceOpen(false)
    setIsOpsOpen(false)
  }, [requestedConversationId, selectedConversationId])

  useLayoutEffect(() => {
    historyOwnerRef.current = { active: true }
    const resetHistoryOperations = () => {
      historyOwnerRef.current.active = false
      historyOwnerRef.current = { active: true }
      deletionsRef.current.clear()
      setDeletingConversationIds(new Set())
      setRemovedConversationIds(new Set())
      setConversationListSnapshot(null)
      setSelectedConversationSnapshot(null)
      setShowDeleteConfirm(null)
      setIsTraceOpen(false)
      setIsOpsOpen(false)
      setRenameConversation(null)
      setRenameError(null)
      setIsRenaming(false)
      renameOperationRef.current = null
      pendingPrependScrollRef.current = null
    }
    globalThis.window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, resetHistoryOperations)
    return () => {
      historyOwnerRef.current.active = false
      globalThis.window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, resetHistoryOperations)
    }
  }, [])

  useEffect(() => {
    if (
      selectedConversationId !== null ||
      selectedConversationIdRef.current !== null ||
      !conversationsQuery.isSuccess ||
      isReadingConversations ||
      isSearchPending ||
      conversationSearchTerm !== '' ||
      historyView !== 'all' ||
      deletingConversationIds.size > 0
    )
      return
    const latestConversation = conversations[0]
    if (latestConversation === undefined) return
    setSelectedConversationSnapshot(latestConversation)
  }, [
    selectedConversationId,
    conversations,
    conversationsQuery.isSuccess,
    isReadingConversations,
    isSearchPending,
    conversationSearchTerm,
    historyView,
    deletingConversationIds,
  ])

  useEffect(() => {
    if (!conversationsQuery.error) return
    reportClientError('Failed to load conversations', conversationsQuery.error)
  }, [conversationsQuery.error])

  useEffect(() => {
    if (historyView !== 'recent') return
    const timer = globalThis.window.setInterval(() => {
      setRecentConversationCutoff(Date.now() - RECENT_CONVERSATION_WINDOW_MS)
    }, 60_000)
    return () => globalThis.window.clearInterval(timer)
  }, [historyView])

  const { fetchNextPage } = conversationsQuery
  const isConversationPageError = conversationsQuery.isError
  const loadMoreConversations = useCallback(() => {
    if (!hasMoreConversations || isReadingConversations || isSearchPending) return
    void fetchNextPage({ cancelRefetch: false })
  }, [fetchNextPage, hasMoreConversations, isReadingConversations, isSearchPending])

  function retryConversations() {
    if (conversationsQuery.isFetchNextPageError) loadMoreConversations()
    else void conversationsQuery.refetch()
  }

  useEffect(() => {
    const node = conversationLoadMoreRef.current
    if (!node || !hasMoreConversations || isConversationPageError) return

    const root = node.closest('[data-history-sidebar-scroll]')
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        void loadMoreConversations()
      },
      {
        root,
        rootMargin: '240px 0px',
      },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasMoreConversations, isConversationPageError, loadMoreConversations])

  useEffect(() => {
    if (matchingConversation !== undefined) setSelectedConversationSnapshot(matchingConversation)
  }, [matchingConversation])

  useEffect(() => {
    if (!selectedConversationId) return
    if (messagesQuery.error) {
      pendingPrependScrollRef.current = null
      reportClientError('Failed to load conversation messages', messagesQuery.error)
      return
    }
    if (!messagesQuery.isSuccess) return
    if (!shouldScrollToEndRef.current) return
    shouldScrollToEndRef.current = false
    const frame = globalThis.window.requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' })
    })
    return () => globalThis.window.cancelAnimationFrame(frame)
  }, [messagesQuery.error, messagesQuery.isSuccess, selectedConversationId])

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

  const handleDeleteConversation = async (conversation: Conversation) => {
    const conversationId = conversation.id
    if (deletionsRef.current.has(conversationId)) return
    const operation: ConversationOperation = {
      owner: historyOwnerRef.current,
      authRevision: getAuthSessionRevision(),
      authScope: getAuthCacheScope(),
    }
    const isCurrentSession = () =>
      operation.authRevision === getAuthSessionRevision() && operation.authScope === getAuthCacheScope()
    deletionsRef.current.set(conversationId, operation)
    setDeletingConversationIds(new Set(deletionsRef.current.keys()))
    const listKeys = [queryKeys.chat.conversationPagesAll, queryKeys.chat.conversationsAll]
    const detailKeys = [
      queryKeys.chat.messagePages(conversationId),
      queryKeys.chat.messages(conversationId).slice(0, -1),
      queryKeys.chat.summary(conversationId),
      queryKeys.chat.ragTraces(conversationId).slice(0, -1),
    ]
    let deleted = false
    try {
      await chatApi.deleteConversation(conversationId)
      deleted = true
      if (!isCurrentSession()) return
      if (operation.owner.active) {
        setRemovedConversationIds((current) => new Set(current).add(conversationId))
        setShowDeleteConfirm((current) => (current === conversationId ? null : current))
        if (selectedConversationIdRef.current === conversationId) {
          selectedConversationIdRef.current = null
          setSelectedConversationSnapshot(null)
          startNavigation(() => router.replace('/history', { scroll: false }))
        }
      }
      await Promise.all([...listKeys, ...detailKeys].map((queryKey) => queryClient.cancelQueries({ queryKey })))
      if (!isCurrentSession()) return
      for (const queryKey of detailKeys) queryClient.removeQueries({ queryKey })
      await Promise.all(listKeys.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
    } catch (error) {
      if (operation.owner.active && isCurrentSession()) {
        const title = conversation.title ?? conversation.id
        const message = deleted ? `对话“${title}”已删除，历史列表刷新失败` : `删除对话“${title}”失败`
        reportClientError(message, error)
        toast.error(`${message}：${formatApiError(error, '操作失败')}`)
      }
    } finally {
      if (deletionsRef.current.get(conversationId) === operation) {
        deletionsRef.current.delete(conversationId)
        if (operation.owner.active) setDeletingConversationIds(new Set(deletionsRef.current.keys()))
      }
    }
  }

  async function handleRenameConversation() {
    const title = renameTitle.trim()
    if (renameConversation === null || title === '' || renameOperationRef.current !== null) return
    const operation: ConversationOperation = {
      owner: historyOwnerRef.current,
      authRevision: getAuthSessionRevision(),
      authScope: getAuthCacheScope(),
    }
    const isCurrentSession = () =>
      operation.owner.active &&
      operation.authRevision === getAuthSessionRevision() &&
      operation.authScope === getAuthCacheScope()
    renameOperationRef.current = operation
    setIsRenaming(true)
    setRenameError(null)
    let renamed = false
    try {
      const updated = await chatApi.updateConversation(renameConversation.id, { title })
      renamed = true
      if (!isCurrentSession()) return
      await Promise.all(
        [queryKeys.chat.conversationPagesAll, queryKeys.chat.conversationsAll].map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }, { throwOnError: true }),
        ),
      )
      if (!isCurrentSession()) return
      setSelectedConversationSnapshot((current) =>
        selectedConversationIdRef.current === updated.id ? updated : current,
      )
      setRenameConversation(null)
    } catch (error) {
      if (isCurrentSession()) {
        reportClientError('Failed to rename conversation', error)
        setRenameError(
          renamed
            ? `名称已保存，历史列表刷新失败：${formatApiError(error, '读取失败')}`
            : formatApiError(error, '重命名失败'),
        )
      }
    } finally {
      if (renameOperationRef.current === operation) {
        renameOperationRef.current = null
        if (isCurrentSession()) setIsRenaming(false)
      }
    }
  }

  const handleContinueChat = useCallback(
    (prompt?: string) => {
      if (selectedConversationId === null || deletionsRef.current.has(selectedConversationId)) return
      const params = new URLSearchParams({ conversation: selectedConversationId })
      if (prompt !== undefined) params.set('prompt', prompt)
      router.push(`/?${params.toString()}`)
    },
    [router, selectedConversationId],
  )

  const handleEvaluateConversation = () => {
    if (selectedConversationId !== null) {
      router.push(`/evaluations?conversation_id=${encodeURIComponent(selectedConversationId)}`, { scroll: false })
    }
  }

  const filteredConversations = useMemo(() => {
    if (displayedSearchTerm !== '' || recentConversationCutoff === null) return conversations

    return conversations.filter((conversation) => {
      const activityDate = conversation.last_message_at ?? conversation.updated_at
      return new Date(activityDate).getTime() >= recentConversationCutoff
    })
  }, [displayedSearchTerm, conversations, recentConversationCutoff])

  const groupLabels = useMemo(
    () => ({
      today: t('groupToday'),
      yesterday: t('groupYesterday'),
      last7Days: t('groupLast7Days'),
      last30Days: t('groupLast30Days'),
      earlier: t('groupEarlier'),
    }),
    [t],
  )

  // 按日期分组
  const groupedConversations = useMemo(
    () => groupConversationsByDate(filteredConversations, groupLabels),
    [filteredConversations, groupLabels],
  )
  const groupOrder = [
    groupLabels.today,
    groupLabels.yesterday,
    groupLabels.last7Days,
    groupLabels.last30Days,
    groupLabels.earlier,
  ]
  const groupedMessages = useMemo(
    () =>
      groupMessagesByDay(messages, locale, {
        today: groupLabels.today,
        yesterday: groupLabels.yesterday,
      }),
    [groupLabels.today, groupLabels.yesterday, locale, messages],
  )

  function loadOlderMessages() {
    if (!hasMoreMessages || isReadingMessages) return

    const el = messagesContainerRef.current
    if (el) {
      pendingPrependScrollRef.current = { top: el.scrollTop, height: el.scrollHeight }
    }

    void messagesQuery.fetchNextPage({ cancelRefetch: false })
  }

  function retryMessages() {
    if (messagesQuery.isFetchNextPageError) loadOlderMessages()
    else void messagesQuery.refetch()
  }

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
          <section data-history-shell="ruled" data-history-design="fog-ink" className={cn(styles.shell, '@container')}>
            <header className={styles.pageHeader}>
              <div className={styles.pageHeading}>
                <span>
                  <History className="size-[21px]" aria-hidden="true" />
                </span>
                <h1>{t('pageTitle')}</h1>
              </div>
              <div className="flex items-center gap-2">
                {showConversationDetail && (
                  <IconButton
                    label={t('expandHistory')}
                    variant="ghost"
                    className="size-11 text-muted-foreground @min-[44rem]:hidden"
                    onClick={() => setShowConversationDetail(false)}
                    aria-controls="history-conversations"
                    aria-expanded={false}
                  >
                    <ArrowLeft className="size-5" />
                  </IconButton>
                )}
                <Button asChild variant="outline" className="h-11 gap-2 px-3 sm:h-9">
                  <Link href="/">
                    <Plus className="size-4" />
                    <span className="hidden sm:inline">{t('newConversation')}</span>
                    <span className="sr-only sm:hidden">{t('newConversation')}</span>
                  </Link>
                </Button>
              </div>
            </header>
            <div className={styles.workspace}>
              {/* 侧边栏 - 对话列表 */}
              <aside
                data-history-sidebar="true"
                id="history-conversations"
                className={cn(
                  styles.queue,
                  'relative z-10 min-w-0 w-full shrink-0 flex-col overflow-hidden border-border @min-[44rem]:w-[284px] @min-[44rem]:border-r',
                  showEmptyHistory ? 'hidden' : showConversationDetail ? 'hidden @min-[44rem]:flex' : 'flex',
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
                    {(
                      [
                        ['all', t('allConversations')],
                        ['recent', t('recentConversations')],
                      ] as const
                    ).map(([value, label]) => (
                      <Button
                        key={value}
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-pressed={(isSearchingHistory ? 'all' : historyView) === value}
                        disabled={isSearchingHistory}
                        onClick={() =>
                          setRecentConversationCutoff(
                            value === 'recent' ? Date.now() - RECENT_CONVERSATION_WINDOW_MS : null,
                          )
                        }
                        className={styles.filter}
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                </div>

                {/* 对话列表 */}
                <div
                  data-history-sidebar-scroll
                  aria-busy={conversationsQuery.isFetching || isSearchPending}
                  className={cn(styles.queueScroll, 'no-scrollbar')}
                >
                  {conversationsQuery.isPaused ||
                  isSearchPending ||
                  (conversationsQuery.isFetching && !isLoadingList) ? (
                    <p role="status" className={styles.status}>
                      {conversationsQuery.isPaused ? '历史记录读取已暂停' : '正在读取历史记录…'}
                    </p>
                  ) : null}
                  {showingPreviousSearch && (
                    <p role="status" className={styles.status}>
                      {t('retainedSearchResults', {
                        query: displayedSearchTerm === '' ? t('allConversations') : displayedSearchTerm,
                      })}
                    </p>
                  )}
                  {isConversationPageError && !isReadingConversations && (
                    <div role="alert" className={styles.status}>
                      <p>{formatApiError(conversationsQuery.error, t('loadConversationListFailed'))}</p>
                      <Button variant="ghost" size="sm" onClick={retryConversations}>
                        重试
                      </Button>
                    </div>
                  )}
                  {(() => {
                    if (isLoadingList) {
                      return (
                        <div role="status" aria-label={t('loading')} className="flex items-center justify-center py-8">
                          <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground" />
                        </div>
                      )
                    }
                    if (filteredConversations.length === 0) {
                      if (
                        displayedConversationData === undefined ||
                        isSearchPending ||
                        isReadingConversations ||
                        showingPreviousSearch ||
                        isConversationPageError
                      )
                        return null
                      return (
                        <HistorySidebarEmptyState
                          isSearching={Boolean(searchQuery.trim())}
                          isRecent={!isSearchingHistory && historyView === 'recent'}
                          hasMoreConversations={hasMoreConversations}
                        />
                      )
                    } else {
                      return (
                        <>
                          {groupOrder.map((group) => {
                            const convs = groupedConversations.get(group)
                            if (!convs || convs.length === 0) return null
                            return (
                              <div key={group} className={styles.dateGroup}>
                                <div className={styles.groupHeading}>
                                  <span suppressHydrationWarning>{group}</span>
                                  <span className={styles.groupCount}>{convs.length}</span>
                                </div>
                                <div className="space-y-1">
                                  {convs.map((conversation) => (
                                    <ConversationItem
                                      key={conversation.id}
                                      conversation={conversation}
                                      isSelected={selectedConversationId === conversation.id}
                                      isDeleting={deletingConversationIds.has(conversation.id)}
                                      onSelect={() => handleSelectConversation(conversation)}
                                      onDelete={() => setShowDeleteConfirm(conversation.id)}
                                      showDeleteConfirm={showDeleteConfirm === conversation.id}
                                      onConfirmDelete={() => handleDeleteConversation(conversation)}
                                      onCancelDelete={() => setShowDeleteConfirm(null)}
                                    />
                                  ))}
                                </div>
                              </div>
                            )
                          })}
                        </>
                      )
                    }
                  })()}
                  {conversationsQuery.data !== undefined &&
                    !showingPreviousSearch &&
                    !isSearchPending &&
                    (hasMoreConversations || conversations.length > 0) && (
                      <div ref={conversationLoadMoreRef} className="px-3 py-3 text-center">
                        {hasMoreConversations ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={loadMoreConversations}
                            disabled={isReadingConversations}
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
                        ) : isReadingConversations || isConversationPageError ? null : (
                          <span className="text-[11px] text-muted-foreground">
                            {conversationSearchTerm.length > 0 ? '已加载全部匹配记录' : '已加载全部历史'}
                          </span>
                        )}
                      </div>
                    )}
                </div>
              </aside>
              {/* 主区域 - 对话详情 */}
              <motion.div
                layout={!reduceMotion}
                className={cn(
                  styles.reading,
                  showEmptyHistory || showConversationDetail ? 'flex' : 'hidden @min-[44rem]:flex',
                )}
              >
                {selectedConversationId !== null ? (
                  <>
                    <div data-history-detail-header="true" className={styles.detailHeader}>
                      <motion.div layout={!reduceMotion} className={styles.detailHeaderInner}>
                        <div className="contents">
                          <div className={styles.detailHeading}>
                            <div className="min-w-0">
                              <h2 title={selectedConversationTitle ?? undefined} className={styles.detailTitle}>
                                {selectedConversationTitle}
                              </h2>
                              <div className={cn(styles.detailMeta, 'tabular-nums')}>
                                {selectedConversation && (
                                  <>
                                    <span>
                                      <MessageSquare aria-hidden="true" />
                                      {t('messageCount', { count: selectedConversation.message_count })}
                                    </span>
                                    <span suppressHydrationWarning>
                                      {formatDate(selectedConversation.created_at, locale)}
                                    </span>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                          {(selectedConversation !== null || messagesQuery.data !== undefined) && (
                            <div className={styles.detailActions}>
                              <Button
                                variant="default"
                                size="sm"
                                onClick={() => handleContinueChat()}
                                disabled={isDeletingSelected || isNavigating}
                                aria-label="继续当前对话"
                                className={styles.continueButton}
                              >
                                继续对话
                                <ArrowUpRight className="size-4" />
                              </Button>
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <IconButton
                                    label="更多对话操作"
                                    disabled={isDeletingSelected || isNavigating}
                                    variant="ghost"
                                    className="size-11 text-muted-foreground md:size-9"
                                  >
                                    <MoreHorizontal className="size-[18px]" />
                                  </IconButton>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" className={styles.menu}>
                                  <DropdownMenuItem
                                    onSelect={() => {
                                      setRenameConversation({
                                        id: selectedConversationId,
                                        title: selectedConversation?.title,
                                      })
                                      setRenameTitle(selectedConversation?.title ?? '')
                                      setRenameError(null)
                                    }}
                                  >
                                    <Pencil className="size-4" />
                                    重命名
                                  </DropdownMenuItem>
                                  <DropdownMenuItem onSelect={handleEvaluateConversation} aria-label="进行对话分析评测">
                                    <BarChart3 className="size-4" />
                                    分析评测
                                  </DropdownMenuItem>
                                  <DropdownMenuItem onSelect={() => setIsTraceOpen(true)} aria-label="查看数据追踪">
                                    <Route className="size-4" />
                                    数据追踪
                                  </DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem onSelect={() => setIsOpsOpen(true)}>
                                    <Download className="size-4" />
                                    导出与检查点
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                          )}
                        </div>
                      </motion.div>
                    </div>

                    {messagesQuery.isError && !isReadingMessages && (
                      <WorkspaceNotice
                        placement="floating"
                        error={messagesQuery.error}
                        fallbackMessage={t('loadConversationMessagesFailed')}
                        retry={retryMessages}
                        retryLabel="重试"
                      />
                    )}
                    {messagesQuery.isPaused ||
                    isNavigating ||
                    (messagesQuery.isFetching && !messagesQuery.isLoading) ? (
                      <p role="status" className="shrink-0 px-4 py-2 text-sm text-muted-foreground">
                        {messagesQuery.isPaused ? '对话记录读取已暂停' : '正在读取对话记录…'}
                      </p>
                    ) : null}
                    {/* 消息列表 */}
                    <div
                      ref={messagesContainerRef}
                      data-history-messages-scroll
                      aria-busy={messagesQuery.isFetching || isDeletingSelected || isNavigating}
                      className={cn(styles.messagesViewport, 'no-scrollbar')}
                    >
                      {(() => {
                        if (messagesQuery.isLoading) {
                          return (
                            <div
                              role="status"
                              aria-label={t('loading')}
                              className="flex h-full items-center justify-center"
                            >
                              <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none text-muted-foreground" />
                            </div>
                          )
                        }
                        if (messagesQuery.data === undefined) return null
                        if (messages.length === 0) {
                          if (isReadingMessages || messagesQuery.isError) return null
                          return (
                            <div className="flex h-full items-center justify-center">
                              <div className="px-6 py-10 text-center text-sm text-muted-foreground">
                                <ConversationHistory className="mx-auto mb-4 size-10" />
                                <p>{t('noMessageRecords')}</p>
                              </div>
                            </div>
                          )
                        } else {
                          return (
                            <AnimatePresence mode="wait">
                              <motion.div
                                layout={!reduceMotion}
                                key={selectedConversationId}
                                initial={reduceMotion ? false : { opacity: 0 }}
                                animate={{ opacity: 1 }}
                                transition={{ duration: reduceMotion ? 0 : 0.16 }}
                                className={styles.messages}
                              >
                                {hasMoreMessages ? (
                                  <div className="flex justify-center mb-4">
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={loadOlderMessages}
                                      disabled={isReadingMessages}
                                      className="text-xs text-muted-foreground"
                                    >
                                      {isLoadingOlder ? t('loading') : t('loadOlderMessages')}
                                    </Button>
                                  </div>
                                ) : null}
                                {groupedMessages.map((group) => (
                                  <div key={group.key} className={styles.messageGroup}>
                                    {groupedMessages.length > 1 && (
                                      <div className={styles.messageDate}>
                                        <div suppressHydrationWarning>{group.label}</div>
                                      </div>
                                    )}
                                    <div>
                                      {group.messages.map((message) => (
                                        <HistoryMessageEntry
                                          key={message.id}
                                          message={message}
                                          onFollowupSelect={handleContinueChat}
                                        />
                                      ))}
                                    </div>
                                  </div>
                                ))}
                                <div ref={messagesEndRef} className="h-4" />
                              </motion.div>
                            </AnimatePresence>
                          )
                        }
                      })()}
                    </div>
                  </>
                ) : isConversationPageError &&
                  !isReadingConversations &&
                  (displayedConversationData === undefined || conversations.length === 0) ? (
                  <div role="alert" className={styles.readingStatus}>
                    <p>{formatApiError(conversationsQuery.error, t('loadConversationListFailed'))}</p>
                    <Button variant="outline" onClick={retryConversations}>
                      重试
                    </Button>
                  </div>
                ) : conversationsQuery.isPaused ? (
                  <div role="status" className={styles.readingStatus}>
                    <p>历史记录读取已暂停</p>
                  </div>
                ) : isReadingConversations ||
                  isNavigating ||
                  (conversationsQuery.isSuccess &&
                    conversations.length > 0 &&
                    conversationSearchTerm === '' &&
                    historyView === 'all') ? (
                  <div role="status" className={styles.readingStatus}>
                    <Loader2 className="size-5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                    <p>{t('loading')}</p>
                  </div>
                ) : (
                  <HistoryMainEmptyState showEmptyHistory={showEmptyHistory} />
                )}
              </motion.div>
            </div>
          </section>
        </div>
        <Dialog
          open={renameConversation !== null}
          onOpenChange={(open) => {
            if (!open && !isRenaming) setRenameConversation(null)
          }}
        >
          <DialogContent
            showCloseButton={!isRenaming}
            className="max-h-[calc(100dvh-2rem)] gap-0 overflow-hidden p-0 sm:max-w-md"
          >
            <DialogHeader className="shrink-0 border-b border-border px-6 py-5">
              <DialogTitle className="text-base font-medium">重命名对话</DialogTitle>
              <DialogDescription className="sr-only">修改当前对话在历史记录中的标题。</DialogDescription>
            </DialogHeader>
            <form
              id="history-rename-form"
              className="min-h-0 overflow-y-auto px-6 py-5"
              onSubmit={(event) => {
                event.preventDefault()
                void handleRenameConversation()
              }}
            >
              <fieldset disabled={isRenaming} className="space-y-2">
                <Label htmlFor="history-conversation-title">对话标题</Label>
                <Input
                  id="history-conversation-title"
                  value={renameTitle}
                  onChange={(event) => setRenameTitle(event.target.value)}
                  required
                  aria-invalid={renameError !== null}
                  aria-describedby={renameError === null ? undefined : 'history-rename-error'}
                />
                {renameError !== null && (
                  <p id="history-rename-error" role="alert" className="text-sm leading-6 text-destructive">
                    {renameError}
                  </p>
                )}
              </fieldset>
            </form>
            <DialogFooter className="shrink-0 gap-2 border-t border-border px-6 py-4">
              <Button type="button" variant="outline" disabled={isRenaming} onClick={() => setRenameConversation(null)}>
                取消
              </Button>
              <Button type="submit" form="history-rename-form" disabled={isRenaming || renameTitle.trim() === ''}>
                {isRenaming ? '保存中…' : '保存'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Dialog open={isOpsOpen} onOpenChange={setIsOpsOpen}>
          <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
            <DialogHeader>
              <DialogTitle>对话操作</DialogTitle>
              <DialogDescription>{selectedConversationTitle}</DialogDescription>
            </DialogHeader>
            {selectedConversationId !== null && (
              <ConversationOpsPanel
                key={selectedConversationId}
                conversationId={selectedConversationId}
                onConversationCreated={handleConversationCreated}
                initiallyExpanded
              />
            )}
          </DialogContent>
        </Dialog>
        <RagTraceDialog
          open={isTraceOpen}
          onOpenChange={setIsTraceOpen}
          conversationId={selectedConversationId}
          title={selectedConversation?.title}
        />
      </PageScaffold>
    </AppFrame>
  )
}

function HistoryMainEmptyState({
  showEmptyHistory,
}: Readonly<{
  showEmptyHistory: boolean
}>) {
  const t = useTranslations('History')
  const title = showEmptyHistory ? t('startFirstConversation') : t('noConversationSelected')
  const description = showEmptyHistory
    ? t('startFirstConversationDescription')
    : t('noConversationSelectedDescription').replace('\n', ' ')

  return (
    <section data-history-main-empty="true" className={styles.emptyStage}>
      <SplitEmptyStudio
        illustration={<ConversationHistory className="size-10" />}
        title={title}
        description={description}
        actions={
          <>
            <Button asChild className="bg-accent text-accent-foreground hover:bg-accent/90">
              <Link href="/">
                <Plus className="size-4" />
                {t('startNewConversation')}
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/knowledge">前往知识库</Link>
            </Button>
          </>
        }
        stepsHeading="问答记录与引用"
        steps={[
          { index: '01', title: '回看多轮对话', description: '按时间浏览记录，继续已有问答。' },
          { index: '02', title: '核对回答引用', description: '从回答下方打开原文，核对来源。' },
          { index: '03', title: '按需查看追踪', description: '在对话操作菜单中查看检索与生成链路。' },
        ]}
      />
    </section>
  )
}

function HistorySidebarEmptyState({
  isSearching,
  isRecent,
  hasMoreConversations,
}: Readonly<{
  isSearching: boolean
  isRecent: boolean
  hasMoreConversations: boolean
}>) {
  const t = useTranslations('History')

  if (!isSearching && isRecent && hasMoreConversations) {
    return (
      <p role="status" className="px-3 py-6 text-sm leading-6 text-muted-foreground">
        已加载的记录中没有近期对话，可继续加载。
      </p>
    )
  }

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
function ConversationItem({
  conversation,
  isSelected,
  isDeleting,
  onSelect,
  onDelete,
  showDeleteConfirm,
  onConfirmDelete,
  onCancelDelete,
}: Readonly<{
  conversation: Conversation
  isSelected: boolean
  isDeleting: boolean
  onSelect: () => void
  onDelete: () => void
  showDeleteConfirm: boolean
  onConfirmDelete: () => void
  onCancelDelete: () => void
}>) {
  const locale = useLocale()
  const t = useTranslations('History')

  return (
    <div aria-busy={isDeleting} className={cn('group relative', showDeleteConfirm && styles.confirmationRow)}>
      <motion.button
        type="button"
        onClick={onSelect}
        aria-pressed={isSelected}
        className={cn(
          styles.conversationButton,
          'text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        )}
      >
        <span title={conversation.title ?? t('untitledConversation')} className={styles.conversationTitle}>
          {conversation.title ?? t('untitledConversation')}
        </span>
        <div className={styles.conversationMeta}>
          <time
            suppressHydrationWarning
            dateTime={conversation.last_message_at ?? conversation.updated_at}
            className="shrink-0"
          >
            {formatRelativeTime(conversation.last_message_at ?? conversation.updated_at, locale, t('justNow'))}
          </time>
          <span className={styles.conversationCount}>
            <MessageSquare className="size-3" />
            {t('messageCount', { count: conversation.message_count })}
          </span>
        </div>
      </motion.button>

      <div
        className={cn(
          styles.rowActions,
          showDeleteConfirm && styles.confirmationActions,
          'transition-opacity motion-reduce:transition-none',
          showDeleteConfirm
            ? 'opacity-100'
            : 'opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100',
        )}
      >
        {showDeleteConfirm ? (
          <div className="flex items-center gap-1">
            <Button
              aria-label={t('confirmDeleteConversation')}
              disabled={isDeleting}
              variant="ghost"
              className="h-11 px-3 text-destructive hover:bg-destructive/10 hover:text-destructive md:h-8 md:px-2"
              onClick={(e) => {
                e.stopPropagation()
                onConfirmDelete()
              }}
            >
              {isDeleting ? (
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
              ) : (
                <Trash2 className="size-4" />
              )}
              {t('confirmDeleteConversation')}
            </Button>
            <Button
              aria-label={t('cancelDelete')}
              disabled={isDeleting}
              variant="ghost"
              className="h-11 px-3 text-muted-foreground md:h-8 md:px-2"
              onClick={(e) => {
                e.stopPropagation()
                onCancelDelete()
              }}
            >
              <X className="size-4" />
              {t('cancelDelete')}
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-1">
            <IconButton
              label={t('deleteConversation')}
              disabled={isDeleting}
              variant="ghost"
              className="size-11 text-muted-foreground hover:bg-destructive/10 hover:text-destructive md:size-8"
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
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
  onFollowupSelect,
}: Readonly<{ message: Message; onFollowupSelect: (prompt: string) => void }>) {
  const isUser = message.role === 'user'
  const reduceMotion = useReducedMotion()
  const requestId = isUser ? undefined : message.message_metadata?.request_id?.trim()

  return (
    <motion.div
      initial={false}
      animate={{ opacity: 1 }}
      transition={{ duration: reduceMotion ? 0 : 0.16 }}
      data-history-message-role={message.role}
      className={cn(styles.messageEntry, 'mx-auto w-full min-w-0')}
    >
      <ChatMessageItem message={message} variant="history" onFollowupSelect={onFollowupSelect} />
      {requestId && hasAnswerLineageEvidence(message) ? (
        <div className="mt-1">
          <AnswerLineageAction requestId={requestId} />
        </div>
      ) : null}
    </motion.div>
  )
}

function hasAnswerLineageEvidence(message: Message): boolean {
  const metadata = message.message_metadata
  return Boolean(
    message.citations?.length ||
    metadata?.retrieved_docs?.length ||
    metadata?.claim_evidence?.some((item) => item.evidence.length > 0) ||
    metadata?.sentence_citations?.some((item) => item.evidence.length > 0) ||
    (metadata?.docs_returned != null && metadata.docs_returned > 0),
  )
}

function localDayStart(date: Date, daysAgo = 0): number {
  const day = new Date(date)
  day.setDate(day.getDate() - daysAgo)
  return day.setHours(0, 0, 0, 0)
}

// 辅助函数：按日期分组
function groupConversationsByDate(conversations: readonly Conversation[], labels: Readonly<ConversationGroupLabels>) {
  const groups = new Map<string, Conversation[]>()
  const now = new Date()
  const today = localDayStart(now)
  const yesterday = localDayStart(now, 1)
  const last7DaysStart = localDayStart(now, 7)
  const last30DaysStart = localDayStart(now, 30)

  for (const conversation of conversations) {
    const activityDate = conversation.last_message_at ?? conversation.updated_at
    const conversationDayStart = localDayStart(new Date(activityDate))

    let group: string
    if (conversationDayStart === today) {
      group = labels.today
    } else if (conversationDayStart === yesterday) {
      group = labels.yesterday
    } else if (conversationDayStart >= last7DaysStart) {
      group = labels.last7Days
    } else if (conversationDayStart >= last30DaysStart) {
      group = labels.last30Days
    } else {
      group = labels.earlier
    }

    const conversationsInGroup = groups.get(group)
    if (conversationsInGroup === undefined) groups.set(group, [conversation])
    else conversationsInGroup.push(conversation)
  }

  return groups
}

function groupMessagesByDay(
  messages: readonly Message[],
  locale: string,
  labels: Readonly<{
    today: string
    yesterday: string
  }>,
) {
  const groups = new Map<number, { key: number; label: string; messages: Message[] }>()

  for (const message of messages) {
    const date = new Date(message.created_at)
    const key = localDayStart(date)

    const group = groups.get(key)
    if (group === undefined) {
      groups.set(key, {
        key,
        label: formatMessageGroupLabel(date, locale, labels),
        messages: [message],
      })
    } else group.messages.push(message)
  }

  return Array.from(groups.values())
}

// 辅助函数：格式化相对时间
function formatRelativeTime(dateString: string, locale: string, justNowLabel: string) {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = date.getTime() - now.getTime()
  const diffMins = Math.trunc(diffMs / (1000 * 60))
  const diffHours = Math.trunc(diffMs / (1000 * 60 * 60))
  const diffDays = Math.trunc(diffMs / (1000 * 60 * 60 * 24))
  const relative = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })

  if (Math.abs(diffMins) < 1) return justNowLabel
  if (Math.abs(diffMins) < 60) return relative.format(diffMins, 'minute')
  if (Math.abs(diffHours) < 24) return relative.format(diffHours, 'hour')
  if (Math.abs(diffDays) < 7) return relative.format(diffDays, 'day')

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
  }>,
) {
  const now = new Date()
  const target = localDayStart(date)

  if (target === localDayStart(now)) return labels.today
  if (target === localDayStart(now, 1)) return labels.yesterday

  return new Intl.DateTimeFormat(locale, {
    year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(date)
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
