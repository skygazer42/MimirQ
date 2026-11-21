// @vitest-environment happy-dom

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CitationSnapshotCard } from './chunk-renderer'
import type { CitationSnapshot, DocumentChunkLocation } from './document-viewer-models'

describe('citation snapshot display', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>
  const copyContent = vi.fn<(content: string) => Promise<void>>()
  const copyLink = vi.fn<(location: DocumentChunkLocation) => Promise<void>>()

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    copyContent.mockReset().mockResolvedValue(undefined)
    copyLink.mockReset().mockResolvedValue(undefined)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  function render(snapshot: CitationSnapshot) {
    act(() =>
      root.render(
        <CitationSnapshotCard snapshot={snapshot} query="" onCopyContent={copyContent} onCopyLink={copyLink} />,
      ),
    )
  }

  it('exposes unknown positions and preserves the actual quoted text without edit actions', async () => {
    const content = '  quoted text\n\n'
    render({ chunkId: 'citation-a', content, range: null })
    expect(container.textContent).toContain('序号未知')
    expect(container.textContent).not.toContain('#0')
    expect(container.textContent).not.toContain('P.0')
    expect(container.querySelector('p')?.textContent).toBe(content)
    expect(container.querySelector('[aria-label="Edit chunk"]')).toBeNull()
    expect(container.querySelector('[aria-label="Delete chunk"]')).toBeNull()
    await act(async () => (container.querySelector('[aria-label="复制引用原文"]') as HTMLButtonElement).click())
    expect(copyContent).toHaveBeenCalledWith(content)
    await act(async () => (container.querySelector('[aria-label="复制定位链接"]') as HTMLButtonElement).click())
    const location = copyLink.mock.calls[0][0]
    expect(location.id).toBe('citation-a')
    expect(location.start_char).toBeUndefined()
    expect(location.end_char).toBeUndefined()
  })

  it('retains genuine zero metadata, empty source text and the known selection range', async () => {
    render({ chunkId: 'citation-b', content: '', chunkIndex: 0, pageNumber: 0, range: { start: 0, end: 4 } })
    expect(container.textContent).toContain('#0')
    expect(container.textContent).toContain('P.0')
    expect(container.textContent).toContain('引用原文为空')
    await act(async () => (container.querySelector('[aria-label="复制引用原文"]') as HTMLButtonElement).click())
    expect(copyContent).toHaveBeenCalledWith('')
    await act(async () => (container.querySelector('[aria-label="复制定位链接"]') as HTMLButtonElement).click())
    expect(copyLink).toHaveBeenCalledWith({ id: 'citation-b', start_char: 0, end_char: 4 })
  })
})
