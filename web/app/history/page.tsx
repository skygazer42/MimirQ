/**
 * 问答历史页面
 */
'use client'

import { useState, useEffect, useRef, Suspense, useCallback, useDeferredValue, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  MessageSquare,
  Search,
  Trash2,
  Send,
  Loader2,
  BarChart3,
  History,
  X,
  Plus
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { ChatMessageItem } from '@/components/chat/message-item'
import { Button } from '@/components/ui/button'
import { chatApi } from '@/lib/api-client'
import { cn } from '@/lib/utils'
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
    <div className="flex h-screen overflow-hidden bg-white dark:bg-slate-950">
      <Navbar />
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    </div>
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
  const [searchQuery, setSearchQuery] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null)
  const [visibleCount, setVisibleCount] = useState(DEFAULT_VISIBLE_MESSAGES)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const deferredSearchQuery = useDeferredValue(searchQuery)

  // define handlers first to avoid ReferenceError
  const loadConversations = useCallback(async () => {
    try {
      setIsLoadingList(true)
      const result = await chatApi.listConversations({ limit: 100 })
      setConversations(result.items || [])
    } catch (error) {
      console.error('Failed to load conversations:', error)
    } finally {
      setIsLoadingList(false)
    }
  }, [])

  const handleSelectConversation = useCallback(async (conversation: Conversation) => {
    if (selectedConversation?.id === conversation.id && messages.length > 0) return

    setSelectedConversation(conversation)
    setMessages([])
    setIsLoadingMessages(true)

    // 更新 URL
    router.push(`/history?id=${conversation.id}`, { scroll: false })

    try {
      const result = await chatApi.getMessages(conversation.id)
      setMessages(result.messages || [])
    } catch (error) {
      console.error('Failed to load messages:', error)
      setMessages([])
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

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    setVisibleCount(DEFAULT_VISIBLE_MESSAGES)
  }, [selectedConversation?.id])

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
  const hiddenMessageCount = Math.max(0, messages.length - visibleCount)
  const visibleMessages = useMemo(
    () => messages.slice(-visibleCount),
    [messages, visibleCount]
  )

  return (
    <div className="flex h-screen overflow-hidden bg-white dark:bg-slate-950 transition-colors duration-300">
      <Navbar />

      <div className="flex-1 flex overflow-hidden">
        {/* 侧边栏 - 对话列表 */}
        <div className="w-80 border-r border-slate-200 dark:border-slate-800 flex flex-col bg-slate-50/50 dark:bg-slate-900/50">
          {/* 头部 */}
          <div className="p-4 border-b border-slate-200 dark:border-slate-800">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder="搜索对话..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
              />
            </div>
          </div>

          {/* 对话列表 */}
          <div className="flex-1 overflow-y-auto">
            {isLoadingList ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />
              </div>
            ) : filteredConversations.length === 0 ? (
              <div className="text-center py-12 px-4 text-slate-500 text-sm">
                <MessageSquare className="h-8 w-8 mx-auto mb-3 opacity-20" />
                <p>{searchQuery ? '没有找到匹配的对话' : '暂无对话记录'}</p>
              </div>
            ) : (
              groupOrder.map((group) => {
                const convs = groupedConversations[group]
                if (!convs || convs.length === 0) return null
                
                return (
                  <div key={group}>
                    <div className="px-4 py-2 text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider sticky top-0 bg-slate-50/90 dark:bg-slate-900/90 backdrop-blur-sm z-10">
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
        <div className="flex-1 flex flex-col bg-white dark:bg-slate-950">
          {selectedConversation ? (
            <>
              {/* 对话头部 */}
              <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between bg-white/80 dark:bg-slate-950/80 backdrop-blur-md sticky top-0 z-10">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center shadow-md shadow-indigo-200 dark:shadow-none">
                    <MessageSquare className="h-5 w-5 text-white" />
                  </div>
                  <div>
                    <h2 className="font-bold text-slate-900 dark:text-white tracking-tight">
                      {selectedConversation.title || '未命名对话'}
                    </h2>
                    <p className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest mt-0.5">
                      {selectedConversation.message_count} 条消息 · {formatDate(selectedConversation.created_at)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleEvaluateConversation}
                    className="gap-2 rounded-xl border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    <BarChart3 className="h-3.5 w-3.5" />
                    RAGAS 评测
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleContinueChat}
                    className="gap-2 rounded-xl bg-slate-900 dark:bg-indigo-600 hover:bg-slate-800 dark:hover:bg-indigo-700 text-white"
                  >
                    <Send className="h-3.5 w-3.5" />
                    继续对话
                  </Button>
                </div>
              </div>

              {/* 消息列表 */}
              <div className="flex-1 overflow-y-auto px-6 py-8">
                {isLoadingMessages ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
                  </div>
                ) : messages.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-slate-400">
                    <MessageSquare className="h-12 w-12 mb-4 opacity-10" />
                    <p>暂无消息记录</p>
                  </div>
                ) : (
                  <div className="max-w-3xl mx-auto space-y-10">
                    {hiddenMessageCount > 0 && (
                      <div className="flex justify-center">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setVisibleCount((count) => Math.min(messages.length, count + LOAD_MORE_STEP))
                          }
                          className="rounded-full text-xs"
                        >
                          显示更早消息（{hiddenMessageCount}）
                        </Button>
                      </div>
                    )}
                    {visibleMessages.map((message) => (
                      <ChatMessageItem key={message.id} message={message} />
                    ))}
                    <div ref={messagesEndRef} className="h-4" />
                  </div>
                )}
              </div>
            </>
          ) : (
            /* 空状态 */
            <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
              <div className="relative mb-8">
                <div className="absolute -inset-4 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-full blur-2xl opacity-10 animate-pulse"></div>
                <div className="relative p-6 bg-white dark:bg-slate-900 rounded-3xl shadow-xl ring-1 ring-slate-200 dark:ring-slate-800">
                  <History className="h-12 w-12 text-indigo-600 dark:text-indigo-400" />
                </div>
              </div>
              <h2 className="text-3xl font-bold text-slate-900 dark:text-white mb-4 tracking-tight">
                问答历史
              </h2>
              <p className="text-slate-500 dark:text-slate-400 max-w-md text-lg leading-relaxed">
                在这里您可以查看过去的对话记录，<br />点击左侧列表开始回顾。
              </p>
            </div>
          )}
        </div>
      </div>
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
      className={cn(
        'group px-4 py-4 cursor-pointer transition-all border-l-4 relative',
        isSelected 
          ? 'bg-indigo-50/50 dark:bg-indigo-900/20 border-l-indigo-600' 
          : 'border-l-transparent hover:bg-slate-100/50 dark:hover:bg-slate-800/50'
      )}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className={cn(
            'font-bold truncate text-[14px] tracking-tight',
            isSelected ? 'text-indigo-900 dark:text-indigo-300' : 'text-slate-700 dark:text-slate-300'
          )}>
            {conversation.title || '未命名对话'}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-1 leading-relaxed opacity-70">
            {conversation.last_message || '暂无消息'}
          </p>
          <div className="flex items-center gap-2 mt-2">
            <span className="text-[9px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
              {formatRelativeTime(conversation.updated_at)}
            </span>
          </div>
        </div>

        {/* 删除按钮 */}
        <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity flex items-center">
          {showDeleteConfirm ? (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <button
                onClick={onConfirmDelete}
                className="p-1.5 text-red-600 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={onCancelDelete}
                className="p-1.5 text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
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
