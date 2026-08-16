// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: React.PropsWithChildren<{ open: boolean }>) => open ? <div>{children}</div> : null,
  DialogContent: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  DialogFooter: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  DialogTitle: ({ children }: React.PropsWithChildren) => <h2>{children}</h2>,
}))
vi.mock('@/components/provider-icon', () => ({
  ProviderIcon: () => null,
}))
vi.mock('@/lib/api', () => ({
  settingsApi: { testLLM: vi.fn() },
}))

import { ModelConfigDialog } from './model-config-dialog'
import { MODEL_PROVIDERS } from '@/types/models'

function setInputValue(input: HTMLInputElement, value: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    setter?.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('ModelConfigDialog custom model IDs', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  })

  afterEach(() => {
    document.body.replaceChildren()
    vi.clearAllMocks()
  })

  it('saves a provider-specific model ID that is not limited to the presets', () => {
    const provider = MODEL_PROVIDERS.find((item) => item.id === 'ark')
    expect(provider).toBeDefined()

    const onSave = vi.fn()
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        <ModelConfigDialog
          provider={{ ...provider!, config: { apiKey: 'test-key' } }}
          open
          onClose={vi.fn()}
          onSave={onSave}
        />
      )
    })

    const modelInput = container.querySelector('input[list]') as HTMLInputElement | null
    expect(modelInput).not.toBeNull()
    setInputValue(modelInput!, 'doubao-seed-2-0-lite-260428-custom')

    const saveButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('保存配置')
    )
    expect(saveButton).toBeDefined()
    act(() => saveButton!.dispatchEvent(new MouseEvent('click', { bubbles: true })))

    expect(onSave).toHaveBeenCalledWith(
      'ark',
      expect.objectContaining({ model: 'doubao-seed-2-0-lite-260428-custom' })
    )
    act(() => root.unmount())
  })

  it('offers the dated Doubao model ID as a preset value', () => {
    const provider = MODEL_PROVIDERS.find((item) => item.id === 'ark')
    expect(provider?.models).toContainEqual(
      expect.objectContaining({ name: 'doubao-seed-2-0-lite-260428' })
    )
  })
})
