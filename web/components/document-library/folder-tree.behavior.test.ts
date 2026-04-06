// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { waitForAssertion } from '@/test/hook-harness'
import { ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

import { DocumentFolderTree } from './folder-tree'

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

function findElementByText(root: ParentNode, text: string): HTMLElement | null {
  return Array.from(root.querySelectorAll<HTMLElement>('*')).find((element) => element.textContent?.trim() === text) ?? null
}

function dispatchPrimaryPress(target: Element | null) {
  if (!target) return
  target.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0 }))
  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }))
  target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }))
  target.dispatchEvent(new MouseEvent('click', { bubbles: true, button: 0 }))
}

describe('DocumentFolderTree behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useParsedFiles.setState({
      files: [],
      folders: [
        {
          id: 'folder-empty',
          name: '空文件夹',
          parentId: ROOT_FOLDER_ID,
          createdAt: new Date().toISOString(),
        },
      ],
      activeFolderId: ROOT_FOLDER_ID,
      isLoaded: true,
    })
  })

  afterEach(() => {
    useParsedFiles.setState({
      files: [],
      folders: [],
      activeFolderId: ROOT_FOLDER_ID,
      isLoaded: true,
    })
  })

  it('deletes an empty folder from the tree through the folder actions menu', async () => {
    const view = renderComponent(React.createElement(DocumentFolderTree, { showFiles: 'expanded' }))

    await waitForAssertion(() => {
      expect(view.container.textContent).toContain('空文件夹')
    })

    const actionButton = view.container.querySelector<HTMLButtonElement>('button[aria-label="Folder actions"]')
    expect(actionButton).not.toBeNull()

    act(() => {
      dispatchPrimaryPress(actionButton)
    })

    await waitForAssertion(() => {
      expect(document.body.textContent).toContain('删除')
    })

    const deleteItem = findElementByText(document.body, '删除')
    expect(deleteItem).not.toBeNull()

    act(() => {
      dispatchPrimaryPress(deleteItem)
    })

    await waitForAssertion(() => {
      expect(document.body.textContent).toContain('删除该文件夹？')
    })

    const confirmButton =
      Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent?.trim() === '删除') ?? null
    expect(confirmButton).not.toBeNull()

    act(() => {
      dispatchPrimaryPress(confirmButton)
    })

    await waitForAssertion(() => {
      expect(useParsedFiles.getState().folders).toEqual([])
      expect(view.container.textContent).not.toContain('空文件夹')
    })

    view.unmount()
  })
})
