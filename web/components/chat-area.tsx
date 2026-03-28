/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect, useCallback, useMemo, useLayoutEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Send, StopCircle, Sparkles, Database, Wand2, Settings2, Bot, Mic, ArrowDown, type LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import { useChat } from '@/hooks/use-chat'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { cn, detachPromise } from '@/lib/utils'
import { datasetApi, documentApi, promptTemplateApi, settingsApi, type PromptTemplate } from '@/lib/api'
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
import { coerceOneOf } from '@/lib/one-of'
import { messages as uiMessages } from '@/lib/messages'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'
const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40
const METADATA_FILTER_MODE_VALUES = ['all', 'exclude_qa', 'qa_only', 'custom'] as const

export function ChatArea({
  initialConversationId,
  initialPrompt,
  initialAutoSendPrompt,
  initialOpenRagSettings,
  onConversationId,
}: Readonly<{
  initialConversationId?: string
  initialPrompt?: string
  initialAutoSendPrompt?: boolean
  initialOpenRagSettings?: boolean
  onConversationId?: (conversationId: string) => void
}> = {}) {
  const router = useRouter()
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
    metadata_filter?: Record<string, unknown> | null
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
  const autoSendPromptRef = useRef(false)
  // Slash Menu State
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashPos, setSlashPos] = useState({ top: 0, left: 0 })
  const [voiceModeOpen, setVoiceModeOpen] = useState(false)
  const [welcomeStats, setWelcomeStats] = useState<{
    datasets: number | null
    documents: number | null
    loading: boolean
  }>({ datasets: null, documents: null, loading: true })

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
    detachPromise(loadRagDefaults())
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    const loadWelcomeStats = async () => {
      try {
        const [datasetsRes, documentsRes] = await Promise.all([
          datasetApi.list({ limit: 1 }),
          documentApi.list({ limit: 1, status: 'completed' }),
        ])
        if (cancelled) return
        setWelcomeStats({
          datasets: Number(datasetsRes.total || 0),
          documents: Number(documentsRes.total || 0),
          loading: false,
        })
      } catch {
        if (cancelled) return
        setWelcomeStats({ datasets: null, documents: null, loading: false })
      }
    }

    detachPromise(loadWelcomeStats())
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

  const handlePrefillInput = useCallback((nextValue: string) => {
    const prompt = nextValue.trim()
    if (!prompt) return

    setInputValue(prompt)
    setSlashOpen(false)

    globalThis.window.requestAnimationFrame(() => {
      const textarea = textareaRef.current
      if (!textarea) return
      textarea.focus()
      const end = prompt.length
      textarea.setSelectionRange(end, end)
    })
  }, [])

  const handleSlashSelect = useCallback((cmd: string) => {
    setSlashOpen(false)

    if (cmd === 'prompt') {
      handlePrefillInput('请基于知识库内容整理一份重点摘要，并标出需要我进一步确认的部分。')
      return
    }

    if (cmd === 'doc') {
      handlePrefillInput('请优先引用知识库中的相关文档回答，并注明结论对应的依据。')
      return
    }

    if (cmd === 'config') {
      setShowRagSettings(true)
      toast.info(uiMessages.chat.openRagConfig)
      return
    }

    if (cmd === 'clear') {
      setInputValue('')
      toast.info(uiMessages.chat.clearInput)
    }
  }, [handlePrefillInput])

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
      toast.error(error || uiMessages.chat.requestFailed)
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
    scrollEventRafRef.current = globalThis.window.requestAnimationFrame(() => {
      scrollEventRafRef.current = null
      updateAutoScroll()
    })
  }, [updateAutoScroll])

  const scheduleScrollToBottom = useCallback((behavior: ScrollBehavior) => {
    if (!autoScrollRef.current) return
    if (scrollRafRef.current != null) return
    scrollRafRef.current = globalThis.window.requestAnimationFrame(() => {
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
        globalThis.window.cancelAnimationFrame(scrollRafRef.current)
        scrollRafRef.current = null
      }
      if (scrollEventRafRef.current != null) {
        globalThis.window.cancelAnimationFrame(scrollEventRafRef.current)
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

  useEffect(() => {
    const p = (initialPrompt || '').trim()
    if (!initialAutoSendPrompt || !p) return
    if (autoSendPromptRef.current) return
    if (isLoading || messages.length > 0) return

    autoSendPromptRef.current = true
    sendMessage(p)
    setInputValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [initialAutoSendPrompt, initialPrompt, isLoading, messages.length, sendMessage])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-background relative transition-colors duration-200 motion-reduce:transition-none">
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
              <WelcomeScreen
                onSelectPrompt={handlePrefillInput}
                onOpenKnowledge={() => router.push('/knowledge')}
                promptTemplateCount={promptTemplates.length}
                stats={welcomeStats}
              />
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
                {uiMessages.chat.showEarlierMessages}（{hiddenCount}）
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
            aria-label={uiMessages.chat.jumpToLatestMessage}
            title={uiMessages.chat.jumpToLatestMessage}
          >
            <ArrowDown className="h-4 w-4 mr-1" />
            {uiMessages.chat.jumpToLatest}
          </Button>
        </div>
      )}

      <div className="px-4 pt-2 z-10 pb-[calc(env(safe-area-inset-bottom)+1.5rem)]">
        <div className="max-w-3xl mx-auto space-y-4">

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.5rem] border border-border/60 bg-background/80 px-3 py-2 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/70">
            <div className="flex min-w-0 items-center gap-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] font-medium text-muted-foreground shadow-sm">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                <span>{uiMessages.chat.conversationTools}</span>
              </div>
              <div className="hidden text-[11px] text-muted-foreground md:block">
                {uiMessages.chat.toolsHint}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {promptTemplates.length > 0 && (
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" size="sm" className="h-9 gap-2 rounded-full border border-border/60 bg-card px-3 text-foreground shadow-sm hover:bg-secondary/80">
                      <Wand2 className="w-3.5 h-3.5 text-primary" />
                      <span className="text-xs">{selectedPromptTemplate?.name || uiMessages.chat.defaultTemplate}</span>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-64 p-2" align="start">
                    <div className="text-xs font-medium text-muted-foreground mb-2 px-2">{uiMessages.chat.selectPromptTemplate}</div>
                    <div className="max-h-60 overflow-y-auto overscroll-contain no-scrollbar space-y-1">
                      <button
                        type="button"
                        className={cn('px-2 py-1.5 rounded-md cursor-pointer text-sm hover:bg-secondary transition-colors', !promptTemplateId && 'bg-secondary/50 font-medium text-primary')}
                        onClick={() => setPromptTemplateId('')}
                      >
                        {uiMessages.chat.defaultTemplate}
                      </button>
                      {promptTemplates.map((t) => (
                        <button
                          type="button"
                          key={t.id}
                          className={cn('px-2 py-1.5 rounded-md cursor-pointer text-sm hover:bg-secondary transition-colors flex flex-col gap-0.5', promptTemplateId === t.id && 'bg-secondary/50 font-medium text-primary')}
                          onClick={() => setPromptTemplateId(t.id)}
                        >
                          <span>{t.name}</span>
                          {t.description ? <span className="text-[10px] text-muted-foreground/70 truncate">{t.description}</span> : null}
                        </button>
                      ))}
                    </div>
                  </PopoverContent>
                </Popover>
              )}

              <Popover open={showRagSettings} onOpenChange={setShowRagSettings}>
                <PopoverTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'h-9 gap-2 rounded-full border px-3 shadow-sm transition-colors',
                      ragConfig.retrieval_mode !== 'auto' || ragConfig.use_graph
                        ? 'border-primary/30 bg-primary/10 text-primary hover:bg-primary/15'
                        : 'border-border/60 bg-card text-muted-foreground hover:bg-secondary/80'
                    )}
                  >
                    <Settings2 className="w-3.5 h-3.5" />
                    <span className="text-xs">RAG 配置</span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-80 p-4" align="end" sideOffset={10}>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <h4 className="font-medium text-sm">检索设置</h4>
                      <span className="text-[10px] text-muted-foreground">调整检索参数</span>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <div className="text-xs text-muted-foreground">检索模式</div>
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
                        <div className="text-xs text-muted-foreground">Top K</div>
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
                      <div className="text-xs text-muted-foreground">Metadata filter</div>
                      <Select
                        value={metadataFilterMode}
                        onValueChange={(value) => applyMetadataFilterPreset(coerceOneOf(METADATA_FILTER_MODE_VALUES, value, 'all'))}
                      >
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
                          title={conversationId ? '查看/更新摘要' : '请先发送一条消息生成会话'}
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
        </div>

	          <div className={cn(
	            "relative group rounded-[2rem] glass border-border/60 transition-colors transition-shadow duration-200 motion-reduce:transition-none",
	            "shadow-soft hover:shadow-strong",
	            "focus-within:ring-1 focus-within:ring-primary/30 focus-within:border-primary/50"
	          )}>
            <Label htmlFor="chat-composer" className="sr-only">
                {uiMessages.chat.messageInput}
              </Label>
	            <textarea
	              id="chat-composer"
	              ref={textareaRef}
	              value={inputValue}
	              onChange={(e) => setInputValue(e.target.value)}
	              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyUp}
	              placeholder={uiMessages.chat.composerPlaceholder}
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
	                  title={uiMessages.chat.voiceMode}
	                  aria-label={uiMessages.chat.voiceMode}
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
	                    title={uiMessages.chat.stopGeneration}
	                    aria-label={uiMessages.chat.stopGeneration}
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
	                    title={uiMessages.chat.send}
	                    aria-label={uiMessages.chat.send}
	                  >
	                    <Send className="h-4 w-4" />
	                  </Button>
                </Magnetic>
              )}
            </div>
          </div>

          <p className="text-[11px] text-center text-muted-foreground/75">
            输入 <span className="font-mono text-foreground/80">/</span> 打开快捷指令 · <span className="font-medium text-foreground/80">Enter</span> 发送 · <span className="font-medium text-foreground/80">Shift + Enter</span> 换行
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

