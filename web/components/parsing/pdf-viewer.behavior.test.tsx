// @vitest-environment happy-dom

import { act, useLayoutEffect, type ComponentProps } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ readData: vi.fn(), loadModule: vi.fn(), getDocument: vi.fn() }))

vi.mock('@/lib/pdf-source', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/pdf-source')>()),
  readPdfSourceData: mocks.readData,
  loadPdfJsModule: mocks.loadModule,
}))

import { PdfViewer } from './pdf-viewer'

const roots = new Set<Root>()
const observers: TestObserver[] = []
const scrollContainers = new Set<HTMLElement>()
const initialCanvasContext = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'getContext')
let layoutWidth = 400
let viewportHeight = 400
let pageHeightRatio = 1.5

function setGeometry(element: Element) {
  if (!(element instanceof HTMLElement)) return
  const pageIndex = element.dataset.pageIndex
  const isPage = pageIndex !== undefined
  Object.defineProperties(element, {
    clientWidth: { configurable: true, get: () => layoutWidth },
    clientHeight: { configurable: true, get: () => (isPage ? layoutWidth * pageHeightRatio : viewportHeight) },
    scrollHeight: {
      configurable: true,
      get: () => {
        const count = element.querySelectorAll('[data-page-index]').length
        return 56 + count * layoutWidth * pageHeightRatio + Math.max(0, count - 1) * 24
      },
    },
    scrollTo: {
      configurable: true,
      value: vi.fn((options: ScrollToOptions) => {
        if (options.top === undefined) return
        const previous = element.scrollTop
        element.scrollTop = Math.max(0, Math.min(options.top, element.scrollHeight - element.clientHeight))
        if (element.scrollTop !== previous) element.dispatchEvent(new Event('scroll'))
      }),
    },
    getBoundingClientRect: {
      configurable: true,
      value: () => {
        if (!isPage) return new DOMRect(0, 0, layoutWidth, viewportHeight)
        let container = element.parentElement
        while (container !== null && !scrollContainers.has(container)) container = container.parentElement
        if (container === null) throw new Error('Test page has no observed scroll container')
        return new DOMRect(
          0,
          28 + Number(pageIndex) * (layoutWidth * pageHeightRatio + 24) - container.scrollTop,
          layoutWidth,
          layoutWidth * pageHeightRatio,
        )
      },
    },
  })
}

class TestObserver {
  readonly elements = new Set<Element>()

  constructor(readonly callback: () => void) {
    observers.push(this)
  }

  readonly observe = vi.fn((element: Element) => {
    this.elements.add(element)
    if (element instanceof HTMLElement && element.getAttribute('aria-label') === 'PDF 页面') {
      scrollContainers.add(element)
    }
    setGeometry(element)
    for (const page of element.querySelectorAll('[data-page-index]')) setGeometry(page)
  })
  readonly disconnect = vi.fn(() => this.elements.clear())
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function documentTask(pageCount: number) {
  const pages = Array.from({ length: pageCount }, () => ({
    getViewport: ({ scale }: { scale: number }) => ({ width: 200 * scale, height: 300 * scale }),
    cleanup: vi.fn(),
    render: vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() })),
  }))
  const doc = {
    numPages: pageCount,
    getPage: vi.fn(async (pageNumber: number) => {
      const page = pages[pageNumber - 1]
      if (page === undefined) throw new RangeError('Invalid test PDF page')
      return page
    }),
  }
  return { doc, pages, task: { promise: Promise.resolve(doc), destroy: vi.fn().mockResolvedValue(undefined) } }
}

async function settleViewport() {
  // Commit each layout frame before advancing the page-recovery timers.
  for (let frame = 0; frame < 3; frame += 1) {
    await act(async () => vi.advanceTimersByTimeAsync(16))
  }
}

