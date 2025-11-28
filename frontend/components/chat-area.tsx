/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, StopCircle, Sparkles } from 'lucide-react'
import { useChat } from '@/hooks/use-chat'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Message, Citation } from '@/types'

export function ChatArea() {
  const [inputValue, setInputValue] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const {
    messages,
    isLoading,
    currentResponse,
    currentCitations,
    sendMessage,
    stopGeneration,
  } = useChat({
    onError: (error) => {
      console.error('Chat error:', error)
      alert(error)
    },
  })

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentResponse])

  // 自动调整输入框高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [inputValue])

  // 发送消息
  const handleSend = () => {
    if (!inputValue.trim() || isLoading) return

    sendMessage(inputValue)
    setInputValue('')
  }

  // 按键处理
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex-1 flex flex-col bg-white h-screen">
      {/* 头部 */}
      <div className="px-8 py-6 border-b border-gray-200 bg-white">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg">
            <Sparkles className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-gray-900">MimirQ</h1>
            <p className="text-sm text-gray-500">AI 知识库助手</p>
          </div>
        </div>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto px-8 py-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.length === 0 && !isLoading && (
            <WelcomeScreen />
          )}

          {messages.map((message) => (
            <MessageItem key={message.id} message={message} />
          ))}

          {/* 正在生成的消息 */}
          {isLoading && currentResponse && (
            <MessageItem
              message={{
                id: 'streaming',
                role: 'assistant',
                content: currentResponse,
                citations: currentCitations,
                created_at: new Date().toISOString(),
              }}
              isStreaming
            />
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* 输入框 */}
      <div className="px-8 py-6 border-t border-gray-200 bg-gray-50">
        <div className="max-w-3xl mx-auto">
          <div className="relative bg-white rounded-2xl border border-gray-200 shadow-sm focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入你的问题..."
              className="w-full px-6 py-4 pr-20 resize-none outline-none rounded-2xl max-h-40"
              rows={1}
            />

            <div className="absolute right-3 bottom-3 flex items-center gap-2">
              {isLoading ? (
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={stopGeneration}
                  className="rounded-xl"
                >
                  <StopCircle className="h-5 w-5 text-red-500" />
                </Button>
              ) : (
                <Button
                  size="icon"
                  onClick={handleSend}
                  disabled={!inputValue.trim()}
                  className="rounded-xl bg-blue-600 hover:bg-blue-700"
                >
                  <Send className="h-5 w-5" />
                </Button>
              )}
            </div>
          </div>

          <p className="text-xs text-gray-400 text-center mt-3">
            按 Enter 发送，Shift + Enter 换行
          </p>
        </div>
      </div>
    </div>
  )
}

// 欢迎屏幕
function WelcomeScreen() {
  return (
    <div className="flex flex-col items-center justify-center h-96 text-center">
      <div className="p-4 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl mb-6">
        <Sparkles className="h-12 w-12 text-white" />
      </div>
      <h2 className="text-2xl font-semibold text-gray-900 mb-2">
        欢迎使用 MimirQ
      </h2>
      <p className="text-gray-500 max-w-md">
        上传文档到左侧知识库，然后开始提问。AI 将基于你的文档内容为你解答。
      </p>
    </div>
  )
}

// 消息项组件
function MessageItem({
  message,
  isStreaming = false,
}: {
  message: Message
  isStreaming?: boolean
}) {
  const isUser = message.role === 'user'

  return (
    <div
      className={cn(
        'flex gap-4',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {/* 头像 */}
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
          <Sparkles className="h-4 w-4 text-white" />
        </div>
      )}

      {/* 消息内容 */}
      <div
        className={cn(
          'max-w-2xl rounded-2xl px-5 py-3',
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-gray-100 text-gray-900'
        )}
      >
        <div className="whitespace-pre-wrap break-words">
          {message.content}
          {isStreaming && <span className="typing-cursor" />}
        </div>

        {/* 引用信息 */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200 space-y-2">
            <p className="text-xs font-medium text-gray-500">参考资料：</p>
            {message.citations.map((citation, idx) => (
              <CitationCard key={idx} citation={citation} index={idx} />
            ))}
          </div>
        )}
      </div>

      {/* 用户头像 */}
      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-300 flex items-center justify-center text-sm font-medium text-gray-700">
          U
        </div>
      )}
    </div>
  )
}

// 引用卡片
function CitationCard({
  citation,
  index,
}: {
  citation: Citation
  index: number
}) {
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
          <p className="text-gray-600 mt-1 line-clamp-2">
            {citation.chunk_content}
          </p>
          <p className="text-gray-400 mt-1">
            相似度: {(citation.relevance_score * 100).toFixed(0)}%
          </p>
        </div>
      </div>
    </div>
  )
}