const QUICK_START_PROMPTS = [
  {
    icon: Sparkles,
    title: '总结产品手册核心要点',
    prompt: '请基于知识库总结产品手册的核心要点，并标出需要我继续确认的风险。',
  },
  {
    icon: Database,
    title: '提取关键指标与日期',
    prompt: '请从知识库中提取这份报告里的关键指标、日期和负责人，并整理成列表。',
  },
  {
    icon: Wand2,
    title: '对比两个方案的差异',
    prompt: '请对比方案 A 和方案 B 的优缺点，并说明分别适合什么场景。',
  },
  {
    icon: Bot,
    title: '生成一份行动清单',
    prompt: '请基于知识库内容给我一份 5 条行动清单，按优先级排序。',
  },
] as const

function WelcomeScreen({
  onSelectPrompt,
  onOpenKnowledge,
  promptTemplateCount,
  stats,
}: Readonly<{
  onSelectPrompt: (prompt: string) => void
  onOpenKnowledge: () => void
  promptTemplateCount: number
  stats: {
    datasets: number | null
    documents: number | null
    loading: boolean
  }
}>) {
  const hour = new Date().getHours()
  const greeting = (() => {
    if (hour < 5) return '夜深了'
    if (hour < 11) return '早上好'
    if (hour < 13) return '中午好'
    if (hour < 18) return '下午好'
    return '晚上好'
  })()

  const datasetCount = Number(stats.datasets || 0)
  const documentCount = Number(stats.documents || 0)
  const hasKnowledge = !stats.loading && documentCount > 0

  return (
    <div className="relative z-10 w-full max-w-4xl space-y-8 px-4 py-10">
      <div className="mx-auto flex max-w-3xl flex-col items-center space-y-5 text-center">
        <div className="flex size-24 items-center justify-center rounded-[2rem] border border-border bg-card shadow-soft">
          <Bot className="h-12 w-12 text-primary" aria-hidden="true" />
        </div>

        <div className="space-y-3">
          <h2 className="text-balance text-3xl font-semibold text-foreground md:text-4xl">
            {greeting}，<span className="text-primary">探索者</span>
          </h2>
          <p className="mx-auto max-w-2xl text-pretty text-sm leading-relaxed text-muted-foreground md:text-base">
            我是 MimirQ，你的智能知识中枢。先选一个示例问题热身，或者直接在下方输入具体问题，
            我会结合你的知识库给出可追溯的回答。
          </p>
        </div>
      </div>

      <div className="mx-auto max-w-3xl rounded-[2rem] border border-border/60 bg-background/80 p-4 shadow-soft backdrop-blur supports-[backdrop-filter]:bg-background/70">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/80">
              快速开始
            </div>
            <div className="mt-1 text-sm text-muted-foreground">
              点击任意问题直接填入输入框，再按 Enter 发送。
            </div>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] font-medium text-muted-foreground shadow-sm">
            <span className="font-mono text-foreground/80">/</span>
            <span>快捷指令</span>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {QUICK_START_PROMPTS.map((item) => (
            <QuickStartChip
              key={item.title}
              icon={item.icon}
              title={item.title}
              prompt={item.prompt}
              onSelect={onSelectPrompt}
            />
          ))}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <WelcomeStatusCard
          icon={Database}
          title={
            stats.loading
              ? '正在读取知识库状态'
              : hasKnowledge
                ? `${documentCount} 份文档已就绪`
                : '还没有可检索文档'
          }
          desc={
            stats.loading
              ? '检查当前知识库与文档数量，稍后会显示实时状态。'
              : hasKnowledge
                ? `当前已连接 ${datasetCount} 个知识库，可以直接开始基于文档提问。`
                : '先上传 PDF、网页或表格，再回来提问，回答会更可靠。'
          }
          actionLabel={stats.loading ? undefined : '前往知识库'}
          onAction={stats.loading ? undefined : onOpenKnowledge}
        />
        <WelcomeStatusCard
          icon={Wand2}
          title={promptTemplateCount > 0 ? `${promptTemplateCount} 个 Prompt 模板可用` : uiMessages.chat.startFromDefaultTemplate}
          desc={
            promptTemplateCount > 0
              ? '你可以在输入框上方切换模板，快速进入摘要、行动项或结构化输出模式。'
              : '当前没有启用额外模板，直接提问即可，后续也可以再细化策略。'
          }
        />
        <WelcomeStatusCard
          icon={Sparkles}
          title="第一次使用建议"
          desc="先问一个具体问题，再用 / 快捷指令或 RAG 配置逐步缩小范围，会比一次性堆太多要求更稳。"
        />
      </div>
    </div>
  )
}

