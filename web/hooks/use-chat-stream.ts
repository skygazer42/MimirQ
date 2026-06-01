'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import type { Citation, Message, StreamEvent } from '@/types'
import { API_LONG_TIMEOUT_MS, API_TIMEOUT_MS } from '@/lib/env'
import { chatApi } from '@/lib/api'
import { reportClientError, reportClientWarning } from '@/lib/client-logging'

import {
  buildChatRequest,
  buildDoneAssistantMessage,
  buildFallbackAssistantMessage,
  getAssistantMessageId,
  getCitations,
  getConversationId,
  getHistory,
  getStepList,
  getStreamEventMessage,
  getTokenContent,
  type ChatRagConfig,
} from './use-chat-formatter'
import { recoverStreamedAssistantMessage } from './use-chat-stream-recovery'

type MutableRef<T> = {
  current: T
}

type UseChatStreamOptions = {
  conversationId?: string
  setConversationId: (conversationId: string | undefined) => void
  messagesRef: MutableRef<Message[]>
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  documentIds?: string[]
  datasetId?: string
  promptTemplateId?: string
  ragConfig?: ChatRagConfig
  structuredOutput?: boolean
  structuredPreset?: string
  enableLongTermMemory?: boolean
  enableSummaryMemory?: boolean
  onConversationId?: (conversationId: string) => void
  onError?: (error: string) => void
}

function parseStreamEvent(jsonStr: string): StreamEvent | null {
  try {
    return JSON.parse(jsonStr) as StreamEvent
  } catch (err) {
    reportClientError('Failed to parse SSE event', err)
    return null
  }
}

