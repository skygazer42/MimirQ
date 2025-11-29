/**
 * 问答历史页面 - GPT风格设计
 */
'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  MessageSquare,
  Plus,
  Search,
  Trash2,
  MoreHorizontal,
  Send,
  StopCircle,
  Sparkles,
  Loader2,
  ChevronLeft,
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { chatApi } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import type { Conversation, Message, Citation } from '@/types'

export default function HistoryPage() {
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

  const messagesEndRef = useRef<HTMLDivElement>(null)

  // 加载对话列表
  useEffect(() => {
    loadConversations()
  }, [])

  // 当 URL 中有 id 参数时，自动选中对话
  useEffect(() => {
    if (conversationId && conversations.length > 0) {
      const conv = conversations.find((c) => c.id === conversationId)
      if (conv) {
        handleSelectConversation(conv)
      }
    }
  }, [conversationId, conversations])

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const loadConversations = async () => {
    try {
      setIsLoadingList(true)
      const result = await chatApi.listConversations({ limit: 100 })
      setConversations(result.items)
    } catch (error) {
      console.error('Failed to load conversations:', error)
    } finally {
      setIsLoadingList(false)
    }
  }

  const handleSelectConversation = async (conversation: Conversation) => {
    setSelectedConversation(conversation)
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
  }

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

  const handleNewChat = () => {
    router.push('/')
  }

  const handleContinueChat = () => {
    if (selectedConversation) {
      router.push(`/?conversation=${selectedConversation.id}`)
    }
  }

  // 过滤对话
  const filteredConversations = conversations.filter(
    (c) =>
      c.title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.last_message?.toLowerCase().includes(searchQuery.toLowerCase())
  )

  // 按日期分组
  const groupedConversations = groupConversationsByDate(filteredConversations)

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar />

      {/* 侧边栏 - 对话列表 */}
      <div className="w-80 border-r border-gray-200 flex flex-col bg-gray-50">
        {/* 头部 */}
        <div className="p-4 border-b border-gray-200">
          <Button
            onClick={handleNewChat}
            className="w-full justify-start gap-2 bg-white border border-gray-200 text-gray-700 hover:bg-gray-100"
            variant="outline"
          >
            <Plus className="h-4 w-4" />
            新建对话
          </Button>

          {/* 搜索框 */}
          <div className="mt-3 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="搜索对话..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
        </div>

        {/* 对话列表 */}
        <div className="flex-1 overflow-y-auto">
          {isLoadingList ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          ) : filteredConversations.length === 0 ? (
            <div className="text-center py-8 text-gray-500 text-sm">
              {searchQuery ? '没有找到匹配的对话' : '暂无对话记录'}
            </div>
          ) : (
            Object.entries(groupedConversations).map(([group, convs]) => (
              <div key={group}>
                <div className="px-4 py-2 text-xs font-medium text-gray-500 bg-gray-100 sticky top-0">
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
            ))
          )}
        </div>
      </div>

      {/* 主区域 - 对话详情 */}
      <div className="flex-1 flex flex-col">
        {selectedConversation ? (
          <>
            {/* 对话头部 */}
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg">
                  <MessageSquare className="h-4 w-4 text-white" />
                </div>
                <div>
                  <h2 className="font-semibold text-gray-900">
                    {selectedConversation.title || '未命名对话'}
                  </h2>
                  <p className="text-xs text-gray-500">
                    {selectedConversation.message_count} 条消息 · {formatDate(selectedConversation.created_at)}
                  </p>
                </div>
              </div>
              <Button
                onClick={handleContinueChat}
                className="gap-2"
              >
                <Send className="h-4 w-4" />
                继续对话
              </Button>
            </div>

            {/* 消息列表 */}
            <div className="flex-1 overflow-y-auto px-6 py-4">
              {isLoadingMessages ? (
                <div className="flex items-center justify-center h-full">
                  <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
                </div>
              ) : messages.length === 0 ? (
                <div className="flex items-center justify-center h-full text-gray-500">
                  暂无消息记录
                </div>
              ) : (
                <div className="max-w-3xl mx-auto space-y-6">
                  {messages.map((message) => (
                    <MessageItem key={message.id} message={message} />
                  ))}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>
          </>
        ) : (
          /* 空状态 */
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <div className="p-4 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl mb-6">
              <MessageSquare className="h-12 w-12 text-white" />
            </div>
            <h2 className="text-2xl font-semibold text-gray-900 mb-2">
              问答历史
            </h2>
            <p className="text-gray-500 max-w-md mb-6">
              选择左侧的对话记录查看详情，或者开始一个新的对话
            </p>
            <Button onClick={handleNewChat} className="gap-2">
              <Plus className="h-4 w-4" />
              开始新对话
            </Button>
          </div>
        )}
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
        'group px-4 py-3 cursor-pointer border-b border-gray-100 transition-colors',
        isSelected ? 'bg-blue-50 border-l-2 border-l-blue-500' : 'hover:bg-gray-100'
      )}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <h3 className={cn(
            'font-medium truncate',
            isSelected ? 'text-blue-900' : 'text-gray-900'
          )}>
            {conversation.title || '未命名对话'}
          </h3>
          <p className="text-sm text-gray-500 truncate mt-0.5">
            {conversation.last_message || '暂无消息'}
          </p>
          <p className="text-xs text-gray-400 mt-1">
            {formatRelativeTime(conversation.updated_at)}
          </p>
        </div>

        {/* 删除按钮 */}
        <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
          {showDeleteConfirm ? (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <button
                onClick={onConfirmDelete}
                className="p-1 text-red-600 hover:bg-red-100 rounded"
              >
                <Trash2 className="h-4 w-4" />
              </button>
              <button
                onClick={onCancelDelete}
                className="p-1 text-gray-500 hover:bg-gray-200 rounded text-xs"
              >
                取消
              </button>
            </div>
          ) : (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              className="p-1 text-gray-400 hover:text-red-500 hover:bg-gray-200 rounded"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// 消息项
function MessageItem({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex gap-4', isUser ? 'justify-end' : 'justify-start')}>
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
          <Sparkles className="h-4 w-4 text-white" />
        </div>
      )}

      <div
        className={cn(
          'max-w-2xl rounded-2xl px-5 py-3',
          isUser ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-900'
        )}
      >
        <div className="whitespace-pre-wrap break-words">{message.content}</div>

        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200 space-y-2">
            <p className="text-xs font-medium text-gray-500">参考资料：</p>
            {message.citations.map((citation, idx) => (
              <CitationCard key={idx} citation={citation} index={idx} />
            ))}
          </div>
        )}
      </div>

      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-300 flex items-center justify-center text-sm font-medium text-gray-700">
          U
        </div>
      )}
    </div>
  )
}

// 引用卡片
function CitationCard({ citation, index }: { citation: Citation; index: number }) {
  return (
    <div className="text-xs bg-white rounded-lg p-2 border border-gray-200">
      <div className="flex items-start gap-2">
        <span className="flex-shrink-0 w-5 h-5 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-xs font-medium">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <p className="font-medium text-gray-900 truncate">
            {citation.document_name}
            {citation.page_number && ` · 第 ${citation.page_number} 页`}
          </p>
          <p className="text-gray-600 mt-1 line-clamp-2">{citation.chunk_content}</p>
        </div>
      </div>
    </div>
  )
}

// 辅助函数：按日期分组
function groupConversationsByDate(conversations: Conversation[]) {
  const groups: Record<string, Conversation[]> = {}
  const now = new Date()

  conversations.forEach((conv) => {
    const date = new Date(conv.updated_at)
    const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24))

    let group: string
    if (diffDays === 0) {
      group = '今天'
    } else if (diffDays === 1) {
      group = '昨天'
    } else if (diffDays < 7) {
      group = '最近7天'
    } else if (diffDays < 30) {
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
