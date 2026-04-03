/**
 * 对话历史页面
 */
'use client'

import { useState, useEffect, useLayoutEffect, useRef, Suspense, useCallback, useDeferredValue, useMemo } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useSearchParams } from 'next/navigation'
import {
  MessageSquare,
  Trash2,
  Send,
  Loader2,
  BarChart3,
  History,
  X,
  Plus,
  Route
} from 'lucide-react'
import { AppFrame } from '@/components/app-frame'
import { ChatMessageItem } from '@/components/chat/message-item'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { RagTraceDialog } from '@/components/rag-trace/rag-trace-dialog'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { SearchInput } from '@/components/ui/search-input'
import { EmptyState } from '@/components/ui/empty-state'
import { PageLoading } from '@/components/ui/page-loading'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { useRouter } from '@/i18n/navigation'
import { chatApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { toast } from 'sonner'
import type { Conversation, Message } from '@/types'

type HistoryPageClientProps = {
  initialConversationId?: string | null
  initialConversations?: Conversation[]
  initialSelectedConversation?: Conversation | null
  initialMessages?: Message[]
  initialHasMoreMessages?: boolean
  initialConversationsLoaded?: boolean
}

type HistoryPageContentProps = {
  initialConversationId: string | null
  initialConversations: Conversation[]
  initialSelectedConversation: Conversation | null
  initialMessages: Message[]
  initialHasMoreMessages: boolean
  initialConversationsLoaded: boolean
}

export default function HistoryPageClient({
  initialConversationId = null,
  initialConversations = [],
  initialSelectedConversation = null,
  initialMessages = [],
  initialHasMoreMessages = false,
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
  initialConversationsLoaded,
}: Readonly<HistoryPageContentProps>) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const locale = useLocale()
  const t = useTranslations('History')
  const conversationId = searchParams.get('id') || initialConversationId || null

  const [conversations, setConversations] = useState<Conversation[]>(initialConversations)
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(initialSelectedConversation)
  const [messages, setMessages] = useState<Message[]>(initialMessages)
  const [isLoadingList, setIsLoadingList] = useState(!initialConversationsLoaded)
  const [isLoadingMessages, setIsLoadingMessages] = useState(false)
  const [hasMoreMessages, setHasMoreMessages] = useState(initialHasMoreMessages)
  const [isLoadingOlder, setIsLoadingOlder] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
  const [isTraceOpen, setIsTraceOpen] = useState(false)

  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const pendingPrependScrollRef = useRef<{ top: number; height: number } | null>(null)
  const deferredSearchQuery = useDeferredValue(searchQuery)

  // define handlers first to avoid ReferenceError
  const loadConversations = useCallback(async () => {
    try {
      setIsLoadingList(true)
      const result = await chatApi.listConversations({ limit: 100 })
      setConversations(result.items || [])
    } catch (error) {
      console.error('Failed to load conversations:', error)
      toast.error(formatApiError(error, t('loadConversationListFailed')))
    } finally {
      setIsLoadingList(false)
    }
  }, [t])

  const handleSelectConversation = useCallback(async (conversation: Conversation) => {
    if (selectedConversation?.id === conversation.id && messages.length > 0) return

    setSelectedConversation(conversation)
    setMessages([])
    setHasMoreMessages(false)
    setIsLoadingMessages(true)

    // 更新 URL
    router.push(`/history?id=${conversation.id}`, { scroll: false })

    try {
      const result = await chatApi.getMessages(conversation.id, { limit: DEFAULT_VISIBLE_MESSAGES })
      setMessages(result.messages || [])
      setHasMoreMessages(Boolean(result.has_more))
      globalThis.window.requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'auto' })
      })
    } catch (error) {
      console.error('Failed to load messages:', error)
      toast.error(formatApiError(error, t('loadConversationMessagesFailed')))
      setMessages([])
      setHasMoreMessages(false)
    } finally {
      setIsLoadingMessages(false)
    }
  }, [router, selectedConversation?.id, messages.length, t])

  // 加载对话列表
  useEffect(() => {
    if (initialConversationsLoaded) return
    loadConversations()
  }, [initialConversationsLoaded, loadConversations])

  // 当 URL 中有 id 参数时，自动选中对话
  useEffect(() => {
    if (conversationId && conversations.length > 0) {
      const conv = conversations.find((c) => c.id === conversationId)
      if (conv && selectedConversation?.id !== conv.id) {
        handleSelectConversation(conv)
      }
    }
  }, [conversationId, conversations, handleSelectConversation, selectedConversation?.id])

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
      setConversations((prev) => prev.filter((c) => c.id !== conversationId))
      if (selectedConversation?.id === conversationId) {
        setSelectedConversation(null)
        setMessages([])
        router.push('/history', { scroll: false })
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error)
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
    const term = deferredSearchQuery.trim().toLowerCase()
    if (!term) return conversations
    return conversations.filter(
      (c) =>
        (c.title || '').toLowerCase().includes(term) ||
        (c.last_message || '').toLowerCase().includes(term)
    )
  }, [conversations, deferredSearchQuery])

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

    setIsLoadingOlder(true)
    try {
      const result = await chatApi.getMessages(selectedConversation.id, { limit: LOAD_MORE_STEP, before: oldestMessageId })
      const older = result.messages || []
      setMessages((prev) => {
        const seen = new Set(prev.map((m) => m.id))
        const prefix = older.filter((m) => !seen.has(m.id))
        return prefix.length ? [...prefix, ...prev] : prev
      })
      setHasMoreMessages(Boolean(result.has_more))
    } catch (error) {
      console.error('Failed to load older messages:', error)
      toast.error(formatApiError(error, t('loadOlderMessagesFailed')))
    } finally {
      setIsLoadingOlder(false)
    }
  }, [selectedConversation, hasMoreMessages, isLoadingMessages, isLoadingOlder, oldestMessageId, t])

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding mainClassName="overflow-hidden">
      <PageScaffold
        title={t('pageTitle')}
        description={t('pageDescription')}
        icon={History}
        iconColor="text-sky-600 dark:text-sky-400"
        size="full"
        bodyClassName="px-0 pb-0 overflow-hidden"
        bodyContainerClassName="h-full"
        actions={
          <Button
            variant="default"
            size="sm"
            className="gap-2 rounded-full"
            onClick={() => router.push('/', { scroll: false })}
          >
            <Plus className="h-4 w-4" />
            {t('newConversation')}
          </Button>
        }
      >
        <div className="h-full p-3 md:p-4">
          <section className="relative flex h-full min-h-0 overflow-hidden rounded-[2rem] border border-border/70 bg-gradient-to-br from-background via-background to-muted/20 shadow-soft">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-primary/[0.07] via-primary/[0.02] to-transparent"
            />

            {/* 侧边栏 - 对话列表 */}
            <aside className="relative z-10 flex w-[19.5rem] shrink-0 flex-col border-r border-border/70 bg-card/90 backdrop-blur xl:w-[20.75rem]">
              {/* 头部 */}
              <div className="border-b border-border/70 p-4">
                <div className="rounded-[1.5rem] border border-border/70 bg-background/80 p-3 shadow-sm">
                  <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl border border-primary/15 bg-primary/10 text-primary shadow-sm">
                      <History className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h2 className="truncate text-sm font-semibold text-foreground">{t('pageTitle')}</h2>
                          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                            {t('pageDescription')}
                          </p>
                        </div>
                        <div
                          aria-label={`${t('pageTitle')}: ${filteredConversations.length}`}
                          className="rounded-2xl border border-border/60 bg-card/80 px-2.5 py-2 text-right shadow-sm"
                        >
                          <div className="text-sm font-semibold tabular-nums text-foreground">
                            {filteredConversations.length}
                          </div>
                          <div className="text-[10px] font-medium tabular-nums text-muted-foreground">
                            {conversations.length}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 rounded-xl border border-border/60 bg-background/80 p-1.5 shadow-sm">
                    <SearchInput
                      value={searchQuery}
                      onValueChange={setSearchQuery}
                      placeholder={t('searchPlaceholder')}
                      inputClassName="h-10 rounded-lg border-0 bg-transparent shadow-none"
                    />
                  </div>
                </div>
              </div>

              {/* 对话列表 */}
              <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar px-3 py-3">
                {(() => {
    if (isLoadingList) {
        return (<div className="flex items-center justify-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                    </div>);
    }
    else if (filteredConversations.length === 0) {
            return (<div className="rounded-[1.5rem] border border-dashed border-border/70 bg-background/70 px-5 py-10 text-center text-sm text-muted-foreground shadow-sm">
                      <MessageSquare className="mx-auto mb-3 h-8 w-8 opacity-20"/>
                      <p>{searchQuery ? t('noMatchedConversation') : t('noConversationRecords')}</p>
                      {searchQuery ? null : (<p className="mt-2 text-[11px] leading-relaxed text-muted-foreground/80">{t('startConversationHint')}</p>)}
                    </div>);
        }
        else {
            return (groupOrder.map((group) => {
                const convs = groupedConversations[group];
                if (!convs || convs.length === 0)
                    return null;
                const groupTone = getConversationGroupTone(group, groupLabels);
                return (<div key={group} className="pb-2 last:pb-0">
                          <div className="sticky top-0 z-10 px-2 pb-2 pt-1 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/85">
                            <div className="flex items-center gap-2">
                              <div className={cn("h-px flex-1", groupTone.lineClass)} />
                              <div className={cn("inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] shadow-sm", groupTone.chipClass)}>
                                <span>{group}</span>
                                <span className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-semibold tracking-normal", groupTone.countClass)}>
                                  {convs.length}
                                </span>
                              </div>
                              <div className={cn("h-px flex-1", groupTone.lineClass)} />
                            </div>
                          </div>
                          <div className="space-y-2 px-1 pb-2">
                            {convs.map((conversation) => (<ConversationItem key={conversation.id} conversation={conversation} isSelected={selectedConversation?.id === conversation.id} onSelect={() => handleSelectConversation(conversation)} onDelete={() => setShowDeleteConfirm(conversation.id)} showDeleteConfirm={showDeleteConfirm === conversation.id} onConfirmDelete={() => handleDeleteConversation(conversation.id)} onCancelDelete={() => setShowDeleteConfirm(null)}/>))}
                          </div>
                        </div>);
            }));
        }
})()}
              </div>
            </aside>

            {/* 主区域 - 对话详情 */}
            <div className="relative flex min-w-0 flex-1 flex-col bg-background/65">
              {selectedConversation ? (
                <>
                  {/* 对话头部 */}
                  <div className="border-b border-border/70 bg-background/85 px-4 py-4 backdrop-blur xl:px-6">
                    <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                      <div className="min-w-0 flex items-start gap-4">
                        <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-primary/20 bg-primary text-primary-foreground shadow-sm">
                          <MessageSquare className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <h2 className="truncate text-base font-semibold text-foreground md:text-lg">
                              {selectedConversation.title || t('untitledConversation')}
                            </h2>
                            <span className="rounded-full border border-primary/15 bg-primary/10 px-2.5 py-1 text-[10px] font-medium text-primary shadow-sm">
                              {t('messageCount', { count: selectedConversation.message_count })}
                            </span>
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span className="rounded-full border border-border/60 bg-background/90 px-2.5 py-1 tabular-nums shadow-sm">
                              {formatDate(selectedConversation.created_at, locale)}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleEvaluateConversation}
                          className="gap-2 rounded-full border-border/70 bg-background/80 hover:bg-background"
                        >
                          <BarChart3 className="h-3.5 w-3.5" />
                          {t('evaluateConversation')}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setIsTraceOpen(true)}
                          className="gap-2 rounded-full border-border/70 bg-background/80 hover:bg-background"
                        >
                          <Route className="h-3.5 w-3.5" />
                          {t('ragTrace')}
                        </Button>
                        <Button
                          size="sm"
                          onClick={handleContinueChat}
                          className="gap-2 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
                        >
                          <Send className="h-3.5 w-3.5" />
                          {t('continueConversation')}
                        </Button>
                      </div>
                    </div>
                  </div>

                  {/* 消息列表 */}
                  <div
                    ref={messagesContainerRef}
                    className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-muted/[0.12] px-4 py-5 md:px-6 md:py-6 xl:px-8"
                  >
                    {(() => {
    if (isLoadingMessages) {
        return (<div className="flex h-full items-center justify-center">
                          <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                        </div>);
    }
    else if (messages.length === 0) {
            return (<div className="flex h-full items-center justify-center">
                          <div className="rounded-[1.75rem] border border-dashed border-border/70 bg-background/80 px-8 py-12 text-center text-muted-foreground shadow-sm">
                            <MessageSquare className="mx-auto mb-4 h-12 w-12 opacity-10"/>
                            <p>{t('noMessageRecords')}</p>
                          </div>
                        </div>);
        }
        else {
            return (<div className="mx-auto w-full max-w-6xl space-y-6">
                          {hasMoreMessages ? (<div className="flex justify-center">
                              <Button variant="outline" size="sm" onClick={loadOlderMessages} disabled={isLoadingOlder} className="rounded-full border-border/70 bg-background/85 text-xs hover:bg-background">
                                {isLoadingOlder ? t('loading') : t('loadOlderMessages')}
                              </Button>
                            </div>) : null}
                          {groupedMessages.map((group) => (<section key={group.key} className="relative overflow-hidden rounded-[1.9rem] border border-border/70 bg-card/55 p-4 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-card/45 md:p-5">
                              <div aria-hidden="true" className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-primary/35 to-transparent" />
                              <div className="mb-5 flex items-center gap-3">
                                <div className="h-px flex-1 bg-border/60" />
                                <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/90 px-3 py-1.5 text-[11px] font-semibold text-foreground shadow-sm">
                                  <span className="h-2 w-2 rounded-full bg-primary/80" />
                                  <span>{group.label}</span>
                                  <span className="text-muted-foreground">·</span>
                                  <span className="text-muted-foreground">{t('messageCount', { count: group.messages.length })}</span>
                                </div>
                                <div className="h-px flex-1 bg-border/60" />
                              </div>
                              <div className="space-y-4">
                                {group.messages.map((message, index) => (<HistoryMessageEntry key={message.id} message={message} locale={locale} isLast={index === group.messages.length - 1}/>))}
                              </div>
                            </section>))}
                          <div ref={messagesEndRef} className="h-4"/>
                        </div>);
        }
})()}
                  </div>
                </>
              ) : (
                <div className="flex-1 bg-muted/[0.12] p-4 md:p-6">
                  <EmptyState
                    icon={History}
                    iconClassName="text-primary"
                    title={t('noConversationSelected')}
                    description={
                      <>
                        {t('noConversationSelectedDescription').split('\n')[0]}<br />
                        {t('noConversationSelectedDescription').split('\n')[1]}
                      </>
                    }
                    className="min-h-full rounded-[2rem] border border-border/70 bg-background/85 px-8 py-10 text-left shadow-soft"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        onClick={() => router.push('/', { scroll: false })}
                        className="rounded-full"
                      >
                        {t('startNewConversation')}
                      </Button>
                      <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 shadow-sm dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
                        <BarChart3 className="h-3.5 w-3.5" />
                        {t('evaluateConversation')}
                      </div>
                      <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-medium text-sky-700 shadow-sm dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-300">
                        <Route className="h-3.5 w-3.5" />
                        {t('ragTrace')}
                      </div>
                    </div>
                  </EmptyState>
                </div>
              )}
            </div>
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
    <div
      className={cn(
        'group relative overflow-hidden rounded-2xl border transition-all duration-200',
        isSelected
          ? 'border-sky-200/80 bg-sky-50/35 shadow-sm shadow-sky-100/50 dark:border-sky-800/70 dark:bg-sky-950/16 dark:shadow-none'
          : 'border-sky-200/55 bg-background/90 shadow-sm shadow-sky-100/25 hover:border-sky-200/85 hover:bg-sky-50/20 hover:shadow-sm hover:shadow-sky-100/35 dark:border-sky-900/55 dark:bg-background/70 dark:shadow-none dark:hover:border-sky-800/70 dark:hover:bg-sky-950/8'
      )}
    >
      {isSelected ? <div aria-hidden="true" className="absolute left-0 top-3 bottom-3 w-1 rounded-r-full bg-primary/75" /> : null}
      <div
        aria-hidden="true"
        className={cn(
          'absolute inset-x-4 top-0 h-px bg-gradient-to-r from-transparent opacity-0 transition-opacity duration-200',
          isSelected ? 'via-sky-300/55 to-transparent opacity-100' : 'via-sky-200/65 to-transparent opacity-100 dark:via-sky-900/70'
        )}
      />
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={onSelect}
          aria-label={`${t('selectConversation')}: ${conversation.title || t('untitledConversation')}`}
          className="min-w-0 flex-1 cursor-pointer px-2.5 py-2.5 text-left focus-ring"
        >
          <h3
            className={cn(
              'truncate text-[13.5px] font-semibold',
              isSelected ? 'text-primary' : 'text-foreground'
            )}
          >
            {conversation.title || t('untitledConversation')}
          </h3>
          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground/80">
            {conversation.last_message || t('noMessage')}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span
              className={cn(
                'rounded-full border px-2 py-1 text-[10px] font-medium tabular-nums shadow-sm',
                isSelected
                  ? 'border-sky-200/65 bg-background/90 text-sky-700 dark:border-sky-800/60 dark:text-sky-300'
                  : 'border-sky-200/55 bg-background/90 text-muted-foreground dark:border-sky-900/55'
              )}
            >
              {formatRelativeTime(conversation.updated_at, locale, t('justNow'))}
            </span>
            <span className="rounded-full border border-sky-200/55 bg-background/90 px-2 py-1 text-[10px] font-medium text-muted-foreground shadow-sm dark:border-sky-900/55">
              {t('messageCount', { count: conversation.message_count })}
            </span>
          </div>
        </button>

        {/* 删除按钮 */}
        <div className="flex flex-shrink-0 items-center py-2.5 pr-2.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          {showDeleteConfirm ? (
            <div className="flex items-center gap-1">
              <IconButton
                label={t('confirmDeleteConversation')}
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={onConfirmDelete}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </IconButton>
              <IconButton
                label={t('cancelDelete')}
                className="text-muted-foreground hover:bg-muted"
                onClick={onCancelDelete}
              >
                <X className="h-3.5 w-3.5" />
              </IconButton>
            </div>
          ) : (
            <IconButton
              onClick={onDelete}
              label={t('deleteConversation')}
              className="hover:bg-muted hover:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </IconButton>
          )}
        </div>
      </div>
    </div>
  )
}

