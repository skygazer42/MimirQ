// @vitest-environment jsdom
import React, { act, StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { FeedbackToast, FEEDBACK_DURATION } from './feedback-toast'

vi.mock('sonner', () => ({ toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

let root: Root
let container: HTMLDivElement

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('state-based application feedback', () => {
  it('shows a finite message once through Strict Mode and ordinary rerenders without adding an inline banner', async () => {
    const render = () => root.render(<StrictMode><FeedbackToast message="参数已变更" type="warning" id="parameters" /></StrictMode>)
    await act(async () => render())
    await act(async () => render())
    expect(toast.warning).toHaveBeenCalledTimes(1)
    expect(toast.warning).toHaveBeenCalledWith('参数已变更', { id: 'parameters', duration: FEEDBACK_DURATION })
    expect(FEEDBACK_DURATION).toBeGreaterThan(0)
    expect(FEEDBACK_DURATION).toBeLessThanOrEqual(5000)
    expect(container.textContent).toBe('')
  })

  it('announces the same error again after a retry clears it, and uses the new success state', async () => {
    await act(async () => root.render(<FeedbackToast message="保存失败" type="error" id="save" />))
    await act(async () => root.render(<FeedbackToast message={null} type="error" id="save" />))
    await act(async () => root.render(<FeedbackToast message="保存失败" type="error" id="save" />))
    expect(toast.error).toHaveBeenCalledTimes(2)
    await act(async () => root.render(<FeedbackToast message="已保存" type="success" id="save" />))
    expect(toast.success).toHaveBeenCalledWith('已保存', { id: 'save', duration: FEEDBACK_DURATION })
  })
})
