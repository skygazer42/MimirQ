'use client'

import { isCancelledError, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { Message } from '@/types/chat'
import { extractBackendMessage, withRequestId } from '@/lib/api-errors'
import { chatApi } from '@/lib/api/chat'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'

type UseChatSessionOptions = {
  initialConversationId?: string
  onConversationId?: (conversationId: string) => void
  onError?: (error: string) => void
}

export function useChatSession({ initialConversationId, onConversationId, onError }: UseChatSessionOptions) {
  const queryClient = useQueryClient()
  const [conversationId, setConversationId] = useState<string | undefined>(initialConversationId)
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const messagesRef = useRef<Message[]>([])
  const loadRequestIdRef = useRef(0)
  const callbacksRef = useRef({ onConversationId, onError })
  const initialConversationIdRef = useRef(initialConversationId)

  useEffect(() => {
    callbacksRef.current = { onConversationId, onError }
  }, [onConversationId, onError])

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(
    () => () => {
      loadRequestIdRef.current += 1
    },
    [],
  )

  const loadConversation = useCallback(
    async (id: string) => {
      const nextConversationId = id.trim()
      if (!nextConversationId) return

      const loadRequestId = ++loadRequestIdRef.current
      const authRevision = getAuthSessionRevision()
      const authScope = getAuthCacheScope()
      const isCurrent = () =>
        loadRequestId === loadRequestIdRef.current &&
        authRevision === getAuthSessionRevision() &&
        authScope === getAuthCacheScope()
      setIsLoading(true)
      try {
        const result = await queryClient.fetchQuery({
          queryKey: queryKeys.chat.messages(nextConversationId),
          queryFn: () => chatApi.getMessages(nextConversationId),
        })
        if (!isCurrent()) return
        setConversationId(nextConversationId)
        messagesRef.current = result.messages || []
        setMessages(result.messages || [])
        callbacksRef.current.onConversationId?.(nextConversationId)
      } catch (err) {
        if (!isCurrent() || isCancelledError(err)) return
        const payload = (err as { response?: { data?: unknown; headers?: Record<string, string> } })?.response?.data
        const requestId =
          (err as { response?: { headers?: Record<string, string> } })?.response?.headers?.['x-request-id'] ||
          (payload as { request_id?: string } | undefined)?.request_id
        const message =
          extractBackendMessage(payload) || (err as { message?: string })?.message || 'Failed to load conversation'
        callbacksRef.current.onError?.(withRequestId(message, requestId))
      } finally {
        if (loadRequestId === loadRequestIdRef.current) {
          setIsLoading(false)
        }
      }
    },
    [queryClient],
  )

  useEffect(() => {
    if (initialConversationIdRef.current) void loadConversation(initialConversationIdRef.current)
  }, [loadConversation])

  const resetConversationState = useCallback(() => {
    loadRequestIdRef.current += 1
    messagesRef.current = []
    setConversationId(undefined)
    setMessages([])
    setIsLoading(false)
  }, [])

  const clearMessages = useCallback(() => {
    loadRequestIdRef.current += 1
    messagesRef.current = []
    setMessages([])
    setIsLoading(false)
  }, [])

  useEffect(() => {
    globalThis.window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, resetConversationState)
    return () => globalThis.window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, resetConversationState)
  }, [resetConversationState])

  return {
    conversationId,
    setConversationId,
    messages,
    setMessages,
    messagesRef,
    isLoading,
    loadConversation,
    resetConversationState,
    clearMessages,
  }
}
