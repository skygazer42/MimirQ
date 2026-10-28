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
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react'
import { useTranslations } from 'next-intl'
import { ArrowUp, StopCircle, Dataset as Database, FileText, Settings2, Mic, ArrowDown, Route, ChevronDown, ChevronLeft, Check, X, GripHorizontal, ArrowRight } from '@/components/icons'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'
import { useChat } from '@/hooks/use-chat'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { datasetApi, promptTemplateApi, settingsApi } from '@/lib/api'
import { ChatMessageItem } from '@/components/chat/message-item'
import { BrandLogo } from '@/components/brand-logo'
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
import { RagTraceDialog } from '@/components/rag-trace/rag-trace-dialog'
import getCaretCoordinates from 'textarea-caret'
import { SlashMenu } from '@/components/chat/slash-menu'
import { globalEventBus } from '@/lib/event-bus'
import { useRouter } from '@/i18n/navigation'
import { coerceOneOf } from '@/lib/one-of'
import { queryKeys } from '@/lib/query-keys'
import { reportClientError } from '@/lib/client-logging'
import { useDocumentView } from '@/store/document-view'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'
const DEFAULT_VISIBLE_MESSAGES = 80
const LOAD_MORE_STEP = 40
const METADATA_FILTER_MODE_VALUES = ['all', 'exclude_qa', 'qa_only', 'custom'] as const
const CHAT_PROMPT_TEMPLATE_PARAMS = { is_active: true, limit: 50 }
const RAG_SETTINGS_VIEWPORT_MARGIN = 12
const RAG_SETTINGS_KEYBOARD_MOVE_STEP = 12

