/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect, useCallback, useMemo, useLayoutEffect } from 'react'
import { Send, StopCircle, Sparkles, Database, Wand2, Settings2, Bot, Mic, ArrowDown } from 'lucide-react'
import { toast } from 'sonner'
import { useChat } from '@/hooks/use-chat'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { promptTemplateApi, settingsApi, type PromptTemplate } from '@/lib/api-client'
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
import { ConversationSummaryDialog } from '@/components/chat/conversation-summary-dialog'
import getCaretCoordinates from 'textarea-caret'
import { SlashMenu } from '@/components/chat/slash-menu'
import { globalEventBus } from '@/lib/event-bus'
import { Magnetic } from '@/components/ui/magnetic'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'
const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40

export function ChatArea({
  initialConversationId,
  initialPrompt,
  initialOpenRagSettings,
  onConversationId,
}: {
  initialConversationId?: string
  initialPrompt?: string
  initialOpenRagSettings?: boolean
  onConversationId?: (conversationId: string) => void
} = {}) {
  const summaryMemoryId = 'chat-enable-summary-memory'
  const [inputValue, setInputValue] = useState(() => (initialPrompt || '').trim())
  const [promptTemplateId, setPromptTemplateId] = useState<string>('')
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([])
  const [showRagSettings, setShowRagSettings] = useState(Boolean(initialOpenRagSettings))
  const [hasSystemRagDefaults, setHasSystemRagDefaults] = useState(false)
  const [ragConfigDirty, setRagConfigDirty] = useState(false)
  const [ragConfig, setRagConfig] = useState<{
    top_k: number
    score_threshold: number
    retrieval_mode: string
    use_graph: boolean
    metadata_filter?: Record<string, any> | null
  }>(() => ({
    top_k: 5,
    score_threshold: 0.7,
    retrieval_mode: 'hybrid',
    use_graph: false,
    metadata_filter: undefined,
  }))
  const [metadataFilterMode, setMetadataFilterMode] = useState<'all' | 'exclude_qa' | 'qa_only' | 'custom'>('all')
  const [metadataFilterText, setMetadataFilterText] = useState('')
  const [metadataFilterError, setMetadataFilterError] = useState<string | null>(null)
  const [structuredOutput, setStructuredOutput] = useState(false)
  const [structuredPreset, setStructuredPreset] = useState<string>('')
  const [enableLongTermMemory, setEnableLongTermMemory] = useState(false)
  const [enableSummaryMemory, setEnableSummaryMemory] = useState(false)
  const [summaryDialogOpen, setSummaryDialogOpen] = useState(false)
  const [visibleCount, setVisibleCount] = useState(DEFAULT_VISIBLE_MESSAGES)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const prevInitialConversationIdRef = useRef<string | undefined>(initialConversationId)
  const autoScrollRef = useRef(true)
  const [isNearBottom, setIsNearBottom] = useState(true)
  const scrollRafRef = useRef<number | null>(null)
  const scrollEventRafRef = useRef<number | null>(null)
  const pendingPrependScrollRef = useRef<{ top: number; height: number } | null>(null)
  const ragSettingsId = 'rag-settings-panel'

  // Slash Menu State
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashPos, setSlashPos] = useState({ top: 0, left: 0 })
  const [voiceModeOpen, setVoiceModeOpen] = useState(false)

  // Initialize chat retrieval defaults from system settings (avoid hard-coded 5/0.7 overriding backend config).
  useEffect(() => {
    let cancelled = false
    const loadRagDefaults = async () => {
      try {
        const system = await settingsApi.get()
        if (cancelled) return
        setHasSystemRagDefaults(true)
        setRagConfig((prev) => {
          const isDefault =
            prev.top_k === 5 &&
            prev.score_threshold === 0.7 &&
            prev.retrieval_mode === 'hybrid' &&
            prev.use_graph === false
          if (!isDefault) return prev
          return {
            ...prev,
            top_k: system.rag?.retrieval_top_k ?? prev.top_k,
            score_threshold: system.rag?.similarity_threshold ?? prev.score_threshold,
          }
        })
      } catch {
        // best-effort only
      }
    }
    void loadRagDefaults()
    return () => {
      cancelled = true
    }
  }, [])

  const applyMetadataFilterPreset = useCallback(
    (mode: 'all' | 'exclude_qa' | 'qa_only' | 'custom') => {
      setMetadataFilterMode(mode)
      setRagConfigDirty(true)
      setMetadataFilterError(null)

      if (mode === 'all') {
        setMetadataFilterText('')
        setRagConfig((prev) => ({ ...prev, metadata_filter: undefined }))
        return
      }

      if (mode === 'exclude_qa') {
        const filter = { file_type: { $ne: 'qa' } }
        setMetadataFilterText(JSON.stringify(filter, null, 2))
        setRagConfig((prev) => ({ ...prev, metadata_filter: filter }))
        return
      }

      if (mode === 'qa_only') {
        const filter = { file_type: { $eq: 'qa' } }
        setMetadataFilterText(JSON.stringify(filter, null, 2))
        setRagConfig((prev) => ({ ...prev, metadata_filter: filter }))
        return
      }

      // custom: keep current JSON text; parsing happens in an effect.
    },
    []
  )

  useEffect(() => {
    if (metadataFilterMode !== 'custom') return

    const raw = (metadataFilterText || '').trim()
    if (!raw) {
      setMetadataFilterError(null)
      setRagConfig((prev) => ({ ...prev, metadata_filter: undefined }))
      return
    }

    try {
      const parsed = JSON.parse(raw)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setMetadataFilterError('metadata_filter must be a JSON object (filter disabled)')
        setRagConfig((prev) => ({ ...prev, metadata_filter: undefined }))
        return
      }
      setMetadataFilterError(null)
      setRagConfig((prev) => ({ ...prev, metadata_filter: parsed }))
    } catch {
      setMetadataFilterError('Invalid JSON (filter disabled)')
      setRagConfig((prev) => ({ ...prev, metadata_filter: undefined }))
    }
  }, [metadataFilterMode, metadataFilterText])

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
    ragConfig: ragConfigDirty || hasSystemRagDefaults ? ragConfig : undefined,
    structuredOutput,
    structuredPreset: structuredPreset || undefined,
    enableLongTermMemory,
    enableSummaryMemory,
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
    const nearBottom = distanceToBottom < 160
    autoScrollRef.current = nearBottom
    setIsNearBottom((prev) => (prev === nearBottom ? prev : nearBottom))
  }, [])

  const handleScroll = useCallback(() => {
    if (scrollEventRafRef.current != null) return
    scrollEventRafRef.current = window.requestAnimationFrame(() => {
      scrollEventRafRef.current = null
      updateAutoScroll()
    })
  }, [updateAutoScroll])

  const scheduleScrollToBottom = useCallback((behavior: ScrollBehavior) => {
    if (!autoScrollRef.current) return
    if (scrollRafRef.current != null) return
    scrollRafRef.current = window.requestAnimationFrame(() => {
      scrollRafRef.current = null
      messagesEndRef.current?.scrollIntoView({ behavior })
    })
  }, [])

  const jumpToBottom = useCallback(() => {
    autoScrollRef.current = true
    setIsNearBottom(true)
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  const handleLoadMore = useCallback(() => {
    const el = scrollContainerRef.current
    if (el) {
      pendingPrependScrollRef.current = { top: el.scrollTop, height: el.scrollHeight }
    }
    setVisibleCount((count) => Math.min(messages.length, count + LOAD_MORE_STEP))
  }, [messages.length])

  // Preserve scroll position when revealing older messages.
  useLayoutEffect(() => {
    const pending = pendingPrependScrollRef.current
    if (!pending) return
    const el = scrollContainerRef.current
    if (!el) {
      pendingPrependScrollRef.current = null
      return
    }
    const delta = el.scrollHeight - pending.height
    el.scrollTop = pending.top + delta
    pendingPrependScrollRef.current = null
    updateAutoScroll()
  }, [visibleCount, updateAutoScroll])

  useEffect(() => {
    if (messages.length === 0) return
    scheduleScrollToBottom('smooth')
  }, [messages.length, scheduleScrollToBottom])

  useEffect(() => {
    if (!currentResponse) return
    scheduleScrollToBottom('auto')
  }, [currentResponse, scheduleScrollToBottom])

  useEffect(() => {
    updateAutoScroll()
    return () => {
      if (scrollRafRef.current != null) {
        window.cancelAnimationFrame(scrollRafRef.current)
        scrollRafRef.current = null
      }
      if (scrollEventRafRef.current != null) {
        window.cancelAnimationFrame(scrollEventRafRef.current)
        scrollEventRafRef.current = null
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

  useEffect(() => {
    if (initialOpenRagSettings) setShowRagSettings(true)
  }, [initialOpenRagSettings])

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
    <div className="flex-1 min-h-0 flex flex-col bg-background relative transition-colors duration-300">
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto overscroll-contain px-4 pb-4 scroll-smooth no-scrollbar"
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
                onClick={handleLoadMore}
                className="rounded-full text-xs text-muted-foreground hover:bg-secondary"
              >
                显示更早消息（{hiddenCount}）
              </Button>
            </div>
          )}

          <div className="space-y-6">
            {visibleMessages.map((message) => (
              <div
                key={message.id}
                className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-200 motion-safe:ease-out"
              >
                <ChatMessageItem message={message} />
              </div>
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

      {!isNearBottom && (messages.length > 0 || Boolean(currentResponse)) && (
        <div className="absolute right-6 bottom-24 z-20">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={jumpToBottom}
            className="rounded-full shadow-md border border-border/60"
            aria-label="回到最新消息"
            title="回到最新消息"
          >
            <ArrowDown className="h-4 w-4 mr-1" />
            回到最新
          </Button>
        </div>
      )}

      <div className="px-4 pt-2 z-10 pb-[calc(env(safe-area-inset-bottom)+1.5rem)]">
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
                    <div className="max-h-60 overflow-y-auto overscroll-contain no-scrollbar space-y-1">
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
	                        onValueChange={(v) => {
	                          setRagConfigDirty(true)
	                          setRagConfig((prev) => ({ ...prev, retrieval_mode: v }))
	                        }}
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
	                        onChange={(e) => {
	                          setRagConfigDirty(true)
	                          setRagConfig((prev) => ({ ...prev, top_k: Number(e.target.value || 0) }))
	                        }}
	                        className="flex h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
	                      />
                    </div>
                  </div>

                  <div className="space-y-2 pt-2 border-t">
                    <label className="text-xs text-muted-foreground">Metadata filter</label>
                    <Select value={metadataFilterMode} onValueChange={(v) => applyMetadataFilterPreset(v as any)}>
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Filter" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All chunks</SelectItem>
                        <SelectItem value="exclude_qa">Exclude Q&A chunks (file_type != qa)</SelectItem>
                        <SelectItem value="qa_only">Q&A only (file_type == qa)</SelectItem>
                        <SelectItem value="custom">Custom JSON</SelectItem>
                      </SelectContent>
                    </Select>

                    {metadataFilterMode === 'custom' ? (
                      <div className="space-y-1.5">
                        <textarea
                          value={metadataFilterText}
                          onChange={(e) => {
                            setRagConfigDirty(true)
                            setMetadataFilterText(e.target.value)
                          }}
                          placeholder='{"source":{"$contains":"handbook"},"page":{"$gte":10}}'
                          className="w-full min-h-[92px] rounded-md border border-input bg-background px-3 py-2 text-[11px] font-mono shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        />
                        {metadataFilterError ? (
                          <div className="text-[11px] text-destructive">{metadataFilterError}</div>
                        ) : null}
                        <details className="group/details rounded-md border border-border bg-muted/30 px-3 py-2">
                          <summary className="cursor-pointer select-none text-[11px] text-muted-foreground">
                            支持的操作符 / 示例
                          </summary>
                          <div className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                            <div className="font-mono text-foreground/80">$eq $ne $gt $gte $lt $lte $in $nin $contains $exists</div>
                            <div>多个字段默认 AND 关系；支持 dotted path（例如 document_user.tags）。</div>
                            <div className="font-mono text-foreground/80">{'{"file_type":{"$ne":"qa"}}'}</div>
                            <div className="font-mono text-foreground/80">{'{"page":{"$gte":10},"source":{"$contains":"handbook"}}'}</div>
                          </div>
                        </details>
                      </div>
                    ) : null}
                  </div>

                  <div className="space-y-3 pt-2 border-t">
                    <label className="flex items-center justify-between text-sm cursor-pointer hover:bg-secondary/50 p-1 rounded-md transition-colors">
                      <span className="text-muted-foreground text-xs">使用知识图谱 (LangGraph)</span>
	                      <input
	                        type="checkbox"
	                        checked={ragConfig.use_graph}
	                        onChange={(e) => {
	                          setRagConfigDirty(true)
	                          setRagConfig((prev) => ({ ...prev, use_graph: e.target.checked }))
	                        }}
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
                    <div className="flex items-center justify-between text-sm hover:bg-secondary/50 p-1 rounded-md transition-colors">
                      <Label
                        htmlFor={summaryMemoryId}
                        className="text-muted-foreground text-xs cursor-pointer"
                      >
                        启用摘要记忆（持久）
                      </Label>
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-[11px] rounded-lg"
                          onClick={() => setSummaryDialogOpen(true)}
                          disabled={!conversationId}
                          title={!conversationId ? '请先发送一条消息生成会话' : '查看/更新摘要'}
                        >
                          查看
                        </Button>
                        <input
                          id={summaryMemoryId}
                          type="checkbox"
                          checked={enableSummaryMemory}
                          onChange={(e) => setEnableSummaryMemory(e.target.checked)}
                          className="accent-primary h-4 w-4 focus-ring"
                        />
                      </div>
                    </div>
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
	            "relative group rounded-[2rem] glass border-border/60 transition-colors duration-200 motion-reduce:transition-none",
	            "shadow-2xl shadow-primary/5 hover:shadow-primary/10",
	            "focus-within:ring-1 focus-within:ring-primary/30 focus-within:border-primary/50"
	          )}>
              <Label htmlFor="chat-composer" className="sr-only">
                消息输入框
              </Label>
	            <textarea
	              id="chat-composer"
	              ref={textareaRef}
	              value={inputValue}
	              onChange={(e) => setInputValue(e.target.value)}
	              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyUp}
	              placeholder="问点什么... (Shift + Enter 换行)"
	              autoFocus
	              className="w-full px-6 py-5 pr-20 resize-none outline-none rounded-[2rem] max-h-48 bg-transparent text-sm leading-relaxed placeholder:text-muted-foreground/40 no-scrollbar text-foreground/90 font-medium"
	              rows={1}
	            />

            <div className="absolute right-2 bottom-2 flex items-center gap-2">
	              <Magnetic strength={0.4}>
	                <Button
	                  size="icon"
	                  variant="ghost"
	                  onClick={() => setVoiceModeOpen(true)}
	                  className="rounded-full h-10 w-10 text-muted-foreground hover:text-foreground hover:bg-muted"
	                  title="语音模式"
	                  aria-label="语音模式"
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
	                    aria-label="停止生成"
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
                      "rounded-full size-9 shadow-sm transition-colors transition-shadow transition-transform duration-200 motion-reduce:transition-none",
                      inputValue.trim()
                        ? "bg-primary text-primary-foreground hover:bg-primary/90 motion-safe:hover:scale-105 hover:shadow-md"
                        : "bg-secondary text-muted-foreground cursor-not-allowed"
	                    )}
	                    title="发送"
	                    aria-label="发送"
	                  >
	                    <Send className="h-4 w-4" />
	                  </Button>
                </Magnetic>
              )}
            </div>
          </div>

	          <p className="text-[10px] text-muted-foreground/70 text-center font-medium opacity-0 group-hover:opacity-100 transition-opacity duration-200 motion-reduce:transition-none">
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

      <ConversationSummaryDialog
        open={summaryDialogOpen}
        onOpenChange={setSummaryDialogOpen}
        conversationId={conversationId}
      />
    </div>
  )
}

