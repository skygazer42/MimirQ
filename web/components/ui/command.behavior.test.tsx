// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { NextIntlClientProvider } from 'next-intl'
import { expect, it, vi } from 'vitest'
import commonMessages from '@/i18n/messages/zh-CN/common'
import { CommandDialog, CommandInput } from './command'
import { Popover, PopoverContent, PopoverTrigger } from './popover'

it('focuses search on open and returns focus to the opener without a Radix trigger', async () => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)

  function Harness() {
    const [open, setOpen] = React.useState(false)
    return (
      <NextIntlClientProvider locale="zh-CN" timeZone="Asia/Shanghai" messages={commonMessages}>
        <button onClick={() => setOpen(true)}>打开命令</button>
        <CommandDialog open={open} onOpenChange={setOpen}>
          <button>快捷键</button>
          <CommandInput aria-label="搜索" />
        </CommandDialog>
      </NextIntlClientProvider>
    )
  }

  try {
    await act(async () => root.render(<React.StrictMode><Harness /></React.StrictMode>))
    const opener = container.querySelector('button')!
    await act(async () => {
      opener.focus()
      opener.click()
    })
    expect(document.querySelector('[data-command-dialog]')).not.toBeNull()
    expect(document.activeElement).toBe(document.querySelector('input'))

    await act(async () => {
      document.querySelector<HTMLButtonElement>('[data-command-dialog] > button')!.click()
    })
    await act(async () => {
      await vi.waitFor(() => expect(document.activeElement).toBe(opener))
    })
  } finally {
    await act(async () => root.unmount())
    container.remove()
  }
})

it('keeps focus on a settings panel opened by a command', async () => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)

  function Harness() {
    const [open, setOpen] = React.useState(false)
    const [settingsOpen, setSettingsOpen] = React.useState(false)
    return (
      <NextIntlClientProvider locale="zh-CN" timeZone="Asia/Shanghai" messages={commonMessages}>
        <button onClick={() => setOpen(true)}>打开命令</button>
        <Popover open={settingsOpen} onOpenChange={setSettingsOpen}>
          <PopoverTrigger asChild><button>选择资料</button></PopoverTrigger>
          <PopoverContent aria-label="检索设置"><button data-settings-back>返回资料</button></PopoverContent>
        </Popover>
        <CommandDialog open={open} onOpenChange={setOpen}>
          <CommandInput aria-label="搜索" />
          <button data-open-settings onClick={() => {
            setOpen(false)
            setSettingsOpen(true)
          }}>打开检索设置</button>
        </CommandDialog>
      </NextIntlClientProvider>
    )
  }

  try {
    await act(async () => root.render(<Harness />))
    const opener = container.querySelector('button')!
    await act(async () => {
      opener.focus()
      opener.click()
    })
    await act(async () => {
      document.querySelector<HTMLButtonElement>('[data-open-settings]')!.click()
    })
    await act(async () => {
      await vi.waitFor(() => {
        const back = document.querySelector('[data-settings-back]')
        expect(back).not.toBeNull()
        expect(document.activeElement).toBe(back)
      })
    })
  } finally {
    await act(async () => root.unmount())
    container.remove()
  }
})
