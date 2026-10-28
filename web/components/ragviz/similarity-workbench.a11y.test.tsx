// @vitest-environment happy-dom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: { collections: [] }, isFetching: false, error: null, refetch: vi.fn() }) }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }))
import { RagvizSimilarityWorkbench } from './similarity-workbench'

describe('Similarity tool dialogs', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div'); document.body.append(container)
    root = createRoot(container)
  })
  afterEach(() => { act(() => root.unmount()); document.body.innerHTML = '' })

  it('keeps source inputs outside the focus order until the dialog opens', () => {
    act(() => root.render(<RagvizSimilarityWorkbench />))
    expect(document.querySelector('[aria-label="横轴数据源 1"]')).toBeNull()
    const trigger = [...container.querySelectorAll('button')].find(button => button.textContent === '数据源与计算')!
    act(() => trigger.click())
    const dialog = document.querySelector('[role="dialog"]')!
    expect(dialog.querySelector('[aria-label="横轴数据源 1"]')).not.toBeNull()
    expect(dialog.querySelector('[aria-label="纵轴数据源 1"]')).not.toBeNull()
    const calculate = [...dialog.querySelectorAll('button')].find(button => button.textContent === '计算相似度')!
    expect(calculate.disabled).toBe(true)
  })
})
