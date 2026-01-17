/**
 * 对话 Hook：负责 SSE 聊天、会话 ID 维护、历史加载
 */
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { Citation, Message, StreamEvent } from '@/types'
import { getAuthHeaders } from '@/lib/auth-headers'
import { extractBackendMessage, withRequestId } from '@/lib/api-errors'
import { API_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { chatApi } from '@/lib/api-client'
import { createSseDataParser } from '@/lib/sse'

interface UseChatOptions {
  conversationId?: string
  documentIds?: string[]
  promptTemplateId?: string
  ragConfig?: Record<string, any>
  structuredOutput?: boolean
  structuredPreset?: string
  enableLongTermMemory?: boolean
  onConversationId?: (conversationId: string) => void
  onError?: (error: string) => void
}

export function useChat({
  conversationId: initialConversationId,
  documentIds,
  promptTemplateId,
  ragConfig,
  structuredOutput,
  structuredPreset,
  enableLongTermMemory,
  onConversationId,
  onError,
}: UseChatOptions = {}) {
  const [conversationId, setConversationId] = useState<string | undefined>(initialConversationId)
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [currentResponse, setCurrentResponse] = useState('')
  const [currentCitations, setCurrentCitations] = useState<Citation[]>([])
  const [currentSteps, setCurrentSteps] = useState<string[]>([])

  const messagesRef = useRef<Message[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)
  const fullResponseRef = useRef<string>('')
  const currentStepsRef = useRef<string[]>([])
  const rafIdRef = useRef<number | null>(null)

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    currentStepsRef.current = currentSteps
  }, [currentSteps])

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
      if (rafIdRef.current != null) {
        window.cancelAnimationFrame(rafIdRef.current)
        rafIdRef.current = null
      }
    }
  }, [])

  const scheduleCurrentResponseUpdate = useCallback(() => {
    if (rafIdRef.current != null) return
    rafIdRef.current = window.requestAnimationFrame(() => {
      rafIdRef.current = null
      setCurrentResponse(fullResponseRef.current)
    })
  }, [])

  const flushCurrentResponseUpdate = useCallback(() => {
    if (rafIdRef.current != null) {
      window.cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
    setCurrentResponse(fullResponseRef.current)
  }, [])

  const loadConversation = useCallback(
    async (id: string) => {
      const convId = (id || '').trim()
      if (!convId) return

      abortControllerRef.current?.abort()
      abortControllerRef.current = null

      setIsLoading(true)
      setCurrentResponse('')
      setCurrentCitations([])
      fullResponseRef.current = ''

      try {
        const result = await chatApi.getMessages(convId)
        setConversationId(convId)
        setMessages(result.messages || [])
        onConversationId?.(convId)
      } catch (err: any) {
        const data = err?.response?.data
        const requestId = err?.response?.headers?.['x-request-id'] || data?.request_id
        const msg = extractBackendMessage(data) || err?.message || 'Failed to load conversation'
        onError?.(withRequestId(msg, requestId))
      } finally {
        setIsLoading(false)
      }
    },
    [onConversationId, onError]
  )

  const resetConversation = useCallback(() => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setConversationId(undefined)
    setMessages([])
    setCurrentResponse('')
    setCurrentCitations([])
    fullResponseRef.current = ''
  }, [])

  /**
   * 发送消息（SSE 流式）
   */
  const sendMessage = useCallback(
    async (message: string) => {
      if (!message.trim() || isLoading) return

      const userMessage: Message = {
        id: Date.now().toString(),
        role: 'user',
        content: message,
        created_at: new Date().toISOString(),
      }

      setMessages((prev) => [...prev, userMessage])
      setIsLoading(true)
      setCurrentResponse('')
      setCurrentCitations([])
      setCurrentSteps([])
      fullResponseRef.current = ''
      currentStepsRef.current = []

      if (rafIdRef.current != null) {
        window.cancelAnimationFrame(rafIdRef.current)
        rafIdRef.current = null
      }

      abortControllerRef.current?.abort()
      abortControllerRef.current = new AbortController()

      let didTimeout = false
      const timeoutId = window.setTimeout(() => {
        didTimeout = true
        abortControllerRef.current?.abort()
      }, API_TIMEOUT_MS)

      try {
        const history = messagesRef.current.slice(-10).map((m) => ({
          role: m.role,
          content: m.content,
        }))

        const requestId =
          typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
            ? crypto.randomUUID()
            : `req-${Date.now()}-${Math.random().toString(16).slice(2)}`

        const effectiveRagConfig = {
          top_k: 5,
          score_threshold: 0.7,
          ...(ragConfig || {}),
        }
        const useGraph = Boolean((effectiveRagConfig as any).use_graph)

        const response = await fetch(`${API_V1_BASE_URL}/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
            'X-Request-ID': requestId,
          },
          body: JSON.stringify({
            conversation_id: conversationId,
            message,
            history,
            document_ids: documentIds,
            prompt_template_id: promptTemplateId,
            stream: !useGraph,
            structured_output: Boolean(structuredOutput),
            structured_preset: structuredPreset || undefined,
            enable_long_term_memory: Boolean(enableLongTermMemory),
            rag_config: effectiveRagConfig,
          }),
          signal: abortControllerRef.current.signal,
        })

        window.clearTimeout(timeoutId)

        if (!response.ok) {
          let requestId = response.headers.get('X-Request-ID') || undefined
          let msg = `HTTP error: ${response.status}`
          try {
            const data = await response.json()
            requestId = (typeof data?.request_id === 'string' ? data.request_id : requestId) || requestId
            msg = extractBackendMessage(data) || msg
          } catch {
            // ignore
          }
          throw new Error(withRequestId(msg, requestId))
        }

        const reader = response.body?.getReader()
        if (!reader) {
          throw new Error('No response body')
        }

        const decoder = new TextDecoder()
        const sse = createSseDataParser()
        let citations: Citation[] = []
        let steps: string[] = []

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunkText = decoder.decode(value, { stream: true })
          for (const jsonStr of sse.feed(chunkText)) {
            let event: StreamEvent
            try {
              event = JSON.parse(jsonStr)
            } catch (e) {
              console.error('Failed to parse SSE event:', e)
              continue
            }

            if (event.type === 'citations') {
              citations = event.data
              setCurrentCitations(citations)
            } else if (event.type === 'event') {
               const msg = event.data?.message
               if (msg) {
                 steps = [...steps, msg]
                 setCurrentSteps(steps)
               }
            } else if (event.type === 'token') {
              fullResponseRef.current += event.data.content
              scheduleCurrentResponseUpdate()
            } else if (event.type === 'done') {
              flushCurrentResponseUpdate()
              const nextConversationId = (event?.data?.conversation_id || '').trim()
              if (nextConversationId && nextConversationId !== (conversationId || '')) {
                setConversationId(nextConversationId)
                onConversationId?.(nextConversationId)
              }

              let assistantContent = fullResponseRef.current
              if (structuredOutput && event?.data?.structured_data != null) {
                try {
                  assistantContent = `\`\`\`json\n${JSON.stringify(event.data.structured_data, null, 2)}\n\`\`\``
                } catch {
                  assistantContent = fullResponseRef.current
                }
              }

              const assistantMessage: Message = {
                id: Date.now().toString(),
                role: 'assistant',
                content: assistantContent,
                citations,
                steps,
                created_at: new Date().toISOString(),
              }

              setMessages((prev) => [...prev, assistantMessage])
              setCurrentResponse('')
              setCurrentCitations([])
              setCurrentSteps([])
              fullResponseRef.current = ''
            } else if (event.type === 'error') {
              const msg = event.data?.message || 'Unknown error'
              throw new Error(withRequestId(msg, event.request_id))
            }
          }
        }

        // Flush any remaining decoder output (best-effort).
        for (const jsonStr of sse.feed(decoder.decode())) {
          let event: StreamEvent
          try {
            event = JSON.parse(jsonStr)
          } catch {
            continue
          }
          if (event.type === 'citations') {
            citations = event.data
            setCurrentCitations(citations)
          } else if (event.type === 'token') {
            fullResponseRef.current += event.data.content
            scheduleCurrentResponseUpdate()
          } else if (event.type === 'error') {
            const msg = event.data?.message || 'Unknown error'
            throw new Error(withRequestId(msg, event.request_id))
          }
        }
        flushCurrentResponseUpdate()
      } catch (err: any) {
        if (err?.name === 'AbortError') {
          if (didTimeout) {
            onError?.('Request timed out')
          } else {
            console.log('Request aborted')
          }
        } else {
          console.error('Chat error:', err)
          onError?.(err?.message || 'Failed to send message')
        }
      } finally {
        window.clearTimeout(timeoutId)
        if (rafIdRef.current != null) {
          window.cancelAnimationFrame(rafIdRef.current)
          rafIdRef.current = null
        }
        setIsLoading(false)
        abortControllerRef.current = null
      }
    },
    [
      conversationId,
      documentIds,
      enableLongTermMemory,
      isLoading,
      onConversationId,
      onError,
      promptTemplateId,
      ragConfig,
      structuredOutput,
      structuredPreset,
      flushCurrentResponseUpdate,
      scheduleCurrentResponseUpdate,
    ]
  )

  const stopGeneration = useCallback(() => {
    abortControllerRef.current?.abort()
  }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
    setCurrentResponse('')
    setCurrentCitations([])
  }, [])

  return {
    messages,
    isLoading,
    currentResponse,
    currentCitations,
    currentSteps,
    sendMessage,
    stopGeneration,
    clearMessages,
    conversationId,
    loadConversation,
    resetConversation,
  }
}
