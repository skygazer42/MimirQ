/**
 * 对话 Hook
 */
'use client'

import { useState, useCallback, useRef } from 'react'
import type { Message, Citation, StreamEvent } from '@/types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface UseChatOptions {
  conversationId?: string
  documentIds?: string[]
  onError?: (error: string) => void
}

export function useChat(options: UseChatOptions = {}) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [currentResponse, setCurrentResponse] = useState('')
  const [currentCitations, setCurrentCitations] = useState<Citation[]>([])

  const abortControllerRef = useRef<AbortController | null>(null)

  /**
   * 发送消息
   */
  const sendMessage = useCallback(
    async (message: string) => {
      if (!message.trim() || isLoading) return

      // 添加用户消息
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

      // 创建 AbortController
      abortControllerRef.current = new AbortController()

      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            conversation_id: options.conversationId,
            message,
            document_ids: options.documentIds,
            stream: true,
            rag_config: {
              top_k: 5,
              score_threshold: 0.7,
            },
          }),
          signal: abortControllerRef.current.signal,
        })

        if (!response.ok) {
          throw new Error('Failed to send message')
        }

        const reader = response.body?.getReader()
        const decoder = new TextDecoder()

        if (!reader) {
          throw new Error('No response body')
        }

        let buffer = ''
        let fullResponse = ''
        let citations: Citation[] = []

        while (true) {
          const { done, value } = await reader.read()

          if (done) break

          // 解码数据
          buffer += decoder.decode(value, { stream: true })

          // 处理 SSE 格式的数据
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const jsonStr = line.slice(6)

              try {
                const event: StreamEvent = JSON.parse(jsonStr)

                if (event.type === 'citations') {
                  citations = event.data
                  setCurrentCitations(citations)
                } else if (event.type === 'token') {
                  fullResponse += event.data.content
                  setCurrentResponse(fullResponse)
                } else if (event.type === 'done') {
                  // 完成，添加助手消息
                  const assistantMessage: Message = {
                    id: Date.now().toString(),
                    role: 'assistant',
                    content: fullResponse,
                    citations,
                    created_at: new Date().toISOString(),
                  }

                  setMessages((prev) => [...prev, assistantMessage])
                  setCurrentResponse('')
                  setCurrentCitations([])
                } else if (event.type === 'error') {
                  throw new Error(event.data.message)
                }
              } catch (e) {
                console.error('Failed to parse SSE event:', e)
              }
            }
          }
        }
      } catch (error: any) {
        if (error.name === 'AbortError') {
          console.log('Request aborted')
        } else {
          console.error('Chat error:', error)
          options.onError?.(error.message || 'Failed to send message')
        }
      } finally {
        setIsLoading(false)
        abortControllerRef.current = null
      }
    },
    [isLoading, options]
  )

  /**
   * 停止生成
   */
  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
  }, [])

  /**
   * 清空消息
   */
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
  }
}
