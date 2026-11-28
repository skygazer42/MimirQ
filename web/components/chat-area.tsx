/**
 * 主对话区域组件
 */
'use client'

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
  useLayoutEffect,
  useSyncExternalStore,
  type ReactNode,
} from 'react'
import { useTranslations } from 'next-intl'
import { ArrowUp, ArrowRight, StopCircle, Settings2, Mic, ArrowDown, Route, ChevronDown } from '@/components/icons'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'
import { useChat } from '@/hooks/use-chat'
import type { ChatRagConfig } from '@/hooks/chat-stream-payload'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { datasetApi } from '@/lib/api/datasets'
import { promptTemplateApi, type PromptTemplate } from '@/lib/api/prompts'
import { recordSchema } from '@/lib/response-schema'
import { settingsApi } from '@/lib/api/settings'
import { ChatMessageItem } from '@/components/chat/message-item'
import messageStyles from '@/components/chat/message-item.module.css'
import { StarterPrompts } from '@/components/chat/starter-prompts'
import { DatasetScopePicker } from '@/components/chat/dataset-scope-picker'
import { BrandLogo } from '@/components/brand-logo'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { VoiceModeOverlay } from '@/components/chat/voice-mode-overlay'
import { ConversationSummaryDialog } from '@/components/chat/conversation-summary-dialog'
import { RagTraceDialog } from '@/components/rag-trace/rag-trace-dialog'
import getCaretCoordinates from 'textarea-caret'
import { SlashMenu } from '@/components/chat/slash-menu'
import { globalEventBus } from '@/lib/event-bus'
import { Link, useRouter } from '@/i18n/navigation'
import { coerceOneOf } from '@/lib/one-of'
import { queryKeys } from '@/lib/query-keys'
import { reportClientError } from '@/lib/client-logging'
import { useDocumentView } from '@/store/document-view'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { getAuthCacheScope, subscribeAuthSession } from '@/lib/auth-storage'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'
const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40
const METADATA_FILTER_MODE_VALUES = ['all', 'exclude_qa', 'qa_only', 'custom'] as const
const CHAT_PROMPT_TEMPLATE_PARAMS = { is_active: true }
const EMPTY_PROMPT_TEMPLATES: PromptTemplate[] = []
const BASIC_RETRIEVAL_MODES = ['hybrid', 'vector', 'keyword'] as const

function renderComposerSlash(chunks: ReactNode) {
  return <span className="font-mono text-foreground/80">{chunks}</span>
}

function renderComposerEnter(chunks: ReactNode) {
  return <span className="font-medium text-foreground/80">{chunks}</span>
}

