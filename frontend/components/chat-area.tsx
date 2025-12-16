/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, StopCircle, Sparkles, Database } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChat } from '@/hooks/use-chat'
import { useDocuments } from '@/hooks/use-documents'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Message, Citation } from '@/types'

export function ChatArea() {
  const [inputValue, setInputValue] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

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

  const { uploadDocument, loadDocuments } = useDocuments()

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file)
      } catch (error) {
        console.error('Upload failed:', error)
      }
    }

    e.target.value = ''
  }

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
    <div className="flex-1 flex flex-col bg-slate-50/50 dark:bg-slate-950 h-screen relative transition-colors duration-300">
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto pt-24 px-4 pb-4 scroll-smooth">
        <div className="max-w-3xl mx-auto space-y-8">
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

          <div ref={messagesEndRef} className="h-4" />
        </div>
      </div>

      {/* 输入框区域 - 悬浮风格 */}
      <div className="px-4 pb-6 pt-2">
        <div className="max-w-3xl mx-auto relative group">
          <div className={cn(
            "relative bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl rounded-3xl shadow-sm border border-slate-200/60 dark:border-slate-800 transition-all duration-300",
            "focus-within:shadow-md focus-within:border-slate-300 dark:focus-within:border-slate-700 focus-within:ring-2 focus-within:ring-slate-100 dark:focus-within:ring-slate-800",
            "hover:border-slate-300 dark:hover:border-slate-700 hover:shadow-sm"
          )}>
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="问点什么... (Shift + Enter 换行)"
              className="w-full px-6 py-4 pr-24 resize-none outline-none rounded-3xl max-h-48 bg-transparent text-slate-700 dark:text-slate-200 placeholder:text-slate-400 font-medium"
              rows={1}
            />

            <div className="absolute right-2 bottom-2 flex items-center gap-2">
              {isLoading ? (
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={stopGeneration}
                  className="rounded-full hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500 transition-colors h-10 w-10 animate-pulse"
                >
                  <StopCircle className="h-5 w-5" />
                </Button>
              ) : (
                <Button
                  size="icon"
                  onClick={handleSend}
                  disabled={!inputValue.trim()}
                  className={cn(
                    "rounded-full h-10 w-10 transition-all duration-300 flex items-center justify-center",
                    inputValue.trim() 
                      ? "bg-slate-900 dark:bg-slate-100 hover:bg-slate-800 dark:hover:bg-slate-200 text-white dark:text-slate-900 shadow-md hover:shadow-lg transform hover:-translate-y-0.5" 
                      : "bg-slate-100 dark:bg-slate-800 text-slate-300 dark:text-slate-600"
                  )}
                >
                  <Send className="h-4 w-4 ml-0.5" />
                </Button>
              )}
            </div>
          </div>
          
          <p className="text-[10px] text-slate-400 dark:text-slate-500 text-center mt-3 font-medium tracking-wide opacity-0 group-hover:opacity-100 transition-opacity duration-500">
             POWERED BY MIMIRQ AI
          </p>
        </div>
      </div>
    </div>
  )
}

