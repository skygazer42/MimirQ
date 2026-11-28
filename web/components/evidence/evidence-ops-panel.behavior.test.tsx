// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const controlled = vi.hoisted(() => ({
  persist: vi.fn(),
  verify: vi.fn(),
  patchSuite: vi.fn(),
  listDatasets: vi.fn(),
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}))
vi.mock('@/lib/api', () => ({
  evidenceApi: {
    persistCapsule: controlled.persist,
    verifyCapsule: controlled.verify,
    patchSuite: controlled.patchSuite,
  },
  datasetApi: { listAll: controlled.listDatasets },
}))
vi.mock('sonner', () => ({ toast: controlled.toast }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: { listAll: controlled.listDatasets } }))

import { EvidenceOpsPanel } from './evidence-ops-panel'

let root: Root
let client: QueryClient
let mounted: boolean

function button(label: string) {
  const element = Array.from(document.querySelectorAll('button')).find((item) => item.textContent?.trim() === label)
  if (element === undefined) throw new Error(`Missing button: ${label}`)
  return element
}

function changePayload(value: string) {
  const textarea = document.querySelector('textarea')!
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, value)
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(async () => {
  vi.clearAllMocks()
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  controlled.listDatasets.mockResolvedValue([])
  controlled.persist.mockResolvedValue({ capsule_id: 'saved' })
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  mounted = true
  await act(async () =>
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="zh-CN" messages={{}}>
          <EvidenceOpsPanel />
        </NextIntlClientProvider>
      </QueryClientProvider>,
    ),
  )
})

afterEach(() => {
  if (mounted) act(() => root.unmount())
  client.clear()
  document.body.replaceChildren()
})

describe('evidence operation payload and lifecycle', () => {
  it.each(['', '[]', 'null', 'false', '{}'])(
    'rejects capsule payload %j before HTTP and retains the draft',
    async (raw) => {
      changePayload(raw)
      await act(async () => button('保存证据快照').click())
      expect(controlled.persist).not.toHaveBeenCalled()
      expect(document.querySelector('[role="alert"]')).not.toBeNull()
      expect(document.querySelector('textarea')?.value).toBe(raw)
      expect(controlled.toast.success).not.toHaveBeenCalled()
    },
  )

  it('does not show late completion after the tools panel unmounts', async () => {
    let complete!: (value: unknown) => void
    controlled.persist.mockReturnValue(
      new Promise((resolve) => {
        complete = resolve
      }),
    )
    act(() => button('保存证据快照').click())
    act(() => root.unmount())
    mounted = false
    await act(async () => complete({ capsule_id: 'saved' }))
    expect(controlled.toast.success).not.toHaveBeenCalled()
  })

  it('keeps a negative capsule validation report as a negative report', async () => {
    controlled.verify.mockResolvedValue({ valid: false, reason: '引用缺失' })
    await act(async () => button('校验证据快照').click())
    expect(document.querySelector('pre')?.textContent).toContain('"valid": false')
    expect(document.querySelector('pre')?.textContent).toContain('引用缺失')
    expect(controlled.toast.warning).toHaveBeenCalledWith('证据快照校验未通过（引用缺失）')
    expect(controlled.toast.success).not.toHaveBeenCalled()
  })
})