type RagSettingsOffset = { x: number; y: number }
type RagSettingsDragState = {
  pointerId: number
  startClientX: number
  startClientY: number
  startOffset: RagSettingsOffset
  baseRect: { left: number; top: number; width: number; height: number }
}

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
  return String(value).replace(/["\\\]]/g, String.raw`\$&`)
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
  const [inputValue, setInputValue] = useState(() => (initialPrompt || '').trim())
  const [promptTemplateId, setPromptTemplateId] = useState<string>('')
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [showConversationTools, setShowConversationTools] = useState(Boolean(initialOpenRagSettings))
  const [showRagSettings, setShowRagSettings] = useState(Boolean(initialOpenRagSettings))
  const [deepReasoningEnabled, setDeepReasoningEnabled] = useState(false)
  const [hasSystemRagDefaults, setHasSystemRagDefaults] = useState(false)
  const [ragConfigDirty, setRagConfigDirty] = useState(false)
  const [ragConfig, setRagConfig] = useState<{
    top_k: number
    score_threshold: number
    retrieval_mode: string
    use_graph: boolean
    enable_multi_query: boolean
    enable_hyde: boolean
    metadata_filter?: Record<string, unknown> | null
  }>(() => ({
    top_k: 5,
    score_threshold: 0.7,
    retrieval_mode: 'hybrid',
    use_graph: false,
    enable_multi_query: false,
    enable_hyde: false,
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
  const [traceDialogOpen, setTraceDialogOpen] = useState(false)
  const [ragSettingsOffset, setRagSettingsOffset] = useState<RagSettingsOffset>({ x: 0, y: 0 })
  const [isRagSettingsDragging, setIsRagSettingsDragging] = useState(false)
  const [visibleCount, setVisibleCount] = useState(DEFAULT_VISIBLE_MESSAGES)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const ragSettingsPanelRef = useRef<HTMLDivElement>(null)
  const ragSettingsTriggerRef = useRef<HTMLButtonElement>(null)
  const ragSettingsBackRef = useRef<HTMLButtonElement>(null)
  const wasRagSettingsOpenRef = useRef(Boolean(initialOpenRagSettings))
  const ragSettingsDragRef = useRef<RagSettingsDragState | null>(null)
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
  const activeDocumentIds = useMemo(
    () => (activeDocumentId ? [activeDocumentId] : undefined),
    [activeDocumentId]
  )

  const settingsQuery = useQuery({
    queryKey: queryKeys.settings.snapshot,
    queryFn: () => settingsApi.get(),
    staleTime: 60_000,
  })

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive({ purpose: 'chat-rag-settings' }),
    queryFn: () => datasetApi.listAll(),
    staleTime: 60_000,
  })

  const promptTemplatesQuery = useQuery({
    queryKey: queryKeys.prompts.list(CHAT_PROMPT_TEMPLATE_PARAMS),
    queryFn: async () => {
      const response = await promptTemplateApi.list(CHAT_PROMPT_TEMPLATE_PARAMS)
      return response.items || []
    },
    staleTime: 60_000,
  })

  const datasets = useMemo(
    () => datasetsQuery.data ?? [],
    [datasetsQuery.data]
  )
  const promptTemplates = useMemo(() => promptTemplatesQuery.data || [], [promptTemplatesQuery.data])
  const datasetsLoading = datasetsQuery.isLoading
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

  useEffect(() => {
    const system = settingsQuery.data
    if (!system || hasSystemRagDefaults) return

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
  }, [hasSystemRagDefaults, settingsQuery.data])

  useEffect(() => {
    setSelectedDatasetId((current) => {
      const trimmed = String(current || '').trim()
      if (trimmed && datasets.some((dataset) => dataset.id === trimmed)) return trimmed
      return String(datasets[0]?.id || '')
    })
  }, [datasets])

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId),
    [datasets, selectedDatasetId]
  )

  const clampRagSettingsOffset = useCallback(
    (
      offset: RagSettingsOffset,
      baseRect: RagSettingsDragState['baseRect']
    ): RagSettingsOffset => {
      if (globalThis.window === undefined) return offset

      const maxX =
        globalThis.window.innerWidth -
        RAG_SETTINGS_VIEWPORT_MARGIN -
        baseRect.left -
        baseRect.width
      const minX = RAG_SETTINGS_VIEWPORT_MARGIN - baseRect.left
      const maxY =
        globalThis.window.innerHeight -
        RAG_SETTINGS_VIEWPORT_MARGIN -
        baseRect.top -
        baseRect.height
      const minY = RAG_SETTINGS_VIEWPORT_MARGIN - baseRect.top
      const safeMaxX = Math.max(minX, maxX)
      const safeMaxY = Math.max(minY, maxY)

      return {
        x: Math.min(Math.max(offset.x, minX), safeMaxX),
        y: Math.min(Math.max(offset.y, minY), safeMaxY),
      }
    },
    []
  )

  const getRagSettingsBaseRect = useCallback(() => {
    const panel = ragSettingsPanelRef.current
    if (!panel) return null

    const rect = panel.getBoundingClientRect()
    return {
      left: rect.left - ragSettingsOffset.x,
      top: rect.top - ragSettingsOffset.y,
      width: rect.width,
      height: rect.height,
    }
  }, [ragSettingsOffset.x, ragSettingsOffset.y])

  const resetRagSettingsPosition = useCallback(() => {
    setRagSettingsOffset({ x: 0, y: 0 })
  }, [])

  const beginRagSettingsDrag = useCallback(
    (event: PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0 && event.pointerType !== 'touch') return

      const baseRect = getRagSettingsBaseRect()
      if (!baseRect) return

      ragSettingsDragRef.current = {
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startOffset: ragSettingsOffset,
        baseRect,
      }
      setIsRagSettingsDragging(true)
      event.currentTarget.setPointerCapture(event.pointerId)
      event.preventDefault()
    },
    [getRagSettingsBaseRect, ragSettingsOffset]
  )

  const moveRagSettingsDrag = useCallback(
    (event: PointerEvent<HTMLButtonElement>) => {
      const drag = ragSettingsDragRef.current
      if (drag?.pointerId !== event.pointerId) return

      const nextOffset = {
        x: drag.startOffset.x + event.clientX - drag.startClientX,
        y: drag.startOffset.y + event.clientY - drag.startClientY,
      }
      setRagSettingsOffset(clampRagSettingsOffset(nextOffset, drag.baseRect))
      event.preventDefault()
    },
    [clampRagSettingsOffset]
  )

  const endRagSettingsDrag = useCallback((event: PointerEvent<HTMLButtonElement>) => {
    const drag = ragSettingsDragRef.current
    if (drag?.pointerId !== event.pointerId) return
    ragSettingsDragRef.current = null
    setIsRagSettingsDragging(false)
  }, [])

  const handleRagSettingsDragKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>) => {
      const arrowDelta: Record<string, RagSettingsOffset> = {
        ArrowUp: { x: 0, y: -RAG_SETTINGS_KEYBOARD_MOVE_STEP },
        ArrowDown: { x: 0, y: RAG_SETTINGS_KEYBOARD_MOVE_STEP },
        ArrowLeft: { x: -RAG_SETTINGS_KEYBOARD_MOVE_STEP, y: 0 },
        ArrowRight: { x: RAG_SETTINGS_KEYBOARD_MOVE_STEP, y: 0 },
      }

      if (event.key === 'Home') {
        resetRagSettingsPosition()
        event.preventDefault()
        return
      }

      const delta = arrowDelta[event.key]
      if (!delta) return

      const baseRect = getRagSettingsBaseRect()
      if (!baseRect) return

      const multiplier = event.shiftKey ? 3 : 1
      setRagSettingsOffset((current) =>
        clampRagSettingsOffset(
          {
            x: current.x + delta.x * multiplier,
            y: current.y + delta.y * multiplier,
          },
          baseRect
        )
      )
      event.preventDefault()
    },
    [clampRagSettingsOffset, getRagSettingsBaseRect, resetRagSettingsPosition]
  )

  useEffect(() => {
    if (showRagSettings) return
    ragSettingsDragRef.current = null
    setIsRagSettingsDragging(false)
  }, [showRagSettings])

  useEffect(() => {
    const wasSettingsOpen = wasRagSettingsOpenRef.current
    wasRagSettingsOpenRef.current = showRagSettings
    if (!showConversationTools) return

    if (showRagSettings) {
      ragSettingsBackRef.current?.focus()
    } else if (wasSettingsOpen) {
      ragSettingsTriggerRef.current?.focus()
    }
  }, [showConversationTools, showRagSettings])

  useEffect(() => {
    if (!showRagSettings) return

    const handleResize = () => {
      const baseRect = getRagSettingsBaseRect()
      if (!baseRect) return
      setRagSettingsOffset((current) => clampRagSettingsOffset(current, baseRect))
    }

    globalThis.window.addEventListener('resize', handleResize)
    return () => globalThis.window.removeEventListener('resize', handleResize)
  }, [clampRagSettingsOffset, getRagSettingsBaseRect, showRagSettings])

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
      setShowConversationTools(true)
      setShowRagSettings(true)
      toast.info(t('openRagConfig'))
      return
    }

    if (cmd === 'clear') {
      setInputValue('')
      toast.info(t('clearInput'))
    }
  }, [handlePrefillInput, router, t])

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

  const effectiveChatRagConfig = useMemo(() => {
    const baseConfig = ragConfigDirty || hasSystemRagDefaults ? ragConfig : {
      enable_multi_query: ragConfig.enable_multi_query,
      enable_hyde: ragConfig.enable_hyde,
    }

    if (!deepReasoningEnabled) return baseConfig

    const topK = Number.isFinite(ragConfig.top_k) ? ragConfig.top_k : 5
    return {
      ...baseConfig,
      top_k: Math.max(topK, 8),
      retrieval_mode: 'hybrid',
      enable_multi_query: true,
      multi_query_count: 3,
      enable_hyde: true,
    }
  }, [deepReasoningEnabled, hasSystemRagDefaults, ragConfig, ragConfigDirty])

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
    datasetId: activeDocumentIds?.length ? undefined : selectedDatasetId || undefined,
    promptTemplateId: promptTemplateId || undefined,
    ragConfig: effectiveChatRagConfig,
    structuredOutput,
    structuredPreset: structuredPreset || undefined,
    enableLongTermMemory,
    enableSummaryMemory,
    onConversationId,
    onError: (error) => {
      reportClientError('Chat request failed', error)
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
          reportClientError('Failed to load conversation', err)
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
    if (!initialOpenRagSettings) return
    setShowConversationTools(true)
    setShowRagSettings(true)
  }, [initialOpenRagSettings])

  const selectedPromptTemplate = useMemo(
    () => promptTemplates.find((template) => template.id === promptTemplateId),
    [promptTemplates, promptTemplateId]
  )
  const hasDocumentScope = Boolean(activeDocumentIds?.length)
  const hasChatScope = hasDocumentScope || Boolean(selectedDatasetId)
  const datasetScopeReady = hasDocumentScope || !datasetsLoading
  const conversationToolsScopeLabel = hasDocumentScope
    ? t('currentDocumentScope')
    : selectedDataset?.name || (datasetsLoading ? t('datasetScopeLoading') : t('selectDataset'))

  const hiddenCount = Math.max(0, messages.length - visibleCount)
  const visibleMessages = useMemo(
    () => messages.slice(-visibleCount),
    [messages, visibleCount]
  )

  const submitMessage = useCallback((nextMessage: string) => {
    if (!nextMessage.trim() || isLoading) return false
    if (!hasChatScope) {
      setShowRagSettings(false)
      setShowConversationTools(true)
      toast.error(datasetsLoading ? t('datasetScopeLoading') : t('datasetScopeRequired'))
      return false
    }
    sendMessage(nextMessage)
    return true
  }, [datasetsLoading, hasChatScope, isLoading, sendMessage, t])

  const handleSend = useCallback(() => {
    if (!submitMessage(inputValue)) return
    setInputValue('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [inputValue, submitMessage])

  useEffect(() => {
    const unsubscribe = globalEventBus.on('chat:submit', (payload: string) => {
      const prompt = payload.trim()
      if (!prompt) return
      if (submitMessage(prompt)) {
        setInputValue('')
        if (textareaRef.current) textareaRef.current.style.height = 'auto'
        return
      }
      setInputValue(prompt)
    })

    return () => unsubscribe()
  }, [submitMessage])

  useEffect(() => {
    const p = (initialPrompt || '').trim()
    if (!initialAutoSendPrompt || !p) return
    if (autoSendPromptRef.current) return
    if (isLoading) return
    if (!datasetScopeReady || !hasChatScope) return

    if (!submitMessage(p)) return
    autoSendPromptRef.current = true
    setInputValue('')
    onPromptConsumed?.()
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }, [datasetScopeReady, hasChatScope, initialAutoSendPrompt, initialPrompt, isLoading, onPromptConsumed, submitMessage])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  const isWelcomeState = messages.length === 0 && !isLoading

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-background relative transition-colors duration-200 motion-reduce:transition-none">
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className={cn(
          'flex-1 overflow-y-auto overscroll-contain px-4 pb-4 scroll-smooth no-scrollbar md:px-6',
          isWelcomeState && 'hidden'
        )}
        role="log"
        aria-live="polite"
        aria-busy={isLoading}
      >
        <div
          className={cn(
            'mx-auto flex min-h-full w-full flex-col py-8 md:py-10',
            isWelcomeState ? 'max-w-6xl' : 'max-w-[44rem]'
          )}
        >
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
          'z-10',
          isWelcomeState
            ? 'flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-5 py-8 sm:px-8 sm:pb-24 sm:pt-12 md:px-10'
            : 'px-4 pt-2 pb-[calc(env(safe-area-inset-bottom)+1.5rem)] md:px-6'
        )}
      >
        <div
          className={cn(
            'mx-auto w-full',
            isWelcomeState ? 'my-auto max-w-3xl xl:max-w-4xl' : 'max-w-[44rem] space-y-2.5'
          )}
        >
          <Popover
            open={showConversationTools}
            onOpenChange={(open) => {
              setShowConversationTools(open)
              if (!open) setShowRagSettings(false)
            }}
          >
            {isWelcomeState ? <WelcomeScreen /> : null}
            <PopoverContent
              id="chat-conversation-tools"
              aria-label={showRagSettings ? t('retrievalSettings') : t('scopeAndRetrieval')}
              align="start"
              side={showRagSettings ? 'top' : 'bottom'}
              sideOffset={8}
              collisionPadding={12}
              className={cn(
                showRagSettings
                  ? 'w-[min(23rem,calc(100vw-1.5rem))] overflow-visible border-0 bg-transparent p-0 shadow-none [box-shadow:none]'
                  : 'max-h-[var(--radix-popover-content-available-height)] w-72 max-w-[calc(100vw-2rem)] overflow-y-auto rounded-xl p-2'
              )}
            >
              {!showRagSettings ? (
              <>
              <div className="px-2 pb-2 pt-1 text-xs font-medium text-muted-foreground">{t('datasetMenuTitle')}</div>
              {hasDocumentScope ? (
                <p className="px-2 pb-2 text-xs leading-5 text-muted-foreground">{t('datasetScopeHint')}</p>
              ) : null}
              <div className="max-h-60 space-y-1 overflow-y-auto overscroll-contain">
                {datasetsLoading ? (
                  <div role="status" className="px-2 py-3 text-sm text-muted-foreground">{t('datasetScopeLoading')}</div>
                ) : datasetsQuery.isError && datasets.length === 0 ? (
                  <div className="flex items-center justify-between gap-3 px-2 py-2">
                    <p role="status" className="text-sm text-muted-foreground">{t('datasetScopeFailed')}</p>
                    <Button type="button" variant="ghost" size="sm" onClick={() => void datasetsQuery.refetch()}>{t('retryDatasets')}</Button>
                  </div>
                ) : datasets.length === 0 ? (
                  <div className="px-2 py-3">
                    <p role="status" className="text-sm text-muted-foreground">{t('datasetScopeEmpty')}</p>
                    <Button
                      type="button"
                      variant="ghost"
                      className="mt-2 h-11 gap-2 px-0 text-sm shadow-none hover:bg-transparent hover:underline"
                      onClick={() => router.push('/datasets')}
                    >
                      {t('openDatasets')}
                      <ArrowRight className="size-3.5" aria-hidden="true" />
                    </Button>
                  </div>
                ) : (
                  datasets.map((dataset) => (
                    <button
                      type="button"
                      key={dataset.id}
                      aria-pressed={selectedDatasetId === dataset.id}
                      className={cn(
                        'flex min-h-11 w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm outline-none transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring',
                        selectedDatasetId === dataset.id && 'bg-muted'
                      )}
                      onClick={() => {
                        setSelectedDatasetId(dataset.id)
                        setShowConversationTools(false)
                        setShowRagSettings(false)
                      }}
                    >
                      <Database className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{dataset.name}</span>
                        {dataset.description ? (
                          <span className="block truncate text-xs text-muted-foreground">{dataset.description}</span>
                        ) : null}
                      </span>
                      {selectedDatasetId === dataset.id ? <Check className="size-4 shrink-0" aria-hidden="true" /> : null}
                    </button>
                  ))
                )}
              </div>
              <div className="mt-2 space-y-1 border-t border-border pt-2">
              {promptTemplates.length > 0 && (
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" size="sm" className="h-11 w-full justify-start gap-3 rounded-lg px-2 text-sm font-normal text-foreground shadow-none hover:bg-muted">
                      <FileText className="size-3.5 text-muted-foreground" />
                      <span className="max-w-[16rem] truncate text-xs">{selectedPromptTemplate?.name || t('defaultTemplate')}</span>
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
                          {t.description ? <span className="text-[11px] text-muted-foreground/70 truncate">{t.description}</span> : null}
                        </button>
                      ))}
                    </div>
                  </PopoverContent>
                </Popover>
              )}

                  <Button
                    ref={ragSettingsTriggerRef}
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-11 w-full justify-start gap-3 rounded-lg px-2 text-sm font-normal text-foreground shadow-none hover:bg-muted"
                    onClick={() => setShowRagSettings(true)}
                  >
                    <Settings2 className="size-3.5 text-muted-foreground" aria-hidden="true" />
                    <span className="flex-1 text-left">{t('ragSettings')}</span>
                    <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
                  </Button>
              </div>
              </>
              ) : (
                  <div
                    ref={ragSettingsPanelRef}
                    className={cn(
                      'flex max-h-[min(calc(100dvh-1.5rem),var(--radix-popover-content-available-height))] flex-col overflow-hidden rounded-xl border border-border bg-popover shadow-strong transition-shadow duration-200 motion-reduce:transition-none',
                      isRagSettingsDragging && 'shadow-[0_28px_68px_-34px_rgba(15,23,42,0.72)]'
                    )}
                    style={{
                      transform: `translate3d(${ragSettingsOffset.x}px, ${ragSettingsOffset.y}px, 0)`,
                    }}
                  >
                    <div className="flex shrink-0 items-center justify-between gap-1 px-5 pb-3 pt-3">
                    <Button
                      ref={ragSettingsBackRef}
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="-ml-2 size-11 shrink-0 rounded-lg text-muted-foreground shadow-none hover:bg-muted hover:text-foreground"
                      aria-label={t('backToSources')}
                      title={t('backToSources')}
                      onClick={() => setShowRagSettings(false)}
                    >
                      <ChevronLeft className="size-4" aria-hidden="true" />
                    </Button>
                    <button
                      type="button"
                      aria-label={t('dragRagSettingsPanel')}
                      title={t('dragRagSettingsPanelHint')}
                      className={cn(
                        'flex min-h-11 min-w-0 flex-1 touch-none select-none items-center gap-2 rounded-md border-0 bg-transparent px-1 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/70',
                        isRagSettingsDragging
                          ? 'cursor-grabbing bg-muted'
                          : 'cursor-grab hover:bg-muted'
                      )}
                      onPointerDown={beginRagSettingsDrag}
                      onPointerMove={moveRagSettingsDrag}
                      onPointerUp={endRagSettingsDrag}
                      onPointerCancel={endRagSettingsDrag}
                      onLostPointerCapture={endRagSettingsDrag}
                      onDoubleClick={resetRagSettingsPosition}
                      onKeyDown={handleRagSettingsDragKeyDown}
                    >
                      <h4 className="text-base font-medium text-foreground">{t('retrievalSettings')}</h4>
                      <GripHorizontal className="size-4 text-muted-foreground/70" aria-hidden="true" />
                    </button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="-mr-2 size-11 rounded-lg text-muted-foreground shadow-none hover:bg-muted hover:text-foreground"
                      aria-label={t('closeRetrievalSettings')}
                      onClick={() => {
                        setShowRagSettings(false)
                        setShowConversationTools(false)
                      }}
                    >
                      <X className="size-4" aria-hidden="true" />
                    </Button>
                    </div>

                  <div className="min-h-0 space-y-5 overflow-y-auto overscroll-contain px-5 pb-5">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-2">
                        <Label htmlFor="chat-retrieval-mode" className="text-sm font-normal">{t('retrievalMode')}</Label>
                        <Select
                          value={deepReasoningEnabled ? 'hybrid' : ragConfig.retrieval_mode}
                          disabled={deepReasoningEnabled}
                          onValueChange={(v) => {
                            setRagConfigDirty(true)
                            setRagConfig((prev) => ({ ...prev, retrieval_mode: v }))
                          }}
                        >
                          <SelectTrigger id="chat-retrieval-mode" className="h-11 text-base shadow-none sm:text-sm">
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
                      <div className="space-y-2">
                        <Label htmlFor="chat-retrieval-count" className="text-sm font-normal">{t('topK')}</Label>
                        <Input
                          id="chat-retrieval-count"
                          type="number"
                          min={1}
                          max={50}
                          title={t('topKHint')}
                          value={deepReasoningEnabled ? Math.max(Number.isFinite(ragConfig.top_k) ? ragConfig.top_k : 5, 8) : ragConfig.top_k}
                          disabled={deepReasoningEnabled}
                          onChange={(e) => {
                            setRagConfigDirty(true)
                            setRagConfig((prev) => ({ ...prev, top_k: Number(e.target.value || 0) }))
                          }}
                          className="h-11 text-base shadow-none sm:h-11 sm:text-sm"
                        />
                      </div>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="chat-metadata-filter" className="text-sm font-normal">{t('metadataFilter')}</Label>
                      <Select
                        value={metadataFilterMode}
                        onValueChange={(value) => applyMetadataFilterPreset(coerceOneOf(METADATA_FILTER_MODE_VALUES, value, 'all'))}
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
                          <Label htmlFor="chat-custom-filter" className="sr-only">{t('customMetadataFilter')}</Label>
                          <textarea
                            id="chat-custom-filter"
                            value={metadataFilterText}
                            onChange={(e) => {
                              setRagConfigDirty(true)
                              setMetadataFilterText(e.target.value)
                            }}
                            placeholder={t.raw('metadataFilterExampleHandbook')}
                            aria-invalid={Boolean(metadataFilterError)}
                            aria-describedby={metadataFilterError ? 'chat-custom-filter-error' : undefined}
                            className="min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-base leading-6 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 aria-[invalid=true]:border-destructive/60 sm:text-sm"
                          />
                          {metadataFilterError ? (
                            <p id="chat-custom-filter-error" role="alert" className="text-xs leading-5 text-destructive">{metadataFilterError}</p>
                          ) : null}
                          <details className="group/details">
                            <summary className="cursor-pointer select-none py-2 text-xs text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                              {t('supportedOperatorsExamples')}
                            </summary>
                            <div className="mt-1 space-y-2 break-words text-xs leading-5 text-muted-foreground">
                              <div className="font-mono text-foreground/80">{t('supportedOperatorsList')}</div>
                              <div>{t('supportedOperatorsHint')}</div>
                              <div className="font-mono text-foreground/80">{t.raw('metadataFilterExampleQa')}</div>
                              <div className="font-mono text-foreground/80">{t.raw('metadataFilterExampleHandbook')}</div>
                            </div>
                          </details>
                        </div>
                      ) : null}
                    </div>

                    <details className="group/advanced border-t border-border pt-2">
                      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-md text-sm font-medium outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                        {t('advancedSettings')}
                        <ChevronDown className="size-4 text-muted-foreground transition-transform duration-150 group-open/advanced:rotate-180 motion-reduce:transition-none" aria-hidden="true" />
                      </summary>
                      <div className="space-y-3 pt-2">
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
                          checked={ragConfig.use_graph}
                          onCheckedChange={(checked) => {
                            setRagConfigDirty(true)
                            setRagConfig((prev) => ({ ...prev, use_graph: checked }))
                          }}
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
                            <Label htmlFor="chat-output-preset" className="text-sm font-normal">{t('structuredPresetLabel')}</Label>
                            <Select
                              value={structuredPreset || SELECT_DEFAULT_VALUE}
                              onValueChange={(v) => setStructuredPreset(v === SELECT_DEFAULT_VALUE ? '' : v)}
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
                        <div className="border-t border-border pt-2">
                          <div className="flex min-h-11 items-center justify-between gap-3">
                            <span className="flex items-center gap-2 text-sm">
                              <Route className="size-4 text-muted-foreground" aria-hidden="true" />
                              {t('ragTraceEntry')}
                            </span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-11 rounded-lg px-2 text-xs shadow-none hover:bg-muted"
                              onClick={() => setTraceDialogOpen(true)}
                              disabled={!conversationId}
                              title={conversationId ? t('viewRagTrace') : t('sendMessageFirst')}
                            >
                              {t('viewTrace')}
                            </Button>
                          </div>
                          {!conversationId ? <p className="text-xs leading-5 text-muted-foreground">{t('conversationRecordsHint')}</p> : null}
                        </div>
                      </div>
                    </details>
                </div>
                </div>
              )}
            </PopoverContent>
          {!isWelcomeState ? (
            <div className="flex justify-end">
              <PopoverTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-9 max-w-full gap-2 rounded-md px-2 text-muted-foreground shadow-none hover:bg-muted hover:text-foreground"
                aria-expanded={showConversationTools}
                aria-controls="chat-conversation-tools"
                title={t('scopeAndRetrieval')}
              >
                <Database className="size-3.5" aria-hidden="true" />
                <span className="max-w-[13rem] truncate text-xs">{conversationToolsScopeLabel}</span>
                <ChevronDown className="size-3.5" aria-hidden="true" />
              </Button>
              </PopoverTrigger>
            </div>
          ) : null}

          <div
            className={cn(
              'relative border transition-[border-color,box-shadow] duration-200 motion-reduce:transition-none',
              isWelcomeState
                ? 'rounded-3xl border-border/80 bg-card shadow-subtle focus-within:border-foreground/40 focus-within:ring-2 focus-within:ring-ring/15'
                : 'rounded-xl border-input bg-card focus-within:border-foreground/40 focus-within:ring-2 focus-within:ring-ring/15'
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
                  ? 'min-h-[72px] rounded-t-3xl px-5 pb-3 pt-4 sm:min-h-[88px] sm:px-6 sm:pb-4 sm:pt-5'
                  : 'min-h-[88px] rounded-t-xl px-5 pb-3 pt-4'
              )}
              rows={1}
            />

            <div className={cn(
              'flex items-center gap-2',
              isWelcomeState ? 'px-2 pb-2 sm:px-3 sm:pb-3' : 'px-3 pb-3 pt-1 sm:px-4'
            )}>
              {isWelcomeState ? (
              <div className="min-w-0 max-w-[calc(100%-6.5rem)] sm:max-w-[60%]">
                <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-11 max-w-full gap-2 rounded-full bg-muted/70 px-3 text-sm font-medium text-foreground shadow-none hover:bg-muted data-[state=open]:bg-muted sm:h-10"
                  aria-expanded={showConversationTools}
                  aria-controls="chat-conversation-tools"
                  title={t('scopeAndRetrieval')}
                >
                  <Database className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span className="truncate">
                    {conversationToolsScopeLabel}
                  </span>
                  <ChevronDown
                    className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none', showConversationTools && 'rotate-180')}
                    aria-hidden="true"
                  />
                </Button>
                </PopoverTrigger>
              </div>
              ) : null}

            <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-2">
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

              {isLoading ? (
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
                  disabled={!inputValue.trim()}
                  className="size-11 rounded-full shadow-none transition-colors duration-150 disabled:bg-muted disabled:text-muted-foreground/60 disabled:opacity-100 motion-reduce:transition-none sm:size-10"
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

          {!isWelcomeState ? (
            <p className="text-[11px] text-center text-muted-foreground/75">
              {t.rich('composerHelpText', {
                slash: renderComposerSlash,
                enter: renderComposerEnter,
                shiftEnter: renderComposerEnter,
              })}
            </p>
          ) : null}
          </Popover>
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
      <Label htmlFor={id} className="flex min-h-11 min-w-0 flex-1 cursor-pointer flex-col justify-center gap-1 py-1 text-sm font-normal leading-5">
        <span id={`${id}-label`}>{label}</span>
        {description ? <span id={`${id}-hint`} className="text-xs font-normal leading-5 text-muted-foreground">{description}</span> : null}
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
    <div className="mb-7 flex items-center justify-center gap-3 sm:mb-8 sm:gap-4">
      <BrandLogo variant="mark" className="size-12 sm:size-14" decorative priority />
      <h1 className="text-[28px] font-semibold leading-10 text-foreground sm:text-4xl sm:leading-12 xl:text-[40px] xl:leading-14">
        {t('welcomeTitle')}
      </h1>
    </div>
  )
}
