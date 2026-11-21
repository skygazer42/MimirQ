// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ConfirmDialog } from './confirm-dialog'

vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))

const cleanups: Array<() => void> = []

function deferred() {
  let resolve!: () => void
  let reject!: (error: unknown) => void
  const promise = new Promise<void>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function button(label: string) {
  const element = [...document.querySelectorAll('button')].find((candidate) => candidate.textContent?.startsWith(label))
  if (element === undefined) throw new Error(`Missing button: ${label}`)
  return element
}

function mount(
  onConfirm: () => void | Promise<void>,
  controlled = false,
  description: React.ReactNode = '删除当前文档',
) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const changes = vi.fn()
  function Harness() {
    const [open, setOpen] = React.useState(false)
    return (
      <ConfirmDialog
        title="删除文件"
        description={description}
        open={controlled ? open : undefined}
        onOpenChange={(next) => {
          changes(next)
          setOpen(next)
        }}
        confirmLabel="删除"
        cancelLabel="返回"
        onConfirm={onConfirm}
      >
        <button type="button">打开确认</button>
      </ConfirmDialog>
    )
  }
  act(() => root.render(<Harness />))
  act(() => button('打开确认').click())
  cleanups.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  return { changes, unmount: () => act(() => root.unmount()) }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
})

describe('confirmation result ownership', () => {
  it('claims a confirmation before two clicks can start duplicate callbacks', async () => {
    const pending = deferred()
    const onConfirm = vi.fn(() => pending.promise)
    mount(onConfirm)
    act(() => {
      const confirmButton = button('删除')
      confirmButton.click()
      confirmButton.click()
    })
    try {
      expect(onConfirm).toHaveBeenCalledTimes(1)
      expect(document.querySelector('[role="alertdialog"]')).not.toBeNull()
    } finally {
      await act(async () => {
        pending.resolve()
        await pending.promise
      })
    }
  })

  it.each([false, true])('keeps confirmation until the operation finishes (controlled=%s)', async (controlled) => {
    const pending = deferred()
    const onConfirm = vi.fn(() => pending.promise)
    mount(onConfirm, controlled)
    act(() => button('删除').click())
    try {
      expect(document.querySelector('[role="alertdialog"]')).not.toBeNull()
      expect(button('删除').disabled).toBe(true)
      expect(button('返回').disabled).toBe(true)
      act(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      })
      expect(document.querySelector('[role="alertdialog"]')).not.toBeNull()
      expect(onConfirm).toHaveBeenCalledTimes(1)
    } finally {
      await act(async () => {
        pending.resolve()
        await pending.promise
      })
    }
    expect(document.querySelector('[role="alertdialog"]')).toBeNull()
  })

  it.each([false, true])('retries from the same failed dialog (controlled=%s)', async (controlled) => {
    const pending = deferred()
    const onConfirm = vi.fn<() => Promise<void>>().mockReturnValueOnce(pending.promise).mockResolvedValueOnce(undefined)
    mount(onConfirm, controlled)
    act(() => button('删除').click())
    await act(async () => {
      pending.reject(new Error('Delete denied'))
      await pending.promise.catch(() => {})
    })

    expect(document.querySelector('[role="alertdialog"]')).not.toBeNull()
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('Delete denied')
    expect(button('删除').disabled).toBe(false)
    await act(async () => {
      button('删除').click()
    })
    expect(document.querySelector('[role="alertdialog"]')).toBeNull()
    expect(onConfirm).toHaveBeenCalledTimes(2)
  })

  it('preserves numeric React content in the description', () => {
    mount(vi.fn(), false, 0)
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain('0')
  })

  it('does not close an owner after its confirmation was unmounted', async () => {
    const pending = deferred()
    const view = mount(() => pending.promise, true)
    act(() => button('删除').click())
    view.changes.mockClear()
    view.unmount()
    await act(async () => {
      pending.resolve()
      await pending.promise
    })
    expect(view.changes).not.toHaveBeenCalled()
  })
})
