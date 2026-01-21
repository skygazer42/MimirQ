/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { Send, StopCircle, Sparkles, Database, Wand2, Settings2, Bot, Mic } from 'lucide-react'
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
import { VoiceModeOverlay } from '@/components/chat/voice-mode-overlay'
import getCaretCoordinates from 'textarea-caret'
import { SlashMenu } from '@/components/chat/slash-menu'
import { globalEventBus } from '@/lib/event-bus'
import { Magnetic } from '@/components/ui/magnetic'
import { ScrollReveal } from '@/components/ui/scroll-reveal'

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

  // Slash Menu State
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashPos, setSlashPos] = useState({ top: 0, left: 0 })
  const [voiceModeOpen, setVoiceModeOpen] = useState(false)

  const handleKeyUp = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === '/') {
      const el = e.currentTarget
      const caret = getCaretCoordinates(el, el.selectionEnd)
      const rect = el.getBoundingClientRect()
      setSlashPos({
        top: rect.top + caret.top + 20, // offset
        left: rect.left + caret.left
      })
      setSlashOpen(true)
    }
  }, [])

  const handleSlashSelect = useCallback((cmd: string) => {
    setSlashOpen(false)
    toast.info(`已执行快捷指令: ${cmd}`)
    setInputValue(prev => prev.slice(0, -1))
    if (cmd === 'clear') {
      // resetConversation logic would be called here if exposed or integrated
    }
  }, [])

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

    const unsubscribe = globalEventBus.on('chat:send', (prompt: string) => {
      setInputValue(prompt)
    })

    return () => unsubscribe()
  }, [])

  const {
    messages,
    isLoading,
    currentResponse,
    currentCitations,
    currentSteps,
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

  // Sync URL conversation -> local state
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

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [inputValue])

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
              <ScrollReveal key={message.id}>
                <ChatMessageItem message={message} />
              </ScrollReveal>
            ))}

            {isLoading && (currentResponse || (currentSteps && currentSteps.length > 0)) && (
              <ChatMessageItem
                message={{
                  id: 'streaming',
                  role: 'assistant',
                  content: currentResponse,
                  citations: currentCitations,
                  steps: currentSteps,
                  created_at: new Date().toISOString(),
                }}
                isStreaming
              />
            )}
          </div>

          <div ref={messagesEndRef} className="h-4" />
        </div>
      </div>

      <div className="px-4 pb-6 pt-2 z-10">
        <div className="max-w-3xl mx-auto space-y-4">

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
                        max={50}
                        value={ragConfig.top_k}
                        onChange={(e) => setRagConfig((prev) => ({ ...prev, top_k: Number(e.target.value || 0) }))}
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

          <div className={cn(
            "relative group rounded-[2rem] glass border-white/10 transition-all duration-500",
            "shadow-2xl shadow-primary/5 hover:shadow-primary/10",
            "focus-within:ring-1 focus-within:ring-primary/30 focus-within:border-primary/50"
          )}>
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyUp}
              placeholder="问点什么... (Shift + Enter 换行)"
              autoFocus
              className="w-full px-6 py-5 pr-20 resize-none outline-none rounded-[2rem] max-h-48 bg-transparent text-sm leading-relaxed placeholder:text-muted-foreground/40 no-scrollbar text-foreground/90 font-medium tracking-wide"
              rows={1}
            />

            <div className="absolute right-2 bottom-2 flex items-center gap-2">
              <Magnetic strength={0.4}>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => setVoiceModeOpen(true)}
                  className="rounded-full h-10 w-10 text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
                  title="语音模式"
                >
                  <Mic className="h-5 w-5" />
                </Button>
              </Magnetic>

              {isLoading ? (
                <Magnetic strength={0.2}>
                  <Button
                    size="icon"
                    onClick={stopGeneration}
                    className="rounded-full h-9 w-9 bg-destructive/10 text-destructive hover:bg-destructive/20 hover:text-destructive shadow-sm"
                    title="停止生成"
                  >
                    <StopCircle className="h-4 w-4" />
                  </Button>
                </Magnetic>
              ) : (
                <Magnetic strength={0.5}>
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
                </Magnetic>
              )}
            </div>
          </div>

          <p className="text-[10px] text-slate-400 dark:text-slate-500 text-center font-medium tracking-wide opacity-0 group-hover:opacity-100 transition-opacity duration-500">
            POWERED BY MIMIRQ AI
          </p>
        </div>
      </div>

      <SlashMenu
        open={slashOpen}
        onOpenChange={setSlashOpen}
        onSelect={handleSlashSelect}
        position={slashPos}
      />

      <VoiceModeOverlay
        isOpen={voiceModeOpen}
        onClose={() => setVoiceModeOpen(false)}
        onSend={(text) => {
          setVoiceModeOpen(false)
          sendMessage(text)
        }}
      />
    </div>
  )
}

function WelcomeScreen() {
  const hour = new Date().getHours()
  const greeting = hour < 5 ? '夜深了' : hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好'

  return (
    <div className="flex flex-col items-center justify-center text-center space-y-10 animate-fade-in-up px-4 py-10 relative z-10">
      <div className="relative">
        <div className="absolute -inset-10 bg-gradient-radial from-primary/20 via-primary/5 to-transparent blur-3xl opacity-40 animate-pulse-subtle"></div>
        <div className="relative h-24 w-24 glass rounded-[2rem] shadow-glow flex items-center justify-center border border-white/20">
          <Bot className="h-12 w-12 text-primary drop-shadow-[0_0_15px_rgba(0,255,255,0.5)]" />
        </div>
      </div>

      <div className="space-y-2 max-w-lg">
        <h2 className="text-3xl font-bold tracking-tight text-foreground">
          {greeting}，<span className="text-primary">探索者</span>
        </h2>
        <p className="text-muted-foreground text-sm md:text-base leading-relaxed">
          我是 MimirQ，你的智能知识中枢。<br />
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
    <div className="p-5 rounded-2xl glass border border-white/5 hover:border-primary/30 hover:bg-white/5 transition-all duration-300 cursor-default text-left group hover:-translate-y-1 hover:shadow-lg hover:shadow-primary/5">
      <Icon className="h-6 w-6 text-primary/80 mb-3 group-hover:text-primary group-hover:scale-110 transition-all duration-300" />
      <h3 className="text-sm font-semibold text-foreground/90 mb-1.5">{title}</h3>
      <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
    </div>
  )
}