async function mount(
  file: File | null = new File(['first'], 'first.pdf'),
  props: Pick<
    ComponentProps<typeof PdfViewer>,
    'activeBlockIds' | 'boxesByPage' | 'blockIdToPageIndex' | 'scrollToPageIndex'
  > = {},
) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.add(root)
  const committedPageCounts: number[] = []
  function CommitProbe() {
    useLayoutEffect(() => {
      committedPageCounts.push(container.querySelectorAll('[data-page-index]').length)
    })
    return null
  }
  async function render(source: File | null) {
    await act(async () =>
      root.render(
        <>
          <PdfViewer {...props} file={source} showToolbar />
          <CommitProbe />
        </>,
      ),
    )
  }
  function unmount() {
    act(() => root.unmount())
    roots.delete(root)
  }
  await render(file)
  return { container, render, unmount, committedPageCounts }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  vi.clearAllMocks()
  observers.length = 0
  scrollContainers.clear()
  layoutWidth = 400
  viewportHeight = 400
  pageHeightRatio = 1.5
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    value: () => ({ clearRect: vi.fn() }),
  })
  vi.stubGlobal('ResizeObserver', TestObserver)
  vi.stubGlobal('requestIdleCallback', undefined)
  mocks.readData.mockResolvedValue(new Uint8Array([1]))
  mocks.loadModule.mockResolvedValue({
    FeatureTest: { isOffscreenCanvasSupported: false },
    getDocument: mocks.getDocument,
  })
  mocks.getDocument.mockReturnValue(documentTask(3).task)
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots.clear()
  document.body.replaceChildren()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  if (initialCanvasContext === undefined) Reflect.deleteProperty(HTMLCanvasElement.prototype, 'getContext')
  else Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', initialCanvasContext)
})

describe('page rendering ownership and bounded recovery', () => {
  it('advances the actual reading page when several short pages are already visible', async () => {
    viewportHeight = 600
    pageHeightRatio = 150 / 400
    const source = documentTask(10)
    for (const page of source.pages) {
      page.getViewport = ({ scale }: { scale: number }) => ({ width: 400 * scale, height: 150 * scale })
    }
    mocks.getDocument.mockReturnValueOnce(source.task)
    const view = await mount()
    await settleViewport()
    const next = view.container.querySelector<HTMLButtonElement>('[aria-label="下一页原文"]')!

    act(() => next.click())
    await settleViewport()
    expect(view.container.textContent).toContain('2 / 10 页')
    act(() => next.click())
    await settleViewport()
    expect(view.container.textContent).toContain('3 / 10 页')
  })

  it('keeps the terminal page failure until an explicit retry instead of restarting it in the background', async () => {
    const source = documentTask(1)
    source.pages[0].render.mockImplementation(() => ({
      promise: Promise.reject(new Error('font rejected')),
      cancel: vi.fn(),
    }))
    mocks.getDocument.mockReturnValueOnce(source.task)
    const view = await mount()
    await settleViewport()
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(view.container.textContent).toContain('渲染失败')
    const completedAttempts = source.pages[0].render.mock.calls.length

    await act(async () => vi.advanceTimersByTimeAsync(2000))

    expect(source.pages[0].render).toHaveBeenCalledTimes(completedAttempts)
    expect(view.container.textContent).toContain('渲染失败')
    source.pages[0].render.mockImplementation(() => ({ promise: Promise.resolve(), cancel: vi.fn() }))
    const retry = view.container.querySelector<HTMLButtonElement>('[aria-label="重试第 1 页"]')!
    act(() => {
      retry.click()
      retry.click()
    })
    await act(async () => vi.advanceTimersByTimeAsync(1))
    expect(source.pages[0].render).toHaveBeenCalledTimes(completedAttempts + 1)
    expect(view.container.querySelector('[data-page-index="0"]')?.getAttribute('data-page-rendered')).toBe('true')
  })

  it('does not let a retired render completion unlock a newer pending render after resize', async () => {
    const source = documentTask(2)
    const renderResults: Array<ReturnType<typeof deferred<void>>> = []
    source.pages[0].render.mockImplementation(() => {
      const result = deferred<void>()
      renderResults.push(result)
      return { promise: result.promise, cancel: vi.fn() }
    })
    mocks.getDocument.mockReturnValueOnce(source.task)
    await mount()
    await settleViewport()
    expect(renderResults.length).toBeGreaterThan(0)
    const oldRender = renderResults.at(-1)!
    const initialRenderCount = renderResults.length
    layoutWidth = 600
    for (const observer of observers) {
      if ([...observer.elements].some((element) => !element.hasAttribute('data-page-index'))) observer.callback()
    }
    await settleViewport()
    expect(renderResults.length).toBeGreaterThan(initialRenderCount)
    try {
      await act(async () => {
        oldRender.reject(new Error('old render cancelled'))
        await vi.advanceTimersByTimeAsync(1)
      })

      expect(source.pages[1].render).not.toHaveBeenCalled()
    } finally {
      await act(async () => {
        for (const result of renderResults) result.resolve()
      })
    }
  })
})

