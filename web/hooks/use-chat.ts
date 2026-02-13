/**
 * 对话 Hook：负责 SSE 聊天、会话 ID 维护、历史加载
 */
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { Citation, Message, StreamEvent } from '@/types'
import { extractBackendMessage, withRequestId } from '@/lib/api-errors'
import { API_LONG_TIMEOUT_MS, API_TIMEOUT_MS } from '@/lib/env'
import { chatApi } from '@/lib/api-client'

interface UseChatOptions {
  conversationId?: string
  documentIds?: string[]
  promptTemplateId?: string
  ragConfig?: Record<string, any>
  structuredOutput?: boolean
  structuredPreset?: string
  enableLongTermMemory?: boolean
  enableSummaryMemory?: boolean
  onConversationId?: (conversationId: string) => void
  onError?: (error: string) => void
}

function formatGraphStep(data: any): string | null {
  if (!data || typeof data !== 'object') return null

  const rawMessage = typeof data.message === 'string' ? data.message.trim() : ''
  if (rawMessage) return rawMessage

  const ev = String(data.event || '').trim()
  if (!ev) return null

  const citationsCount =
    typeof data.citations_count === 'number' && Number.isFinite(data.citations_count) ? data.citations_count : null
  const elapsedSec = typeof data.elapsed_sec === 'number' && Number.isFinite(data.elapsed_sec) ? data.elapsed_sec : null
  const answerChars = typeof data.answer_chars === 'number' && Number.isFinite(data.answer_chars) ? data.answer_chars : null

  switch (ev) {
    case 'retrieve_start':
      return '开始检索相关资料…'
    case 'retrieve_done': {
      let msg = '检索完成'
      if (citationsCount != null) msg += `：${citationsCount} 条引用`
      if (elapsedSec != null) msg += `（${elapsedSec.toFixed(2)}s）`
      return msg
    }
    case 'generate_start':
      return '开始生成回答…'
    case 'generate_done': {
      let msg = '生成完成'
      if (answerChars != null) msg += `：${answerChars} 字符`
      if (elapsedSec != null) msg += `（${elapsedSec.toFixed(2)}s）`
      return msg
    }
    default:
      return `Graph: ${ev}`
  }
}

function formatRouteStep(data: any): string | null {
  if (!data || typeof data !== 'object') return null
  const modelUsed = typeof data.model_used === 'string' ? data.model_used.trim() : ''
  const route = typeof data.route === 'string' ? data.route.trim() : ''
  const reason = typeof data.reason === 'string' ? data.reason.trim() : ''

  let msg = '模型路由'
  if (route) msg += `：${route}`
  if (modelUsed) msg += `（${modelUsed}）`
  if (!route && modelUsed) msg = `模型：${modelUsed}`
  if (reason) msg += ` - ${reason.slice(0, 120)}`
  return msg
}

function formatRewriteStep(data: any): string | null {
  if (!data || typeof data !== 'object') return null
  const used = Boolean(data.used)
  if (!used) return null

  const rewritten = typeof data.rewritten === 'string' ? data.rewritten.trim() : ''
  const elapsedSec = typeof data.elapsed_sec === 'number' && Number.isFinite(data.elapsed_sec) ? data.elapsed_sec : null

  if (!rewritten) return null
  const preview = rewritten.length > 120 ? `${rewritten.slice(0, 120)}…` : rewritten
  return elapsedSec != null ? `查询改写：${preview}（${elapsedSec.toFixed(2)}s）` : `查询改写：${preview}`
}

