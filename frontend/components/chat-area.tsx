/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, StopCircle, Sparkles, Upload, Wand2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChat } from '@/hooks/use-chat'
import { useDocuments } from '@/hooks/use-documents'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Message, Citation } from '@/types'
import { ManualUploadDialog } from '@/components/manual-upload-dialog'

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
    <div className="flex-1 flex flex-col bg-gray-50/30 h-screen relative">
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
        <div className="max-w-3xl mx-auto relative">
          <div className={cn(
            "relative bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 transition-all duration-300",
            "focus-within:shadow-2xl focus-within:shadow-blue-100/50 focus-within:border-blue-200 focus-within:ring-4 focus-within:ring-blue-50/50"
          )}>
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="问点什么... (Shift + Enter 换行)"
              className="w-full px-6 py-4 pr-24 resize-none outline-none rounded-2xl max-h-48 bg-transparent text-gray-700 placeholder:text-gray-400"
              rows={1}
            />

            <div className="absolute right-2 bottom-2 flex items-center gap-2">
              {isLoading ? (
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={stopGeneration}
                  className="rounded-xl hover:bg-red-50 text-red-500 transition-colors h-10 w-10"
                >
                  <StopCircle className="h-5 w-5" />
                </Button>
              ) : (
                <Button
                  size="icon"
                  onClick={handleSend}
                  disabled={!inputValue.trim()}
                  className={cn(
                    "rounded-xl h-10 w-10 transition-all duration-300",
                    inputValue.trim() 
                      ? "bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-200" 
                      : "bg-gray-100 text-gray-400 hover:bg-gray-200"
                  )}
                >
                  <Send className="h-4 w-4 ml-0.5" />
                </Button>
              )}
            </div>
          </div>
          
          <p className="text-[10px] text-gray-300 text-center mt-3 font-medium tracking-wide">
             POWERED BY MIMIRQ AI
          </p>
        </div>
      </div>
      
      {/* 浮动上传入口 */}
      <FloatingUpload
        onClickUpload={() => fileInputRef.current?.click()}
        onManualUploaded={loadDocuments}
      />

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.txt,.md"
        className="hidden"
        onChange={handleFileUpload}
      />
    </div>
  )
}

// 欢迎屏幕
function WelcomeScreen() {
  const hour = new Date().getHours()
  const greeting = hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好'

  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[70vh] text-center animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="relative group cursor-default mb-6">
        <div className="absolute -inset-1 bg-gradient-to-r from-blue-600 to-violet-600 rounded-full blur opacity-25 group-hover:opacity-50 transition duration-1000 group-hover:duration-200"></div>
        <div className="relative p-6 bg-white rounded-3xl shadow-xl ring-1 ring-gray-900/5 leading-none flex items-center justify-center">
          <Sparkles className="h-12 w-12 text-blue-600" />
        </div>
      </div>
      
      <h2 className="text-3xl font-bold text-gray-900 mb-3 tracking-tight">
        {greeting}，有什么可以帮您？
      </h2>
      <p className="text-gray-500 max-w-xl text-lg font-light leading-relaxed">
        我是您的 AI 知识助手。上传文档，我会帮您分析、总结并回答相关问题。
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
        'flex gap-5 px-4 group animate-fade-in-up',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {/* AI 头像 */}
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-white border border-gray-200 flex items-center justify-center shadow-sm mt-1">
          <Sparkles className="h-4 w-4 text-blue-600" />
        </div>
      )}

      {/* 消息内容 */}
      <div
        className={cn(
          'max-w-2xl rounded-2xl px-6 py-4 shadow-sm relative',
          isUser
            ? 'bg-blue-600 text-white rounded-br-sm shadow-blue-200'
            : 'bg-white text-gray-800 border border-gray-100 rounded-bl-sm'
        )}
      >
        <div className={cn(
          "prose max-w-none break-words leading-relaxed",
          isUser ? "prose-invert prose-p:text-white" : "prose-slate",
          "prose-pre:bg-gray-800 prose-pre:text-gray-100 prose-pre:rounded-lg prose-pre:p-4",
          "prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-sm prose-code:font-mono prose-code:before:content-none prose-code:after:content-none",
          isUser && "prose-code:bg-blue-700/50 prose-code:text-white"
        )}>
          {isUser ? (
             <div className="whitespace-pre-wrap font-normal text-[15px]">
               {message.content}
             </div>
          ) : (
            <ReactMarkdown 
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({children}) => <p className="mb-2 last:mb-0">{children}</p>,
                ul: ({children}) => <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>,
                ol: ({children}) => <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>,
                li: ({children}) => <li className="mb-0.5">{children}</li>,
                a: ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">{children}</a>,
                blockquote: ({children}) => <blockquote className="border-l-4 border-gray-200 pl-4 italic text-gray-500 my-2">{children}</blockquote>,
                code: ({node, className, children, ...props}) => {
                  const match = /language-(\w+)/.exec(className || '')
                  return match ? (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  ) : (
                    <code className={cn("bg-gray-100 px-1.5 py-0.5 rounded text-sm text-red-500 font-mono", className)} {...props}>
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
          <div className="mt-4 pt-3 border-t border-gray-100 space-y-2.5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-400 uppercase tracking-wider">
              <span className="w-1 h-1 rounded-full bg-blue-500"></span>
              参考来源
            </div>
            {message.citations.map((citation, idx) => (
              <CitationCard key={idx} citation={citation} index={idx} />
            ))}
          </div>
        )}
      </div>
      
      {/* 用户头像 (可选，当前设计主要强调消息气泡) */}
      {isUser && (
        <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-xs font-medium text-gray-500 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
          You
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
    <div className="text-xs bg-gray-50/50 hover:bg-blue-50/50 rounded-lg p-3 border border-gray-100 hover:border-blue-100 transition-colors cursor-pointer group">
      <div className="flex items-start gap-2.5">
        <span className="flex-shrink-0 w-4 h-4 bg-white text-blue-600 border border-blue-100 rounded flex items-center justify-center text-[10px] font-bold shadow-sm">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-700 truncate group-hover:text-blue-700 transition-colors">
            {citation.document_name}
          </p>
          <p className="text-gray-500 mt-1 line-clamp-2 leading-relaxed">
            "{citation.chunk_content}"
          </p>
          <div className="flex items-center gap-2 mt-2">
            <span className="bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded text-[10px]">
              相似度 {(citation.relevance_score * 100).toFixed(0)}%
            </span>
            {citation.page_number && (
              <span className="text-gray-400">P.{citation.page_number}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function FloatingUpload({
  onClickUpload,
  onManualUploaded,
}: {
  onClickUpload: () => void
  onManualUploaded: () => void
}) {
  const [openManual, setOpenManual] = useState(false)

  return (
    <div className="fixed bottom-6 right-6 flex flex-col gap-3 z-40">
      <Button
        size="lg"
        className="shadow-lg bg-blue-600 hover:bg-blue-700 text-white gap-2"
        onClick={onClickUpload}
      >
        <Upload className="h-4 w-4" />
        上传文档
      </Button>

      <Button
        size="lg"
        variant="outline"
        className="shadow-lg gap-2"
        onClick={() => setOpenManual(true)}
      >
        <Wand2 className="h-4 w-4" />
        高级切片
      </Button>

      {openManual && (
        <ManualUploadDialog
          onUploaded={() => {
            onManualUploaded()
            setOpenManual(false)
          }}
        />
      )}
    </div>
  )
}