function escapeAttributeSelector(value: string): string {
  if (typeof globalThis.CSS?.escape === 'function') {
    return globalThis.CSS.escape(value)
  }
  return value.replace(/["\\\]]/g, String.raw`\$&`)
}

export function ChatArea({
  initialConversationId,
  initialPrompt,
  initialAutoSendPrompt,
  initialOpenRagSettings,
  onConversationId,
  onPromptConsumed,
}: Readonly<{
  initialConversationId?: string
  initialPrompt?: string
  initialAutoSendPrompt?: boolean
  initialOpenRagSettings?: boolean
  onConversationId?: (conversationId: string) => void
  onPromptConsumed?: () => void
}> = {}) {
  const router = useRouter()
  const t = useTranslations('Chat')
  const activeDocumentId = useDocumentView((state) => state.documentId)
  const summaryMemoryId = 'chat-enable-summary-memory'
  const [inputValue, setInputValue] = useState(() => initialPrompt?.trim() ?? '')
  const [promptTemplateId, setPromptTemplateId] = useState<string>('')
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const datasetPreferenceScope = useSyncExternalStore(subscribeAuthSession, getAuthCacheScope, getAuthCacheScope)
  const datasetPreferenceKey = `ragvia_chat_dataset:${datasetPreferenceScope}`
  const [datasetPreferenceHydrated, setDatasetPreferenceHydrated] = useState(false)
  const [datasetPickerOpen, setDatasetPickerOpen] = useState(false)
  const [showRagSettings, setShowRagSettings] = useState(Boolean(initialOpenRagSettings))
  const [deepReasoningEnabled, setDeepReasoningEnabled] = useState(false)
  const [ragOverrides, setRagOverrides] = useState<ChatRagConfig>({})
  const [metadataFilterMode, setMetadataFilterMode] = useState<'all' | 'exclude_qa' | 'qa_only' | 'custom'>('all')
  const [metadataFilterText, setMetadataFilterText] = useState('')
  const [metadataFilterError, setMetadataFilterError] = useState<string | null>(null)
  const [structuredOutput, setStructuredOutput] = useState(false)
  const [structuredPreset, setStructuredPreset] = useState<string>()
  const [enableLongTermMemory, setEnableLongTermMemory] = useState(false)
  const [enableSummaryMemory, setEnableSummaryMemory] = useState(false)
  const [summaryDialogOpen, setSummaryDialogOpen] = useState(false)
  const [traceDialogOpen, setTraceDialogOpen] = useState(false)
  const [visibleCount, setVisibleCount] = useState(DEFAULT_VISIBLE_MESSAGES)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const advancedRetrievalModeRef = useRef<HTMLDivElement>(null)
  const autoScrollRef = useRef(true)
  const [isNearBottom, setIsNearBottom] = useState(true)
  const [focusedMessageId, setFocusedMessageId] = useState<string | null>(null)
  const scrollRafRef = useRef<number | null>(null)
  const scrollEventRafRef = useRef<number | null>(null)
  const focusMessageTimerRef = useRef<number | null>(null)
  const pendingPrependScrollRef = useRef<{ top: number; height: number } | null>(null)
  const autoSendPromptRef = useRef<string | null>(null)
  // Slash Menu State
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashPos, setSlashPos] = useState({ top: 0, left: 0 })
  const [voiceModeOpen, setVoiceModeOpen] = useState(false)
  const activeDocumentIds = useMemo(() => (activeDocumentId ? [activeDocumentId] : undefined), [activeDocumentId])

  const settingsQuery = useQuery({
    queryKey: queryKeys.settings.snapshot,
    queryFn: () => settingsApi.get(),
    staleTime: 60_000,
  })

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    staleTime: 5 * 60_000,
  })

  const promptTemplatesQuery = useQuery({
    queryKey: queryKeys.prompts.list({ scope: 'all', ...CHAT_PROMPT_TEMPLATE_PARAMS }),
    queryFn: ({ signal }) => promptTemplateApi.listAll(CHAT_PROMPT_TEMPLATE_PARAMS, { signal }),
    staleTime: 60_000,
  })

  const datasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])
  const promptTemplates = promptTemplatesQuery.data?.items ?? EMPTY_PROMPT_TEMPLATES
  const datasetsLoading = datasetsQuery.isPending
  const focusMessageById = useCallback((messageId: string) => {
    const container = scrollContainerRef.current
    if (!container) return false

    const node = container.querySelector<HTMLElement>(`[data-chat-message-id="${escapeAttributeSelector(messageId)}"]`)
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

  useLayoutEffect(() => {
    const savedDatasetId = readClientStorage(datasetPreferenceKey)
    setSelectedDatasetId(savedDatasetId === null ? '' : savedDatasetId)
    setDatasetPreferenceHydrated(true)
  }, [datasetPreferenceKey])

  useEffect(() => {
    if (datasetPreferenceHydrated && selectedDatasetId === '' && datasets[0] !== undefined) {
      setSelectedDatasetId(datasets[0].id)
    }
  }, [datasetPreferenceHydrated, datasets, selectedDatasetId])

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId),
    [datasets, selectedDatasetId],
  )

  const applyMetadataFilterPreset = useCallback((mode: 'all' | 'exclude_qa' | 'qa_only' | 'custom') => {
    setMetadataFilterMode(mode)
    setMetadataFilterError(null)

    if (mode === 'all') {
      setMetadataFilterText('')
      setRagOverrides((previous) => ({ ...previous, metadata_filter: undefined }))
      return
    }

    if (mode === 'exclude_qa') {
      const filter = { file_type: { $ne: 'qa' } }
      setMetadataFilterText(JSON.stringify(filter, null, 2))
      setRagOverrides((previous) => ({ ...previous, metadata_filter: filter }))
      return
    }

    if (mode === 'qa_only') {
      const filter = { file_type: { $eq: 'qa' } }
      setMetadataFilterText(JSON.stringify(filter, null, 2))
      setRagOverrides((previous) => ({ ...previous, metadata_filter: filter }))
    }

    // custom: keep current JSON text; parsing happens in an effect.
  }, [])

  useEffect(() => {
    if (metadataFilterMode !== 'custom') return

    const raw = metadataFilterText.trim()
    if (raw === '') {
      setMetadataFilterError(null)
      setRagOverrides((previous) => ({ ...previous, metadata_filter: undefined }))
      return
    }

    try {
      const parsed = recordSchema.safeParse(JSON.parse(raw))
      if (!parsed.success) {
        setMetadataFilterError(t('metadataFilterObjectError'))
        setRagOverrides((previous) => ({ ...previous, metadata_filter: undefined }))
        return
      }
      setMetadataFilterError(null)
      setRagOverrides((previous) => ({ ...previous, metadata_filter: parsed.data }))
    } catch {
      setMetadataFilterError(t('metadataFilterInvalidJson'))
      setRagOverrides((previous) => ({ ...previous, metadata_filter: undefined }))
    }
  }, [metadataFilterMode, metadataFilterText, t])

  const handleKeyUp = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === '/') {
      const el = e.currentTarget
      const caret = getCaretCoordinates(el, el.selectionEnd)
      const rect = el.getBoundingClientRect()
      setSlashPos({
        top: rect.top + caret.top + 20, // offset
        left: rect.left + caret.left,
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

  const handleSlashSelect = useCallback(
    (cmd: string) => {
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
        setDatasetPickerOpen(false)
        setShowRagSettings(true)
        toast.info(t('openRagConfig'))
        return
      }

      if (cmd === 'clear') {
        setInputValue('')
        toast.info(t('clearInput'))
      }
    },
    [handlePrefillInput, router, t],
  )

  useEffect(() => {
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

  const datasetRagDefaults = selectedDataset?.rag_defaults
  const topK = ragOverrides.top_k ?? datasetRagDefaults?.top_k ?? settingsQuery.data?.rag.retrieval_top_k ?? 5
  const effectiveTopK = deepReasoningEnabled ? Math.max(topK, 8) : topK
  const retrievalMode = deepReasoningEnabled
    ? 'hybrid'
    : (ragOverrides.retrieval_mode ?? datasetRagDefaults?.retrieval_mode ?? 'hybrid')
  const graphEnabled = ragOverrides.use_graph ?? false

  const effectiveChatRagConfig = useMemo<ChatRagConfig>(() => {
    if (!deepReasoningEnabled) return ragOverrides
    return {
      ...ragOverrides,
      top_k: effectiveTopK,
      retrieval_mode: 'hybrid',
      enable_multi_query: true,
      multi_query_count: 3,
      enable_hyde: true,
    }
  }, [deepReasoningEnabled, effectiveTopK, ragOverrides])

  const {
    messages,
    isLoading,
    isGenerating,
    conversationError,
    currentResponse,
    currentCitations,
    currentSteps,
    sendMessage,
    stopGeneration,
    conversationId,
    loadConversation,
  } = useChat({
    conversationId: initialConversationId,
    documentIds: activeDocumentIds,
    datasetId: selectedDatasetId.length === 0 ? undefined : selectedDatasetId,
    promptTemplateId: promptTemplateId.length === 0 ? undefined : promptTemplateId,
    ragConfig: effectiveChatRagConfig,
    structuredOutput,
    structuredPreset,
    enableLongTermMemory,
    enableSummaryMemory,
    onConversationId,
    onError: (error) => {
      reportClientError('Chat request failed', error)
      toast.error(error)
    },
    onUnconfirmedMessage: (message) => {
      setInputValue((current) => (current.length === 0 ? message : current))
    },
  })

  useEffect(() => {
    const unsubscribe = globalEventBus.on('chat:focus-message', ({ messageId }) => {
      const id = messageId.trim()
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
    const prompt = initialPrompt?.trim()
    if (!prompt) return
    setInputValue((prev) => (prev.trim() === '' ? prompt : prev))
  }, [initialPrompt])

  useEffect(() => {
    if (!initialOpenRagSettings) return
    setDatasetPickerOpen(false)
    setShowRagSettings(true)
  }, [initialOpenRagSettings])

  const hasDocumentScope = Boolean(activeDocumentIds?.length)
  const hasChatScope = hasDocumentScope || selectedDataset !== undefined
  const datasetScopeReady = hasDocumentScope || (datasetPreferenceHydrated && !datasetsLoading)
  const topKMaximum = Math.max(50, effectiveTopK, settingsQuery.data?.rag.retrieval_top_k ?? 50)
  const datasetScopeLabel = hasDocumentScope
    ? t('currentDocumentScope')
    : selectedDataset !== undefined
      ? selectedDataset.name.trim() === ''
        ? selectedDataset.id
        : selectedDataset.name
      : selectedDatasetId === ''
        ? t('selectDataset')
        : selectedDatasetId

  const hiddenCount = Math.max(0, messages.length - visibleCount)
  const visibleMessages = useMemo(() => messages.slice(-visibleCount), [messages, visibleCount])

  const submitMessage = useCallback(
    (nextMessage: string) => {
      if (nextMessage.trim() === '' || isLoading) return false
      if (metadataFilterError) {
        toast.error(metadataFilterError)
        return false
      }
      if (!hasChatScope) {
        setShowRagSettings(false)
        setDatasetPickerOpen(true)
        toast.error(
          datasetsLoading
            ? t('datasetScopeLoading')
            : datasetsQuery.isError
              ? t('datasetScopeFailed')
              : selectedDatasetId !== ''
                ? t('datasetScopeMissing')
                : t('datasetScopeRequired'),
        )
        return false
      }
      if (!sendMessage(nextMessage)) return false
      setInputValue((current) => (current.trim() === nextMessage.trim() ? '' : current))
      return true
    },
    [
      datasetsLoading,
      datasetsQuery.isError,
      hasChatScope,
      isLoading,
      metadataFilterError,
      selectedDatasetId,
      sendMessage,
      t,
    ],
  )

  const handleSend = useCallback(() => {
    submitMessage(inputValue)
  }, [inputValue, submitMessage])

  useEffect(() => {
    const unsubscribe = globalEventBus.on('chat:submit', (payload: string) => {
      const prompt = payload.trim()
      if (!prompt) return
      if (submitMessage(prompt)) return
      setInputValue((current) => (current.trim() === '' ? prompt : current))
    })

    return () => unsubscribe()
  }, [submitMessage])

  useEffect(() => {
    const prompt = initialPrompt?.trim()
    if (!initialAutoSendPrompt || !prompt) {
      autoSendPromptRef.current = null
      return
    }
    if (autoSendPromptRef.current === prompt) return
    if (isLoading) return
    if (!datasetScopeReady || !hasChatScope) return

    if (!submitMessage(prompt)) return
    autoSendPromptRef.current = prompt
    onPromptConsumed?.()
  }, [
    datasetScopeReady,
    hasChatScope,
    initialAutoSendPrompt,
    initialPrompt,
    isLoading,
    onPromptConsumed,
    submitMessage,
  ])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  const isWelcomeState = messages.length === 0 && !isLoading && conversationError === undefined
  const insertStarterPrompt = (prompt: string) => {
    setInputValue((current) => (current.trim() === '' ? prompt : `${current}\n\n${prompt}`))
    textareaRef.current?.focus()
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col overflow-hidden bg-background relative transition-colors duration-200 motion-reduce:transition-none">
      <header className="relative z-10 flex h-[52px] shrink-0 items-center justify-between gap-3 border-b border-border/75 bg-background/95 pl-16 pr-4 sm:px-5">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-xs">
          <span className="truncate font-medium">{t('workspaceTitle')}</span>
          <span className="hidden text-muted-foreground sm:inline" aria-hidden="true">
            /
          </span>
          <span className="hidden min-w-0 truncate text-muted-foreground sm:inline">
            {isLoading
              ? t('conversationProcessing')
              : conversationId === undefined
                ? t('newConversationState')
                : t('conversationActive')}
          </span>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-11 shrink-0 gap-2 rounded-lg border border-border/70 bg-card px-2 text-xs font-normal shadow-[0_1px_2px_hsl(var(--foreground)/0.04)] hover:border-foreground/20 hover:bg-surface-2 disabled:shadow-none md:h-8"
          disabled={!conversationId}
          onClick={() => setTraceDialogOpen(true)}
          title={conversationId ? t('viewRagTrace') : t('sendMessageFirst')}
        >
          <Route className="size-3.5" aria-hidden="true" />
          {t('ragTraceEntry')}
        </Button>
      </header>
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className={cn(
          messageStyles.studioMessages,
          'flex-1 overflow-y-auto overscroll-contain px-4 pb-20 scroll-smooth no-scrollbar sm:pb-8 md:px-6',
          isWelcomeState && 'hidden',
        )}
        role="log"
        aria-live="polite"
        aria-busy={isLoading}
      >
        <div
          className={cn(
            'mx-auto flex min-h-full w-full flex-col py-8 md:py-10',
            isWelcomeState ? 'max-w-6xl' : 'max-w-[44rem]',
          )}
        >
          {conversationError !== undefined && initialConversationId !== undefined && (
            <div
              role="alert"
              className="mb-4 flex items-center justify-between gap-4 rounded-lg border border-border p-4"
            >
              <p className="text-sm text-destructive">{conversationError}</p>
              <Button
                type="button"
                variant="outline"
                disabled={isLoading}
                onClick={() => void loadConversation(initialConversationId)}
              >
                {t('retryConversation')}
              </Button>
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
                  focusedMessageId === message.id &&
                    'ring-2 ring-primary/35 ring-offset-2 ring-offset-background shadow-lg shadow-primary/10',
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
        <div className="absolute right-6 bottom-24 z-20 animate-scale-fade-in">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={jumpToBottom}
            className="rounded-full shadow-md border border-border/60"
            aria-label={t('jumpToLatestMessage')}
            title={t('jumpToLatestMessage')}
          >
            <ArrowDown className="size-4 mr-1" />
            {t('jumpToLatest')}
          </Button>
        </div>
      )}

      <div
        className={cn(
          'relative z-10',
          isWelcomeState
            ? "flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain bg-[radial-gradient(hsl(var(--foreground)/0.065)_1px,transparent_1px)] px-[clamp(1rem,4%,2.5rem)] py-6 [background-size:20px_20px] before:flex-[0.38] before:content-[''] after:flex-[0.62] after:content-['']"
            : 'px-4 pt-2 pb-[calc(env(safe-area-inset-bottom)+1.5rem)] md:px-6',
        )}
      >
        <div
          className={cn(
            '@container mx-auto w-full shrink-0',
            isWelcomeState ? 'max-w-[760px]' : 'max-w-[44rem] space-y-2.5',
          )}
        >
          {isWelcomeState ? <WelcomeScreen /> : null}

          <div
            className={cn(
              '@container relative rounded-2xl border border-border bg-card shadow-[0_2px_8px_hsl(var(--foreground)/0.05),0_14px_30px_-14px_hsl(var(--foreground)/0.1)] transition-[border-color,box-shadow] duration-200 hover:border-foreground/22 focus-within:border-foreground/30 focus-within:ring-[3px] focus-within:ring-accent/12 focus-within:shadow-[0_4px_16px_hsl(var(--foreground)/0.08)] dark:shadow-[0_4px_20px_rgba(0,0,0,0.38)] dark:focus-within:border-foreground/35 motion-reduce:transition-none',
            )}
          >
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
              aria-describedby={!hasChatScope && inputValue.trim() ? 'chat-composer-scope-hint' : undefined}
              autoFocus
              className={cn(
                'block w-full resize-none outline-none max-h-[200px] bg-transparent text-base leading-7 placeholder:text-muted-foreground no-scrollbar text-foreground',
                isWelcomeState
                  ? 'min-h-[72px] rounded-t-2xl px-5 pb-3 pt-4 sm:min-h-[88px] sm:px-6 sm:pb-4 sm:pt-5'
                  : 'min-h-[88px] rounded-t-2xl px-5 pb-3 pt-4',
              )}
              rows={1}
            />

            <div
              className={cn(
                'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-t border-border/55 pt-2 @min-[30rem]:flex',
                isWelcomeState ? 'px-2 pb-2 sm:px-3 sm:pb-3' : 'px-3 pb-3 sm:px-4',
              )}
            >
              <div className="col-span-2 flex min-w-0 flex-wrap items-center gap-2 @min-[30rem]:flex-1">
                <div className="min-w-0 max-w-[50%] @min-[30rem]:max-w-[280px]">
                  <DatasetScopePicker
                    open={datasetPickerOpen}
                    onOpenChange={(open) => {
                      setDatasetPickerOpen(open)
                      if (open) setShowRagSettings(false)
                    }}
                    datasets={datasets}
                    selectedId={selectedDatasetId}
                    label={datasetScopeLabel}
                    documentScoped={hasDocumentScope}
                    loading={datasetsLoading}
                    fetching={datasetsQuery.isFetching}
                    error={datasetsQuery.error}
                    onSelect={(datasetId) => {
                      setSelectedDatasetId(datasetId)
                      writeClientStorage(datasetPreferenceKey, datasetId)
                    }}
                    onRetry={() => {
                      void datasetsQuery.refetch()
                    }}
                  />
                </div>

                <Popover
                  open={showRagSettings}
                  onOpenChange={(open) => {
                    setShowRagSettings(open)
                    if (open) setDatasetPickerOpen(false)
                  }}
                >
                  <PopoverTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-11 shrink-0 gap-1.5 rounded-lg px-2 text-xs text-muted-foreground shadow-none data-[state=open]:bg-muted data-[state=open]:text-foreground @min-[30rem]:h-8"
                      title={t('retrievalSettings')}
                      aria-label={t('retrievalSettings')}
                      aria-controls="chat-retrieval-settings"
                    >
                      <Settings2 className="size-4" aria-hidden="true" />
                      <span className="max-w-24 truncate @min-[30rem]:max-w-40">
                        {t(`retrievalModes.${retrievalMode}`)}
                        {graphEnabled && <> · {t('graphRetrieval')}</>}
                      </span>
                      <span className="font-mono text-[11px] tabular-nums">Top {effectiveTopK}</span>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent
                    id="chat-retrieval-settings"
                    aria-labelledby="chat-retrieval-settings-title"
                    side="bottom"
                    align="end"
                    sideOffset={8}
                    avoidCollisions
                    collisionPadding={16}
                    className="max-h-[min(34rem,var(--radix-popover-content-available-height))] w-80 max-w-[calc(100vw-3rem)] space-y-4 overflow-y-auto overscroll-contain rounded-xl p-4 pb-5"
                  >
                    <h2 id="chat-retrieval-settings-title" className="text-sm font-medium">
                      {t('retrievalSettings')}
                    </h2>
                    <fieldset disabled={deepReasoningEnabled} className="space-y-2">
                      <legend className="mb-2 text-xs text-muted-foreground">{t('retrievalMode')}</legend>
                      <div className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
                        {BASIC_RETRIEVAL_MODES.map((mode) => (
                          <label key={mode} className="relative cursor-pointer text-center">
                            <input
                              type="radio"
                              name="chat-basic-retrieval-mode"
                              value={mode}
                              checked={retrievalMode === mode}
                              onChange={() => setRagOverrides((previous) => ({ ...previous, retrieval_mode: mode }))}
                              className="peer sr-only"
                            />
                            <span className="block rounded-md px-2 py-2 text-xs text-muted-foreground peer-checked:bg-card peer-checked:text-foreground peer-checked:shadow-subtle peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-disabled:cursor-not-allowed peer-disabled:opacity-50">
                              {t(`retrievalModes.${mode}`)}
                            </span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <Label htmlFor="chat-retrieval-count" className="text-xs font-normal">
                          {t('topK')}
                        </Label>
                        <output
                          htmlFor="chat-retrieval-count"
                          className="rounded-md bg-muted px-2 py-1 font-mono text-xs tabular-nums"
                        >
                          {effectiveTopK}
                        </output>
                      </div>
                      <input
                        id="chat-retrieval-count"
                        type="range"
                        min={1}
                        max={topKMaximum}
                        step={1}
                        value={effectiveTopK}
                        disabled={deepReasoningEnabled}
                        onChange={(event) => {
                          const topK = event.currentTarget.valueAsNumber
                          setRagOverrides((previous) => ({ ...previous, top_k: topK }))
                        }}
                        aria-describedby="chat-retrieval-count-range"
                        className="h-8 w-full cursor-pointer accent-accent focus-ring disabled:cursor-not-allowed disabled:opacity-50"
                      />
                      <p
                        id="chat-retrieval-count-range"
                        className="flex justify-between font-mono text-[11px] tabular-nums text-muted-foreground"
                      >
                        <span>1</span>
                        <span>{topKMaximum}</span>
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="chat-metadata-filter" className="text-sm font-normal">
                        {t('metadataFilter')}
                      </Label>
                      <Select
                        value={metadataFilterMode}
                        onValueChange={(value) =>
                          applyMetadataFilterPreset(coerceOneOf(METADATA_FILTER_MODE_VALUES, value, 'all'))
                        }
                      >
                        <SelectTrigger id="chat-metadata-filter" className="h-11 text-base shadow-none sm:text-sm">
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
                          <Label htmlFor="chat-custom-filter" className="sr-only">
                            {t('customMetadataFilter')}
                          </Label>
                          <textarea
                            id="chat-custom-filter"
                            value={metadataFilterText}
                            onChange={(event) => setMetadataFilterText(event.target.value)}
                            placeholder={t.raw('metadataFilterExampleHandbook')}
                            aria-invalid={Boolean(metadataFilterError)}
                            aria-describedby={metadataFilterError ? 'chat-custom-filter-error' : undefined}
                            className="min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-base leading-6 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 aria-[invalid=true]:border-destructive/60 sm:text-sm"
                          />
                          {metadataFilterError ? (
                            <p
                              id="chat-custom-filter-error"
                              role="alert"
                              className="text-xs leading-5 text-destructive"
                            >
                              {metadataFilterError}
                            </p>
                          ) : null}
                          <details className="group/details">
                            <summary className="cursor-pointer select-none py-2 text-xs text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                              {t('supportedOperatorsExamples')}
                            </summary>
                            <div className="mt-1 space-y-2 break-words text-xs leading-5 text-muted-foreground">
                              <div className="font-mono text-foreground/80">{t('supportedOperatorsList')}</div>
                              <div>{t('supportedOperatorsHint')}</div>
                              <div className="font-mono text-foreground/80">{t.raw('metadataFilterExampleQa')}</div>
                              <div className="font-mono text-foreground/80">
                                {t.raw('metadataFilterExampleHandbook')}
                              </div>
                            </div>
                          </details>
                        </div>
                      ) : null}
                    </div>

                    <details
                      className="group/advanced border-t border-border pt-2"
                      onToggle={(event) => {
                        if (event.currentTarget.open) {
                          advancedRetrievalModeRef.current?.scrollIntoView({ block: 'nearest' })
                        }
                      }}
                    >
                      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-md text-sm font-medium outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                        {t('advancedSettings')}
                        <ChevronDown
                          className="size-4 text-muted-foreground transition-transform duration-150 group-open/advanced:rotate-180 motion-reduce:transition-none"
                          aria-hidden="true"
                        />
                      </summary>
                      <div className="space-y-3 pt-2">
                        <div ref={advancedRetrievalModeRef} className="space-y-2 scroll-my-1">
                          <Label htmlFor="chat-other-retrieval-mode" className="text-sm font-normal">
                            {t('allRetrievalModes')}
                          </Label>
                          <Select
                            value={retrievalMode}
                            disabled={deepReasoningEnabled}
                            onValueChange={(mode) =>
                              setRagOverrides((previous) => ({ ...previous, retrieval_mode: mode }))
                            }
                          >
                            <SelectTrigger id="chat-other-retrieval-mode" className="h-11 text-sm shadow-none">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {['hybrid', 'vector', 'keyword', 'auto', 'mmr'].map((mode) => (
                                <SelectItem key={mode} value={mode}>
                                  {t(`retrievalModes.${mode}`)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        {promptTemplates.length > 0 && (
                          <div className="space-y-2">
                            <Label htmlFor="chat-prompt-template" className="text-sm font-normal">
                              {t('selectPromptTemplate')}
                            </Label>
                            <Select
                              value={promptTemplateId === '' ? SELECT_DEFAULT_VALUE : promptTemplateId}
                              onValueChange={(value) =>
                                setPromptTemplateId(value === SELECT_DEFAULT_VALUE ? '' : value)
                              }
                            >
                              <SelectTrigger id="chat-prompt-template" className="h-11 text-sm shadow-none">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={SELECT_DEFAULT_VALUE}>{t('defaultTemplate')}</SelectItem>
                                {promptTemplates.map((template) => (
                                  <SelectItem key={template.id} value={template.id}>
                                    {template.name}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        )}
                        <RetrievalSettingToggle
                          id="chat-extended-retrieval"
                          label={t('extendedRetrieval')}
                          description={t('extendedRetrievalHint')}
                          checked={deepReasoningEnabled}
                          onCheckedChange={setDeepReasoningEnabled}
                        />
                        <RetrievalSettingToggle
                          id="chat-use-knowledge-graph"
                          label={t('useKnowledgeGraph')}
                          description={t('knowledgeGraphHint')}
                          checked={graphEnabled}
                          onCheckedChange={(checked) =>
                            setRagOverrides((previous) => ({ ...previous, use_graph: checked }))
                          }
                        />
                        <RetrievalSettingToggle
                          id="chat-enable-memory"
                          label={t('enableLongTermMemory')}
                          description={t('longTermMemoryHint')}
                          checked={enableLongTermMemory}
                          onCheckedChange={setEnableLongTermMemory}
                        />
                        <RetrievalSettingToggle
                          id={summaryMemoryId}
                          label={t('enableSummaryMemory')}
                          checked={enableSummaryMemory}
                          onCheckedChange={setEnableSummaryMemory}
                          action={
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-11 rounded-lg px-2 text-xs shadow-none hover:bg-muted"
                              onClick={() => setSummaryDialogOpen(true)}
                              disabled={!conversationId}
                              title={conversationId ? t('viewOrUpdateSummary') : t('sendMessageFirst')}
                            >
                              {t('viewSummary')}
                            </Button>
                          }
                        />
                        <RetrievalSettingToggle
                          id="chat-structured-output"
                          label={t('structuredOutput')}
                          description={t('structuredOutputHint')}
                          checked={structuredOutput}
                          onCheckedChange={setStructuredOutput}
                        />
                        {structuredOutput && (
                          <div className="space-y-2 pb-1">
                            <Label htmlFor="chat-output-preset" className="text-sm font-normal">
                              {t('structuredPresetLabel')}
                            </Label>
                            <Select
                              value={structuredPreset ?? SELECT_DEFAULT_VALUE}
                              onValueChange={(value) =>
                                setStructuredPreset(value === SELECT_DEFAULT_VALUE ? undefined : value)
                              }
                            >
                              <SelectTrigger id="chat-output-preset" className="h-11 text-base shadow-none sm:text-sm">
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
                    </details>
                  </PopoverContent>
                </Popover>
              </div>

              <div className="col-span-2 ml-auto flex shrink-0 items-center gap-1 sm:gap-2">
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => setVoiceModeOpen(true)}
                  className="size-11 rounded-full text-muted-foreground shadow-none hover:bg-muted hover:text-foreground sm:size-10"
                  title={t('voiceMode')}
                  aria-label={t('voiceMode')}
                >
                  <Mic className="size-5" aria-hidden="true" />
                </Button>

                {isGenerating ? (
                  <Button
                    type="button"
                    size="icon"
                    onClick={stopGeneration}
                    className="size-11 rounded-full bg-destructive/10 text-destructive shadow-none hover:bg-destructive/20 hover:text-destructive sm:size-10"
                    title={t('stopGeneration')}
                    aria-label={t('stopGeneration')}
                  >
                    <StopCircle className="size-4" aria-hidden="true" />
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="icon"
                    onClick={handleSend}
                    disabled={isLoading || !inputValue.trim() || Boolean(metadataFilterError)}
                    className="size-11 rounded-full bg-accent text-accent-foreground shadow-[0_1px_2px_hsl(var(--foreground)/0.12),inset_0_1px_0_hsl(var(--accent-foreground)/0.16)] transition-[background-color,box-shadow] duration-150 hover:bg-accent/90 hover:shadow-[0_2px_5px_hsl(var(--foreground)/0.14)] disabled:bg-muted disabled:text-muted-foreground/60 disabled:opacity-100 disabled:shadow-none motion-reduce:transition-none sm:size-10"
                    title={t('composerSendHint')}
                    aria-label={t('send')}
                    aria-describedby={!hasChatScope && inputValue.trim() ? 'chat-composer-scope-hint' : undefined}
                  >
                    <ArrowUp className="size-5" aria-hidden="true" />
                  </Button>
                )}
              </div>
            </div>
          </div>

          {!hasChatScope && inputValue.trim() ? (
            <p id="chat-composer-scope-hint" role="status" className="sr-only">
              {datasetsLoading
                ? t('datasetScopeLoading')
                : datasetsQuery.isError && datasets.length === 0
                  ? t('datasetScopeFailed')
                  : datasets.length === 0
                    ? t('composerScopeEmpty')
                    : t('composerScopeRequired')}
            </p>
          ) : null}

          {!hasDocumentScope && selectedDataset?.ingestion_summary?.total_chunks === 0 ? (
            <p
              role="status"
              className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/80 bg-muted/45 px-3.5 py-2 text-xs text-muted-foreground"
            >
              <span className="inline-flex items-center gap-2">
                <span className="size-1.5 shrink-0 rounded-full bg-warning" aria-hidden="true" />
                {t('composerNoTextChunks')}
              </span>
              <Link
                href={`/knowledge?dataset=${selectedDataset.id}`}
                className="inline-flex min-h-8 items-center gap-1 rounded-sm text-foreground hover:underline underline-offset-4 focus-ring"
              >
                {t('inspectDocuments')}
                <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            </p>
          ) : null}

          {!isWelcomeState ? (
            <p className="hidden text-[11px] text-center text-muted-foreground/75 sm:block">
              {t.rich('composerHelpText', {
                slash: renderComposerSlash,
                enter: renderComposerEnter,
                shiftEnter: renderComposerEnter,
              })}
            </p>
          ) : null}
          {isWelcomeState && <StarterPrompts onSelect={insertStarterPrompt} />}
        </div>
      </div>

      <SlashMenu open={slashOpen} onOpenChange={setSlashOpen} onSelect={handleSlashSelect} position={slashPos} />

      <VoiceModeOverlay
        isOpen={voiceModeOpen}
        onClose={() => setVoiceModeOpen(false)}
        onSend={(text) => {
          if (submitMessage(text)) {
            setVoiceModeOpen(false)
          }
        }}
      />

      <ConversationSummaryDialog
        open={summaryDialogOpen}
        onOpenChange={setSummaryDialogOpen}
        conversationId={conversationId}
      />
      <RagTraceDialog
        open={traceDialogOpen}
        onOpenChange={setTraceDialogOpen}
        conversationId={conversationId ?? null}
      />
    </div>
  )
}

function RetrievalSettingToggle({
  id,
  label,
  description,
  checked,
  onCheckedChange,
  action,
}: Readonly<{
  id: string
  label: string
  description?: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  action?: ReactNode
}>) {
  return (
    <div className="flex min-h-11 items-center gap-2">
      <Label
        htmlFor={id}
        className="flex min-h-11 min-w-0 flex-1 cursor-pointer flex-col justify-center gap-1 py-1 text-sm font-normal leading-5"
      >
        <span id={`${id}-label`}>{label}</span>
        {description ? (
          <span id={`${id}-hint`} className="text-xs font-normal leading-5 text-muted-foreground">
            {description}
          </span>
        ) : null}
      </Label>
      {action}
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        aria-labelledby={`${id}-label`}
        aria-describedby={description ? `${id}-hint` : undefined}
        className="motion-reduce:transition-none [&>span]:motion-reduce:transition-none"
      />
    </div>
  )
}

function WelcomeScreen() {
  const t = useTranslations('Chat')

  return (
    <header className="mb-6 text-center sm:mb-7">
      <div className="flex items-center justify-center gap-3">
        <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl border border-border/80 bg-card shadow-[0_1px_3px_hsl(var(--foreground)/0.05)] sm:size-11">
          <BrandLogo variant="mark" className="size-7 shrink-0 sm:size-8" decorative priority />
        </span>
        <h1 className="text-xl font-medium leading-8 text-foreground sm:text-[24px]">{t('welcomeTitle')}</h1>
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{t('welcomeSubtitle')}</p>
    </header>
  )
}
