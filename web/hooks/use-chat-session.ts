'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { Message } from '@/types'
import { extractBackendMessage, withRequestId } from '@/lib/api-errors'
import { chatApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'

type UseChatSessionOptions = {
  initialConversationId?: string
  onConversationId?: (conversationId: string) => void
  onError?: (error: string) => void
}

export function useChatSession({
  initialConversationId,
  onConversationId,
  onError,
}: UseChatSessionOptions) {
  const queryClient = useQueryClient()
  const [conversationId, setConversationId] = useState<string | undefined>(initialConversationId)
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const messagesRef = useRef<Message[]>([])
  const loadRequestIdRef = useRef(0)

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(
    () => () => {
      loadRequestIdRef.current += 1
    },
    []
  )

  const loadConversation = useCallback(
    async (id: string) => {
      const nextConversationId = id.trim()
      if (!nextConversationId) return

      const loadRequestId = ++loadRequestIdRef.current
      setIsLoading(true)
      try {
        const result = await queryClient.fetchQuery({
          queryKey: queryKeys.chat.messages(nextConversationId),
          queryFn: () => chatApi.getMessages(nextConversationId),
        })
        if (loadRequestId !== loadRequestIdRef.current) return
        setConversationId(nextConversationId)
        setMessages(result.messages || [])
        onConversationId?.(nextConversationId)
      } catch (err) {
        if (loadRequestId !== loadRequestIdRef.current) return
        const payload = (err as { response?: { data?: unknown; headers?: Record<string, string> } })?.response?.data
        const requestId =
          (err as { response?: { headers?: Record<string, string> } })?.response?.headers?.['x-request-id'] ||
          (payload as { request_id?: string } | undefined)?.request_id
        const message =
          extractBackendMessage(payload) ||
          (err as { message?: string })?.message ||
          'Failed to load conversation'
        onError?.(withRequestId(message, requestId))
      } finally {
        if (loadRequestId === loadRequestIdRef.current) {
          setIsLoading(false)
        }
      }
    },
    [onConversationId, onError, queryClient]
  )

  const resetConversationState = useCallback(() => {
    loadRequestIdRef.current += 1
    setConversationId(undefined)
    setMessages([])
    setIsLoading(false)
  }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
  }, [])

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
