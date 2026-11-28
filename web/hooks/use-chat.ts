'use client'

import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react'

import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { matchesResourceId } from '@/lib/resource-id'

import type { ChatRagConfig } from './chat-stream-payload'
import { useChatSession } from './use-chat-session'
import { useChatStream } from './use-chat-stream'

type UseChatOptions = {
  conversationId?: string
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
  onUnconfirmedMessage,
}: UseChatOptions = {}) {
  const authSessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const normalizedConversationId = initialConversationId?.trim()
  const requestedConversationId = normalizedConversationId === '' ? undefined : normalizedConversationId

  const session = useChatSession({
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
    onUnconfirmedMessage,
  })
  const {
    conversationId,
    conversationIdRef,
    isLoadingRef,
    loadConversation: loadSession,
    cancelConversationLoad,
    resetConversationState,
    clearMessages: clearSession,
  } = session
  const { discardGeneration, sendMessage: sendStreamMessage } = stream
  const appliedRouteConversationIdRef = useRef<string | undefined>(undefined)
  const isConversationCurrent =
    requestedConversationId === undefined || matchesResourceId(conversationId, requestedConversationId)

  const sendMessage = useCallback(
    (message: string) => {
      // A send can arrive before the route effect has reset the previous conversation.
      if (authSessionKey !== getAuthSessionKey() || appliedRouteConversationIdRef.current !== requestedConversationId)
        return false
      if (!isConversationCurrent || isLoadingRef.current || conversationIdRef.current !== conversationId) return false
      return sendStreamMessage(message)
    },
    [
      authSessionKey,
      conversationId,
      conversationIdRef,
      isConversationCurrent,
      isLoadingRef,
      requestedConversationId,
      sendStreamMessage,
    ],
  )

  const loadConversation = useCallback(
    (id: string) => {
      discardGeneration()
      return loadSession(id)
    },
    [discardGeneration, loadSession],
  )

  const resetConversation = useCallback(() => {
    discardGeneration()
    resetConversationState()
  }, [discardGeneration, resetConversationState])

  const clearMessages = useCallback(() => {
    discardGeneration()
    clearSession()
  }, [clearSession, discardGeneration])

  useEffect(() => {
    const previousRouteConversationId = appliedRouteConversationIdRef.current
    appliedRouteConversationIdRef.current = requestedConversationId

    if (requestedConversationId === undefined) {
      if (previousRouteConversationId !== undefined) resetConversation()
      return
    }
    if (matchesResourceId(conversationIdRef.current, requestedConversationId)) return

    void loadConversation(requestedConversationId)
    return cancelConversationLoad
  }, [
    authSessionKey,
    requestedConversationId,
    conversationIdRef,
    loadConversation,
    cancelConversationLoad,
    resetConversation,
  ])

  const { loadError } = session
  const conversationError =
    requestedConversationId === undefined || loadError?.conversationId === requestedConversationId
      ? loadError?.message
      : undefined
  const isLoading = session.isLoading || stream.isLoading || (!isConversationCurrent && conversationError === undefined)

  return {
    messages: isConversationCurrent ? session.messages : [],
    isLoading,
    isGenerating: isConversationCurrent && stream.isLoading,
    conversationError,
    currentResponse: isConversationCurrent ? stream.currentResponse : '',
    currentCitations: isConversationCurrent ? stream.currentCitations : [],
    currentSteps: isConversationCurrent ? stream.currentSteps : [],
    sendMessage,
    stopGeneration: stream.stopGeneration,
    clearMessages,
    conversationId: isConversationCurrent ? conversationId : undefined,
    loadConversation,
    resetConversation,
  }
}
