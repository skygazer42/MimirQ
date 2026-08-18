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
import Image from 'next/image'
import { useTranslations } from 'next-intl'
import { Send, StopCircle, Sparkles, Database, Wand2, Settings2, Mic, ArrowDown, Route, Keyboard, Palette } from 'lucide-react'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'
import { useChat } from '@/hooks/use-chat'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { datasetApi, promptTemplateApi, settingsApi } from '@/lib/api'
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
import { RagTraceDialog } from '@/components/rag-trace/rag-trace-dialog'
import getCaretCoordinates from 'textarea-caret'
import { SlashMenu } from '@/components/chat/slash-menu'
import { globalEventBus } from '@/lib/event-bus'
import { Magnetic } from '@/components/ui/magnetic'
import { useRouter } from '@/i18n/navigation'
import { coerceOneOf } from '@/lib/one-of'
import { queryKeys } from '@/lib/query-keys'
import { reportClientError } from '@/lib/client-logging'
import { useDocumentView } from '@/store/document-view'
import { ThemeCustomizer } from '@/components/theme-customizer'

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

  const openCommandMenu = useCallback((query = '') => {
    globalEventBus.emit('command-menu:set-open', { open: true, query })
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
    if (initialOpenRagSettings) setShowRagSettings(true)
  }, [initialOpenRagSettings])

  const selectedPromptTemplate = useMemo(
    () => promptTemplates.find((template) => template.id === promptTemplateId),
    [promptTemplates, promptTemplateId]
  )
  const hasDocumentScope = Boolean(activeDocumentIds?.length)
  const hasChatScope = hasDocumentScope || Boolean(selectedDatasetId)
  const datasetScopeReady = hasDocumentScope || !datasetsLoading

  const hiddenCount = Math.max(0, messages.length - visibleCount)
  const visibleMessages = useMemo(
    () => messages.slice(-visibleCount),
    [messages, visibleCount]
  )

  const submitMessage = useCallback((nextMessage: string) => {
    if (!nextMessage.trim() || isLoading) return false
    if (!hasChatScope) {
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
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  const isWelcomeState = messages.length === 0 && !isLoading

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-background relative transition-colors duration-200 motion-reduce:transition-none">
      {isWelcomeState ? (
        <div className="pointer-events-none absolute right-5 top-5 z-30 hidden items-center gap-2 md:flex">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="pointer-events-auto h-9 gap-1.5 rounded-full border border-border/60 bg-card/80 px-3 text-xs font-semibold text-muted-foreground shadow-sm backdrop-blur hover:border-primary/20 hover:bg-card hover:text-foreground"
            onClick={() => openCommandMenu('')}
          >
            <Keyboard className="size-3.5" />
            快捷键
          </Button>
          <ThemeCustomizer
            trigger={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="pointer-events-auto h-9 gap-1.5 rounded-full border border-border/60 bg-card/80 px-3 text-xs font-semibold text-muted-foreground shadow-sm backdrop-blur hover:border-primary/20 hover:bg-card hover:text-foreground"
              >
                <Palette className="size-3.5" />
                个性化
              </Button>
            }
          />
        </div>
      ) : null}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className={cn(
          'flex-1 overflow-y-auto overscroll-contain px-4 pb-4 scroll-smooth no-scrollbar md:px-6',
          isWelcomeState && 'overflow-hidden'
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
          {isWelcomeState && (
            <div className="flex-1 flex justify-center">
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
          'z-10 md:px-6',
          isWelcomeState
            ? 'absolute inset-x-0 top-[438px] px-4'
            : 'px-4 pt-2 pb-[calc(env(safe-area-inset-bottom)+1.5rem)]'
        )}
      >
        <div
          className={cn(
            'mx-auto w-full',
            isWelcomeState ? 'max-w-[1040px]' : 'max-w-[48rem] space-y-2.5'
          )}
        >
          <div
            aria-label={t('conversationTools')}
            className="flex flex-col gap-2 rounded-[1.5rem] border border-border/55 bg-background/60 px-2.5 py-2 shadow-sm backdrop-blur-xl supports-[backdrop-filter]:bg-background/55 md:flex-row md:flex-nowrap md:items-center md:justify-between"
          >
            <div className="flex min-w-0 items-center gap-2 px-1">
              <div className="hidden size-7 shrink-0 items-center justify-center rounded-full border border-primary/15 bg-primary/10 text-primary sm:flex">
                <Sparkles className="size-3.5 text-primary" />
              </div>
              <span className="text-[11px] font-bold uppercase tracking-[0.16em] text-muted-foreground/70">
                {t('conversationTools')}
              </span>
            </div>

            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 md:flex-nowrap md:justify-end">
              {promptTemplates.length > 0 && (
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" size="sm" className="h-8 max-w-full gap-2 rounded-full border border-border/60 bg-card/80 px-3 text-foreground shadow-sm hover:border-primary/25 hover:bg-secondary/70 md:max-w-[15rem]">
                      <Wand2 className="w-3.5 h-3.5 text-primary" />
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

              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={t('selectDataset')}
                    className="h-8 max-w-full gap-2 rounded-full border border-border/60 bg-card/80 px-3 text-foreground shadow-sm hover:border-primary/25 hover:bg-secondary/70 md:max-w-[14rem]"
                  >
                    <Database className="w-3.5 h-3.5 text-primary" />
                    <span className="max-w-[12rem] truncate text-xs">
                      {hasDocumentScope
                        ? t('currentDocumentScope')
                        : selectedDataset?.name || (datasetsLoading ? t('datasetScopeLoading') : t('selectDataset'))}
                    </span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-72 p-2" align="start">
                  <div className="px-2 pb-2">
                    <div className="text-xs font-medium text-muted-foreground">{t('selectDataset')}</div>
                    <div className="mt-1 text-[11px] text-muted-foreground/80">{t('datasetScopeHint')}</div>
                  </div>
                  <div className="max-h-60 overflow-y-auto overscroll-contain no-scrollbar space-y-1">
                    {datasetsLoading ? (
                      <div className="px-2 py-1.5 text-sm text-muted-foreground">{t('datasetScopeLoading')}</div>
                    ) : datasets.length === 0 ? (
                      <div className="px-2 py-1.5 text-sm text-muted-foreground">{t('datasetScopeEmpty')}</div>
                    ) : (
                      datasets.map((dataset) => (
                        <button
                          type="button"
                          key={dataset.id}
                          className={cn(
                            'flex w-full flex-col gap-0.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-secondary',
                            selectedDatasetId === dataset.id && 'bg-secondary/50 font-medium text-primary'
                          )}
                          onClick={() => setSelectedDatasetId(dataset.id)}
                        >
                          <span className="truncate">{dataset.name}</span>
                          {dataset.description ? (
                            <span className="truncate text-[11px] text-muted-foreground/70">{dataset.description}</span>
                          ) : null}
                        </button>
                      ))
                    )}
                  </div>
                </PopoverContent>
              </Popover>

              <Popover open={showRagSettings} onOpenChange={setShowRagSettings}>
                <PopoverTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className={cn(
                      'h-8 gap-2 rounded-full border px-3 text-xs shadow-sm transition-colors',
                      ragConfig.retrieval_mode !== 'auto' || ragConfig.use_graph
                        ? 'border-primary/30 bg-primary/10 text-primary hover:bg-primary/15'
                        : 'border-border/60 bg-card/80 text-muted-foreground hover:border-primary/25 hover:bg-secondary/70'
                    )}
                  >
                    <Settings2 className="w-3.5 h-3.5" />
                    <span>{t('ragSettings')}</span>
                  </Button>
                </PopoverTrigger>
                <PopoverContent
                  className="w-[min(20rem,calc(100vw-1.5rem))] overflow-visible border-transparent bg-transparent p-0 shadow-none [box-shadow:none]"
                  align="end"
                  sideOffset={10}
                >
                  <div
                    ref={ragSettingsPanelRef}
                    className={cn(
                      'rounded-lg bg-popover p-4 shadow-strong transition-shadow duration-200',
                      isRagSettingsDragging && 'shadow-[0_28px_68px_-34px_rgba(15,23,42,0.72)]'
                    )}
                    style={{
                      transform: `translate3d(${ragSettingsOffset.x}px, ${ragSettingsOffset.y}px, 0)`,
                    }}
                  >
                  <div className="space-y-4">
                    <button
                      type="button"
                      aria-label={t('dragRagSettingsPanel')}
                      title={t('dragRagSettingsPanelHint')}
                      className={cn(
                        '-mx-2 -mt-2 flex w-[calc(100%+1rem)] touch-none select-none items-start justify-between gap-3 rounded-md border-0 bg-transparent px-2 py-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/70',
                        isRagSettingsDragging
                          ? 'cursor-grabbing bg-secondary/70'
                          : 'cursor-grab hover:bg-secondary/55'
                      )}
                      onPointerDown={beginRagSettingsDrag}
                      onPointerMove={moveRagSettingsDrag}
                      onPointerUp={endRagSettingsDrag}
                      onPointerCancel={endRagSettingsDrag}
                      onLostPointerCapture={endRagSettingsDrag}
                      onDoubleClick={resetRagSettingsPosition}
                      onKeyDown={handleRagSettingsDragKeyDown}
                    >
                      <div className="min-w-0">
                        <h4 className="font-medium text-sm">{t('retrievalSettings')}</h4>
                        <span className="mt-0.5 block text-[11px] text-muted-foreground">
                          {t('adjustRetrievalParameters')}
                        </span>
                      </div>
                      <span className="shrink-0 rounded-full border border-border/70 bg-background/70 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                        {t('dragToMove')}
                      </span>
                    </button>

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
                     <div className="flex items-center justify-between text-sm hover:bg-secondary/50 p-1 rounded-md transition-colors">
                       <div className="flex min-w-0 items-center gap-2 text-muted-foreground text-xs">
                         <Route className="size-3.5 shrink-0" />
                         <span className="truncate">{t('ragTraceEntry')}</span>
                       </div>
                       <Button
                         type="button"
                         variant="ghost"
                         size="sm"
                         className="h-7 px-2 text-[11px] rounded-lg"
                         onClick={() => setTraceDialogOpen(true)}
                         disabled={!conversationId}
                         title={conversationId ? t('viewRagTrace') : t('sendMessageFirst')}
                       >
                         {t('viewTrace')}
                       </Button>
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
                </div>
              </PopoverContent>
            </Popover>
          </div>
          </div>

          <div
            className={cn(
              'relative group overflow-hidden transition-colors duration-150',
              isWelcomeState
                ? 'rounded-[28px] border border-border/50 bg-card/72 px-3 pb-3 pt-2 shadow-[0_16px_44px_-36px_rgba(2,8,23,0.24)] backdrop-blur-xl focus-within:border-primary/25'
                : 'rounded-[2rem] border border-border/55 bg-background/95 shadow-[0_18px_50px_-34px_rgba(15,23,42,0.55)] hover:border-primary/20 hover:shadow-[0_22px_60px_-36px_rgba(15,23,42,0.62)] focus-within:border-primary/40 focus-within:ring-0 focus-within:shadow-[0_0_0_3px_hsl(var(--primary)/0.07),0_22px_60px_-36px_rgba(15,23,42,0.62)]'
            )}
          >
            <Label htmlFor="chat-composer" className="sr-only">
              {t('messageInput')}
            </Label>
            {isWelcomeState ? (
              <div className="pointer-events-none absolute left-5 top-4 z-10 flex size-8 items-center justify-center rounded-full bg-muted/70 text-muted-foreground">
                <Sparkles className="size-4" />
              </div>
            ) : null}
            <textarea
              id="chat-composer"
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyUp}
              placeholder={t('composerPlaceholder')}
              autoFocus
              className={cn(
                'w-full resize-none outline-none max-h-[200px] bg-transparent text-sm leading-relaxed placeholder:text-muted-foreground/40 no-scrollbar text-foreground',
                isWelcomeState
                  ? 'min-h-[70px] rounded-[22px] px-12 pb-4 pt-4 pr-24'
                  : 'min-h-[92px] rounded-[2rem] px-5 pb-14 pt-5 pr-24'
              )}
              rows={1}
            />

            <div className={cn('absolute flex items-center gap-2', isWelcomeState ? 'right-4 top-4' : 'right-2 bottom-2')}>
              <Magnetic strength={0.4}>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => setVoiceModeOpen(true)}
                  className={cn(
                    'rounded-full text-muted-foreground hover:text-foreground hover:bg-muted',
                    isWelcomeState ? 'size-9' : 'h-10 w-10'
                  )}
                  title={t('voiceMode')}
                  aria-label={t('voiceMode')}
                >
                  <Mic className={cn(isWelcomeState ? 'size-4' : 'size-5')} />
                </Button>
              </Magnetic>

              {isLoading ? (
                <Magnetic strength={0.2}>
                  <Button
                    size="icon"
                    onClick={stopGeneration}
                    className={cn(
                      'rounded-full bg-destructive/10 text-destructive hover:bg-destructive/20 hover:text-destructive shadow-sm',
                      isWelcomeState ? 'size-10' : 'h-9 w-9'
                    )}
                    title={t('stopGeneration')}
                    aria-label={t('stopGeneration')}
                  >
                    <StopCircle className="size-4" />
                  </Button>
                </Magnetic>
              ) : (
                <Magnetic strength={0.5}>
                  <Button
                    size="icon"
                    onClick={handleSend}
                    disabled={!inputValue.trim() || !hasChatScope}
                    className={cn(
                      'rounded-full shadow-sm transition-colors transition-shadow transition-transform duration-200 motion-reduce:transition-none',
                      isWelcomeState ? 'size-10' : 'size-9',
                      inputValue.trim() && hasChatScope
                        ? 'bg-info text-primary-foreground hover:bg-info/90'
                        : 'bg-muted/50 text-muted-foreground/50 cursor-not-allowed'
                    )}
                    title={hasChatScope ? t('send') : (datasetsLoading ? t('datasetScopeLoading') : t('datasetScopeRequired'))}
                    aria-label={t('send')}
                  >
                    <Send className="size-4" />
                  </Button>
                </Magnetic>
              )}
            </div>

            {isWelcomeState ? (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/45 px-1 pt-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-pressed={deepReasoningEnabled}
                    title="启用后会提高召回强度：多查询、假设性答案扩展与更高 Top K"
                    className={cn(
                      'h-9 gap-1.5 rounded-full border px-3 text-xs font-semibold shadow-sm transition-colors',
                      deepReasoningEnabled
                        ? 'border-primary/35 bg-primary/10 text-primary hover:bg-primary/15'
                        : 'border-border/60 bg-background/80 text-foreground hover:border-primary/25 hover:bg-primary/5'
                    )}
                    onClick={() => setDeepReasoningEnabled((enabled) => !enabled)}
                  >
                    <Sparkles className="size-3.5" />
                    深度思考 (R1)
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-9 gap-1.5 rounded-full border border-border/60 bg-background/80 px-3 text-xs font-semibold text-foreground shadow-sm hover:border-primary/25 hover:bg-primary/5"
                    onClick={() => openCommandMenu('/')}
                  >
                    <Settings2 className="size-3.5" />
                    工具
                  </Button>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="h-9 rounded-full bg-muted px-4 text-xs font-bold text-foreground shadow-sm hover:bg-primary/10 hover:text-primary"
                  onClick={() => setShowRagSettings(true)}
                >
                  RAG 检索
                </Button>
              </div>
            ) : null}
          </div>

          {isWelcomeState ? null : (
            <p className="text-[11px] text-center text-muted-foreground/75">
              {t.rich('composerHelpText', {
                slash: renderComposerSlash,
                enter: renderComposerEnter,
                shiftEnter: renderComposerEnter,
              })}
            </p>
          )}
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

function WelcomeScreen() {
  return (
    <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col items-center px-4 pb-8 pt-32 md:px-8 md:pt-48">
      <div className="flex flex-col items-center text-center space-y-4 animate-fade-in-up">
        <div className="flex w-full justify-center">
          <Image
            src="/brand/mimirq-lockup-image2.png"
            alt="MimirQ"
            width={1708}
            height={504}
            priority
            unoptimized
            className="h-auto w-[min(76vw,560px)] select-none object-contain dark:hidden"
          />
          <Image
            src="/brand/mimirq-lockup-image2-dark.png"
            alt="MimirQ"
            width={1744}
            height={524}
            priority
            unoptimized
            className="hidden h-auto w-[min(76vw,560px)] select-none object-contain dark:block"
          />
        </div>
      </div>
    </div>
  )
}
