// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WorkspaceNotice, WorkspaceNoticeStack } from './operational-workspace'

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
})

describe('WorkspaceNoticeStack auto-minimize orb', () => {
  it('auto-minimizes to a circular status orb after 6 seconds and re-expands on click', () => {
    const retry = vi.fn()
    act(() => {
      root.render(
        React.createElement(
          WorkspaceNoticeStack,
          null,
          React.createElement(
            WorkspaceNotice,
            {
              tone: 'warning',
              title: '权限信息更新失败',
              retry,
              retryLabel: '重新校验',
            },
            '服务连接暂时中断 (request_id=req-orb-1)',
          ),
        ),
      )
    })

    expect(container.querySelector('[role="alert"]')?.textContent).toContain('权限信息更新失败')
    expect(container.querySelector('[data-workspace-notice-orb]')).toBeNull()

    act(() => {
      vi.advanceTimersByTime(6000)
    })

    const orb = container.querySelector<HTMLButtonElement>('[data-workspace-notice-orb]')
    expect(orb).not.toBeNull()
    expect(orb?.getAttribute('aria-label')).toBe('展开 1 条异常提示')
    expect(container.querySelector('[role="alert"]')).toBeNull()

    act(() => {
      orb!.click()
    })

    expect(container.querySelector('[role="alert"]')?.textContent).toContain('权限信息更新失败')
    expect(container.querySelector('[data-workspace-notice-orb]')).toBeNull()
  })

  it('pauses auto-minimize while hovered and supports manual minimize', () => {
    act(() => {
      root.render(
        React.createElement(
          WorkspaceNoticeStack,
          null,
          React.createElement(WorkspaceNotice, { title: '读取失败' }, '服务连接暂时中断'),
        ),
      )
    })

    const stack = container.querySelector<HTMLDivElement>('[data-workspace-notice-stack]')!
    act(() => {
      stack.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    })
    act(() => {
      vi.advanceTimersByTime(10000)
    })
    expect(container.querySelector('[role="alert"]')).not.toBeNull()
    expect(container.querySelector('[data-workspace-notice-orb]')).toBeNull()

    const minimizeBtn = container.querySelector<HTMLButtonElement>('button[aria-label="收起提示"]')!
    act(() => {
      minimizeBtn.click()
    })
    expect(container.querySelector('[data-workspace-notice-orb]')).not.toBeNull()
  })

  it('keeps diagnostic details open until the user closes them', () => {
    act(() => {
      root.render(
        React.createElement(
          WorkspaceNoticeStack,
          null,
          React.createElement(WorkspaceNotice, { title: '读取失败', requestId: 'req-details' }, '服务连接暂时中断'),
        ),
      )
    })

    const details = container.querySelector('details')!
    act(() => {
      details.open = true
      details.dispatchEvent(new Event('toggle'))
    })
    act(() => {
      vi.advanceTimersByTime(10000)
    })
    expect(container.querySelector('[role="alert"]')).not.toBeNull()
    expect(container.querySelector('details')?.open).toBe(true)

    act(() => {
      details.open = false
      details.dispatchEvent(new Event('toggle'))
    })
    act(() => {
      vi.advanceTimersByTime(6000)
    })
    expect(container.querySelector('[data-workspace-notice-orb]')).not.toBeNull()
  })
})
