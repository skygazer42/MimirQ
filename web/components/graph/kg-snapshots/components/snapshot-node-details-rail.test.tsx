// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SnapshotNodeDetailsRail } from './snapshot-node-details-rail'

describe('SnapshotNodeDetailsRail', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    document.body.innerHTML = ''
  })

  it('closes the rail and selects the exact relation target id', () => {
    const onClose = vi.fn()
    const onSelectRelationTarget = vi.fn()

    act(() => {
      root.render(
        <SnapshotNodeDetailsRail
          selectedNode={{
            id: 'node-a',
            label: '重复名称',
            type: 'entity',
            kind: 'entity',
            description: 'source node',
            x: 0,
            y: 0,
            tone: 'blue',
            icon: <span>A</span>,
            occurrences: 1,
            status: '一致',
            relations: [
              { label: '关联', target: '重复名称', targetId: 'node-b' },
            ],
          }}
          diffOverview={[]}
          onClose={onClose}
          onSelectRelationTarget={onSelectRelationTarget}
        />
      )
    })

    const closeButton = container.querySelector(
      '[aria-label="收起节点详情"]'
    ) as HTMLButtonElement
    const relationButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent?.includes('关联')
    ) as HTMLButtonElement

    act(() => closeButton.click())
    act(() => relationButton.click())

    expect(onClose).toHaveBeenCalledOnce()
    expect(onSelectRelationTarget).toHaveBeenCalledWith('node-b')
  })
})