export function useChat({
  conversationId: initialConversationId,
  documentIds,
  promptTemplateId,
  ragConfig,
  structuredOutput,
  structuredPreset,
  enableLongTermMemory,
  enableSummaryMemory,
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
      let timeoutId = window.setTimeout(() => {
        didTimeout = true
        abortControllerRef.current?.abort()
      }, API_TIMEOUT_MS)

      try {
        const history = messagesRef.current.slice(-10).map((m) => ({
          role: m.role,
          content: m.content,
        }))

        const effectiveRagConfig = ragConfig || {}
        const useGraph = Boolean((effectiveRagConfig as any).use_graph)
        let citations: Citation[] = []
        let steps: string[] = []
        let sawFirstEvent = false
        let sawDone = false
        let streamError: Error | null = null

        const chatRequest = {
          conversation_id: conversationId,
          message,
          history,
          document_ids: documentIds,
          prompt_template_id: promptTemplateId,
          stream: !useGraph,
          structured_output: Boolean(structuredOutput),
          structured_preset: structuredPreset || undefined,
          enable_long_term_memory: Boolean(enableLongTermMemory),
          enable_summary_memory: Boolean(enableSummaryMemory),
          rag_config: Object.keys(effectiveRagConfig).length ? effectiveRagConfig : undefined,
        }

        try {
          await chatApi.streamChat(
            chatRequest,
            (jsonStr) => {
              if (!sawFirstEvent) {
                sawFirstEvent = true
                // Treat this as a "connect" timeout: once the first SSE frame arrives, stop the timer.
                window.clearTimeout(timeoutId)
              }

              let event: StreamEvent
              try {
                event = JSON.parse(jsonStr)
              } catch (e) {
                console.error('Failed to parse SSE event:', e)
                return
              }

              if (event.type === 'citations') {
                citations = event.data
                setCurrentCitations(citations)
                return
              }

              if (event.type === 'event') {
                const msg = event.data?.message
                if (msg) {
                  steps = [...steps, msg]
                  setCurrentSteps(steps)
                }
                return
              }

              if (event.type === 'graph') {
                const msg = formatGraphStep(event.data)
                if (msg) {
                  steps = [...steps, msg]
                  setCurrentSteps(steps)
                }
                return
              }

              if (event.type === 'route') {
                const msg = formatRouteStep(event.data)
                if (msg) {
                  steps = [...steps, msg]
                  setCurrentSteps(steps)
                }
                return
              }

              if (event.type === 'rewrite') {
                const msg = formatRewriteStep(event.data)
                if (msg) {
                  steps = [...steps, msg]
                  setCurrentSteps(steps)
                }
                return
              }

              if (event.type === 'token') {
                fullResponseRef.current += event.data.content
                scheduleCurrentResponseUpdate()
                return
              }

              if (event.type === 'done') {
                sawDone = true
                flushCurrentResponseUpdate()
                const nextConversationId = (event?.data?.conversation_id || '').trim()
                if (nextConversationId && nextConversationId !== (conversationId || '')) {
                  setConversationId(nextConversationId)
                  onConversationId?.(nextConversationId)
                }

                const doneData = event?.data || {}
                const assistantMessageId = String(
                  doneData?.assistant_message_id || doneData?.message_id || Date.now().toString()
                )

                let assistantContent = fullResponseRef.current
                if (structuredOutput && event?.data?.structured_data != null) {
                  try {
                    assistantContent = `\`\`\`json\n${JSON.stringify(event.data.structured_data, null, 2)}\n\`\`\``
                  } catch {
                    assistantContent = fullResponseRef.current
                  }
                }

                const messageMetadata = {
                  ...(doneData?.metrics || {}),
                  request_id: event.request_id || doneData?.request_id,
                  total_tokens: doneData?.total_tokens,
                  total_chars: doneData?.total_chars,
                  citations_count: doneData?.citations_count,
                  model_used: doneData?.model_used,
                  route: doneData?.route,
                  retrieval_mode: doneData?.retrieval_mode,
                  vector_backend: doneData?.vector_backend,
                  structured: doneData?.structured,
                  structured_preset: doneData?.structured_preset,
                  structured_parse_ok: (doneData?.metrics || {})?.structured_parse_ok,
                }

                const assistantMessage: Message = {
                  id: assistantMessageId,
                  role: 'assistant',
                  content: assistantContent,
                  citations,
                  steps,
                  message_metadata: messageMetadata,
                  created_at: new Date().toISOString(),
                }

                setMessages((prev) => [...prev, assistantMessage])
                setCurrentResponse('')
                setCurrentCitations([])
                setCurrentSteps([])
                fullResponseRef.current = ''
                return
              }

              if (event.type === 'error') {
                const msg = event.data?.message || 'Unknown error'
                streamError = new Error(withRequestId(msg, event.request_id))
              }
            },
            { signal: abortControllerRef.current.signal }
          )

          if (streamError) throw streamError
          if (!sawFirstEvent || !sawDone) {
            throw new Error('SSE stream ended unexpectedly')
          }
        } catch (streamErr: any) {
          if (streamErr?.name === 'AbortError') throw streamErr
          if (sawDone) {
            console.warn('SSE closed after done', streamErr)
          } else {
            console.warn('SSE unavailable; falling back to non-streaming chat', streamErr)

            // Switch to a longer timeout when falling back to non-streaming chat.
            window.clearTimeout(timeoutId)
            timeoutId = window.setTimeout(() => {
              didTimeout = true
              abortControllerRef.current?.abort()
            }, API_LONG_TIMEOUT_MS)

            const resp = await chatApi.chat(chatRequest, { signal: abortControllerRef.current.signal })

            window.clearTimeout(timeoutId)

            const nextConversationId = (resp?.conversation_id || '').trim()
            if (nextConversationId && nextConversationId !== (conversationId || '')) {
              setConversationId(nextConversationId)
              onConversationId?.(nextConversationId)
            }

            let assistantContent = resp?.content || ''
            if (structuredOutput && resp?.structured_data != null) {
              try {
                assistantContent = `\`\`\`json\n${JSON.stringify(resp.structured_data, null, 2)}\n\`\`\``
              } catch {
                assistantContent = resp?.content || ''
              }
            }

            const citationsFromResp = resp?.citations || []
            const messageMetadata = {
              ...(resp?.metrics || {}),
              request_id: resp?.request_id,
              total_tokens: resp?.total_tokens,
              total_chars: resp?.total_chars,
              citations_count: citationsFromResp.length,
              retrieval_mode: resp?.retrieval_mode,
              vector_backend: resp?.vector_backend,
              structured: resp?.structured,
              structured_preset: structuredPreset || undefined,
              structured_parse_ok: (resp?.metrics || {})?.structured_parse_ok,
            }

            const assistantMessage: Message = {
              id: String(resp?.assistant_message_id || Date.now().toString()),
              role: 'assistant',
              content: assistantContent,
              citations: citationsFromResp,
              steps: [],
              message_metadata: messageMetadata,
              created_at: new Date().toISOString(),
            }

            setMessages((prev) => [...prev, assistantMessage])
            setCurrentResponse('')
            setCurrentCitations([])
            setCurrentSteps([])
            fullResponseRef.current = ''
          }
        }

        flushCurrentResponseUpdate()
      } catch (err: any) {
        const isAbort = err?.name === 'AbortError' || err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED'
        if (isAbort) {
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
      enableSummaryMemory,
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