function QuickStartChip({
  icon: Icon,
  title,
  prompt,
  onSelect,
}: Readonly<{
  icon: LucideIcon
  title: string
  prompt: string
  onSelect: (prompt: string) => void
}>) {
  return (
    <button
      type="button"
      onClick={() => onSelect(prompt)}
      className="group rounded-[1.5rem] border border-border/60 bg-card/90 p-4 text-left shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:bg-card hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex size-10 items-center justify-center rounded-2xl border border-primary/15 bg-primary/10 text-primary">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-foreground">{title}</div>
          <div className="mt-1 text-xs leading-5 text-muted-foreground group-hover:text-foreground/80">
            {prompt}
          </div>
        </div>
      </div>
    </button>
  )
}

function WelcomeStatusCard({
  icon: Icon,
  title,
  desc,
  actionLabel,
  onAction,
}: Readonly<{
  icon: LucideIcon
  title: string
  desc: string
  actionLabel?: string
  onAction?: () => void
}>) {
  return (
    <div className="rounded-[1.5rem] border border-border/60 bg-card/90 p-5 text-left shadow-soft">
      <div className="mb-3 flex size-11 items-center justify-center rounded-2xl border border-primary/15 bg-primary/10 text-primary">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </div>
      <h3 className="text-sm font-semibold text-foreground/95">{title}</h3>
      <p className="mt-2 text-xs leading-6 text-muted-foreground">{desc}</p>
      {actionLabel && onAction ? (
        <Button type="button" variant="outline" size="sm" className="mt-4 rounded-full" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  )
}