export function useChatStream({
  conversationId,
  setConversationId,
  messagesRef,
  setMessages,
  documentIds,
  datasetId,
  promptTemplateId,
  ragConfig,
  structuredOutput,
  structuredPreset,
  enableLongTermMemory,
  enableSummaryMemory,
  onConversationId,
  onError,
}: UseChatStreamOptions) {
  const [isLoading, setIsLoading] = useState(false)
  const [currentResponse, setCurrentResponse] = useState('')
  const [currentCitations, setCurrentCitations] = useState<Citation[]>([])
  const [currentSteps, setCurrentSteps] = useState<string[]>([])

  const abortControllerRef = useRef<AbortController | null>(null)
  const activeConversationIdRef = useRef<string | undefined>(conversationId)
  const fullResponseRef = useRef('')
  const currentStepsRef = useRef<string[]>([])
  const rafIdRef = useRef<number | null>(null)
  const streamRequestIdRef = useRef<string | null>(null)

  const clearRaf = useCallback(() => {
    if (rafIdRef.current != null) {
      globalThis.window.cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
  }, [])

  const resetTransientState = useCallback(() => {
    clearRaf()
    setCurrentResponse('')
    setCurrentCitations([])
    setCurrentSteps([])
    streamRequestIdRef.current = null
    fullResponseRef.current = ''
    currentStepsRef.current = []
  }, [clearRaf])

  useEffect(() => {
    activeConversationIdRef.current = conversationId
  }, [conversationId])

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
      clearRaf()
    }
  }, [clearRaf])

  const scheduleCurrentResponseUpdate = useCallback(() => {
    if (rafIdRef.current != null) return
    rafIdRef.current = globalThis.window.requestAnimationFrame(() => {
      rafIdRef.current = null
      setCurrentResponse(fullResponseRef.current)
    })
  }, [])

  const flushCurrentResponseUpdate = useCallback(() => {
    clearRaf()
    setCurrentResponse(fullResponseRef.current)
  }, [clearRaf])

  const appendStep = useCallback((message: string | null) => {
    if (!message) return
    const nextSteps = [...currentStepsRef.current, message]
    currentStepsRef.current = nextSteps
    setCurrentSteps(nextSteps)
  }, [])

  const updateConversation = useCallback(
    (nextConversationId: string) => {
      if (!nextConversationId || nextConversationId === (conversationId || '')) return
      activeConversationIdRef.current = nextConversationId
      setConversationId(nextConversationId)
      onConversationId?.(nextConversationId)
    },
    [conversationId, onConversationId, setConversationId]
  )

  const stopGeneration = useCallback(() => {
    abortControllerRef.current?.abort()
  }, [])

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
      resetTransientState()

      abortControllerRef.current?.abort()
      abortControllerRef.current = new AbortController()

      let didTimeout = false
      let timeoutId = globalThis.window.setTimeout(() => {
        didTimeout = true
        abortControllerRef.current?.abort()
      }, API_TIMEOUT_MS)

      try {
        const effectiveRagConfig = ragConfig
        const useGraph = Boolean(effectiveRagConfig?.use_graph)
        const chatRequest = buildChatRequest({
          conversationId,
          message,
          history: getHistory(messagesRef.current),
          documentIds,
          datasetId,
          promptTemplateId,
          structuredOutput,
          structuredPreset,
          enableLongTermMemory,
          enableSummaryMemory,
          ragConfig: effectiveRagConfig,
          useGraph,
        })

        let citations: Citation[] = []
        let sawFirstEvent = false
        let sawDone = false
        let streamAccepted = false
        let streamError: Error | null = null

        try {
          await chatApi.streamChat(
            chatRequest,
            (jsonStr) => {
              if (!sawFirstEvent) {
                sawFirstEvent = true
                globalThis.window.clearTimeout(timeoutId)
              }

              const event = parseStreamEvent(jsonStr)
              if (!event) return

              if (event.type === 'citations') {
                citations = getCitations(event.data)
                setCurrentCitations(citations)
                return
              }

              const stepMessage = getStreamEventMessage(event.type, event.data)
              if (stepMessage) {
                appendStep(stepMessage)
                return
              }

              if (event.type === 'token') {
                fullResponseRef.current += getTokenContent(event.data)
                scheduleCurrentResponseUpdate()
                return
              }

              if (event.type === 'done') {
                sawDone = true
                flushCurrentResponseUpdate()

                const doneData = (event.data && typeof event.data === 'object'
                  ? (event.data as Record<string, unknown>)
                  : {}) as Record<string, unknown>

                updateConversation(getConversationId(doneData.conversation_id))

                const assistantMessage = buildDoneAssistantMessage({
                  assistantMessageId: getAssistantMessageId(doneData.assistant_message_id || doneData.message_id),
                  content: fullResponseRef.current,
                  citations,
                  steps: getStepList(currentStepsRef.current),
                  doneData,
                  structuredOutput,
                  requestId: event.request_id,
                })

                setMessages((prev) => [...prev, assistantMessage])
                resetTransientState()
                return
              }

              if (event.type === 'error') {
                const payload = (event.data && typeof event.data === 'object'
                  ? (event.data as Record<string, unknown>)
                  : {}) as Record<string, unknown>
                streamError = new Error(String(payload.message || 'Unknown error'))
              }
            },
            {
              signal: abortControllerRef.current.signal,
              onOpen: ({ requestId, conversationId: openedConversationId }) => {
                streamAccepted = true
                streamRequestIdRef.current = requestId
                if (openedConversationId) {
                  activeConversationIdRef.current = openedConversationId
                  updateConversation(openedConversationId)
                }
              },
            }
          )

          if (streamError) throw streamError
          if (!sawFirstEvent || !sawDone) {
            throw new Error('SSE stream ended unexpectedly')
          }
        } catch (streamErr) {
          if ((streamErr as { name?: string })?.name === 'AbortError') throw streamErr

          if (sawDone) {
            reportClientWarning('SSE closed after done', streamErr)
          } else if (streamAccepted && !streamError) {
            const recoveredMessage = await recoverStreamedAssistantMessage({
              conversationId: String(activeConversationIdRef.current || ''),
              requestId: String(streamRequestIdRef.current || ''),
              getMessages: (nextConversationId, params) => chatApi.getMessages(nextConversationId, params),
            })

            if (recoveredMessage) {
              setMessages((prev) => {
                if (prev.some((item) => item.id === recoveredMessage.id)) return prev
                return [...prev, recoveredMessage]
              })
              resetTransientState()
            } else {
              throw new Error('Chat stream interrupted before completion and could not be recovered')
            }
          } else {
            reportClientWarning('SSE unavailable; falling back to non-streaming chat', streamErr)
            globalThis.window.clearTimeout(timeoutId)
            timeoutId = globalThis.window.setTimeout(() => {
              didTimeout = true
              abortControllerRef.current?.abort()
            }, API_LONG_TIMEOUT_MS)

            const response = await chatApi.chat(chatRequest, { signal: abortControllerRef.current.signal })
            globalThis.window.clearTimeout(timeoutId)

            updateConversation(getConversationId(response.conversation_id))
            setMessages((prev) => [
              ...prev,
              buildFallbackAssistantMessage({
                response,
                structuredOutput,
                structuredPreset,
              }),
            ])
            resetTransientState()
          }
        }

        flushCurrentResponseUpdate()
      } catch (err) {
        const maybeError = err as { name?: string; code?: string; message?: string }
        const isAbort =
          maybeError?.name === 'AbortError' || maybeError?.name === 'CanceledError' || maybeError?.code === 'ERR_CANCELED'

        if (isAbort) {
          if (didTimeout) {
            onError?.('Request timed out')
          }
        } else {
          reportClientError('Chat request failed', err)
          onError?.(maybeError?.message || 'Failed to send message')
        }
      } finally {
        globalThis.window.clearTimeout(timeoutId)
        clearRaf()
        setIsLoading(false)
        abortControllerRef.current = null
      }
    },
    [
      appendStep,
      clearRaf,
      conversationId,
      datasetId,
      documentIds,
      enableLongTermMemory,
      enableSummaryMemory,
      flushCurrentResponseUpdate,
      isLoading,
      messagesRef,
      onError,
      promptTemplateId,
      ragConfig,
      resetTransientState,
      scheduleCurrentResponseUpdate,
      setMessages,
      structuredOutput,
      structuredPreset,
      updateConversation,
    ]
  )

  return {
    isLoading,
    currentResponse,
    currentCitations,
    currentSteps,
    sendMessage,
    stopGeneration,
    resetTransientState,
  }
}