function HistoryMessageEntry({
  message,
  locale,
  isLast,
}: Readonly<{
  message: Message
  locale: string
  isLast: boolean
}>) {
  const t = useTranslations('History')
  const isUser = message.role === 'user'

  return (
    <div className="space-y-3">
      <div className="group/entry grid gap-3 md:grid-cols-[6rem_minmax(0,1fr)] md:gap-5">
        <div className="hidden md:flex flex-col items-end pt-4">
          <div
            className={cn(
              'inline-flex min-w-[4.75rem] items-center justify-center rounded-full border px-2.5 py-1 text-[11px] font-medium tabular-nums shadow-sm',
              isUser
                ? 'border-primary/15 bg-primary/10 text-primary'
                : 'border-border/60 bg-background/90 text-muted-foreground'
            )}
          >
            {formatMessageTime(message.created_at, locale)}
          </div>
          <div className="mt-3 flex flex-1 items-start justify-end pr-1">
            <div className="flex h-full flex-col items-center">
              <span
                className={cn(
                  'size-3 rounded-full border-2 shadow-sm',
                  isUser
                    ? 'border-primary/15 bg-primary'
                    : 'border-sky-100 bg-sky-500 dark:border-sky-950'
                )}
              />
              {!isLast ? (
                <span className="mt-2 w-px flex-1 bg-gradient-to-b from-border/80 via-border/60 to-transparent" />
              ) : null}
            </div>
          </div>
        </div>

        <div className="relative overflow-hidden rounded-[1.75rem] border border-border/70 bg-background/90 p-2 shadow-sm transition-all duration-200 group-hover/entry:border-primary/20 group-hover/entry:shadow-md">
          <div aria-hidden="true" className="absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-primary/35 to-transparent" />
          <div className="mb-2 flex items-center justify-between gap-2 px-4 pt-3 md:hidden">
            <HistoryMessageRoleBadge role={message.role} />
            <span className="text-[11px] font-medium tabular-nums text-muted-foreground">
              {formatMessageTime(message.created_at, locale)}
            </span>
          </div>
          <div className="hidden px-4 pb-1 pt-3 md:flex">
            <HistoryMessageRoleBadge role={message.role} />
          </div>
          <ChatMessageItem message={message} />
          <div className="px-4 pb-2 pt-1 text-[11px] text-muted-foreground/80 md:hidden">
            {isUser ? t('speakerQuestion') : t('speakerAnswer')}
          </div>
        </div>
      </div>
      {!isLast ? (
        <div
          aria-hidden="true"
          className="h-px bg-gradient-to-r from-transparent via-border/70 to-transparent md:ml-[7.25rem]"
        />
      ) : null}
    </div>
  )
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
      chipClass: 'border-[#B6D7A8]/90 bg-[#F2F8ED] text-[#5E7E4D] dark:border-[#5E7E4D]/50 dark:bg-[#20311A]/70 dark:text-[#C8E0BA]',
      countClass: 'bg-[#DDECCF] text-[#4F6B41] dark:bg-[#2B4421] dark:text-[#D3E7C7]',
      lineClass: 'bg-[#B6D7A8]/75 dark:bg-[#5E7E4D]/70',
    }
  }

  if (group === labels.yesterday) {
    return {
      chipClass: 'border-[#B0D2EF]/90 bg-[#EEF6FC] text-[#4F7090] dark:border-[#4F7090]/55 dark:bg-[#182635]/80 dark:text-[#C6DDEF]',
      countClass: 'bg-[#D9EAF8] text-[#476786] dark:bg-[#21364A] dark:text-[#D3E6F5]',
      lineClass: 'bg-[#B0D2EF]/75 dark:bg-[#4F7090]/70',
    }
  }

  if (group === labels.last7Days) {
    return {
      chipClass: 'border-[#FFBEBA]/90 bg-[#FFF1F0] text-[#A86762] dark:border-[#A86762]/55 dark:bg-[#341C1A]/80 dark:text-[#FFD0CC]',
      countClass: 'bg-[#FFDCD8] text-[#955A56] dark:bg-[#472625] dark:text-[#FFDAD6]',
      lineClass: 'bg-[#FFBEBA]/75 dark:bg-[#A86762]/70',
    }
  }

  if (group === labels.last30Days) {
    return {
      chipClass: 'border-[#F4D8A6]/90 bg-[#FFF7E9] text-[#8A6A31] dark:border-[#8A6A31]/55 dark:bg-[#352813]/80 dark:text-[#F8E1B7]',
      countClass: 'bg-[#FCE9C3] text-[#785B28] dark:bg-[#49371A] dark:text-[#F6E1BC]',
      lineClass: 'bg-[#F4D8A6]/75 dark:bg-[#8A6A31]/70',
    }
  }

  return {
    chipClass: 'border-slate-200/90 bg-slate-50/95 text-slate-600 dark:border-slate-700/70 dark:bg-slate-900/60 dark:text-slate-300',
    countClass: 'bg-slate-200/80 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
    lineClass: 'bg-slate-200/80 dark:bg-slate-700/70',
  }
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
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const lastWeek = new Date(today)
  lastWeek.setDate(lastWeek.getDate() - 7)
  const lastMonth = new Date(today)
  lastMonth.setMonth(lastMonth.getMonth() - 1)

  conversations.forEach((conv) => {
    const date = new Date(conv.updated_at)
    const convDate = new Date(date.getFullYear(), date.getMonth(), date.getDate())

    let group: string
    if (convDate.getTime() === today.getTime()) {
      group = labels.today
    } else if (convDate.getTime() === yesterday.getTime()) {
      group = labels.yesterday
    } else if (convDate.getTime() >= lastWeek.getTime()) {
      group = labels.last7Days
    } else if (convDate.getTime() >= lastMonth.getTime()) {
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
    const key = [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, '0'),
      String(date.getDate()).padStart(2, '0'),
    ].join('-')

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
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate())

  if (target.getTime() === today.getTime()) return labels.today
  if (target.getTime() === yesterday.getTime()) return labels.yesterday

  return new Intl.DateTimeFormat(locale, {
    year: target.getFullYear() === today.getFullYear() ? undefined : 'numeric',
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
