// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { PipelineOptionsProvider } from '@/contexts/pipeline-options-context'
import commonMessages from '@/i18n/messages/zh-CN/common'
import { PipelineOptionsPanel } from './pipeline-options-panel'

let container: HTMLDivElement
let root: Root

describe('pipeline option disclosures', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    localStorage.clear()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    localStorage.clear()
  })

  it.each([undefined, 'panel', 'form'] as const)(
    'only collapses index presets in the form layout (layout=%s)',
    async (layout) => {
      await act(async () => {
        root.render(
          <NextIntlClientProvider locale="zh-CN" messages={commonMessages}>
            <PipelineOptionsProvider>
              <PipelineOptionsPanel compact enabled hideEnabledToggle layout={layout} />
            </PipelineOptionsProvider>
          </NextIntlClientProvider>,
        )
      })

      const indexPreset = container.querySelector('[aria-label="索引模式"]')!
      expect(indexPreset).not.toBeNull()
      const disclosure = indexPreset.closest('details')
      if (layout === 'form') {
        expect(disclosure?.querySelector('summary')?.textContent).toBe('索引模式')
        expect(disclosure?.open).toBe(false)
      } else {
        expect(disclosure).toBeNull()
      }
      for (const details of container.querySelectorAll('details')) {
        expect(details.firstElementChild?.tagName).toBe('SUMMARY')
      }
      expect(container.textContent).toContain('高级治理参数')
    },
  )
})
