/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { Send, StopCircle, Sparkles, Database, Wand2, Settings2, Bot } from 'lucide-react'
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
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'
const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40

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
  const [visibleCount, setVisibleCount] = useState(DEFAULT_VISIBLE_MESSAGES)
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

  useEffect(() => {
    setVisibleCount(DEFAULT_VISIBLE_MESSAGES)
  }, [conversationId])

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

  // 自动滚动
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
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [inputValue])

  // Support deep-linking
  useEffect(() => {
    const p = (initialPrompt || '').trim()
    if (!p) return
    setInputValue((prev) => (prev.trim() ? prev : p))
  }, [initialPrompt])

  const selectedPromptTemplate = useMemo(
    () => promptTemplates.find((template) => template.id === promptTemplateId),
    [promptTemplates, promptTemplateId]
  )

  const hiddenCount = Math.max(0, messages.length - visibleCount)
  const visibleMessages = useMemo(
    () => messages.slice(-visibleCount),
    [messages, visibleCount]
  )

  const handleSend = useCallback(() => {
    if (!inputValue.trim() || isLoading) return
    sendMessage(inputValue)
    setInputValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [inputValue, isLoading, sendMessage])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return (
    <div className="flex-1 flex flex-col bg-background h-screen relative transition-colors duration-300">
      {/* 消息列表区域 */}
      <div
        ref={scrollContainerRef}
        onScroll={updateAutoScroll}
        className="flex-1 overflow-y-auto px-4 pb-4 scroll-smooth scrollbar-thin scrollbar-thumb-secondary/50 scrollbar-track-transparent"
        role="log"
        aria-live="polite"
        aria-busy={isLoading}
      >
        <div className="max-w-4xl mx-auto flex flex-col min-h-full py-10">
          {messages.length === 0 && !isLoading && (
            <div className="flex-1 flex items-center justify-center">
              <WelcomeScreen />
            </div>
          )}

          {hiddenCount > 0 && (
            <div className="flex justify-center py-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setVisibleCount((count) => Math.min(messages.length, count + LOAD_MORE_STEP))}
                className="rounded-full text-xs text-muted-foreground hover:bg-secondary"
              >
                显示更早消息（{hiddenCount}）
              </Button>
            </div>
          )}

          <div className="space-y-6">
            {visibleMessages.map((message) => (
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
          </div>

          <div ref={messagesEndRef} className="h-4" />
        </div>
      </div>

      {/* 底部输入区域 */}
      <div className="px-4 pb-6 pt-2 z-10">
        <div className="max-w-3xl mx-auto space-y-4">
          
          {/* 工具栏 (Settings & Templates) */}
          <div className="flex items-center justify-between px-2 animate-fade-in opacity-0 hover:opacity-100 focus-within:opacity-100 transition-opacity duration-300">
            <div className="flex items-center gap-2">
                {promptTemplates.length > 0 && (
                    <Popover>
                        <PopoverTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-8 gap-2 text-muted-foreground hover:text-primary rounded-full hover:bg-secondary/80">
                                <Wand2 className="w-3.5 h-3.5" />
                                <span className="text-xs">{selectedPromptTemplate?.name || '默认模板'}</span>
                            </Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-64 p-2" align="start">
                             <div className="text-xs font-medium text-muted-foreground mb-2 px-2">选择 Prompt 模板</div>
                             <div className="max-h-60 overflow-y-auto space-y-1">
                                <div 
                                    className={cn("px-2 py-1.5 rounded-md cursor-pointer text-sm hover:bg-secondary transition-colors", !promptTemplateId && "bg-secondary/50 font-medium text-primary")}
                                    onClick={() => setPromptTemplateId('')}
                                >
                                    默认模板
                                </div>
                                {promptTemplates.map(t => (
                                    <div 
                                        key={t.id}
                                        className={cn("px-2 py-1.5 rounded-md cursor-pointer text-sm hover:bg-secondary transition-colors flex flex-col gap-0.5", promptTemplateId === t.id && "bg-secondary/50 font-medium text-primary")}
                                        onClick={() => setPromptTemplateId(t.id)}
                                    >
                                        <span>{t.name}</span>
                                        {t.description && <span className="text-[10px] text-muted-foreground/70 truncate">{t.description}</span>}
                                    </div>
                                ))}
                             </div>
                        </PopoverContent>
                    </Popover>
                )}
            </div>

            <Popover open={showRagSettings} onOpenChange={setShowRagSettings}>
                <PopoverTrigger asChild>
                    <Button variant="ghost" size="sm" className={cn("h-8 gap-1.5 rounded-full transition-colors", (ragConfig.retrieval_mode !== 'auto' || ragConfig.use_graph) ? "text-primary bg-primary/10 hover:bg-primary/20" : "text-muted-foreground hover:bg-secondary/80")}>
                        <Settings2 className="w-3.5 h-3.5" />
                        <span className="text-xs">RAG 配置</span>
                    </Button>
                </PopoverTrigger>
                <PopoverContent className="w-80 p-4" align="end" sideOffset={10}>
                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            <h4 className="font-medium text-sm">检索设置</h4>
                            <span className="text-[10px] text-muted-foreground">Adjust retrieval parameters</span>
                        </div>
                        
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-1.5">
                                <label className="text-xs text-muted-foreground">检索模式</label>
                                <Select
                                    value={ragConfig.retrieval_mode}
                                    onValueChange={(v) => setRagConfig((prev) => ({ ...prev, retrieval_mode: v }))}
                                >
                                    <SelectTrigger className="h-8 text-xs">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="auto">Auto (自动)</SelectItem>
                                        <SelectItem value="hybrid">Hybrid (混合)</SelectItem>
                                        <SelectItem value="vector">Vector (向量)</SelectItem>
                                        <SelectItem value="keyword">Keyword (关键词)</SelectItem>
                                        <SelectItem value="mmr">MMR (多样性)</SelectItem>
                                    </SelectContent>
                                </Select>
                            </div>
                             <div className="space-y-1.5">
                                <label className="text-xs text-muted-foreground">Top K</label>
                                <input
                                    type="number"
                                    min={1}
                                    max={20}
                                    value={ragConfig.top_k}
                                    onChange={(e) => setRagConfig((prev) => ({ ...prev, top_k: Number(e.target.value) }))}
                                    className="flex h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                                />
                            </div>
                        </div>

                        <div className="space-y-3 pt-2 border-t">
                            <label className="flex items-center justify-between text-sm cursor-pointer hover:bg-secondary/50 p-1 rounded-md transition-colors">
                                <span className="text-muted-foreground text-xs">使用知识图谱 (LangGraph)</span>
                                <input
                                    type="checkbox"
                                    checked={ragConfig.use_graph}
                                    onChange={(e) => setRagConfig((prev) => ({ ...prev, use_graph: e.target.checked }))}
                                    className="accent-primary h-4 w-4"
                                />
                            </label>
                            <label className="flex items-center justify-between text-sm cursor-pointer hover:bg-secondary/50 p-1 rounded-md transition-colors">
                                <span className="text-muted-foreground text-xs">启用长短期记忆</span>
                                <input
                                    type="checkbox"
                                    checked={enableLongTermMemory}
                                    onChange={(e) => setEnableLongTermMemory(e.target.checked)}
                                    className="accent-primary h-4 w-4"
                                />
                            </label>
                            <label className="flex items-center justify-between text-sm cursor-pointer hover:bg-secondary/50 p-1 rounded-md transition-colors">
                                <span className="text-muted-foreground text-xs">结构化输出</span>
                                <input
                                    type="checkbox"
                                    checked={structuredOutput}
                                    onChange={(e) => setStructuredOutput(e.target.checked)}
                                    className="accent-primary h-4 w-4"
                                />
                            </label>
                             {structuredOutput && (
                                <div className="pl-4 pt-1">
                                    <Select
                                        value={structuredPreset || SELECT_DEFAULT_VALUE}
                                        onValueChange={(v) => setStructuredPreset(v === SELECT_DEFAULT_VALUE ? '' : v)}
                                    >
                                        <SelectTrigger className="h-7 text-xs w-full">
                                            <SelectValue placeholder="选择 Preset" />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value={SELECT_DEFAULT_VALUE}>Custom (默认)</SelectItem>
                                            <SelectItem value="faq">FAQ</SelectItem>
                                            <SelectItem value="summary">Summary</SelectItem>
                                            <SelectItem value="action_items">Action Items</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                            )}
                        </div>
                    </div>
                </PopoverContent>
            </Popover>
          </div>

          {/* 输入框本体 */}
          <div className={cn(
            "relative group rounded-3xl bg-background border transition-all duration-300",
            "shadow-[0_2px_15px_-3px_rgba(0,0,0,0.07),0_10px_20px_-2px_rgba(0,0,0,0.04)] dark:shadow-none",
            "focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary/50",
            "hover:border-primary/30"
          )}>
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="问点什么... (Shift + Enter 换行)"
              autoFocus
              className="w-full px-5 py-4 pr-16 resize-none outline-none rounded-3xl max-h-48 bg-transparent text-sm leading-relaxed placeholder:text-muted-foreground/60 scrollbar-hide"
              rows={1}
            />

            <div className="absolute right-2 bottom-2">
              {isLoading ? (
                <Button
                  size="icon"
                  onClick={stopGeneration}
                  className="rounded-full h-9 w-9 bg-destructive/10 text-destructive hover:bg-destructive/20 hover:text-destructive shadow-sm"
                  title="停止生成"
                >
                  <StopCircle className="h-4 w-4" />
                </Button>
              ) : (
                <Button
                  size="icon"
                  onClick={handleSend}
                  disabled={!inputValue.trim()}
                  className={cn(
                    "rounded-full h-9 w-9 transition-all duration-300 shadow-sm",
                    inputValue.trim() 
                      ? "bg-primary text-primary-foreground hover:bg-primary/90 hover:scale-105 hover:shadow-md" 
                      : "bg-secondary text-muted-foreground cursor-not-allowed"
                  )}
                  title="发送"
                >
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
          
          <div className="text-center">
            <p className="text-[10px] text-muted-foreground/40 font-medium tracking-widest uppercase scale-90">
                AI can make mistakes. Check important info.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

// 欢迎屏幕 - 优化版
function WelcomeScreen() {
  const hour = new Date().getHours()
  const greeting = hour < 5 ? '夜深了' : hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好'

  return (
    <div className="flex flex-col items-center justify-center text-center space-y-8 animate-fade-in-up px-4">
      <div className="relative">
         <div className="absolute -inset-4 bg-gradient-to-tr from-primary/30 to-purple-500/30 rounded-full blur-2xl opacity-20 animate-pulse-subtle"></div>
         <div className="relative h-20 w-20 bg-background rounded-2xl shadow-xl flex items-center justify-center border border-border/50">
            <Bot className="h-10 w-10 text-primary" />
         </div>
      </div>

      <div className="space-y-2 max-w-lg">
        <h2 className="text-3xl font-bold tracking-tight text-foreground">
            {greeting}，<span className="text-primary">探索者</span>
        </h2>
        <p className="text-muted-foreground text-sm md:text-base leading-relaxed">
            我是 MimirQ，你的智能知识中枢。<br/>
            我可以协助你分析文档、提取信息或进行深入的研究。
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 w-full max-w-2xl opacity-0 animate-fade-in-up" style={{ animationDelay: '200ms', animationFillMode: 'forwards' }}>
         <FeatureCard icon={Database} title="混合检索" desc="结合语义与关键词的精准召回" />
         <FeatureCard icon={Sparkles} title="智能问答" desc="基于上下文的深度推理与回答" />
         <FeatureCard icon={Wand2} title="结构化输出" desc="将非结构化数据转化为表格或JSON" />
      </div>
    </div>
  )
}

function FeatureCard({ icon: Icon, title, desc }: { icon: any, title: string, desc: string }) {
    return (
        <div className="p-4 rounded-xl bg-secondary/30 border border-border/50 hover:bg-secondary/60 transition-colors cursor-default text-left group">
            <Icon className="h-5 w-5 text-primary mb-2 opacity-70 group-hover:opacity-100 transition-opacity" />
            <h3 className="text-sm font-medium text-foreground mb-1">{title}</h3>
            <p className="text-xs text-muted-foreground">{desc}</p>
        </div>
    )
}
