'use client'

import { isCancelledError, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState, type SetStateAction } from 'react'

import type { Message } from '@/types/chat'
import { formatApiError } from '@/lib/api-errors'
import { chatApi } from '@/lib/api/chat'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'

type UseChatSessionOptions = {
  onConversationId?: (conversationId: string) => void
  onError?: (error: string) => void
}

export function useChatSession({ onConversationId, onError }: UseChatSessionOptions) {
  const queryClient = useQueryClient()
  const [conversationId, setConversationState] = useState<string | undefined>()
  const conversationIdRef = useRef<string | undefined>(undefined)
  const [messages, setMessageState] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [loadError, setLoadError] = useState<{ conversationId: string; message: string }>()
  const isLoadingRef = useRef(isLoading)
  const messagesRef = useRef<Message[]>([])
  const loadRequestIdRef = useRef(0)
  const callbacksRef = useRef({ onConversationId, onError })

  useEffect(() => {
    callbacksRef.current = { onConversationId, onError }
  }, [onConversationId, onError])

  const setConversationId = useCallback((id: string | undefined) => {
    conversationIdRef.current = id
    setConversationState(id)
  }, [])

  const setMessages = useCallback((update: SetStateAction<Message[]>) => {
    const nextMessages = typeof update === 'function' ? update(messagesRef.current) : update
    messagesRef.current = nextMessages
    setMessageState(nextMessages)
  }, [])

  const setHistoryLoading = useCallback((loading: boolean) => {
    isLoadingRef.current = loading
    setIsLoading(loading)
  }, [])

  const cancelConversationLoad = useCallback(() => {
    loadRequestIdRef.current += 1
    setHistoryLoading(false)
    setLoadError(undefined)
  }, [setHistoryLoading])

  const loadConversation = useCallback(
    async (id: string) => {
      const requestedConversationId = id.trim()
      if (requestedConversationId === '') return

      const loadRequestId = ++loadRequestIdRef.current
      const authSessionKey = getAuthSessionKey()
      const isCurrent = () => loadRequestId === loadRequestIdRef.current && authSessionKey === getAuthSessionKey()
      setHistoryLoading(true)
      setLoadError(undefined)
      try {
        const result = await queryClient.fetchQuery({
          queryKey: queryKeys.chat.messages(requestedConversationId),
          staleTime: 0,
          queryFn: ({ signal }) => chatApi.getMessages(requestedConversationId, undefined, { signal }),
        })
        if (!isCurrent()) return
        setConversationId(result.conversation_id)
        setMessages(result.messages)
        callbacksRef.current.onConversationId?.(result.conversation_id)
      } catch (error) {
        if (!isCurrent() || isCancelledError(error)) return
        const message = formatApiError(error, 'Failed to load conversation')
        setLoadError({ conversationId: requestedConversationId, message })
        callbacksRef.current.onError?.(message)
      } finally {
        if (isCurrent()) {
          setHistoryLoading(false)
        }
      }
    },
    [queryClient, setConversationId, setHistoryLoading, setMessages],
  )

  const resetConversationState = useCallback(() => {
    cancelConversationLoad()
    setConversationId(undefined)
    setMessages([])
  }, [cancelConversationLoad, setConversationId, setMessages])

  const clearMessages = useCallback(() => {
    cancelConversationLoad()
    setMessages([])
  }, [cancelConversationLoad, setMessages])

  useEffect(() => {
    const unsubscribe = subscribeAuthSession(resetConversationState)
    return () => {
      unsubscribe()
      loadRequestIdRef.current += 1
    }
  }, [resetConversationState])

  return {
    conversationId,
    conversationIdRef,
    setConversationId,
    messages,
    setMessages,
    messagesRef,
    isLoading,
    isLoadingRef,
    loadError,
    loadConversation,
    cancelConversationLoad,
    resetConversationState,
    clearMessages,
  }
}
