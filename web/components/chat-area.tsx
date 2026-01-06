/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { Send, StopCircle, Sparkles, Database, Wand2 } from 'lucide-react'
import { toast } from 'sonner'
import { useChat } from '@/hooks/use-chat'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { promptTemplateApi, PromptTemplate } from '@/lib/api-client'
import { ChatMessageItem } from '@/components/chat/message-item'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'

export function ChatArea({
  initialConversationId,
  initialPrompt,
  onConversationId,
}: {
  initialConversationId?: string
  initialPrompt?: string
  onConversationId?: (conversationId: string) => void
} = {}) {
  const [inputValue, setInputValue] = useState(() => (initialPrompt || '').trim())
  const [promptTemplateId, setPromptTemplateId] = useState<string>('')
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([])
  const [showRagSettings, setShowRagSettings] = useState(false)
  const [ragConfig, setRagConfig] = useState<{
    top_k: number
    score_threshold: number
    retrieval_mode: string
    use_graph: boolean
  }>(() => ({
    top_k: 5,
    score_threshold: 0.7,
    retrieval_mode: 'hybrid',
    use_graph: false,
  }))
  const [structuredOutput, setStructuredOutput] = useState(false)
  const [structuredPreset, setStructuredPreset] = useState<string>('')
  const [enableLongTermMemory, setEnableLongTermMemory] = useState(false)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const prevInitialConversationIdRef = useRef<string | undefined>(initialConversationId)
  const autoScrollRef = useRef(true)
  const scrollRafRef = useRef<number | null>(null)
  const ragSettingsId = 'rag-settings-panel'

  // Load prompt templates
  useEffect(() => {
    const loadTemplates = async () => {
      try {
        const response = await promptTemplateApi.list({ is_active: true, limit: 50 })
        setPromptTemplates(response.items)
      } catch (error) {
        console.error('Failed to load prompt templates:', error)
      }
    }
    loadTemplates()
  }, [])

  const {
    messages,
    isLoading,
    currentResponse,
    currentCitations,
    sendMessage,
    stopGeneration,
    conversationId,
    loadConversation,
    resetConversation,
  } = useChat({
    conversationId: initialConversationId,
    promptTemplateId: promptTemplateId || undefined,
    ragConfig,
    structuredOutput,
    structuredPreset: structuredPreset || undefined,
    enableLongTermMemory,
    onConversationId,
    onError: (error) => {
      console.error('Chat error:', error)
      toast.error(error || '聊天请求失败')
    },
  })

  // Sync URL conversation -> local state (History -> Chat)
  useEffect(() => {
    const prev = (prevInitialConversationIdRef.current || '').trim()
    const desired = (initialConversationId || '').trim()
    prevInitialConversationIdRef.current = initialConversationId

    const current = (conversationId || '').trim()
    if (desired) {
      if (desired !== current) {
        loadConversation(desired).catch((err) => {
          console.error('Failed to load conversation:', err)
        })
      }
      return
    }
    // URL cleared: only reset when we were previously bound to a conversation id.
    if (prev && current) {
      resetConversation()
    }
  }, [initialConversationId, conversationId, loadConversation, resetConversation])

  const updateAutoScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    autoScrollRef.current = distanceToBottom < 160
  }, [])

  const scheduleScrollToBottom = useCallback((behavior: ScrollBehavior) => {
    if (!autoScrollRef.current) return
    if (scrollRafRef.current != null) return
    scrollRafRef.current = window.requestAnimationFrame(() => {
      scrollRafRef.current = null
      messagesEndRef.current?.scrollIntoView({ behavior })
    })
  }, [])

  // 自动滚动：仅在用户停留在底部附近时触发，并做 rAF 节流，避免流式输出时抖动/卡顿。
  useEffect(() => {
    scheduleScrollToBottom('smooth')
  }, [messages.length, scheduleScrollToBottom])

  useEffect(() => {
    scheduleScrollToBottom('auto')
  }, [currentResponse, scheduleScrollToBottom])

  useEffect(() => {
    updateAutoScroll()
    return () => {
      if (scrollRafRef.current != null) {
        window.cancelAnimationFrame(scrollRafRef.current)
        scrollRafRef.current = null
      }
    }
  }, [updateAutoScroll])

  // 自动调整输入框高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [inputValue])

  // Support deep-linking with prefilled prompt (?prompt=...)
  useEffect(() => {
    const p = (initialPrompt || '').trim()
    if (!p) return
    setInputValue((prev) => (prev.trim() ? prev : p))
  }, [initialPrompt])

  const selectedPromptTemplate = useMemo(
    () => promptTemplates.find((template) => template.id === promptTemplateId),
    [promptTemplates, promptTemplateId]
  )

  // 发送消息
  const handleSend = useCallback(() => {
    if (!inputValue.trim() || isLoading) return

    sendMessage(inputValue)
    setInputValue('')
  }, [inputValue, isLoading, sendMessage])

  // 按键处理
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return (
    <div className="flex-1 flex flex-col bg-slate-50/50 dark:bg-slate-950 h-screen relative transition-colors duration-300">
      {/* 消息列表 */}
      <div
        ref={scrollContainerRef}
        onScroll={updateAutoScroll}
        className="flex-1 overflow-y-auto pt-24 px-4 pb-4 scroll-smooth"
        role="log"
        aria-live="polite"
        aria-busy={isLoading}
      >
        <div className="max-w-3xl mx-auto space-y-8">
          {messages.length === 0 && !isLoading && (
            <WelcomeScreen />
          )}

          {messages.map((message) => (
            <ChatMessageItem key={message.id} message={message} />
          ))}

          {/* 正在生成的消息 */}
          {isLoading && currentResponse && (
            <ChatMessageItem
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
        <div className="max-w-3xl mx-auto space-y-3">
          {/* 提示词模板选择器 */}
          {promptTemplates.length > 0 && (
            <div className="flex items-center gap-2 px-2">
              <Wand2 className="w-4 h-4 text-slate-400" />
              <Select
                value={promptTemplateId || SELECT_DEFAULT_VALUE}
                onValueChange={(v) => setPromptTemplateId(v === SELECT_DEFAULT_VALUE ? '' : v)}
              >
                <SelectTrigger className="w-[240px] h-8 text-sm">
                  <SelectValue placeholder="选择提示词模板" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={SELECT_DEFAULT_VALUE}>默认模板</SelectItem>
                  {promptTemplates.map((template) => (
                    <SelectItem key={template.id} value={template.id}>
                      {template.name}
                      {template.category && (
                        <span className="text-xs text-muted-foreground ml-2">
                          ({template.category})
                        </span>
                      )}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {promptTemplateId && (
                <span className="text-xs text-slate-500">
                  {selectedPromptTemplate?.description}
                </span>
              )}
            </div>
          )}

          {/* RAG 参数（联调用：让前端能直接控制后端 rag_config） */}
          <div className="px-2">
            <Button
              type="button"
              variant="ghost"
              className="h-8 px-2 text-xs text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
              onClick={() => setShowRagSettings((v) => !v)}
              aria-expanded={showRagSettings}
              aria-controls={ragSettingsId}
            >
              <Database className="w-4 h-4 mr-2" />
              RAG 设置
            </Button>
          </div>

          {showRagSettings && (
            <div
              id={ragSettingsId}
              className="px-2 flex flex-wrap items-center gap-3 text-xs text-slate-600 dark:text-slate-300"
            >
              <div className="flex items-center gap-2">
                <span className="text-slate-400">检索</span>
                <Select
                  value={ragConfig.retrieval_mode}
                  onValueChange={(v) => setRagConfig((prev) => ({ ...prev, retrieval_mode: v }))}
                >
                  <SelectTrigger className="w-[140px] h-8 text-xs">
                    <SelectValue placeholder="选择模式" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">auto（自动）</SelectItem>
                    <SelectItem value="hybrid">hybrid（混合）</SelectItem>
                    <SelectItem value="vector">vector（向量）</SelectItem>
                    <SelectItem value="keyword">keyword（全文）</SelectItem>
                    <SelectItem value="mmr">mmr（多样性）</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <label className="flex items-center gap-2">
                <span className="text-slate-400">TopK</span>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={ragConfig.top_k}
                  onChange={(e) => setRagConfig((prev) => ({ ...prev, top_k: Number(e.target.value || 0) }))}
                  className="w-16 h-8 px-2 rounded-md border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/70"
                />
              </label>

              <label className="flex items-center gap-2">
                <span className="text-slate-400">阈值</span>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={ragConfig.score_threshold}
                  onChange={(e) => setRagConfig((prev) => ({ ...prev, score_threshold: Number(e.target.value || 0) }))}
                  className="w-20 h-8 px-2 rounded-md border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-900/70"
                />
              </label>

              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={ragConfig.use_graph}
                  onChange={(e) => setRagConfig((prev) => ({ ...prev, use_graph: e.target.checked }))}
                />
                <span>LangGraph</span>
              </label>

              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={structuredOutput}
                  onChange={(e) => setStructuredOutput(e.target.checked)}
                />
                <span>结构化</span>
              </label>

                {structuredOutput && (
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400">Preset</span>
                    <Select
                      value={structuredPreset || SELECT_DEFAULT_VALUE}
                      onValueChange={(v) => setStructuredPreset(v === SELECT_DEFAULT_VALUE ? '' : v)}
                    >
                      <SelectTrigger className="w-[160px] h-8 text-xs">
                        <SelectValue placeholder="选择 preset" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={SELECT_DEFAULT_VALUE}>custom（默认）</SelectItem>
                        <SelectItem value="faq">faq</SelectItem>
                        <SelectItem value="summary">summary</SelectItem>
                        <SelectItem value="action_items">action_items</SelectItem>
                      </SelectContent>
                  </Select>
                </div>
              )}

              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={enableLongTermMemory}
                  onChange={(e) => setEnableLongTermMemory(e.target.checked)}
                />
                <span>长记忆</span>
              </label>
            </div>
          )}

          {/* 输入框 */}
          <div className="relative group">
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
              autoFocus
              aria-label="聊天输入框"
              enterKeyHint="send"
              className="w-full px-6 py-4 pr-24 resize-none outline-none rounded-3xl max-h-48 bg-transparent text-slate-700 dark:text-slate-200 placeholder:text-slate-400 font-medium"
              rows={1}
            />

            <div className="absolute right-2 bottom-2 flex items-center gap-2">
              {isLoading ? (
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={stopGeneration}
                  title="停止生成"
                  aria-label="停止生成"
                  className="rounded-full hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500 transition-colors h-10 w-10 animate-pulse"
                >
                  <StopCircle className="h-5 w-5" />
                </Button>
              ) : (
                <Button
                  size="icon"
                  onClick={handleSend}
                  disabled={!inputValue.trim()}
                  title="发送消息"
                  aria-label="发送消息"
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

          <p className="text-[10px] text-slate-400 dark:text-slate-500 text-center font-medium tracking-wide opacity-0 group-hover:opacity-100 transition-opacity duration-500">
             POWERED BY MIMIRQ AI
          </p>
          </div>
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
