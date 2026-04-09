// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { waitForAssertion } from '@/test/hook-harness'

const apiMocks = vi.hoisted(() => ({
  kgApi: {
    listPredicateOntology: vi.fn(),
  },
  settingsApi: {
    get: vi.fn(),
  },
}))

const toastMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  kgApi: apiMocks.kgApi,
  settingsApi: apiMocks.settingsApi,
}))

vi.mock('sonner', () => ({
  toast: toastMocks,
}))

import { KgPredicateOntologySettings } from './kg-predicate-ontology-settings'

function renderComponent(element: React.ReactElement) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(element)
  })

  return {
    container,
    unmount() {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
}

describe('KgPredicateOntologySettings behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not request predicate ontology when KG feature flag is disabled', async () => {
    apiMocks.settingsApi.get.mockResolvedValue({
      feature_flags: {
        kg_enabled: false,
      },
    })

    const view = renderComponent(React.createElement(KgPredicateOntologySettings))

    await waitForAssertion(() => {
      expect(apiMocks.settingsApi.get).toHaveBeenCalledTimes(1)
      expect(apiMocks.kgApi.listPredicateOntology).not.toHaveBeenCalled()
      expect(view.container.textContent).toContain('KG 功能当前未启用')
    })

    view.unmount()
  })
})
