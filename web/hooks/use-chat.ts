/**
 * 对话 Hook：负责 SSE 聊天、会话 ID 维护、历史加载
 */
'use client'

import { useCallback, useRef, useState } from 'react'
import type { Citation, Message, StreamEvent } from '@/types'
import { getAuthHeaders } from '@/lib/auth-headers'
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

  const abortControllerRef = useRef<AbortController | null>(null)

  const loadConversation = useCallback(
    async (id: string) => {
      const convId = (id || '').trim()
      if (!convId) return

      abortControllerRef.current?.abort()
      abortControllerRef.current = null

      setIsLoading(true)
      setCurrentResponse('')
      setCurrentCitations([])

      try {
        const result = await chatApi.getMessages(convId)
        setConversationId(convId)
        setMessages(result.messages || [])
        onConversationId?.(convId)
      } catch (err: any) {
        const msg = err?.response?.data?.detail || err?.message || 'Failed to load conversation'
        onError?.(msg)
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

      abortControllerRef.current?.abort()
      abortControllerRef.current = new AbortController()

      let didTimeout = false
      const timeoutId = window.setTimeout(() => {
        didTimeout = true
        abortControllerRef.current?.abort()
      }, API_TIMEOUT_MS)

      try {
        const history = messages.slice(-10).map((m) => ({
          role: m.role,
          content: m.content,
        }))

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
          throw new Error(`HTTP error: ${response.status}`)
        }

        const reader = response.body?.getReader()
        if (!reader) {
          throw new Error('No response body')
        }

        const decoder = new TextDecoder()
        const sse = createSseDataParser()
        let fullResponse = ''
        let citations: Citation[] = []

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunkText = decoder.decode(value, { stream: true })
          for (const jsonStr of sse.feed(chunkText)) {
            try {
              const event: StreamEvent = JSON.parse(jsonStr)

              if (event.type === 'citations') {
                citations = event.data
                setCurrentCitations(citations)
              } else if (event.type === 'token') {
                fullResponse += event.data.content
                setCurrentResponse(fullResponse)
              } else if (event.type === 'done') {
                const nextConversationId = (event?.data?.conversation_id || '').trim()
                if (nextConversationId && nextConversationId !== (conversationId || '')) {
                  setConversationId(nextConversationId)
                  onConversationId?.(nextConversationId)
                }

                let assistantContent = fullResponse
                if (structuredOutput && event?.data?.structured_data != null) {
                  try {
                    assistantContent = `\`\`\`json\n${JSON.stringify(event.data.structured_data, null, 2)}\n\`\`\``
                  } catch {
                    assistantContent = fullResponse
                  }
                }

                const assistantMessage: Message = {
                  id: Date.now().toString(),
                  role: 'assistant',
                  content: assistantContent,
                  citations,
                  created_at: new Date().toISOString(),
                }

                setMessages((prev) => [...prev, assistantMessage])
                setCurrentResponse('')
                setCurrentCitations([])
              } else if (event.type === 'error') {
                throw new Error(event.data?.message || 'Unknown error')
              }
            } catch (e) {
              console.error('Failed to parse SSE event:', e)
            }
          }
        }

        // Flush any remaining decoder output (best-effort).
        for (const jsonStr of sse.feed(decoder.decode())) {
          try {
            const event: StreamEvent = JSON.parse(jsonStr)
            if (event.type === 'citations') {
              citations = event.data
              setCurrentCitations(citations)
            } else if (event.type === 'token') {
              fullResponse += event.data.content
              setCurrentResponse(fullResponse)
            }
          } catch {
            // ignore
          }
        }
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
        setIsLoading(false)
        abortControllerRef.current = null
      }
    },
    [
      conversationId,
      documentIds,
      enableLongTermMemory,
      isLoading,
      messages,
      onConversationId,
      onError,
      promptTemplateId,
      ragConfig,
      structuredOutput,
      structuredPreset,
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
    sendMessage,
    stopGeneration,
    clearMessages,
    conversationId,
    loadConversation,
    resetConversation,
  }
}
