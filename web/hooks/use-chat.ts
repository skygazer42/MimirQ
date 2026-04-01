/**
 * 对话 Hook：负责 SSE 聊天、会话 ID 维护、历史加载
 */
'use client'

import { useCallback } from 'react'

import type { UseChatOptions } from './use-chat-formatter'
import { useChatSession } from './use-chat-session'
import { useChatStream } from './use-chat-stream'

export function useChat({
  conversationId: initialConversationId,
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
}: UseChatOptions = {}) {
  const session = useChatSession({
    initialConversationId,
    onConversationId,
    onError,
  })
  const stream = useChatStream({
    conversationId: session.conversationId,
    setConversationId: session.setConversationId,
    messagesRef: session.messagesRef,
    setMessages: session.setMessages,
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
  })

  const loadConversation = useCallback(
    async (id: string) => {
      stream.stopGeneration()
      stream.resetTransientState()
      await session.loadConversation(id)
    },
    [session, stream]
  )

  const resetConversation = useCallback(() => {
    stream.stopGeneration()
    stream.resetTransientState()
    session.resetConversationState()
  }, [session, stream])

  const clearMessages = useCallback(() => {
    session.clearMessages()
    stream.resetTransientState()
  }, [session, stream])

  const isLoading = session.isLoading || stream.isLoading

  return {
    messages: session.messages,
    isLoading,
    currentResponse: stream.currentResponse,
    currentCitations: stream.currentCitations,
    currentSteps: stream.currentSteps,
    sendMessage: stream.sendMessage,
    stopGeneration: stream.stopGeneration,
    clearMessages,
    conversationId: session.conversationId,
    loadConversation,
    resetConversation,
  }
}
