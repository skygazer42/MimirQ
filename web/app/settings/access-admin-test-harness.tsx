import React, { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'

import { QueryProvider } from '@/components/providers/query-provider'
import { setAuthSession } from '@/lib/auth-storage'
import type { TenantMember } from '@/lib/api/access'
import type { TenantGroupOut } from '@/types/backend'
import { useAccessAdminSession } from './use-access-admin-session'

export const A = '11111111-1111-4111-8111-111111111111'
export const B = '22222222-2222-4222-8222-222222222222'
export const MEMBER = 'member@example.com'
export const adminAccess = {
  is_active: true,
  permissions: ['settings.read', 'settings.write'],
  account_id: 'self@example.com',
}
const cleanup: Array<() => void> = []

export function group(id: string, name: string): TenantGroupOut {
  return { id, name, external_id: null, tenant_id: 'tenant', created_at: '2026-11-05T00:00:00Z' }
}

export function member(id: string, role = 'viewer'): TenantMember {
  return { id, user_id: id, tenant_id: 'tenant', role, is_active: true, is_current: false, username: id, email: id }
}

export function login(id = 'current') {
  setAuthSession({
    token: { access_token: 'access-token', token_type: 'bearer', expires_in: 3600 },
    user: { id, username: id, email: `${id}@example.com`, is_active: true, created_at: '2026-11-05T00:00:00Z' },
  })
}

export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

export function mountAdmin<T>(useController: () => T, children: ReactNode = null) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const result = { current: undefined as T | undefined }
  let client!: QueryClient
  let visible = true
  let content: ReactNode = children
  let useCurrentController = useController
  let controllerVersion = 0
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  function Controller() {
    result.current = useCurrentController()
    return content
  }
  function Host() {
    client = useQueryClient()
    const session = useAccessAdminSession()
    return visible ? <Controller key={`${session}:${controllerVersion}`} /> : null
  }
  const render = () =>
    act(() =>
      root.render(
        <QueryProvider>
          <Host />
        </QueryProvider>,
      ),
    )
  render()
  cleanup.push(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  return {
    result: result as { current: T },
    client,
    container,
    setChildren(next: ReactNode) {
      content = next
      render()
    },
    setController(useNextController: () => T) {
      useCurrentController = useNextController
      controllerVersion += 1
      render()
    },
    navigate(show: boolean, id?: string) {
      if (id) window.history.replaceState({}, '', `/settings/groups?group=${id}`)
      visible = show
      render()
      if (show && id) act(() => window.dispatchEvent(new PopStateEvent('popstate')))
    },
  }
}

export function cleanupAdmin() {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  document.body.replaceChildren()
}
