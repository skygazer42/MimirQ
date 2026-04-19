/**
 * 对话历史页面
 */
'use client'

import { useState, useEffect, useLayoutEffect, useRef, Suspense, useCallback, useDeferredValue, useMemo } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useSearchParams } from 'next/navigation'
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
  Bot
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
import { Link, useRouter } from '@/i18n/navigation'
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
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
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
  const selectionRequestSeqRef = useRef(0)
  const selectedConversationIdRef = useRef<string | null>(initialSelectedConversation?.id ?? null)
  const messagesLengthRef = useRef(initialMessages.length)
  const deferredSearchQuery = useDeferredValue(searchQuery)

  useEffect(() => {
    selectedConversationIdRef.current = selectedConversation?.id ?? null
    messagesLengthRef.current = messages.length
  }, [selectedConversation?.id, messages.length])

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
    if (selectedConversationIdRef.current === conversation.id && messagesLengthRef.current > 0) return

    const requestSeq = selectionRequestSeqRef.current + 1
    selectionRequestSeqRef.current = requestSeq
    selectedConversationIdRef.current = conversation.id
    messagesLengthRef.current = 0
    setSelectedConversation(conversation)
    setMessages([])
    setHasMoreMessages(false)
    setIsLoadingMessages(true)

    // 更新 URL
    router.push(`/history?id=${conversation.id}`, { scroll: false })

    try {
      const result = await chatApi.getMessages(conversation.id, { limit: DEFAULT_VISIBLE_MESSAGES })
      if (requestSeq !== selectionRequestSeqRef.current) return
      const newMessages = result.messages || []
      messagesLengthRef.current = newMessages.length
      setMessages(newMessages)
      setHasMoreMessages(Boolean(result.has_more))

      // 实时同步元数据：如果返回的消息中有最新的，更新选中对话的状态
      if (newMessages.length > 0) {
        const lastMsg = newMessages[newMessages.length - 1]
        setSelectedConversation({
          ...conversation,
          message_count: conversation.message_count,
          updated_at: lastMsg.created_at || conversation.updated_at,
          last_message: buildConversationPreview(lastMsg.content) || conversation.last_message,
        })
      }

      globalThis.window.requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'auto' })
      })
    } catch (error) {
      if (requestSeq !== selectionRequestSeqRef.current) return
      messagesLengthRef.current = 0
      console.error('Failed to load messages:', error)
      toast.error(formatApiError(error, t('loadConversationMessagesFailed')))
      setMessages([])
      setHasMoreMessages(false)
    } finally {
      if (requestSeq !== selectionRequestSeqRef.current) return
      setIsLoadingMessages(false)
    }
  }, [router, t])

  // 加载对话列表
  useEffect(() => {
    if (initialConversationsLoaded) return
    loadConversations()
  }, [initialConversationsLoaded, loadConversations])

  // 当 URL 中有 id 参数时，自动选中对话
  useEffect(() => {
    if (conversationId && conversations.length > 0) {
      const conv = conversations.find((c) => c.id === conversationId)
      if (conv && selectedConversationIdRef.current !== conv.id) {
        handleSelectConversation(conv)
      }
    }
  }, [conversationId, conversations, handleSelectConversation])

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
                width: isSidebarCollapsed ? 0 : (globalThis.window?.innerWidth >= 1280 ? '20.75rem' : '19.5rem'),
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
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary border border-primary/10">
                      <History className="size-4" />
                    </div>
                    <h2 className="text-sm font-semibold text-foreground tracking-tight uppercase">历史记录</h2>
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
              </div>

              {/* 对话列表 */}
              <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar px-0 py-0.5">
                {(() => {
    if (isLoadingList) {
        return (<div className="flex items-center justify-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                    </div>);
    }
    else if (filteredConversations.length === 0) {
            return (<div className="rounded-3xl border border-dashed border-border/70 bg-background/70 px-5 py-10 text-center text-sm text-muted-foreground shadow-sm">
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
                return (<div key={group} className="pb-0.5 last:pb-0">
                          <div className="sticky top-0 z-10 px-0 pb-0 pt-0 bg-transparent">
                            <div className="flex items-center gap-2">
                              <div className={cn("h-px flex-1", groupTone.lineClass)} />
                              <div className={cn("inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] shadow-sm", groupTone.chipClass)}>
                                <span>{group}</span>
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
            }));
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
                            <h2 className="truncate text-base font-semibold text-foreground tracking-tight leading-tight md:text-lg">
                              {selectedConversation.title || t("untitledConversation")}
                            </h2>
                            <div className="flex items-center gap-1 mt-0.5 tabular-nums">
                              <span className="inline-flex items-center rounded-md bg-muted/30 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground/50 border border-border/10">
                                {t("messageCount", { count: selectedConversation.message_count })}
                              </span>
                              <span className="text-muted-foreground/20 text-[11px] leading-none px-0.5">•</span>
                              <span className="inline-flex items-center gap-1 rounded-md bg-muted/30 px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground/50 border border-border/10">
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
                            className="h-8 gap-1.5 rounded-lg text-[11px] font-semibold text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-all"
                          >
                            <BarChart3 className="size-3.5" />
                            分析评测
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setIsTraceOpen(true)}
                            aria-label="查看数据追踪"
                            className="h-8 gap-1.5 rounded-lg text-[11px] font-semibold text-muted-foreground hover:text-foreground hover:bg-muted/80 transition-all"
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
                            className="h-8 gap-1.5 rounded-lg px-3.5 text-[11px] font-semibold shadow-sm"
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
                          {hasMoreMessages ? (<div className="flex justify-center mb-4">
                              <Button variant="ghost" size="sm" onClick={loadOlderMessages} disabled={isLoadingOlder} className="rounded-full text-[11px] font-bold uppercase tracking-widest text-muted-foreground/60 hover:text-foreground">
                                {isLoadingOlder ? t('loading') : t('loadOlderMessages')}
                              </Button>
                            </div>) : null}
                          {groupedMessages.map((group) => (<div key={group.key} className="space-y-6">
                              <div className="flex items-center gap-6 py-1">
                                <div className="h-px flex-1 bg-border/30" />
                                <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-muted-foreground/20 whitespace-nowrap">
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
                    className="min-h-full rounded-3xl border border-border/70 bg-background/85 px-8 py-10 text-left shadow-soft"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Button asChild className="rounded-full">
                        <Link href="/">{t('startNewConversation')}</Link>
                      </Button>
                      <Button
                        asChild
                        variant="outline"
                        size="sm"
                        className="h-auto rounded-full border-warning/20 bg-warning/10 px-3 py-2 text-xs font-medium text-warning shadow-sm hover:bg-warning/15 hover:text-warning"
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
                        className="h-auto rounded-full border-info/20 bg-info/10 px-3 py-2 text-xs font-medium text-info shadow-sm hover:bg-info/15 hover:text-info"
                      >
                        <Link href="/observability">
                          <Route className="h-3.5 w-3.5" />
                          {t('ragTrace')}
                        </Link>
                      </Button>
                    </div>
                  </EmptyState>
                </div>
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
    <div className="relative group px-0 antialiased">
      <motion.button
        type="button"
        onClick={onSelect}
        whileHover={{ scale: 1.01, y: -0.5 }}
        whileTap={{ scale: 0.99 }}
        className={cn(
          'w-full flex flex-col gap-0.5 px-3 py-2 text-left transition-all duration-200 rounded-xl relative overflow-hidden border border-transparent focus-visible:outline-none focus-visible:ring-0',
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
            'flex-1 truncate text-[13.5px] font-medium leading-snug tracking-normal',
            isSelected ? 'text-primary' : 'text-foreground/90'
          )}>
            {conversation.title || t('untitledConversation')}
          </span>
          <span className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground/30 pt-1.5 tabular-nums group-hover:text-muted-foreground/50 transition-colors shrink-0">
            {formatRelativeTime(conversation.last_message_at || conversation.updated_at, locale, t('justNow'))}
          </span>
        </div>
        <div className="flex items-center gap-2 text-[11px] font-medium text-muted-foreground/40 tabular-nums">
          <span className="shrink-0">{t('messageCount', { count: conversation.message_count })}</span>
          <span className="text-muted-foreground/20">/</span>
          <p className="truncate flex-1 font-normal tracking-normal text-muted-foreground/50 lowercase">
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
          <IconButton
            label={t('deleteConversation')}
            variant="ghost"
            className="size-8 text-muted-foreground/30 hover:text-destructive hover:bg-destructive/10 active:bg-destructive/20 rounded-full transition-all"
            onClick={(e) => { e.stopPropagation(); onDelete() }}
          >
            <Trash2 className="size-4" />
          </IconButton>
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
        <ChatMessageItem message={message} variant="minimal" />
      </div>
    </motion.div>
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
  const lastWeek = new Date(today)
  lastWeek.setDate(lastWeek.getDate() - 7)
  const lastMonth = new Date(today)
  lastMonth.setDate(lastMonth.getDate() - 30)

  conversations.forEach((conv) => {
    const activityDate = conv.last_message_at || conv.created_at || conv.updated_at
    const date = new Date(activityDate)
    const convDate = new Date(date.getFullYear(), date.getMonth(), date.getDate())

    let group: string
    if (convDate.getTime() === today.getTime()) {
      group = labels.today
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

function buildConversationPreview(content: string | null | undefined, maxChars = 100) {
  const text = String(content || '').trim()
  if (!text) return ''
  return text.length > maxChars ? `${text.slice(0, maxChars)}...` : text
}