// 欢迎屏幕
function WelcomeScreen() {
  const hour = new Date().getHours()
  const greeting = hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好'

  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center animate-in fade-in slide-in-from-bottom-4 duration-700 select-none">
      <div className="relative group cursor-default mb-8">
        <div className="absolute -inset-4 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-full blur-xl opacity-20 group-hover:opacity-40 transition duration-1000 group-hover:duration-200"></div>
        <div className="relative p-6 bg-white dark:bg-slate-900 rounded-2xl shadow-sm ring-1 ring-slate-200/50 dark:ring-slate-800 flex items-center justify-center transform transition-transform duration-500 group-hover:scale-105">
          <Sparkles className="h-10 w-10 text-indigo-600 dark:text-indigo-400" />
        </div>
      </div>
      
      <h2 className="text-3xl font-bold text-slate-900 dark:text-white mb-4 tracking-tight">
        {greeting}，<span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-purple-600 dark:from-indigo-400 dark:to-purple-400">朋友</span>
      </h2>
      <p className="text-slate-500 dark:text-slate-400 max-w-md text-base leading-relaxed">
        我是您的智能知识助手。您可以随时向我提问，我会帮您分析、总结并回答相关问题。
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
        'flex gap-4 px-4 group animate-in fade-in slide-in-from-bottom-2 duration-500',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {/* AI 头像 */}
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-indigo-50 dark:bg-indigo-900/30 border border-indigo-100 dark:border-indigo-800 flex items-center justify-center shadow-sm mt-1">
          <Sparkles className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
        </div>
      )}

      {/* 消息内容 */}
      <div
        className={cn(
          'max-w-2xl px-6 py-4 shadow-sm relative text-[15px]',
          isUser
            ? 'bg-slate-900 dark:bg-indigo-600 text-white rounded-2xl rounded-tr-sm shadow-md'
            : 'bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 border border-slate-100 dark:border-slate-800 rounded-2xl rounded-tl-sm'
        )}
      >
        <div className={cn(
          "prose max-w-none break-words leading-relaxed dark:prose-invert",
          isUser ? "prose-invert" : "prose-slate",
          "prose-p:my-1.5 prose-p:leading-7",
          "prose-pre:bg-slate-900 dark:prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-800 dark:prose-pre:border-slate-800 prose-pre:text-slate-50 prose-pre:rounded-xl prose-pre:p-4 prose-pre:my-2",
          "prose-code:bg-slate-100 dark:prose-code:bg-slate-800 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-sm prose-code:font-mono prose-code:text-pink-600 dark:prose-code:text-pink-400 prose-code:before:content-none prose-code:after:content-none",
          isUser && "prose-code:bg-slate-800 prose-code:text-slate-200"
        )}>
          {isUser ? (
             <div className="whitespace-pre-wrap font-normal">
               {message.content}
             </div>
          ) : (
            <ReactMarkdown 
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({children}) => <p className="mb-2 last:mb-0">{children}</p>,
                ul: ({children}) => <ul className="list-disc pl-4 mb-2 space-y-1 marker:text-slate-400">{children}</ul>,
                ol: ({children}) => <ol className="list-decimal pl-4 mb-2 space-y-1 marker:text-slate-400">{children}</ol>,
                li: ({children}) => <li className="mb-0.5">{children}</li>,
                a: ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-600 dark:text-indigo-400 font-medium hover:underline decoration-indigo-300 underline-offset-2">{children}</a>,
                blockquote: ({children}) => <blockquote className="border-l-4 border-indigo-200 dark:border-indigo-800 pl-4 italic text-slate-500 dark:text-slate-400 my-2 bg-slate-50 dark:bg-slate-800/50 py-2 rounded-r-lg">{children}</blockquote>,
                code: ({node, className, children, ...props}) => {
                  const match = /language-(\w+)/.exec(className || '')
                  return match ? (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  ) : (
                    <code className={cn("bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded-md text-sm text-pink-500 dark:text-pink-400 font-mono", className)} {...props}>
                      {children}
                    </code>
                  )
                }
              }}
            >
              {message.content + (isStreaming ? '▍' : '')}
            </ReactMarkdown>
          )}
        </div>

        {/* 引用信息 */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800 space-y-2">
            <div className="flex items-center gap-2 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              <Database className="w-3 h-3" />
              参考来源
            </div>
            <div className="grid grid-cols-1 gap-2">
              {message.citations.map((citation, idx) => (
                <CitationCard key={idx} citation={citation} index={idx} />
              ))}
            </div>
          </div>
        )}
      </div>
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
    <div className="text-xs bg-slate-50 dark:bg-slate-800/50 hover:bg-white dark:hover:bg-slate-800 rounded-lg p-2.5 border border-slate-100 dark:border-slate-700 hover:border-indigo-200 dark:hover:border-indigo-700 transition-all cursor-pointer group shadow-sm hover:shadow-md">
      <div className="flex items-start gap-2.5">
        <span className="flex-shrink-0 w-4 h-4 bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-800 rounded flex items-center justify-center text-[10px] font-bold shadow-sm group-hover:bg-indigo-50 dark:group-hover:bg-indigo-900/50 group-hover:border-indigo-200 transition-colors">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-slate-700 dark:text-slate-300 truncate group-hover:text-indigo-700 dark:group-hover:text-indigo-400 transition-colors">
            {citation.document_name}
          </p>
          <p className="text-slate-500 dark:text-slate-400 mt-1 line-clamp-2 leading-relaxed group-hover:text-slate-600 dark:group-hover:text-slate-300">
            "{citation.chunk_content}"
          </p>
          <div className="flex items-center gap-2 mt-2">
            <span className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-400 dark:text-slate-500 px-1.5 py-0.5 rounded text-[10px] group-hover:border-indigo-100 dark:group-hover:border-indigo-800 group-hover:text-indigo-400 transition-colors">
              相似度 {Math.round(citation.relevance_score * 100)}%
            </span>
            {citation.page_number && (
              <span className="text-slate-300 dark:text-slate-600">P.{citation.page_number}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