describe('real navigation requests', () => {
  it('preserves manual reading when another page becomes ready after a box selection was completed', async () => {
    const source = documentTask(3)
    const secondPage = deferred<(typeof source.pages)[number]>()
    source.doc.getPage.mockImplementation(async (pageNumber: number) =>
      pageNumber === 2 ? secondPage.promise : source.pages[pageNumber - 1],
    )
    mocks.getDocument.mockReturnValueOnce(source.task)
    const selected = {
      id: 'selected',
      position: { pages: [0], left: 10, right: 20, top: 10, bottom: 20, raw: 'actual-position' },
    }
    await mount(new File(['first'], 'first.pdf'), {
      activeBlockIds: ['selected'],
      blockIdToPageIndex: new Map([['selected', 0]]),
      boxesByPage: new Map([[0, [selected]]]),
    })
    await settleViewport()
    await settleViewport()
    const container = [...scrollContainers][0]
    const scroll = vi.mocked(container.scrollTo)
    scroll.mockClear()
    container.scrollTop = 700
    act(() => container.dispatchEvent(new Event('scroll')))
    await settleViewport()

    await act(async () => secondPage.resolve(source.pages[1]))
    await settleViewport()

    expect(container.scrollTop).toBe(700)
    expect(scroll).not.toHaveBeenCalled()
  })

  it('does not turn an out-of-range requested page into the last actual page', async () => {
    await mount(new File(['first'], 'first.pdf'), { scrollToPageIndex: 99 })
    await settleViewport()

    expect([...scrollContainers][0].scrollTo).not.toHaveBeenCalled()
  })
})

describe('PDF document source and loading task ownership', () => {
  it('destroys the pending loading task when a new source takes over', async () => {
    const first = documentTask(3)
    const pending = deferred<typeof first.doc>()
    first.task.promise = pending.promise
    const second = documentTask(1)
    mocks.getDocument.mockReturnValueOnce(first.task).mockReturnValueOnce(second.task)
    const view = await mount()
    try {
      await view.render(new File(['second'], 'second.pdf'))
      expect(first.task.destroy).toHaveBeenCalledOnce()
      expect(view.container.querySelectorAll('[data-page-index]')).toHaveLength(1)
    } finally {
      await act(async () => pending.resolve(first.doc))
    }
  })

  it('destroys the accepted loading task when its viewer unmounts', async () => {
    const first = documentTask(3)
    mocks.getDocument.mockReturnValueOnce(first.task)
    const view = await mount()
    expect(view.container.querySelectorAll('[data-page-index]')).toHaveLength(3)

    view.unmount()

    expect(first.task.destroy).toHaveBeenCalledOnce()
  })

  it('does not start a PDF.js document when a retired file read completes later', async () => {
    const pending = deferred<Uint8Array>()
    mocks.readData.mockReturnValueOnce(pending.promise)
    const view = await mount()
    view.unmount()

    await act(async () => pending.resolve(new Uint8Array([1])))

    expect(mocks.getDocument).not.toHaveBeenCalled()
  })

  it('never exposes the previous document pages in the first committed frame for a new source', async () => {
    const first = documentTask(3)
    const second = documentTask(1)
    const pending = deferred<typeof second.doc>()
    second.task.promise = pending.promise
    mocks.getDocument.mockReturnValueOnce(first.task).mockReturnValueOnce(second.task)
    const view = await mount()
    expect(view.container.querySelectorAll('[data-page-index]')).toHaveLength(3)
    view.committedPageCounts.length = 0
    try {
      await view.render(new File(['second'], 'second.pdf'))

      expect(view.committedPageCounts[0]).toBe(0)
    } finally {
      await act(async () => pending.resolve(second.doc))
    }
  })

  it('releases a failed document task while keeping the actual error visible', async () => {
    const failed = {
      promise: Promise.reject(new Error('document rejected')),
      destroy: vi.fn().mockResolvedValue(undefined),
    }
    mocks.getDocument.mockReturnValueOnce(failed)
    const view = await mount()

    expect(view.container.textContent).toContain('document rejected')
    expect(failed.destroy).toHaveBeenCalledOnce()
  })

  it('keeps no source distinct from a loading or failed document', async () => {
    const view = await mount(null)

    expect(view.container.textContent).toContain('未选择 PDF')
    expect(view.container.querySelectorAll('[data-page-index]')).toHaveLength(0)
    expect(mocks.getDocument).not.toHaveBeenCalled()
  })
})
