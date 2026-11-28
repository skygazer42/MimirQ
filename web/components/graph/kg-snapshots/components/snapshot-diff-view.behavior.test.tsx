// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { SnapshotDiffView } from './snapshot-diff-view'

describe('SnapshotDiffView secondary tools', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    document.body.innerHTML = ''
  })

  it('preserves filters when tools collapse and while switching to original content', () => {
    act(() => {
      root.render(
        <SnapshotDiffView
          titleA="快照 A"
          titleB="快照 B"
          leftCode={'{"name":"旧手册"}'}
          rightCode={'{"name":"新手册"}'}
          diff={{
            nodes_added: [{ id: 'node-a', name: '节点甲' }],
            edges_added: [{ id: 'edge-a', name: '关系甲' }],
          }}
          onCopy={() => undefined}
          onDownload={() => undefined}
        />,
      )
    })
    const toggle = container.querySelector<HTMLButtonElement>('button[aria-controls]')
    expect(toggle?.getAttribute('aria-expanded')).toBe('false')
    act(() => toggle!.click())
    expect(toggle?.getAttribute('aria-expanded')).toBe('true')

    const kind = container.querySelector<HTMLSelectElement>('[aria-label="变更对象类别"]')!
    act(() => {
      kind.value = '关系'
      kind.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(container.querySelector('table')?.textContent).toContain('关系甲')
    expect(container.querySelector('table')?.textContent).not.toContain('节点甲')

    act(() => toggle!.click())
    expect(toggle?.getAttribute('aria-expanded')).toBe('false')
    act(() => toggle!.click())
    const raw = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === '原始对照')!
    act(() => raw.click())
    expect(container.querySelector('[aria-label="快照原始对照"]')?.textContent).toContain('旧手册')

    const changes = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '变更明细',
    )!
    act(() => changes.click())
    expect(container.querySelector<HTMLSelectElement>('[aria-label="变更对象类别"]')?.value).toBe('关系')
    expect(container.querySelector('table')?.textContent).toContain('关系甲')
    expect(container.querySelector('table')?.textContent).not.toContain('节点甲')
  })
})
