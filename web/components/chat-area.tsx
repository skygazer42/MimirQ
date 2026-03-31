/**
 * 主对话区域组件
 */
'use client'

import { useState, useRef, useEffect, useCallback, useMemo, useLayoutEffect } from 'react'
import { useTranslations } from 'next-intl'
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
import { useRouter } from '@/i18n/navigation'
import { coerceOneOf } from '@/lib/one-of'
import { useDocumentView } from '@/store/document-view'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'
const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40
const METADATA_FILTER_MODE_VALUES = ['all', 'exclude_qa', 'qa_only', 'custom'] as const

function escapeAttributeSelector(value: string): string {
  if (typeof globalThis.CSS?.escape === 'function') {
    return globalThis.CSS.escape(value)
  }
  return String(value).replace(/["\\\]]/g, '\\$&')
}

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
  const t = useTranslations('Chat')
  const activeDocumentId = useDocumentView((state) => state.documentId)
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
  const [focusedMessageId, setFocusedMessageId] = useState<string | null>(null)
  const scrollRafRef = useRef<number | null>(null)
  const scrollEventRafRef = useRef<number | null>(null)
  const focusMessageTimerRef = useRef<number | null>(null)
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
  const activeDocumentIds = useMemo(
    () => (activeDocumentId ? [activeDocumentId] : undefined),
    [activeDocumentId]
  )

  const focusMessageById = useCallback((messageId: string) => {
    const container = scrollContainerRef.current
    if (!container) return false

    const node = container.querySelector<HTMLElement>(
      `[data-chat-message-id="${escapeAttributeSelector(messageId)}"]`
    )
    if (!node) return false

    node.scrollIntoView({ behavior: 'smooth', block: 'center' })
    node.focus({ preventScroll: true })
    setFocusedMessageId(messageId)
    if (focusMessageTimerRef.current != null) {
      globalThis.window.clearTimeout(focusMessageTimerRef.current)
    }
    focusMessageTimerRef.current = globalThis.window.setTimeout(() => {
      setFocusedMessageId((current) => (current === messageId ? null : current))
      focusMessageTimerRef.current = null
    }, 1800)
    return true
  }, [])

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
        setMetadataFilterError(t('metadataFilterObjectError'))
        setRagConfig((prev) => ({ ...prev, metadata_filter: undefined }))
        return
      }
      setMetadataFilterError(null)
      setRagConfig((prev) => ({ ...prev, metadata_filter: parsed }))
    } catch {
      setMetadataFilterError(t('metadataFilterInvalidJson'))
      setRagConfig((prev) => ({ ...prev, metadata_filter: undefined }))
    }
  }, [metadataFilterMode, metadataFilterText, t])

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

    if (cmd === 'knowledge') {
      router.push('/knowledge')
      return
    }

    if (cmd === 'history') {
      router.push('/history')
      return
    }

    if (cmd === 'prompt') {
      handlePrefillInput(t('slashPromptSummary'))
      return
    }

    if (cmd === 'cite_analysis') {
      handlePrefillInput(t('slashPromptCiteAnalysis'))
      return
    }

    if (cmd === 'config') {
      setShowRagSettings(true)
      toast.info(t('openRagConfig'))
      return
    }

    if (cmd === 'clear') {
      setInputValue('')
      toast.info(t('clearInput'))
    }
  }, [handlePrefillInput, router, t])

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

  useEffect(() => {
    return () => {
      if (focusMessageTimerRef.current != null) {
        globalThis.window.clearTimeout(focusMessageTimerRef.current)
      }
    }
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
    documentIds: activeDocumentIds,
    promptTemplateId: promptTemplateId || undefined,
    ragConfig: ragConfigDirty || hasSystemRagDefaults ? ragConfig : undefined,
    structuredOutput,
    structuredPreset: structuredPreset || undefined,
    enableLongTermMemory,
    enableSummaryMemory,
    onConversationId,
    onError: (error) => {
      console.error('Chat error:', error)
      toast.error(error || t('requestFailed'))
    },
  })

  useEffect(() => {
    const unsubscribe = globalEventBus.on('chat:focus-message', ({ messageId }) => {
      const id = String(messageId || '').trim()
      if (!id) return

      if (messages.some((message) => message.id === id)) {
        setVisibleCount((current) => Math.max(current, messages.length))
      }

      globalThis.window.requestAnimationFrame(() => {
        if (focusMessageById(id)) return
        globalThis.window.setTimeout(() => {
          focusMessageById(id)
        }, 80)
      })
    })

    return () => unsubscribe()
  }, [focusMessageById, messages])

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
                {t('showEarlierMessages')}（{hiddenCount}）
              </Button>
            </div>
          )}

          <div className="space-y-6">
            {visibleMessages.map((message) => (
              <div
                key={message.id}
                data-chat-message-id={message.id}
                tabIndex={-1}
                className={cn(
                  'rounded-3xl outline-none transition-shadow duration-300 motion-reduce:transition-none motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-200 motion-safe:ease-out',
                  focusedMessageId === message.id && 'ring-2 ring-primary/35 ring-offset-2 ring-offset-background shadow-lg shadow-primary/10'
                )}
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
            aria-label={t('jumpToLatestMessage')}
            title={t('jumpToLatestMessage')}
          >
            <ArrowDown className="h-4 w-4 mr-1" />
            {t('jumpToLatest')}
          </Button>
        </div>
      )}

      <div className="px-4 pt-2 z-10 pb-[calc(env(safe-area-inset-bottom)+1.5rem)]">
        <div className="max-w-3xl mx-auto space-y-4">

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[1.5rem] border border-border/60 bg-background/80 px-3 py-2 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/70">
            <div className="flex min-w-0 items-center gap-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] font-medium text-muted-foreground shadow-sm">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                <span>{t('conversationTools')}</span>
              </div>
              <div className="hidden text-[11px] text-muted-foreground md:block">
                {t('toolsHint')}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {promptTemplates.length > 0 && (
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" size="sm" className="h-9 gap-2 rounded-full border border-border/60 bg-card px-3 text-foreground shadow-sm hover:bg-secondary/80">
                      <Wand2 className="w-3.5 h-3.5 text-primary" />
                      <span className="text-xs">{selectedPromptTemplate?.name || t('defaultTemplate')}</span>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-64 p-2" align="start">
                    <div className="text-xs font-medium text-muted-foreground mb-2 px-2">{t('selectPromptTemplate')}</div>
                    <div className="max-h-60 overflow-y-auto overscroll-contain no-scrollbar space-y-1">
                      <button
                        type="button"
                        className={cn('px-2 py-1.5 rounded-md cursor-pointer text-sm hover:bg-secondary transition-colors', !promptTemplateId && 'bg-secondary/50 font-medium text-primary')}
                        onClick={() => setPromptTemplateId('')}
                      >
                        {t('defaultTemplate')}
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
                    <span className="text-xs">{t('ragSettings')}</span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-80 p-4" align="end" sideOffset={10}>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <h4 className="font-medium text-sm">{t('retrievalSettings')}</h4>
                      <span className="text-[10px] text-muted-foreground">{t('adjustRetrievalParameters')}</span>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <div className="text-xs text-muted-foreground">{t('retrievalMode')}</div>
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
                            <SelectItem value="auto">{t('retrievalModes.auto')}</SelectItem>
                            <SelectItem value="hybrid">{t('retrievalModes.hybrid')}</SelectItem>
                            <SelectItem value="vector">{t('retrievalModes.vector')}</SelectItem>
                            <SelectItem value="keyword">{t('retrievalModes.keyword')}</SelectItem>
                            <SelectItem value="mmr">{t('retrievalModes.mmr')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <div className="text-xs text-muted-foreground">{t('topK')}</div>
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
                      <div className="text-xs text-muted-foreground">{t('metadataFilter')}</div>
                      <Select
                        value={metadataFilterMode}
                        onValueChange={(value) => applyMetadataFilterPreset(coerceOneOf(METADATA_FILTER_MODE_VALUES, value, 'all'))}
                      >
                        <SelectTrigger className="h-8 text-xs">
                          <SelectValue placeholder={t('metadataFilterPlaceholder')} />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">{t('metadataFilters.allChunks')}</SelectItem>
                          <SelectItem value="exclude_qa">{t('metadataFilters.excludeQa')}</SelectItem>
                          <SelectItem value="qa_only">{t('metadataFilters.qaOnly')}</SelectItem>
                          <SelectItem value="custom">{t('metadataFilters.customJson')}</SelectItem>
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
                            placeholder={t('metadataFilterExampleHandbook')}
                            className="w-full min-h-[92px] rounded-md border border-input bg-background px-3 py-2 text-[11px] font-mono shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                          />
                          {metadataFilterError ? (
                            <div className="text-[11px] text-destructive">{metadataFilterError}</div>
                          ) : null}
                          <details className="group/details rounded-md border border-border bg-muted/30 px-3 py-2">
                            <summary className="cursor-pointer select-none text-[11px] text-muted-foreground">
                              {t('supportedOperatorsExamples')}
                            </summary>
                            <div className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                              <div className="font-mono text-foreground/80">{t('supportedOperatorsList')}</div>
                              <div>{t('supportedOperatorsHint')}</div>
                              <div className="font-mono text-foreground/80">{t('metadataFilterExampleQa')}</div>
                              <div className="font-mono text-foreground/80">{t('metadataFilterExampleHandbook')}</div>
                            </div>
                          </details>
                        </div>
                      ) : null}
                    </div>

                    <div className="space-y-3 pt-2 border-t">
                      <label className="flex items-center justify-between text-sm cursor-pointer hover:bg-secondary/50 p-1 rounded-md transition-colors">
                        <span className="text-muted-foreground text-xs">{t('useKnowledgeGraph')}</span>
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
                      <span className="text-muted-foreground text-xs">{t('enableLongTermMemory')}</span>
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
                        {t('enableSummaryMemory')}
                      </Label>
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-[11px] rounded-lg"
                          onClick={() => setSummaryDialogOpen(true)}
                          disabled={!conversationId}
                          title={conversationId ? t('viewOrUpdateSummary') : t('sendMessageFirst')}
                        >
                          {t('viewSummary')}
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
                      <span className="text-muted-foreground text-xs">{t('structuredOutput')}</span>
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
                            <SelectValue placeholder={t('structuredPresetPlaceholder')} />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={SELECT_DEFAULT_VALUE}>{t('structuredPresetCustom')}</SelectItem>
                            <SelectItem value="faq">{t('structuredPresetFaq')}</SelectItem>
                            <SelectItem value="summary">{t('structuredPresetSummary')}</SelectItem>
                            <SelectItem value="action_items">{t('structuredPresetActionItems')}</SelectItem>
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
                {t('messageInput')}
              </Label>
	            <textarea
	              id="chat-composer"
	              ref={textareaRef}
	              value={inputValue}
	              onChange={(e) => setInputValue(e.target.value)}
	              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyUp}
	              placeholder={t('composerPlaceholder')}
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
	                  title={t('voiceMode')}
	                  aria-label={t('voiceMode')}
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
	                    title={t('stopGeneration')}
	                    aria-label={t('stopGeneration')}
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
	                    title={t('send')}
	                    aria-label={t('send')}
	                  >
	                    <Send className="h-4 w-4" />
	                  </Button>
                </Magnetic>
              )}
            </div>
          </div>

          <p className="text-[11px] text-center text-muted-foreground/75">
            {t.rich('composerHelpText', {
              slash: (chunks) => <span className="font-mono text-foreground/80">{chunks}</span>,
              enter: (chunks) => <span className="font-medium text-foreground/80">{chunks}</span>,
              shiftEnter: (chunks) => <span className="font-medium text-foreground/80">{chunks}</span>,
            })}
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
  const t = useTranslations('Chat')
  const hour = new Date().getHours()
  const greeting = (() => {
    if (hour < 5) return t('greetings.lateNight')
    if (hour < 11) return t('greetings.morning')
    if (hour < 13) return t('greetings.noon')
    if (hour < 18) return t('greetings.afternoon')
    return t('greetings.evening')
  })()
  const quickStartPrompts = useMemo(
    () => [
      {
        icon: Sparkles,
        title: t('quickStartExamples.productManual.title'),
        prompt: t('quickStartExamples.productManual.prompt'),
      },
      {
        icon: Database,
        title: t('quickStartExamples.metrics.title'),
        prompt: t('quickStartExamples.metrics.prompt'),
      },
      {
        icon: Wand2,
        title: t('quickStartExamples.comparePlans.title'),
        prompt: t('quickStartExamples.comparePlans.prompt'),
      },
      {
        icon: Bot,
        title: t('quickStartExamples.actionItems.title'),
        prompt: t('quickStartExamples.actionItems.prompt'),
      },
    ],
    [t]
  )

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
          <h2 className="text-balance text-3xl font-semibold leading-tight text-foreground md:text-4xl">
            {greeting}，<span className="text-primary">{t('explorer')}</span>
          </h2>
          <p className="mx-auto max-w-2xl text-pretty text-sm leading-7 text-muted-foreground/90 md:text-base">
            {t('welcomeLead')}
          </p>
        </div>
      </div>

      <div className="mx-auto max-w-3xl rounded-[2rem] border border-border/60 bg-background/80 p-4 shadow-soft backdrop-blur supports-[backdrop-filter]:bg-background/70">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/80">
              {t('quickStart.title')}
            </div>
            <div className="mt-1 text-sm leading-6 text-muted-foreground">
              {t('quickStart.description')}
            </div>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card px-3 py-1 text-[11px] font-medium tracking-[0.08em] text-muted-foreground shadow-sm">
            <span className="font-mono text-foreground/80">/</span>
            <span>{t('quickStart.slashCommands')}</span>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {quickStartPrompts.map((item) => (
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
              ? t('knowledgeStatus.loadingTitle')
              : hasKnowledge
                ? t('knowledgeStatus.readyTitle', { count: documentCount })
                : t('knowledgeStatus.emptyTitle')
          }
          desc={
            stats.loading
              ? t('knowledgeStatus.loadingDescription')
              : hasKnowledge
                ? t('knowledgeStatus.readyDescription', { count: datasetCount })
                : t('knowledgeStatus.emptyDescription')
          }
          actionLabel={stats.loading ? undefined : t('knowledgeStatus.actionLabel')}
          onAction={stats.loading ? undefined : onOpenKnowledge}
        />
        <WelcomeStatusCard
          icon={Wand2}
          title={promptTemplateCount > 0 ? t('promptTemplatesAvailable', { count: promptTemplateCount }) : t('startFromDefaultTemplate')}
          desc={
            promptTemplateCount > 0
              ? t('promptTemplatesAvailableDescription')
              : t('noPromptTemplateDescription')
          }
        />
        <WelcomeStatusCard
          icon={Sparkles}
          title={t('firstUseAdviceTitle')}
          desc={t('firstUseAdviceDescription')}
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
          <div className="text-sm font-semibold leading-snug text-foreground">{title}</div>
          <div className="mt-1 text-xs leading-5 text-muted-foreground/90 group-hover:text-foreground/80">
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
      <h3 className="text-sm font-semibold leading-snug text-foreground/95">{title}</h3>
      <p className="mt-2 text-xs leading-6 text-muted-foreground/90">{desc}</p>
      {actionLabel && onAction ? (
        <Button type="button" variant="outline" size="sm" className="mt-4 rounded-full" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  )
}
