// @vitest-environment jsdom

import React, { act, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { QueryProvider } from './query-provider'

let activeQueryClient: ReturnType<typeof useQueryClient> | null = null

function QueryClientProbe() {
  const queryClient = useQueryClient()
  useEffect(() => {
    activeQueryClient = queryClient
    return () => {
      activeQueryClient = null
    }
  }, [queryClient])
  return null
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  activeQueryClient = null
  localStorage.setItem('mimirq_user_id', 'user-a')
})

afterEach(() => {
  activeQueryClient = null
  localStorage.clear()
  document.body.innerHTML = ''
})

describe('QueryProvider auth scope', () => {
  it('clears private query data when another tab changes the authenticated user', () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => {
      root.render(
        <QueryProvider>
          <QueryClientProbe />
        </QueryProvider>
      )
    })

    activeQueryClient?.setQueryData(['documents'], { owner: 'user-a' })
    expect(activeQueryClient?.getQueryCache().getAll()).toHaveLength(1)

    act(() => {
      localStorage.setItem('mimirq_user_id', 'user-b')
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: 'mimirq_user_id',
          oldValue: 'user-a',
          newValue: 'user-b',
        })
      )
    })

    expect(activeQueryClient?.getQueryCache().getAll()).toHaveLength(0)
    act(() => root.unmount())
  })
})
