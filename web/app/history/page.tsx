/**
 * 问答历史页面
 */
'use client'

import { useState, useEffect, useLayoutEffect, useRef, Suspense, useCallback, useDeferredValue, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
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
import { chatApi } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { toast } from 'sonner'
import type { Conversation, Message } from '@/types'

export default function HistoryPage() {
  return (
    <Suspense fallback={<HistoryPageLoading />}>
      <HistoryPageContent />
    </Suspense>
  )
}

const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40

function HistoryPageLoading() {
  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding>
      <PageLoading message="正在加载历史记录..." srMessage="Loading history" />
    </AppFrame>
  )
}

function HistoryPageContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const conversationId = searchParams.get('id')

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoadingList, setIsLoadingList] = useState(true)
  const [isLoadingMessages, setIsLoadingMessages] = useState(false)
  const [hasMoreMessages, setHasMoreMessages] = useState(false)
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
      toast.error(formatApiError(error, '加载对话列表失败'))
    } finally {
      setIsLoadingList(false)
    }
  }, [])

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
      window.requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'auto' })
      })
    } catch (error) {
      console.error('Failed to load messages:', error)
      toast.error(formatApiError(error, '加载对话消息失败'))
      setMessages([])
      setHasMoreMessages(false)
    } finally {
      setIsLoadingMessages(false)
    }
  }, [router, selectedConversation?.id, messages.length])

  // 加载对话列表
  useEffect(() => {
    loadConversations()
  }, [loadConversations])

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

  // 按日期分组
  const groupedConversations = useMemo(
    () => groupConversationsByDate(filteredConversations),
    [filteredConversations]
  )
  const groupOrder = ['今天', '昨天', '最近7天', '最近30天', '更早']
  const oldestMessageId = messages[0]?.id

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
      toast.error(formatApiError(error, '加载更早消息失败'))
    } finally {
      setIsLoadingOlder(false)
    }
  }, [selectedConversation, hasMoreMessages, isLoadingMessages, isLoadingOlder, oldestMessageId])

  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding mainClassName="overflow-hidden">
      <PageScaffold
        title="问答历史"
        description="查看与管理历史对话，并快速回到对话继续交流"
        icon={History}
        iconColor="text-sky-600 dark:text-sky-400"
        size="full"
        bodyClassName="px-0 pb-0 overflow-hidden"
        bodyContainerClassName="h-full"
        actions={
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => router.push('/', { scroll: false })}
          >
            <Plus className="h-4 w-4" />
            新建对话
          </Button>
        }
      >
        <div className="flex h-full min-h-0 overflow-hidden">
          {/* 侧边栏 - 对话列表 */}
          <div className="w-80 border-r border-border flex flex-col bg-card">
            {/* 头部 */}
            <div className="p-4 border-b border-border">
              <SearchInput
                value={searchQuery}
                onValueChange={setSearchQuery}
                placeholder="搜索对话..."
                inputClassName="rounded-xl bg-background/80 shadow-sm"
              />
            </div>

            {/* 对话列表 */}
            <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar">
              {isLoadingList ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground" />
                </div>
              ) : filteredConversations.length === 0 ? (
                <div className="text-center py-12 px-4 text-muted-foreground text-sm">
                  <MessageSquare className="h-8 w-8 mx-auto mb-3 opacity-20" />
                  <p>{searchQuery ? '没有找到匹配的对话' : '暂无对话记录'}</p>
                </div>
              ) : (
                groupOrder.map((group) => {
                  const convs = groupedConversations[group]
                  if (!convs || convs.length === 0) return null

                  return (
                    <div key={group}>
                      <div className="px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase sticky top-0 bg-card z-10 border-b border-border/60">
                        {group}
                      </div>
                      {convs.map((conversation) => (
                        <ConversationItem
                          key={conversation.id}
                          conversation={conversation}
                          isSelected={selectedConversation?.id === conversation.id}
                          onSelect={() => handleSelectConversation(conversation)}
                          onDelete={() => setShowDeleteConfirm(conversation.id)}
                          showDeleteConfirm={showDeleteConfirm === conversation.id}
                          onConfirmDelete={() => handleDeleteConversation(conversation.id)}
                          onCancelDelete={() => setShowDeleteConfirm(null)}
                        />
                      ))}
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* 主区域 - 对话详情 */}
          <div className="flex-1 flex flex-col bg-background">
            {selectedConversation ? (
              <>
                {/* 对话头部 */}
		                <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-background">
		                  <div className="flex items-center gap-4">
		                    <div className="size-10 rounded-xl bg-primary text-primary-foreground border border-primary/20 shadow-sm flex items-center justify-center">
		                      <MessageSquare className="h-5 w-5" />
		                    </div>
		                    <div>
		                      <h2 className="font-semibold text-foreground">
		                        {selectedConversation.title || '未命名对话'}
	                      </h2>
	                      <p className="text-[11px] font-medium text-muted-foreground mt-0.5 tabular-nums">
	                        {selectedConversation.message_count} 条消息 · {formatDate(selectedConversation.created_at)}
	                      </p>
	                    </div>
	                  </div>
                  <div className="flex items-center gap-3">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleEvaluateConversation}
                      className="gap-2 rounded-xl hover:bg-muted/50"
                    >
                      <BarChart3 className="h-3.5 w-3.5" />
                      RAGAS 评测
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setIsTraceOpen(true)}
                      className="gap-2 rounded-xl hover:bg-muted/50"
                    >
                      <Route className="h-3.5 w-3.5" />
                      RAG Trace
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleContinueChat}
                      className="gap-2 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground"
                    >
                      <Send className="h-3.5 w-3.5" />
                      继续对话
                    </Button>
                  </div>
                </div>

                {/* 消息列表 */}
                <div ref={messagesContainerRef} className="flex-1 overflow-y-auto overscroll-contain no-scrollbar px-6 py-8">
                  {isLoadingMessages ? (
                    <div className="flex items-center justify-center h-full">
                      <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none text-muted-foreground" />
                    </div>
                  ) : messages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                      <MessageSquare className="h-12 w-12 mb-4 opacity-10" />
                      <p>暂无消息记录</p>
                    </div>
                  ) : (
                    <div className="max-w-3xl mx-auto space-y-10">
                      {hasMoreMessages ? (
                        <div className="flex justify-center">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={loadOlderMessages}
                            disabled={isLoadingOlder}
                            className="rounded-full text-xs"
                          >
                            {isLoadingOlder ? '加载中…' : '加载更早消息'}
                          </Button>
                        </div>
                      ) : null}
                      {messages.map((message) => (
                        <ChatMessageItem key={message.id} message={message} />
                      ))}
                      <div ref={messagesEndRef} className="h-4" />
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex-1 p-6">
                <EmptyState
                  icon={History}
                  iconClassName="text-primary"
                  title="还没有选择对话"
                  description={
                    <>
                      在这里您可以查看过去的对话记录。<br />
                      点击左侧列表开始回顾，或新建一个对话继续交流。
                    </>
                  }
                  className="min-h-full border-0 bg-transparent shadow-none"
                />
              </div>
            )}
          </div>
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
}: {
  conversation: Conversation
  isSelected: boolean
  onSelect: () => void
  onDelete: () => void
  showDeleteConfirm: boolean
  onConfirmDelete: () => void
  onCancelDelete: () => void
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      className={cn(
        'group px-4 py-4 cursor-pointer transition-colors border-l-4 relative focus-ring',
        isSelected 
          ? 'bg-primary/10 border-l-primary' 
          : 'border-l-transparent hover:bg-muted/30'
      )}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
	          <h3 className={cn(
	            'font-semibold truncate text-[14px]',
	            isSelected ? 'text-primary' : 'text-foreground'
	          )}>
	            {conversation.title || '未命名对话'}
	          </h3>
          <p className="text-xs text-muted-foreground truncate mt-1 leading-relaxed opacity-70">
            {conversation.last_message || '暂无消息'}
          </p>
	          <div className="flex items-center gap-2 mt-2">
	            <span className="text-[10px] font-medium text-muted-foreground tabular-nums bg-muted/60 px-1.5 py-0.5 rounded">
	              {formatRelativeTime(conversation.updated_at)}
	            </span>
	          </div>
        </div>

        {/* 删除按钮 */}
        <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity flex items-center">
          {showDeleteConfirm ? (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <IconButton
                label="确认删除对话"
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={onConfirmDelete}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </IconButton>
              <IconButton
                label="取消删除"
                className="text-muted-foreground hover:bg-muted"
                onClick={onCancelDelete}
              >
                <X className="h-3.5 w-3.5" />
              </IconButton>
            </div>
          ) : (
            <IconButton
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              label="删除对话"
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

// 辅助函数：按日期分组
function groupConversationsByDate(conversations: Conversation[]) {
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
      group = '今天'
    } else if (convDate.getTime() === yesterday.getTime()) {
      group = '昨天'
    } else if (convDate.getTime() >= lastWeek.getTime()) {
      group = '最近7天'
    } else if (convDate.getTime() >= lastMonth.getTime()) {
      group = '最近30天'
    } else {
      group = '更早'
    }

    if (!groups[group]) {
      groups[group] = []
    }
    groups[group].push(conv)
  })

  return groups
}

// 辅助函数：格式化相对时间
function formatRelativeTime(dateString: string) {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / (1000 * 60))
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffMins < 1) return '刚刚'
  if (diffMins < 60) return `${diffMins} 分钟前`
  if (diffHours < 24) return `${diffHours} 小时前`
  if (diffDays < 7) return `${diffDays} 天前`

  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
  })
}

// 辅助函数：格式化日期
function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