function WelcomeScreen() {
  const hour = new Date().getHours()
  const greeting = hour < 5 ? '夜深了' : hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好'

  const focusComposer = () => {
    if (typeof document === 'undefined') return
    const el = document.getElementById('chat-composer') as HTMLTextAreaElement | null
    el?.focus()
  }

  return (
    <div className="flex flex-col items-center justify-center text-center space-y-8 px-4 py-10 relative z-10">
      <div className="size-24 rounded-[2rem] border border-border bg-card shadow-soft flex items-center justify-center">
        <Bot className="h-12 w-12 text-primary" aria-hidden="true" />
      </div>

      <div className="space-y-2 max-w-lg">
        <h2 className="text-balance text-3xl font-semibold text-foreground">
          {greeting}，<span className="text-primary">探索者</span>
        </h2>
        <p className="text-pretty text-muted-foreground text-sm md:text-base leading-relaxed">
          我是 MimirQ，你的智能知识中枢。<br />
          你可以在下方输入问题，我会基于你的知识库进行检索与回答。
        </p>
      </div>

      <div>
        <Button type="button" onClick={focusComposer} className="rounded-full">
          开始提问
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 w-full max-w-2xl">
        <FeatureCard icon={Database} title="混合检索" desc="结合语义与关键词的精准召回" />
        <FeatureCard icon={Sparkles} title="智能问答" desc="基于上下文的推理与回答" />
        <FeatureCard icon={Wand2} title="结构化输出" desc="将非结构化内容整理为表格或 JSON" />
      </div>
    </div>
  )
}

function FeatureCard({ icon: Icon, title, desc }: { icon: any, title: string, desc: string }) {
  return (
    <div className="p-5 rounded-2xl border border-border bg-card shadow-soft cursor-default text-left">
      <Icon className="h-6 w-6 text-primary/80 mb-3" aria-hidden="true" />
      <h3 className="text-sm font-semibold text-balance text-foreground/90 mb-1.5">{title}</h3>
      <p className="text-xs text-pretty text-muted-foreground leading-relaxed">{desc}</p>
    </div>
  )
}
