'use client'

import { useEffect, useId, useRef } from 'react'
import { toast } from 'sonner'

export const FEEDBACK_DURATION = 4000

type FeedbackType = 'success' | 'error' | 'warning' | 'info'

/** Present state-based action feedback through the shared, transient notification surface. */
export function FeedbackToast({ message, type = 'info', id }: Readonly<{
  message?: string | null
  type?: FeedbackType
  id?: string
}>) {
  const instanceId = useId()
  const previous = useRef<string | null>(null)

  useEffect(() => {
    const current = message?.trim() || null
    if (!current) {
      previous.current = null
      return
    }
    const identity = `${type}:${current}`
    if (previous.current === identity) return
    previous.current = identity
    toast[type](current, { id: id || instanceId, duration: FEEDBACK_DURATION })
  }, [id, instanceId, message, type])

  return null
}
