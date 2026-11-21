// @vitest-environment happy-dom

import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from './hook-harness'

describe('waitForAssertion', () => {
  it('observes a completed React update when flushing it crosses the deadline', async () => {
    const hook = renderHook(() => useState('waiting'))
    const clock = vi.spyOn(Date, 'now').mockReturnValue(0)
    const timer = setTimeout(() => {
      clock.mockReturnValue(100)
      hook.result.current[1]('ready')
    }, 0)

    try {
      await waitForAssertion(() => expect(hook.result.current[0]).toBe('ready'), 50)
    } finally {
      clearTimeout(timer)
      clock.mockRestore()
      hook.unmount()
    }
  })

  it('retains the assertion failure when the update never becomes ready', async () => {
    const hook = renderHook(() => useState('waiting'))
    const clock = vi.spyOn(Date, 'now').mockReturnValue(0)
    const timer = setTimeout(() => clock.mockReturnValue(100), 0)

    try {
      await expect(waitForAssertion(() => expect(hook.result.current[0]).toBe('ready'), 50)).rejects.toThrow(
        "expected 'waiting' to be 'ready'",
      )
    } finally {
      clearTimeout(timer)
      clock.mockRestore()
      hook.unmount()
    }
  })
})
