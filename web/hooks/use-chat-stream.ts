'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { EventType } from '@ag-ui/core'
import { EventSchema } from '@ag-ui/core/schemas'

import type { Message, StreamEvent } from '@/types/chat'
import type { Citation } from '@/types/processing'
import { API_LONG_TIMEOUT_MS, API_TIMEOUT_MS } from '@/lib/env'
import { chatApi } from '@/lib/api/chat'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { reportClientError, reportClientWarning } from '@/lib/client-logging'
import { formatApiError, withRequestId } from '@/lib/api-errors'
import { citationListSchema } from '@/lib/citations'
import { generateRequestId } from '@/lib/request-id'
import { queryKeys } from '@/lib/query-keys'

import {
  buildChatRequest,
  buildDoneAssistantMessage,
  getHistory,
  getStreamEventMessage,
  type ChatRagConfig,
} from './chat-stream-payload'
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
  onUnconfirmedMessage?: (message: string) => void
}

function parseStreamEvent(jsonStr: string): StreamEvent {
  return EventSchema.parse(JSON.parse(jsonStr))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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
  onUnconfirmedMessage,
}: UseChatStreamOptions) {
  const queryClient = useQueryClient()
  const invalidateConversationLists = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.chat.conversationsAll })
    void queryClient.invalidateQueries({ queryKey: queryKeys.chat.conversationPagesAll })
  }, [queryClient])
  const [isLoading, setIsLoading] = useState(false)
  const [currentResponse, setCurrentResponse] = useState('')
  const [currentCitations, setCurrentCitations] = useState<Citation[]>([])
  const [currentSteps, setCurrentSteps] = useState<string[]>([])

  const activeRequestRef = useRef<(() => void) | null>(null)
  const activeConversationIdRef = useRef<string | undefined>(conversationId)
  const fullResponseRef = useRef('')
  const currentStepsRef = useRef<string[]>([])
  const currentCitationsRef = useRef<Citation[]>([])
  const rafIdRef = useRef<number | null>(null)
  const mountedRef = useRef(true)

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
    fullResponseRef.current = ''
    currentStepsRef.current = []
    currentCitationsRef.current = []
  }, [clearRaf])

  const cancelActiveRequest = useCallback(() => {
    const stopRequest = activeRequestRef.current
    activeRequestRef.current = null
    stopRequest?.()
  }, [])

  const discardGeneration = useCallback(() => {
    cancelActiveRequest()
    setIsLoading(false)
    resetTransientState()
  }, [cancelActiveRequest, resetTransientState])

  useEffect(() => {
    if (activeConversationIdRef.current !== conversationId) discardGeneration()
    activeConversationIdRef.current = conversationId
  }, [conversationId, discardGeneration])

  useEffect(() => {
    mountedRef.current = true
    const unsubscribe = subscribeAuthSession(discardGeneration)
    return () => {
      mountedRef.current = false
      unsubscribe()
      cancelActiveRequest()
      clearRaf()
    }
  }, [cancelActiveRequest, clearRaf, discardGeneration])

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

  const appendStep = useCallback((message: string | undefined) => {
    if (!message) return
    const nextSteps = [...currentStepsRef.current, message]
    currentStepsRef.current = nextSteps
    setCurrentSteps(nextSteps)
  }, [])

  const updateConversation = useCallback(
    (nextConversationId: string) => {
      if (nextConversationId === activeConversationIdRef.current) return
      activeConversationIdRef.current = nextConversationId
      setConversationId(nextConversationId)
      onConversationId?.(nextConversationId)
    },
    [onConversationId, setConversationId],
  )

  const stopGeneration = useCallback(() => {
    activeRequestRef.current?.()
  }, [])

  const sendMessage = useCallback(
    (message: string) => {
      if (!mountedRef.current || !message.trim() || activeRequestRef.current !== null) return false

      const history = getHistory(messagesRef.current)
      const userMessage: Message = {
        id: `local-user:${generateRequestId()}`,
        role: 'user',
        content: message,
        message_metadata: { send_state: 'sending' },
        created_at: new Date().toISOString(),
      }

      const controller = new AbortController()
      const recoveryController = new AbortController()
      const authSessionKey = getAuthSessionKey()
      let userStopped = false
      let timeoutId: number | undefined
      const clearStreamTimeout = () => {
        globalThis.window.clearTimeout(timeoutId)
        timeoutId = undefined
      }
      const stopActiveRequest = () => {
        userStopped = true
        clearStreamTimeout()
        controller.abort()
        recoveryController.abort()
      }
      activeRequestRef.current = stopActiveRequest
      const isCurrent = () => activeRequestRef.current === stopActiveRequest && authSessionKey === getAuthSessionKey()

      setMessages((prev) => [...prev, userMessage])
      setIsLoading(true)
      resetTransientState()

      let didTimeout = false
      let sawDone = false
      let streamAccepted = false
      let acceptedRequestId: string | undefined
      let acceptedAssistantMessageId: string | undefined
      let acceptedRunId: string | undefined
      let acceptedThreadId: string | undefined
      let runStarted = false
      let textStarted = false
      let textEnded = false
      const toolCalls = new Map<string, { name: string; args: string; ended: boolean; resultReceived: boolean }>()
      const armTimeout = (timeoutMs: number) => {
        clearStreamTimeout()
        timeoutId = globalThis.window.setTimeout(() => {
          didTimeout = true
          controller.abort()
        }, timeoutMs)
      }
      armTimeout(API_TIMEOUT_MS)

      const sendRequest = async () => {
        try {
          const chatRequest = buildChatRequest({
            conversationId,
            message,
            history,
            documentIds,
            datasetId,
            promptTemplateId,
            structuredOutput,
            structuredPreset,
            enableLongTermMemory,
            enableSummaryMemory,
            ragConfig,
          })

          let citations: Citation[] = []
          let eventFailed = false

          try {
            await chatApi.streamChat(
              chatRequest,
              (jsonStr) => {
                if (!isCurrent() || controller.signal.aborted) return
                try {
                  const event = parseStreamEvent(jsonStr)
                  if (sawDone) return
                  armTimeout(API_LONG_TIMEOUT_MS)
                  if (
                    (event.metadata?.runId !== undefined && event.metadata.runId !== acceptedRunId) ||
                    (event.metadata?.threadId !== undefined && event.metadata.threadId !== acceptedThreadId) ||
                    acceptedRunId === undefined ||
                    acceptedThreadId === undefined
                  ) {
                    throw new TypeError('AG-UI event belongs to another run')
                  }
                  if (
                    acceptedAssistantMessageId !== undefined &&
                    event.metadata?.assistantMessageId !== undefined &&
                    event.metadata.assistantMessageId !== acceptedAssistantMessageId
                  ) {
                    throw new TypeError('AG-UI event belongs to another assistant message')
                  }

                  if (event.type === EventType.RUN_STARTED) {
                    if (runStarted || event.runId !== acceptedRunId || event.threadId !== acceptedThreadId) {
                      throw new TypeError('Invalid AG-UI run start')
                    }
                    runStarted = true
                    return
                  }
                  if (!runStarted) throw new TypeError('AG-UI event arrived before its run started')

                  if (event.type === EventType.TEXT_MESSAGE_START) {
                    if (
                      textStarted ||
                      (event.role !== undefined && event.role !== 'assistant') ||
                      (acceptedAssistantMessageId !== undefined && acceptedAssistantMessageId !== event.messageId) ||
                      (event.metadata?.assistantMessageId !== undefined &&
                        event.metadata.assistantMessageId !== event.messageId)
                    ) {
                      throw new TypeError('Invalid AG-UI assistant message start')
                    }
                    acceptedAssistantMessageId = event.messageId
                    textStarted = true
                    return
                  }
                  if (event.type === EventType.TEXT_MESSAGE_CONTENT || event.type === EventType.TEXT_MESSAGE_END) {
                    if (!textStarted || textEnded || event.messageId !== acceptedAssistantMessageId) {
                      throw new TypeError('AG-UI text event belongs to an inactive message')
                    }
                    if (event.type === EventType.TEXT_MESSAGE_END) textEnded = true
                    else {
                      fullResponseRef.current += event.delta
                      scheduleCurrentResponseUpdate()
                    }
                    return
                  }

                  if (event.type === EventType.CUSTOM) {
                    if (event.name === 'ragvia.citations') {
                      citations = citationListSchema.parse(event.value)
                      currentCitationsRef.current = citations
                      setCurrentCitations(citations)
                    } else if (event.name.startsWith('ragvia.')) {
                      appendStep(getStreamEventMessage(event.name.slice('ragvia.'.length), event.value))
                    }
                    return
                  }

                  if (event.type === EventType.TOOL_CALL_START) {
                    if (
                      !textStarted ||
                      toolCalls.has(event.toolCallId) ||
                      (event.parentMessageId !== undefined && event.parentMessageId !== acceptedAssistantMessageId)
                    ) {
                      throw new TypeError('Invalid AG-UI tool call start')
                    }
                    toolCalls.set(event.toolCallId, {
                      name: event.toolCallName,
                      args: '',
                      ended: false,
                      resultReceived: false,
                    })
                    appendStep(`工具调用：${event.toolCallName}`)
                    return
                  }

                  if (
                    event.type === EventType.TOOL_CALL_ARGS ||
                    event.type === EventType.TOOL_CALL_END ||
                    event.type === EventType.TOOL_CALL_RESULT
                  ) {
                    const tool = toolCalls.get(event.toolCallId)
                    if (tool === undefined || tool.resultReceived) throw new TypeError('AG-UI tool call is not active')
                    if (event.type === EventType.TOOL_CALL_ARGS) {
                      if (tool.ended) throw new TypeError('AG-UI tool arguments have already ended')
                      tool.args += event.delta
                    } else if (event.type === EventType.TOOL_CALL_END) {
                      if (tool.ended) throw new TypeError('AG-UI tool arguments have already ended')
                      JSON.parse(tool.args)
                      tool.ended = true
                    } else {
                      const success: unknown = event.metadata?.success
                      if (!tool.ended || (success !== undefined && typeof success !== 'boolean')) {
                        throw new TypeError('Invalid AG-UI tool result')
                      }
                      tool.resultReceived = true
                      const error: unknown = event.metadata?.error
                      const detail = typeof error === 'string' ? `：${error}` : ''
                      const outcome = success === undefined ? '结果' : success ? '完成' : '失败'
                      appendStep(`工具${outcome}：${tool.name}${detail}`)
                    }
                    return
                  }

                  if (event.type === EventType.RUN_FINISHED) {
                    if (event.runId !== acceptedRunId || event.threadId !== acceptedThreadId) {
                      throw new TypeError('AG-UI run completion belongs to another run')
                    }
                    if (event.outcome?.type === 'cancelled') {
                      stopActiveRequest()
                      throw new DOMException('Aborted', 'AbortError')
                    }
                    if (event.outcome?.type === 'interrupt') {
                      throw new Error('当前运行需要用户输入，但聊天暂不支持继续被中断的运行')
                    }
                    if (
                      !textEnded ||
                      acceptedAssistantMessageId === undefined ||
                      [...toolCalls.values()].some((tool) => !tool.resultReceived)
                    ) {
                      throw new TypeError('Invalid AG-UI run completion')
                    }
                    const result: unknown = event.result
                    const doneData: Record<string, unknown> = isRecord(result) ? result : {}
                    if (doneData.conversation_id !== undefined && doneData.conversation_id !== acceptedThreadId) {
                      throw new TypeError('Chat completion belongs to another conversation')
                    }
                    if (
                      doneData.assistant_message_id !== undefined &&
                      doneData.assistant_message_id !== acceptedAssistantMessageId
                    ) {
                      throw new TypeError('Chat completion belongs to another assistant message')
                    }
                    const assistantMessage = buildDoneAssistantMessage({
                      assistantMessageId: acceptedAssistantMessageId,
                      content: fullResponseRef.current,
                      citations,
                      steps: currentStepsRef.current,
                      doneData,
                      structuredOutput,
                      requestId: acceptedRequestId,
                    })

                    sawDone = true
                    flushCurrentResponseUpdate()
                    setMessages((prev) => [...prev, assistantMessage])
                    invalidateConversationLists()
                    resetTransientState()
                    return
                  }

                  if (event.type === EventType.RUN_ERROR) {
                    throw new Error(withRequestId(event.message, acceptedRequestId))
                  }
                  throw new TypeError('Unsupported AG-UI chat event')
                } catch (error) {
                  eventFailed = true
                  throw error instanceof Error ? error : new Error('Invalid AG-UI chat event', { cause: error })
                }
              },
              {
                signal: controller.signal,
                messages: [...history, { id: userMessage.id, role: 'user', content: message }],
                onOpen: ({ requestId, conversationId: openedConversationId, assistantMessageId, runId }) => {
                  if (!isCurrent() || controller.signal.aborted) return
                  streamAccepted = true
                  invalidateConversationLists()
                  acceptedRequestId = requestId
                  acceptedRunId = runId
                  acceptedThreadId = openedConversationId
                  setMessages((previous) =>
                    previous.map<Message>((item) =>
                      item.id === userMessage.id
                        ? {
                            ...item,
                            message_metadata: {
                              ...item.message_metadata,
                              send_state: 'accepted',
                              request_id: requestId,
                            },
                          }
                        : item,
                    ),
                  )
                  armTimeout(API_LONG_TIMEOUT_MS)
                  updateConversation(openedConversationId)
                  acceptedAssistantMessageId = assistantMessageId
                },
              },
            )

            if (!isCurrent()) return
            if (userStopped) throw new DOMException('Aborted', 'AbortError')
            if (!sawDone) {
              throw new Error('SSE stream ended unexpectedly')
            }
          } catch (streamErr) {
            clearStreamTimeout()
            if (!isCurrent()) return
            if (userStopped) throw new DOMException('Aborted', 'AbortError')
            if (sawDone) {
              const context = didTimeout ? '回答已生成，但后续处理等待超时' : '回答已生成，但后续处理未正常结束'
              throw new Error(
                withRequestId(`${context}：${formatApiError(streamErr, '处理失败')}`, acceptedRequestId),
                {
                  cause: streamErr,
                },
              )
            } else {
              if (!streamAccepted || eventFailed) throw streamErr
              reportClientWarning('Chat stream interrupted; reading the persisted answer', streamErr)
              const recoveredMessage = await recoverStreamedAssistantMessage({
                conversationId: acceptedThreadId,
                requestId: acceptedRequestId,
                getMessages: chatApi.getMessages,
                signal: recoveryController.signal,
              })

              if (!isCurrent()) return
              if (userStopped) throw new DOMException('Aborted', 'AbortError')
              if (recoveredMessage) {
                invalidateConversationLists()
                setMessages((prev) => {
                  if (prev.some((item) => item.id === recoveredMessage.id)) return prev
                  return [...prev, recoveredMessage]
                })
                resetTransientState()
              } else {
                throw new Error(
                  withRequestId(
                    'Chat stream interrupted before completion and could not be recovered',
                    acceptedRequestId,
                  ),
                  { cause: streamErr },
                )
              }
            }
          }

          flushCurrentResponseUpdate()
        } catch (err) {
          if (!isCurrent()) return
          if (!streamAccepted) {
            setMessages((previous) =>
              previous.map<Message>((item) =>
                item.id === userMessage.id
                  ? { ...item, message_metadata: { ...item.message_metadata, send_state: 'unconfirmed' } }
                  : item,
              ),
            )
            onUnconfirmedMessage?.(message)
          }
          if (sawDone && !userStopped) {
            reportClientError('Chat post-processing failed after the answer was generated', err)
            onError?.(formatApiError(err, '回答已生成，但后续处理失败'))
            return
          }
          if (userStopped) {
            const partialContent = fullResponseRef.current
            if (partialContent && acceptedAssistantMessageId !== undefined) {
              const stoppedMessage: Message = {
                id: `local-assistant:${acceptedAssistantMessageId}`,
                role: 'assistant',
                content: partialContent,
                citations: currentCitationsRef.current,
                steps: currentStepsRef.current,
                message_metadata: {
                  stopped: true,
                  request_id: acceptedRequestId,
                  assistant_message_id: acceptedAssistantMessageId,
                },
                created_at: new Date().toISOString(),
              }
              setMessages((prev) => [...prev, stoppedMessage])
            }
            resetTransientState()
            return
          }
          reportClientError(didTimeout ? 'Chat request timed out' : 'Chat request failed', err)
          const errorMessage = didTimeout ? 'Request timed out' : formatApiError(err, 'Failed to send message')
          onError?.(withRequestId(errorMessage, acceptedRequestId))
        } finally {
          clearStreamTimeout()
          recoveryController.abort()
          if (activeRequestRef.current === stopActiveRequest) {
            activeRequestRef.current = null
            clearRaf()
            setIsLoading(false)
          }
        }
      }
      void sendRequest()
      return true
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
      messagesRef,
      invalidateConversationLists,
      onError,
      onUnconfirmedMessage,
      promptTemplateId,
      ragConfig,
      resetTransientState,
      scheduleCurrentResponseUpdate,
      setMessages,
      structuredOutput,
      structuredPreset,
      updateConversation,
    ],
  )

  return {
    isLoading,
    currentResponse,
    currentCitations,
    currentSteps,
    sendMessage,
    stopGeneration,
    discardGeneration,
  }
}
